"""Назначение и снятие администраторов."""
from __future__ import annotations

import re
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from epidemic.config import Config
from epidemic.db import Database
from epidemic.handlers.admin.base import ADMIN, OWNER, SENIOR, Staff, arg, log_action, who
from epidemic.handlers.common import PREFIX, cmd
from epidemic.repo import admin as admin_repo
from epidemic.utils.fmt import now_ts
from epidemic.utils.targets import resolve_arg

router = Router(name="admin_roles")


async def admins_text(db: Database, config: Config) -> str:
    text = "👥 <b>Администрация</b>\n\n"
    for owner_id in sorted(config.owner_ids):
        text += f"👑 Владелец: {await who(db, owner_id)}\n"
    rows = await admin_repo.list_admins(db)
    if not rows:
        return text + "\nАдминистраторы пока не назначены."
    text += "\n"
    for r in rows:
        icon, title = ("⭐", "Старший администратор") if r["role"] == "senior" else ("🛡", "Администратор")
        text += f"{icon} {escape(r['full_name'] or str(r['user_id']))} — {title} (<code>{r['user_id']}</code>)\n"
    return text


async def _target(message: Message, db: Database, token: str | None) -> int | None:
    target = await resolve_arg(db, message, token)
    if target is None:
        await message.answer("📝 Укажите пользователя: ID, @username или ответом на сообщение")
    return target


async def _appoint(message: Message, db: Database, config: Config, token: str | None, role: str) -> None:
    target = await _target(message, db, token)
    if target is None:
        return
    if target in config.owner_ids:
        await message.answer("👑 Владелец уже имеет максимальные права.")
        return
    current = await admin_repo.role(db, target)
    if current == role:
        await message.answer("📝 У пользователя уже есть эта роль.")
        return
    if role == "admin" and current == "senior":
        await message.answer("⭐ Это старший администратор. Понизить может только владелец: <code>-старший ID</code>")
        return
    async with db.tx() as t:
        await admin_repo.set_role(t, target, role, message.from_user.id, now_ts())
        await log_action(t, message.from_user.id, target, f"appoint_{role}")
    title = "старшим администратором" if role == "senior" else "администратором"
    await message.answer(f"✅ {await who(db, target)} назначен {title}.")


async def _dismiss(message: Message, db: Database, config: Config, token: str | None, role: str) -> None:
    target = await _target(message, db, token)
    if target is None:
        return
    if target in config.owner_ids:
        await message.answer("👑 Владельца снять нельзя.")
        return
    current = await admin_repo.role(db, target)
    if current != role:
        await message.answer("📝 У пользователя нет этой роли.")
        return
    async with db.tx() as t:
        await admin_repo.remove_role(t, target)
        await log_action(t, message.from_user.id, target, f"remove_{role}")
    await message.answer(f"🔓 {await who(db, target)} снят с должности.")


@router.message(cmd(r"\+админ(?:\s+(?P<target>\S+))?"), Staff(SENIOR))
async def appoint_admin(message: Message, m: re.Match, db: Database, config: Config) -> None:
    await _appoint(message, db, config, m.group("target"), "admin")


@router.message(cmd(r"-админ(?:\s+(?P<target>\S+))?"), Staff(SENIOR))
async def remove_admin(message: Message, m: re.Match, db: Database, config: Config) -> None:
    await _dismiss(message, db, config, m.group("target"), "admin")


@router.message(cmd(r"\+старший(?:\s+(?P<target>\S+))?"), Staff(OWNER))
async def appoint_senior(message: Message, m: re.Match, db: Database, config: Config) -> None:
    await _appoint(message, db, config, m.group("target"), "senior")


@router.message(cmd(r"-старший(?:\s+(?P<target>\S+))?"), Staff(OWNER))
async def remove_senior(message: Message, m: re.Match, db: Database, config: Config) -> None:
    await _dismiss(message, db, config, m.group("target"), "senior")


@router.message(Command("add_admin"), Staff(SENIOR))
async def add_admin_command(message: Message, command: CommandObject, db: Database, config: Config) -> None:
    await _appoint(message, db, config, arg(command), "admin")


@router.message(Command("remove_admin"), Staff(SENIOR))
async def remove_admin_command(message: Message, command: CommandObject, db: Database, config: Config) -> None:
    await _dismiss(message, db, config, arg(command), "admin")


@router.message(cmd(rf"{PREFIX}админы"), Staff(ADMIN))
async def list_admins(message: Message, db: Database, config: Config) -> None:
    await message.answer(await admins_text(db, config))
