"""Досье лаборатории, мини-лаба, названия, видимость досье и эмодзи."""
from __future__ import annotations

import re
from html import escape

import emoji as emoji_lib
from aiogram import Router
from aiogram.types import Message

from epidemic import keyboards as kb
from epidemic import texts
from epidemic.db import Database, Row
from epidemic.game.naming import claim_lab_name, name_mute_error
from epidemic.game.settings import GameSettings
from epidemic.handlers.common import PREFIX, cmd
from epidemic.repo import corps, labs, victims
from epidemic.utils.fmt import mention, now_ts
from epidemic.utils.parse import parse_target_token
from epidemic.utils.targets import mentioned_user, reply_user, resolve_ref
from epidemic.views import lab as view

router = Router(name="lab")

_LAB_WORD = r"(?:лаб|лаба|лаборатория|моя\s+(?:лаб|лаба|лаборатория))"
_LAB_NAME_WORD = r"(?:лаб|лабы|лаборатория|лаборатории)"


async def dossier_text(db: Database, gs: GameSettings, lab: Row, now: int) -> str:
    """Полное досье лаборатории — для игроков («лаб») и администраторов (/labinfo)."""
    user_id = lab["user_id"]
    return view.dossier(
        lab,
        await corps.membership(db, user_id),
        await victims.count_owned(db, user_id, now),
        await victims.count_illnesses(db, user_id, now),
        gs,
        now,
    )


async def send_dossier(message: Message, db: Database, gs: GameSettings, target_id: int, viewer_id: int) -> None:
    lab = await labs.get(db, target_id)
    if lab is None or lab["is_bot"]:
        await message.answer(texts.NO_INFO_ABOUT_USER)
        return
    if target_id != viewer_id and not lab["dossier_open"]:
        await message.answer(view.DOSSIER_SECRET)
        return
    # Как в оригинале, кнопки прокачки видны под любым досье; чужие нажатия отсекает проверка владельца.
    await message.answer(await dossier_text(db, gs, lab, now_ts()), reply_markup=kb.lab_navigation(target_id))


# --- Эмодзи (раньше просмотра досье: «лаб эмоджи» иначе примется за цель) ---

@router.message(cmd(rf"{PREFIX}{_LAB_WORD}\s+эмоджи\s+(?P<emoji>.+)"))
async def set_emoji(message: Message, m: re.Match, db: Database) -> None:
    value = m.group("emoji").strip()
    if not emoji_lib.purely_emoji(value) or emoji_lib.emoji_count(value) > 3:
        await message.answer(view.EMOJI_WRONG)
        return
    await labs.set_fields(db, message.from_user.id, emoji=value)
    await message.answer(view.emoji_set(value))


@router.message(cmd(rf"[!./-]?{_LAB_WORD}\s+эмоджи"))
async def remove_emoji(message: Message, db: Database) -> None:
    lab = await labs.get(db, message.from_user.id)
    if lab is None or not lab["emoji"]:
        await message.answer(view.EMOJI_NONE)
        return
    await labs.set_fields(db, message.from_user.id, emoji=None)
    await message.answer(view.emoji_removed(lab["emoji"]))


# --- Досье ---

@router.message(cmd(rf"{PREFIX}{_LAB_WORD}(?:\s+(?P<target>\S+))?"))
async def view_lab(message: Message, m: re.Match, db: Database, gs: GameSettings) -> None:
    viewer = message.from_user.id
    token = m.group("target")
    if token:
        mention_user = mentioned_user(message)
        if mention_user is not None:
            target = mention_user.id
        else:
            ref = parse_target_token(token)
            if ref is None:
                return  # «лаб что-то» — не команда
            target = await resolve_ref(db, ref)
            if target is None:
                await message.answer(texts.NO_INFO_ABOUT_USER)
                return
    else:
        replied = reply_user(message)
        target = replied.id if replied is not None else viewer
    await send_dossier(message, db, gs, target, viewer)


@router.message(cmd(rf"{PREFIX}мл"))
async def mini_lab(message: Message, db: Database) -> None:
    lab = await labs.get(db, message.from_user.id)
    if lab is None:
        await message.answer(view.NO_LAB_MINI)
        return
    await message.answer(view.mini(lab, await corps.membership(db, message.from_user.id)))


@router.message(cmd(r"(?P<sign>[+-])(?:лаб|лаба|лаборатория)"))
async def toggle_dossier(message: Message, m: re.Match, db: Database) -> None:
    is_open = m.group("sign") == "+"
    await labs.set_fields(db, message.from_user.id, dossier_open=int(is_open))
    who = mention(message.from_user.id, message.from_user.full_name)
    await message.answer(view.dossier_toggled(is_open, who))


# --- Названия ---

_RENAMED = {
    "lab": "✅ Название лаборатории изменено на <b><i>«{}»</i></b>",
    "pathogen": "♻️ Новый идентификатор патогена изменён на <b>«{}»</b>",
}


async def _rename(message: Message, db: Database, kind: str, raw: str | None) -> None:
    user_id = message.from_user.id
    lab = await labs.get(db, user_id)
    if lab is None:
        await message.answer(texts.NO_INFO_ABOUT_USER)
        return
    if labs.is_disabled(lab, now_ts()):
        await message.answer(texts.lab_disabled(lab["disabled_reason"]))
        return
    if muted := await name_mute_error(db, user_id, now_ts()):
        await message.answer(muted)
        return
    if raw is None:
        if kind == "pathogen":
            await labs.set_name(db, user_id, kind, None, None)
            await message.answer("❌ Информация о названии патогена утеряна")
        else:
            # как в оригинале: название становится «лаб {имя}» (без ключа уникальности — оно служебное)
            default = f"лаб {lab['full_name']}"
            await labs.set_name(db, user_id, kind, default, None)
            await message.answer(f"❎ Название лаборатории изменено на <b><i>«{escape(default)}»</i></b>")
        return
    name, error = await claim_lab_name(db, user_id, kind, raw)
    await message.answer(error or _RENAMED[kind].format(escape(name)))


@router.message(cmd(r"[+!./]имя\s+патогена\s+(?P<name>.+)"))
async def set_pathogen_name(message: Message, m: re.Match, db: Database) -> None:
    await _rename(message, db, "pathogen", m.group("name"))


@router.message(cmd(r"-имя\s+патогена"))
async def remove_pathogen_name(message: Message, db: Database) -> None:
    await _rename(message, db, "pathogen", None)


@router.message(cmd(rf"[+!./]имя\s+{_LAB_NAME_WORD}\s+(?P<name>.+)"))
async def set_lab_name(message: Message, m: re.Match, db: Database) -> None:
    await _rename(message, db, "lab", m.group("name"))


@router.message(cmd(rf"-имя\s+{_LAB_NAME_WORD}"))
async def remove_lab_name(message: Message, db: Database) -> None:
    await _rename(message, db, "lab", None)
