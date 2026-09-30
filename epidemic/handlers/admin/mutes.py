"""Команды модерации из оригинала: «эпимут», «эпиас», их снятие и списки, «!чек», «!стата»,
«/game_exp», «/search_pathogen». Тексты — views/moderation.py."""
from __future__ import annotations

import re

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from epidemic import texts
from epidemic.config import Config
from epidemic.db import Database, Row
from epidemic.handlers.admin.base import (
    ADMIN, ISSUED_BY_HIGHER, NOT_OUTRANKED, Staff, arg, issued_by_higher, log_action, outranks,
)
from epidemic.handlers.common import PREFIX, cmd, safe_send
from epidemic.middlewares.access import IgnoreList
from epidemic.repo import admin as admin_repo
from epidemic.repo import chats, labs, users
from epidemic.utils import names
from epidemic.utils.fmt import comma, now_ts
from epidemic.utils.parse import parse_target_token
from epidemic.utils.targets import resolve_ref
from epidemic.views import moderation as view

router = Router(name="admin_mutes")

_DAY = 86400
_MUTE_ARGS = r"\s+(?P<days>\d{1,4})\s+(?P<target>\S+)\s+(?P<reason>.+)"


async def _target(message: Message, db: Database, token: str) -> Row | None:
    """Игрок из ссылки/@username/ID; в оригинале без найденной цели команда молчит — сообщаем об этом."""
    target_id = await resolve_ref(db, parse_target_token(token))
    user = await users.get(db, target_id) if target_id is not None else None
    if user is None:
        await message.answer(texts.NO_INFO_ABOUT_USER)
    return user


async def _allowed(
    message: Message, db: Database, config: Config, staff_lvl: int, target_id: int, kind: str
) -> bool:
    """Цель ниже по должности, и её действующий мут этого вида не выдан кем-то выше нас."""
    if not await outranks(db, config, staff_lvl, target_id):
        await message.answer(NOT_OUTRANKED)
        return False
    if await issued_by_higher(db, config, staff_lvl, target_id, kind):
        await message.answer(ISSUED_BY_HIGHER)
        return False
    return True


async def _admins_of(db: Database, rows: list[Row | None]) -> dict[int, Row]:
    found: dict[int, Row] = {}
    for admin_id in {r["created_by"] for r in rows if r is not None}:
        if (admin := await users.get(db, admin_id)) is not None:
            found[admin_id] = admin
    return found


# --- эпимут: запрет на игровые названия ---

@router.message(cmd(rf"{PREFIX}эпимут{_MUTE_ARGS}"), Staff(ADMIN))
async def name_mute(message: Message, m: re.Match, staff_lvl: int, bot: Bot, db: Database, config: Config) -> None:
    user = await _target(message, db, m.group("target"))
    if user is None or not await _allowed(message, db, config, staff_lvl, user["user_id"], "name_mute"):
        return
    days, reason, target = int(m.group("days")), m.group("reason").strip(), user["user_id"]
    now = now_ts()
    async with db.tx() as t:
        # как в оригинале: мут заменяет прежний, названия лаборатории и патогена сбрасываются
        await admin_repo.deactivate(t, target, "name_mute")
        await admin_repo.add_sanction(t, target, "name_mute", reason, message.from_user.id, now, now + days * _DAY)
        await labs.set_name(t, target, "lab", None, None)
        await labs.set_name(t, target, "pathogen", None, None)
        await log_action(t, message.from_user.id, target, "name_mute", f"{days} д.: {reason}")
    await message.answer(view.name_mute_done(target, user["full_name"], days, reason))
    await safe_send(bot, target, view.name_mute_pm(days, reason, config))


@router.message(cmd(r"-эпимут\s+(?P<target>\S+)"), Staff(ADMIN))
async def name_unmute(message: Message, m: re.Match, staff_lvl: int, bot: Bot, db: Database, config: Config) -> None:
    user = await _target(message, db, m.group("target"))
    if user is None or not await _allowed(message, db, config, staff_lvl, user["user_id"], "name_mute"):
        return
    async with db.tx() as t:
        await admin_repo.deactivate(t, user["user_id"], "name_mute")
        await log_action(t, message.from_user.id, user["user_id"], "name_unmute")
    await message.answer(view.name_unmute_done(user["user_id"], user["full_name"]))
    await safe_send(bot, user["user_id"], view.name_unmute_pm(config))


# --- эпиас: игровой мут (бот не реагирует на игрока) ---

@router.message(cmd(rf"{PREFIX}эпиас{_MUTE_ARGS}"), Staff(ADMIN))
async def game_mute(
    message: Message, m: re.Match, staff_lvl: int, bot: Bot, db: Database, config: Config, ignores: IgnoreList
) -> None:
    user = await _target(message, db, m.group("target"))
    if user is None or not await _allowed(message, db, config, staff_lvl, user["user_id"], "game_mute"):
        return
    days, reason, target = int(m.group("days")), m.group("reason").strip(), user["user_id"]
    now = now_ts()
    async with db.tx() as t:
        # как в оригинале: новый мут заменяет прежний. Отдельный вид санкции — чтобы админ через «-эпиас»
        # не мог снять полный игнор («+ас»), который выдаёт только владелец
        await ignores.unignore(t, target, kind="game_mute")
        await ignores.ignore(t, target, reason, message.from_user.id, now, now + days * _DAY, kind="game_mute")
        await log_action(t, message.from_user.id, target, "game_mute", f"{days} д.: {reason}")
    await message.answer(view.game_mute_done(target, user["full_name"], days, reason))
    await safe_send(bot, target, view.game_mute_pm(days, reason, config))


@router.message(cmd(r"-эпиас\s+(?P<target>\S+)"), Staff(ADMIN))
async def game_unmute(
    message: Message, m: re.Match, staff_lvl: int, bot: Bot, db: Database, config: Config, ignores: IgnoreList
) -> None:
    user = await _target(message, db, m.group("target"))
    if user is None or not await _allowed(message, db, config, staff_lvl, user["user_id"], "game_mute"):
        return
    async with db.tx() as t:
        await ignores.unignore(t, user["user_id"], kind="game_mute")
        await log_action(t, message.from_user.id, user["user_id"], "game_unmute")
    await message.answer(view.game_unmute_done(user["user_id"], user["full_name"]))
    await safe_send(bot, user["user_id"], view.game_unmute_pm(config))


# --- Списки и проверка ---

@router.message(cmd(r"!(?P<kind>эпимут|эпиас)"), Staff(ADMIN))
async def mute_list(message: Message, m: re.Match, db: Database, config: Config) -> None:
    name_mutes = m.group("kind").lower() == "эпимут"
    rows = await admin_repo.active_list(db, "name_mute" if name_mutes else "game_mute", now_ts())
    title = view.BIOMUTE_LIST if name_mutes else view.GAMEMUTE_LIST
    await message.answer(view.mute_list(title, rows, await _admins_of(db, rows), config.tz))


@router.message(cmd(rf"{PREFIX}!чек\s+(?P<target>\S+)"), Staff(ADMIN))
async def mute_check(message: Message, m: re.Match, db: Database) -> None:
    # как в оригинале — только со ссылкой на игрока; «!чек» ответом остаётся обычной проверкой жертвы
    user = await _target(message, db, m.group("target"))
    if user is None:
        return
    now = now_ts()
    name_mute_row = await admin_repo.active_sanction(db, user["user_id"], "name_mute", now)
    game_mute_row = await admin_repo.active_sanction(db, user["user_id"], "game_mute", now)
    admins = await _admins_of(db, [name_mute_row, game_mute_row])
    await message.answer(view.mute_check(name_mute_row, game_mute_row, admins))


@router.message(cmd(r"!стата"), Staff(ADMIN))
async def bot_stats(message: Message, db: Database) -> None:
    private_chats, groups = await chats.counts(db)
    await message.answer(view.bot_stats(private_chats, groups, await labs.total_exp(db)))


@router.message(Command("game_exp"), Staff(ADMIN))
async def game_exp(message: Message, db: Database) -> None:
    await message.answer(comma(await labs.total_exp(db)))


@router.message(Command("search_pathogen"), Staff(ADMIN))
async def search_pathogen(message: Message, command: CommandObject, db: Database) -> None:
    query = arg(command)
    rows = await labs.search_pathogen(db, names.name_key(query)) if query else []
    await message.reply(view.pathogen_search(query or "", rows))
