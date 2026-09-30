"""Корпорации: команды и кнопки. Правила — в game/corps.py, тексты — в views/corp.py."""
from __future__ import annotations

import re
from html import escape

from aiogram import Bot, Router
from aiogram.types import CallbackQuery, Message, User

from epidemic import keyboards as kb
from epidemic.db import Database
from epidemic.game import constants as C
from epidemic.game import corps as svc
from epidemic.handlers.common import PREFIX, cmd, safe_send, user_mention
from epidemic.repo import corps, labs, victims
from epidemic.utils.fmt import mention, now_ts, user_link
from epidemic.utils.targets import resolve_arg
from epidemic.views import corp as view

router = Router(name="corp")

_CODE = rf"[a-z0-9]{{1,{C.CORP_CODE_LEN}}}"


def _code(m: re.Match) -> str | None:
    return (m.group("code") or "").lower() or None


def _who(user: User) -> str:
    """Упоминание игрока, как в оригинале: ссылка на профиль (tg://user)."""
    return user_link(user.id, user.full_name)


def _who_public(user: User) -> str:
    """Ссылка с учётом username (как entity_create_consider_username в оригинале)."""
    if user.username:
        return f'<a href="https://t.me/{user.username}">{escape(user.full_name)}</a>'
    return mention(user.id, user.full_name)


# --- Просмотр ---

async def _card(db: Database, corp) -> str:
    now = now_ts()
    leader = await labs.get(db, corp["leader_id"]) or {
        "user_id": corp["leader_id"], "full_name": corp["leader_name"], "bio_exp": 0,
    }
    exp, infected, lab_count = await corps.stats(db, corp["corp_id"], now)
    leader_infected = await victims.count_owned(db, corp["leader_id"], now)
    return view.card(corp, leader, leader_infected, exp, infected, lab_count)


@router.message(cmd(rf"{PREFIX}(?:моя\s+)?(?:корпорация|корп)(?:\s+(?P<code>{_CODE}))?"))
async def corp_card(message: Message, m: re.Match, db: Database) -> None:
    result = await svc.visible(db, message.from_user.id, _code(m))
    if result.status != svc.OK:
        await message.answer(view.status_text(result, _who(message.from_user)))
        return
    await message.answer(await _card(db, result.corp), reply_markup=kb.corp_navigation(result.corp["code"]))


async def _members_text(db: Database, viewer: User, code: str | None) -> str:
    result = await svc.visible(db, viewer.id, code)
    if result.status != svc.OK:
        return view.status_text(result, _who(viewer))
    return view.members(result.corp, await corps.members(db, result.corp["corp_id"]))


@router.message(cmd(rf"{PREFIX}корп\s+участники(?:\s+(?P<code>{_CODE}))?"))
async def corp_members(message: Message, m: re.Match, db: Database) -> None:
    await message.answer(await _members_text(db, message.from_user, _code(m)))


@router.message(cmd(rf"{PREFIX}(?:биотоп\s+корп|корп\s+топ)"))
async def corp_top(message: Message, db: Database) -> None:
    await message.answer(view.top(await corps.top(db, C.CORP_TOP_LIMIT)))


@router.message(cmd(rf"{PREFIX}корп\s+соруки"))
async def corp_staff_list(message: Message, db: Database) -> None:
    corp = await corps.membership(db, message.from_user.id)
    if corp is None or corp["role"] != "leader":
        await message.answer(view.NOT_LEADER)
        return
    await message.answer(view.staff(corp, await corps.staff(db, corp["corp_id"])))


@router.message(cmd(rf"{PREFIX}корп\s+заявки"))
async def corp_requests(message: Message, db: Database) -> None:
    corp = await corps.membership(db, message.from_user.id)
    if corp is None or corp["role"] not in svc.STAFF_ROLES:
        await message.answer(view.LAB_NOT_IN_CORP if corp is None else view.NOT_STAFF)
        return
    await message.answer(view.requests(corp, await corps.requests(db, corp["corp_id"])))


# --- Создание, переименование, досье, удаление ---

@router.message(cmd(rf"{PREFIX}корп\s+создать(?:\s+(?P<name>.+))?"))
async def corp_create(message: Message, m: re.Match, db: Database) -> None:
    if not m.group("name"):
        await message.answer(view.NAME_USAGE)
        return
    result = await svc.create(db, message.from_user.id, m.group("name"), now_ts())
    await message.answer(view.created(result.name, result.code) if result.status == svc.OK else view.status_text(result))


@router.message(cmd(rf"{PREFIX}корп\s+изменить\s+(?P<name>.+)"))
async def corp_rename(message: Message, m: re.Match, db: Database) -> None:
    result = await svc.rename(db, message.from_user.id, m.group("name"))
    await message.answer(view.renamed(result.name) if result.status == svc.OK else view.status_text(result))


@router.message(cmd(r"(?P<sign>[+-])корп\s+досье"))
async def corp_dossier(message: Message, m: re.Match, db: Database) -> None:
    is_open = m.group("sign") == "+"
    result = await svc.set_dossier(db, message.from_user.id, is_open)
    if result.status == svc.OK:
        await message.answer(view.DOSSIER_OPENED if is_open else view.DOSSIER_HIDDEN)
    else:
        await message.answer(view.status_text(result))


@router.message(cmd(rf"{PREFIX}корп\s+(?:удалить|ликвидировать)"))
async def corp_delete(message: Message, db: Database) -> None:
    result = await svc.delete(db, message.from_user.id)
    await message.answer(view.deleted(result.corp["name"]) if result.status == svc.OK else view.status_text(result))


# --- Вступление ---

async def request_join(db: Database, user: User, code: str, inline: bool = False) -> str:
    result = await svc.request(db, user.id, code, now_ts())
    if result.status == svc.OK:
        return view.request_sent(_who(user) if inline else _who_public(user), result.corp["name"])
    # у кнопки «Вступить» ошибки начинаются с упоминания нажавшего, как в оригинале
    return view.status_text(result, _who(user) if inline else None)


@router.message(cmd(rf"\+корп\s+(?P<code>{_CODE})"))
async def corp_request(message: Message, m: re.Match, db: Database) -> None:
    await message.answer(await request_join(db, message.from_user, _code(m)))


async def _target(message: Message, db: Database, m: re.Match) -> int | None:
    target = await resolve_arg(db, message, m.group("target"))
    if target is None:
        await message.answer(view.TARGET_USAGE)
    return target


@router.message(cmd(rf"{PREFIX}корп\s+принять(?:\s+(?P<target>\S+))?"))
async def corp_accept(message: Message, m: re.Match, bot: Bot, db: Database) -> None:
    target = await _target(message, db, m)
    if target is None:
        return
    result = await svc.accept(db, message.from_user.id, target, now_ts())
    if result.status != svc.OK:
        await message.answer(view.status_text(result))
        return
    await message.answer(view.accepted(await user_mention(db, target)))
    await safe_send(bot, target, view.accepted_pm(result.corp["name"]))


@router.message(cmd(rf"{PREFIX}корп\s+отказать(?:\s+(?P<target>\S+))?"))
async def corp_reject(message: Message, m: re.Match, db: Database) -> None:
    target = await _target(message, db, m)
    if target is None:
        return
    result = await svc.reject(db, message.from_user.id, target)
    await message.answer(view.REQUEST_REJECTED if result.status == svc.OK else view.status_text(result))


# --- Состав ---

@router.message(cmd(r"-корп"))
async def corp_leave(message: Message, db: Database) -> None:
    result = await svc.leave(db, message.from_user.id)
    await message.answer(view.left(result.corp["name"]) if result.status == svc.OK else view.status_text(result))


@router.message(cmd(rf"{PREFIX}корп\s+кик(?:\s+(?P<target>\S+))?"))
async def corp_kick(message: Message, m: re.Match, db: Database) -> None:
    target = await _target(message, db, m)
    if target is None:
        return
    result = await svc.kick(db, message.from_user.id, target)
    if result.status == svc.OK:
        await message.answer(view.kicked(await user_mention(db, target), mention(target, result.corp["name"])))
    else:
        await message.answer(view.status_text(result))


@router.message(cmd(r"(?P<sign>[+-])корп\s+сорук(?:\s+(?P<target>\S+))?"))
async def corp_staff_toggle(message: Message, m: re.Match, db: Database) -> None:
    target = await _target(message, db, m)
    if target is None:
        return
    promote = m.group("sign") == "+"
    result = await svc.set_admin(db, message.from_user.id, target, promote)
    who = await user_mention(db, target)
    texts_by_status = {
        svc.OK: view.admin_added(who) if promote else view.admin_removed(who),
        svc.ALREADY_ADMIN: view.already_admin(who),
        svc.NOT_ADMIN: view.not_admin(who),
    }
    await message.answer(texts_by_status.get(result.status) or view.status_text(result))


# Последним среди «+корп …»: код не того вида («+корп код», «+корп абв») или его нет вовсе.
# Раньше такая команда молча не срабатывала — теперь игрок видит, что не так.
@router.message(cmd(r"\+корп(?:\s+(?P<code>.+))?"))
async def corp_request_bad_code(message: Message, m: re.Match) -> None:
    await message.answer(view.CORP_NOT_FOUND if m.group("code") else view.JOIN_USAGE)


# --- Кнопки под карточкой ---

@router.callback_query(kb.CorpCb.filter())
async def corp_button(call: CallbackQuery, callback_data: kb.CorpCb, db: Database) -> None:
    await call.answer()
    if not isinstance(call.message, Message):
        return
    if callback_data.action == "members":
        await call.message.answer(view.button_pressed(_who(call.from_user)))
        await call.message.answer(await _members_text(db, call.from_user, callback_data.code))
    else:
        await call.message.answer(await request_join(db, call.from_user, callback_data.code, inline=True))
