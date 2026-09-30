"""Управление игроками: досье, экономика, модерация, названия."""
from __future__ import annotations

import re
from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from epidemic.config import Config
from epidemic.db import Database, Row, Tx
from epidemic.game import upgrade
from epidemic.game.naming import claim_lab_name, fallback_corp_name
from epidemic.game.settings import GameSettings
from epidemic.handlers.admin.base import (
    ADMIN, ISSUED_BY_HIGHER, MAX_AMOUNT, MAX_SKILL_LEVEL, NOT_OUTRANKED, OWNER, SENIOR, Staff, arg,
    issued_by_higher, log_action, outranks, term, who,
)
from epidemic.handlers.admin.panel import SKILL_FIELDS, SKILL_HINT
from epidemic.handlers.common import cmd, safe_send
from epidemic.handlers.lab import dossier_text
from epidemic.middlewares.access import IgnoreList
from epidemic.repo import admin as admin_repo
from epidemic.repo import corps, labs
from epidemic.utils import names
from epidemic.utils.fmt import datetime_str, join_limited, num, now_ts
from epidemic.utils.parse import parse_duration, parse_target_token
from epidemic.utils.targets import resolve_arg, resolve_ref

router = Router(name="admin_manage")

USAGE_TARGET = "📝 Укажите игрока: ID, @username или ответом на сообщение"
LAB_NOT_FOUND = "📝 Лаборатория не найдена."


def _int(token: str, limit: int = MAX_AMOUNT) -> int | None:
    """Целое число не больше limit по модулю (иначе None)."""
    try:
        value = int(token)
    except ValueError:
        return None
    return value if abs(value) <= limit else None


async def _lab_target(
    message: Message, db: Database, token: str | None, default: int | None = None
) -> tuple[int | None, Row | None]:
    """Игрок из аргумента/упоминания/ответа (или default). Ошибку сообщает сам."""
    target = await resolve_arg(db, message, token) or default
    if target is None:
        await message.answer(USAGE_TARGET)
        return None, None
    lab = await labs.get(db, target)
    if lab is None:
        await message.answer(LAB_NOT_FOUND)
        return None, None
    return target, lab


# --- Досье ---

@router.message(Command("labinfo"), Staff(ADMIN))
async def labinfo(message: Message, command: CommandObject, db: Database, gs: GameSettings, config: Config) -> None:
    target, lab = await _lab_target(message, db, arg(command))
    if lab is None:
        return
    now = now_ts()
    status = "🟢 активна"
    if labs.is_disabled(lab, now):
        until = f" до {datetime_str(lab['disabled_until'], config.tz)}" if lab["disabled_until"] else " бессрочно"
        status = f"🚫 отключена{until}: {escape(lab['disabled_reason'] or '—')}"
    sanctions = await admin_repo.sanctions_of(db, target, 100)
    await message.answer(
        await dossier_text(db, gs, lab, now)
        + "\n\n<b>🔐 Служебное</b>\n"
        f"Статус: {status}\n"
        f"Скрыта в биотопе: {'да' if lab['hidden'] else 'нет'}\n"
        f"Username: {('@' + escape(lab['username'])) if lab['username'] else '—'}\n"
        f"Уведомления: <code>{lab['notify_chat_id'] or 'выключены'}</code>\n"
        f"Создана: {datetime_str(lab['created_at'], config.tz)}\n"
        f"Наказаний: {len(sanctions)}"
    )


@router.message(Command("hide", "unhide"), Staff(SENIOR))
async def hide(message: Message, command: CommandObject, staff_lvl: int, db: Database, config: Config) -> None:
    target, lab = await _lab_target(message, db, arg(command))
    if lab is None:
        return
    if not await outranks(db, config, staff_lvl, target):
        await message.answer(NOT_OUTRANKED)
        return
    hidden = command.command == "hide"
    async with db.tx() as t:
        await labs.set_fields(t, target, hidden=int(hidden))
        await log_action(t, message.from_user.id, target, command.command)
    await message.answer(f"{'🙈 Скрыт' if hidden else '👀 Снова виден'}: {await who(db, target)}")


# --- Экономика ---

async def _change_currency(message: Message, db: Database, target: int, field: str, amount: int) -> None:
    async with db.tx() as t:
        if field == "bio_res":
            await labs.add_resources(t, target, amount)
        else:
            await labs.add_exp(t, target, amount)
        await log_action(t, message.from_user.id, target, f"give_{field}", str(amount))
    lab = await labs.get(db, target)
    icon, title = ("🧬", "ресурсов") if field == "bio_res" else ("☣️", "опыта")
    sign = "+" if amount >= 0 else "−"
    await message.answer(f"{icon} {await who(db, target)}: {sign}{num(abs(amount))} {title}. Теперь: {num(lab[field])}")


async def _may_harm(message: Message, db: Database, config: Config, staff_lvl: int, target: int) -> bool:
    """Отнимать ресурсы и менять уровни можно себе и тем, кто ниже по должности."""
    if target == message.from_user.id or await outranks(db, config, staff_lvl, target):
        return True
    await message.answer(NOT_OUTRANKED)
    return False


@router.message(Command("give_res", "give_xp"), Staff(SENIOR))
async def give_currency(message: Message, command: CommandObject, staff_lvl: int, db: Database, config: Config) -> None:
    parts = (command.args or "").split()
    amount = _int(parts[-1]) if parts else None
    if amount is None or len(parts) > 2:
        await message.answer(
            f"Использование: <code>/{command.command} ID СУММА</code> (или ответом: <code>/{command.command} СУММА</code>)"
        )
        return
    target, lab = await _lab_target(message, db, parts[0] if len(parts) == 2 else None)
    if lab is None or (amount < 0 and not await _may_harm(message, db, config, staff_lvl, target)):
        return
    await _change_currency(message, db, target, "bio_res" if command.command == "give_res" else "bio_exp", amount)


@router.message(cmd(r"!выдать\s+(?P<what>ресурсы|опыт)\s+(?P<amount>-?\d{1,12})"), Staff(OWNER))
async def quick_give(message: Message, m: re.Match, staff_lvl: int, db: Database, config: Config) -> None:
    target, lab = await _lab_target(message, db, None, default=message.from_user.id)
    amount = int(m.group("amount"))
    if lab is None or (amount < 0 and not await _may_harm(message, db, config, staff_lvl, target)):
        return
    field = "bio_res" if m.group("what").lower() == "ресурсы" else "bio_exp"
    await _change_currency(message, db, target, field, amount)


async def _set_level(message: Message, db: Database, target: int, field: str, value: int) -> None:
    async def audit(t: Tx, old: int, new: int) -> None:
        await log_action(t, message.from_user.id, target, "set_skill", f"{field}: {old} → {new}")

    result = await upgrade.set_level(db, target, field, value, on_change=audit)
    if result is None:
        await message.answer(LAB_NOT_FOUND)
        return
    old, new = result
    await message.answer(f"📈 {await who(db, target)}: <b>{field}</b> {num(old)} → {num(new)}")


@router.message(Command("set_skill"), Staff(SENIOR))
async def set_skill(message: Message, command: CommandObject, staff_lvl: int, db: Database, config: Config) -> None:
    parts = (command.args or "").split()
    if len(parts) not in (2, 3) or parts[-2].lower() not in SKILL_FIELDS or _int(parts[-1], MAX_SKILL_LEVEL) is None:
        await message.answer(f"Использование: <code>/set_skill ID НАВЫК ЗНАЧЕНИЕ</code>\nНавыки: {SKILL_HINT}")
        return
    target, lab = await _lab_target(message, db, parts[0] if len(parts) == 3 else None)
    if lab is not None and await _may_harm(message, db, config, staff_lvl, target):
        await _set_level(message, db, target, SKILL_FIELDS[parts[-2].lower()], int(parts[-1]))


@router.message(cmd(r"!(?P<op>повысить|понизить)\s+(?P<skill>\S+)\s+(?P<amount>\d{1,6})"), Staff(OWNER))
async def quick_skill(message: Message, m: re.Match, staff_lvl: int, db: Database, config: Config) -> None:
    field = SKILL_FIELDS.get(m.group("skill").lower())
    if field is None:
        await message.answer(f"❌ Неизвестный навык. Доступно: {SKILL_HINT}")
        return
    target, lab = await _lab_target(message, db, None, default=message.from_user.id)
    if lab is not None and await _may_harm(message, db, config, staff_lvl, target):
        delta = int(m.group("amount")) * (1 if m.group("op").lower() == "повысить" else -1)
        await _set_level(message, db, target, field, lab[field] + delta)


# --- Модерация ---

async def _target_term_reason(message: Message, db: Database, raw: str | None) -> tuple[int | None, int | None, str]:
    """Разбор «[цель] [срок] [причина]». Цель — первое слово, если это ID/@username/ссылка,
    иначе упоминание или автор сообщения, на которое ответили. Срок: 30m, 12h, 7d."""
    tokens = (raw or "").split()
    ref = parse_target_token(tokens[0]) if tokens else None
    if ref is not None:
        target = await resolve_ref(db, ref)
        tokens = tokens[1:]
    else:
        target = await resolve_arg(db, message, None)
    seconds = parse_duration(tokens[0]) if tokens else None
    if seconds:
        tokens = tokens[1:]
    return target, seconds, " ".join(tokens)


@router.message(Command("disable_lab"), Staff(ADMIN))
async def disable_lab(
    message: Message, command: CommandObject, staff_lvl: int, bot: Bot, db: Database, config: Config
) -> None:
    target, seconds, reason = await _target_term_reason(message, db, command.args)
    if target is None or not reason:
        await message.answer(
            "Использование: <code>/disable_lab ID [срок] причина</code> (срок: 30m, 12h, 7d) — или ответом на сообщение"
        )
        return
    if await labs.get(db, target) is None:
        await message.answer(LAB_NOT_FOUND)
        return
    if not await outranks(db, config, staff_lvl, target):
        await message.answer(NOT_OUTRANKED)
        return
    if await issued_by_higher(db, config, staff_lvl, target, "lab_disabled"):
        await message.answer(ISSUED_BY_HIGHER)
        return
    now = now_ts()
    until = now + seconds if seconds else None
    async with db.tx() as t:
        await labs.set_fields(t, target, disabled=1, disabled_reason=reason[:300], disabled_until=until)
        await admin_repo.add_sanction(t, target, "lab_disabled", reason, message.from_user.id, now, until)
        await log_action(t, message.from_user.id, target, "disable_lab", reason)
    await message.answer(f"🚫 Лаборатория {await who(db, target)} отключена {term(seconds)}.")
    await safe_send(bot, target, f"🚫 Ваша лаборатория отключена администрацией {term(seconds)}.\nПричина: {escape(reason)}")


@router.message(Command("enable_lab"), Staff(ADMIN))
async def enable_lab(
    message: Message, command: CommandObject, staff_lvl: int, bot: Bot, db: Database, config: Config
) -> None:
    target, lab = await _lab_target(message, db, arg(command))
    if lab is None:
        return
    # снять отключение может только тот, кто выше по должности (и не с самого себя),
    # и только если отключал не кто-то выше него
    if not await outranks(db, config, staff_lvl, target):
        await message.answer(NOT_OUTRANKED)
        return
    if await issued_by_higher(db, config, staff_lvl, target, "lab_disabled"):
        await message.answer(ISSUED_BY_HIGHER)
        return
    async with db.tx() as t:
        await labs.set_fields(t, target, disabled=0, disabled_reason=None, disabled_until=None)
        await admin_repo.deactivate(t, target, "lab_disabled")
        await log_action(t, message.from_user.id, target, "enable_lab")
    await message.answer(f"🔓 Лаборатория {await who(db, target)} включена.")
    await safe_send(bot, target, "🔓 Ваша лаборатория снова активна.")


@router.message(Command("sanction"), Staff(ADMIN))
async def sanction(
    message: Message, command: CommandObject, staff_lvl: int, bot: Bot, db: Database, config: Config
) -> None:
    target, _, reason = await _target_term_reason(message, db, command.args)
    if target is None or not reason:
        await message.answer("Использование: <code>/sanction ID причина</code> — или ответом на сообщение")
        return
    if not await outranks(db, config, staff_lvl, target):
        await message.answer(NOT_OUTRANKED)
        return
    async with db.tx() as t:
        await admin_repo.add_sanction(t, target, "warning", reason, message.from_user.id, now_ts())
        await log_action(t, message.from_user.id, target, "warning", reason)
    await message.answer(f"⚠️ Предупреждение выдано: {await who(db, target)}")
    await safe_send(bot, target, f"⚠️ Вам вынесено предупреждение администрации.\nПричина: {escape(reason)}")


_SANCTION_KINDS = {
    "warning": "⚠️ предупреждение",
    "ignore": "🔇 игнор",
    "lab_disabled": "🚫 отключение",
    "name_mute": "📕 эпимут (названия)",
    "game_mute": "🔇 эпиас (игровой мут)",
}


@router.message(Command("sanctions"), Staff(ADMIN))
async def sanctions(message: Message, command: CommandObject, db: Database, config: Config) -> None:
    target = await resolve_arg(db, message, arg(command))
    if target is None:
        await message.answer(USAGE_TARGET)
        return
    rows = await admin_repo.sanctions_of(db, target)
    if not rows:
        await message.answer(f"✅ У {await who(db, target)} нет наказаний.")
        return
    lines = [f"📋 Наказания {await who(db, target)}:\n"]
    for r in rows:
        state = "" if r["active"] else " (снято)"
        lines.append(f"{datetime_str(r['created_at'], config.tz)} — {_SANCTION_KINDS[r['kind']]}{state}: {escape(r['reason'])}")
    await message.answer(join_limited(lines))


@router.message(cmd(r"\+ас(?:\s+(?P<args>.+))?"), Staff(OWNER))
async def ignore_on(message: Message, m: re.Match, db: Database, config: Config, ignores: IgnoreList) -> None:
    target, seconds, reason = await _target_term_reason(message, db, m.group("args"))
    if target is None:
        await message.answer(USAGE_TARGET)
        return
    if target in config.owner_ids:
        await message.answer("👑 Владельца игнорировать нельзя.")
        return
    now = now_ts()
    reason = reason or "Полный игнор"
    requested = now + seconds if seconds else None
    async with db.tx() as t:
        await ignores.ignore(t, target, reason, message.from_user.id, now, requested)
        await log_action(t, message.from_user.id, target, "ignore_on", reason)
    # действует самый длинный игнор: временный не сокращает уже выданный бессрочный — так и отвечаем
    effective = ignores.until(target)
    if effective != requested:  # значит, уже действовал более длинный
        tail = "бессрочно" if effective is None else f"до {datetime_str(effective, config.tz)}"
        await message.answer(f"🔇 Полный игнор уже действует {tail}: {await who(db, target)}")
        return
    await message.answer(f"🔇 Полный игнор {term(seconds)}: {await who(db, target)}")


@router.message(cmd(r"-ас(?:\s+(?P<target>\S+))?"), Staff(OWNER))
async def ignore_off(message: Message, m: re.Match, db: Database, ignores: IgnoreList) -> None:
    target = await resolve_arg(db, message, m.group("target"))
    if target is None:
        await message.answer(USAGE_TARGET)
        return
    async with db.tx() as t:
        await ignores.unignore(t, target)
        await log_action(t, message.from_user.id, target, "ignore_off")
    await message.answer(f"🔊 Полный игнор снят: {await who(db, target)}")


# --- Названия ---

_KINDS = ("lab", "pathogen", "corp")


@router.message(Command("ban_name"), Staff(ADMIN))
async def ban_name(message: Message, command: CommandObject, db: Database) -> None:
    kind, _, rest = (command.args or "").strip().partition(" ")
    name, sep, reason = rest.partition("|")
    name, reason = names.normalize(name), reason.strip()
    if kind not in _KINDS or not name or not sep or not reason:
        await message.answer("Использование: <code>/ban_name lab|pathogen|corp Название | причина</code>")
        return
    key = names.name_key(name)
    async with db.tx() as t:
        added = await admin_repo.ban_name(t, kind, name, key, reason, message.from_user.id, now_ts())
        reset = 0
        if added and kind == "corp":
            corp_id = await corps.name_owner(t, key)
            if corp_id is not None:
                await corps.rename(t, corp_id, *fallback_corp_name(corp_id))
                reset = 1
        elif added:
            reset = await labs.reset_names(t, kind, key)
        if added:
            await log_action(t, message.from_user.id, None, "ban_name", f"{kind}:{name} / {reason}")
    if not added:
        await message.answer("📝 Это название уже запрещено.")
        return
    await message.answer(f"🚫 Название «{escape(name)}» запрещено. Сброшено у {reset}.")


@router.message(Command("unban_name"), Staff(ADMIN))
async def unban_name(message: Message, command: CommandObject, db: Database) -> None:
    kind, _, name = (command.args or "").strip().partition(" ")
    if kind not in _KINDS or not name.strip():
        await message.answer("Использование: <code>/unban_name lab|pathogen|corp Название</code>")
        return
    async with db.tx() as t:
        removed = await admin_repo.unban_name(t, kind, names.name_key(name))
        await log_action(t, message.from_user.id, None, "unban_name", f"{kind}:{name.strip()}")
    await message.answer("🔓 Запрет снят." if removed else "📝 Такого запрета нет.")


@router.message(Command("names"), Staff(ADMIN))
async def banned_names(message: Message, db: Database) -> None:
    rows = await admin_repo.banned_names(db)
    if not rows:
        await message.answer("📝 Список запрещённых названий пуст.")
        return
    lines = ["📝 <b>Запрещённые названия</b>\n"]
    lines += [f"[{r['kind']}] <b>{escape(r['name'])}</b> — {escape(r['reason'])}" for r in rows]
    await message.answer(join_limited(lines))


@router.message(Command("force_rename"), Staff(ADMIN))
async def force_rename(message: Message, command: CommandObject, staff_lvl: int, db: Database, config: Config) -> None:
    parts = (command.args or "").split(maxsplit=2)
    if len(parts) != 3 or parts[1] not in ("lab", "pathogen"):
        await message.answer("Использование: <code>/force_rename ID lab|pathogen Название</code>")
        return
    target, lab = await _lab_target(message, db, parts[0])
    if lab is None:
        return
    if target != message.from_user.id and not await outranks(db, config, staff_lvl, target):
        await message.answer(NOT_OUTRANKED)
        return
    kind = parts[1]
    # администратор не ограничен набором символов и запретами — только длиной и уникальностью
    async def audit(t: Tx, name: str) -> None:
        await log_action(t, message.from_user.id, target, "force_rename", f"{kind}: {name}")

    name, error = await claim_lab_name(db, target, kind, parts[2], strict=False, on_claim=audit)
    if error:
        await message.answer(error)
        return
    await message.answer(f"✅ Готово: {await who(db, target)} → «{escape(name)}»")
