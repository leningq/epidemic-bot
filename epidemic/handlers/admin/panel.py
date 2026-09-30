"""Админ-панель: меню, статистика, история, глобальные настройки, техработы."""
from __future__ import annotations

import os
import re
from html import escape

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from epidemic import keyboards as kb
from epidemic.config import Config
from epidemic.game import constants as C
from epidemic.db import Database, Tx
from epidemic.game import economy
from epidemic.game.settings import SPECS, GameSettings
from epidemic.handlers.admin.base import ADMIN, OWNER, Staff, log_action
from epidemic.handlers.admin.roles import admins_text
from epidemic.handlers.common import cmd, staff_level
from epidemic.repo import admin as admin_repo
from epidemic.repo import corps, labs, users, victims
from epidemic.utils.fmt import datetime_str, join_limited, num, now_ts

router = Router(name="admin_panel")

# Имена полей для /set_skill и !повысить: русские и английские названия навыков + «готовые» патогены.
SKILL_FIELDS: dict[str, str] = {
    **C.SKILL_ALIASES, **{s: s for s in C.SKILLS}, "готовые": "ready_pathogens", "ready": "ready_pathogens",
}
SKILL_HINT = ", ".join((*C.SKILL_COMMAND.values(), "готовые"))

PANEL_TITLE = "🔐 <b>Панель управления</b>\n\nВсе изменения выполняются только вручную и пишутся в историю."

SECTION_HELP = {
    "labs": (
        "🧪 <b>Лаборатории</b>\n\n"
        "<code>/labinfo ID</code> — досье и служебная информация (ID, @username или ответом)\n"
        "<code>/hide ID</code> / <code>/unhide ID</code> — скрыть/показать в биотопе и случайных целях"
    ),
    "economy": (
        "💰 <b>Экономика</b> (старший администратор и выше)\n\n"
        "<code>/give_res ID СУММА</code> — выдать или забрать (отрицательная сумма) био-ресурсы\n"
        "<code>/give_xp ID СУММА</code> — то же для био-опыта\n"
        "<code>/set_skill ID НАВЫК ЗНАЧЕНИЕ</code> — установить уровень\n"
        f"Навыки: {SKILL_HINT}\n\n"
        "Быстрые команды (себе или ответом на сообщение):\n"
        "<code>!выдать ресурсы 1000</code>, <code>!выдать опыт 1000</code>\n"
        "<code>!повысить заразность 5</code>, <code>!понизить иммунитет 2</code>"
    ),
    "moderation": (
        "🚫 <b>Модерация</b>\n\n"
        "<code>/disable_lab ID [срок] причина</code> — отключить лабораторию (срок: 30m, 12h, 7d)\n"
        "<code>/enable_lab ID</code> — включить\n"
        "<code>/sanction ID причина</code> — предупреждение (игроку придёт ЛС)\n"
        "<code>/sanctions ID</code> — история наказаний\n"
        "<code>+ас ID [срок] [причина]</code> / <code>-ас ID</code> — полный игнор (владелец)"
    ),
    "names": (
        "📝 <b>Названия</b>\n\n"
        "<code>/ban_name lab|pathogen|corp Название | причина</code> — запретить и сбросить у всех\n"
        "<code>/unban_name lab|pathogen|corp Название</code>\n"
        "<code>/names</code> — список запретов\n"
        "<code>/force_rename ID lab|pathogen Название</code>"
    ),
}


async def settings_text(gs: GameSettings) -> str:
    lines = ["⚙️ <b>Глобальные настройки</b>\n"]
    for key, spec in SPECS.items():
        value = gs.get(key)
        shown = ("ВКЛ" if value else "ВЫКЛ") if spec.maximum == 1 else num(value)
        lines.append(f"{spec.title}: <b>{shown}</b>  <code>{key}</code>")
    lines.append("\nИзменение: <code>/set_game_setting KEY VALUE</code>")
    lines.append("Техработы: <code>тех+</code> / <code>тех-</code>")
    return "\n".join(lines)


async def stats_text(db: Database) -> str:
    now = now_ts()
    day_ago = now - 86400
    infections = await db.fetchval(
        "SELECT COUNT(*) FROM infection_log WHERE created_at > ?", (day_ago,), default=0
    )
    chats = await db.fetchval("SELECT COUNT(*) FROM chats", default=0)
    active = await db.fetchval("SELECT COUNT(*) FROM users WHERE is_bot = 0 AND last_seen > ?", (day_ago,), default=0)
    size = os.path.getsize(db.path) if db.path != ":memory:" and os.path.exists(db.path) else 0
    return (
        "📊 <b>Статистика</b>\n\n"
        f"👤 Игроков: <b>{num(await users.count(db))}</b> (активны за сутки: {num(active)})\n"
        f"🧪 Лабораторий: <b>{num(await labs.count(db))}</b>\n"
        f"🦠 Активных заражений: <b>{num(await victims.count_active(db, now))}</b>\n"
        f"🤒 Заражений за сутки: <b>{num(infections)}</b>\n"
        f"🔆 Корпораций: <b>{num(await corps.count(db))}</b>\n"
        f"💬 Чатов: <b>{num(chats)}</b>\n"
        f"💾 База: <b>{size / 1024 / 1024:.1f} МБ</b>"
    )


async def history_text(db: Database, config: Config, limit: int = 20) -> str:
    rows = await admin_repo.history(db, limit)
    if not rows:
        return "📋 История пуста."
    lines = ["📋 <b>История действий</b>\n"]
    for r in rows:
        target = f" → <code>{r['target_id']}</code>" if r["target_id"] else ""
        details = f" — {escape(r['details'])}" if r["details"] else ""
        lines.append(
            f"{datetime_str(r['created_at'], config.tz)} <code>{r['actor_id']}</code>{target}: "
            f"{escape(r['action'])}{details}"
        )
    return join_limited(lines)


@router.message(Command("admin"))
async def admin_panel(message: Message, db: Database, config: Config) -> None:
    if await staff_level(db, config, message.from_user.id) < ADMIN:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(PANEL_TITLE, reply_markup=kb.admin_panel())


@router.callback_query(kb.AdminCb.filter(), Staff(ADMIN))
async def admin_section(
    call: CallbackQuery, callback_data: kb.AdminCb, staff_lvl: int, db: Database, gs: GameSettings, config: Config
) -> None:
    section = callback_data.section
    if section == "main":
        text, markup = PANEL_TITLE, kb.admin_panel()
    elif section == "settings":
        if staff_lvl < OWNER:
            await call.answer("Только владелец может менять глобальные настройки.", show_alert=True)
            return
        text, markup = await settings_text(gs), kb.admin_back()
    elif section == "stats":
        text, markup = await stats_text(db), kb.admin_back()
    elif section == "history":
        text, markup = await history_text(db, config), kb.admin_back()
    elif section == "admins":
        text = await admins_text(db, config) + (
            "\n\n<b>Назначение:</b> <code>+админ ID</code> / <code>-админ ID</code> (старший и выше)\n"
            "<b>Старший:</b> <code>+старший ID</code> / <code>-старший ID</code> (владелец)"
        )
        markup = kb.admin_back()
    elif section in SECTION_HELP:
        text, markup = SECTION_HELP[section], kb.admin_back()
    else:
        await call.answer("Раздел не найден")
        return
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass
    await call.answer()


@router.message(Command("stats"), Staff(ADMIN))
async def stats_command(message: Message, db: Database) -> None:
    await message.answer(await stats_text(db))


@router.message(Command("admin_history"), Staff(ADMIN))
async def history_command(message: Message, command: CommandObject, db: Database, config: Config) -> None:
    arg = (command.args or "").strip()
    limit = min(50, int(arg)) if arg.isdecimal() and int(arg) > 0 else 20
    await message.answer(await history_text(db, config, limit))


@router.message(Command("set_game_setting"), Staff(OWNER))
async def set_game_setting(message: Message, command: CommandObject, db: Database, gs: GameSettings) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.answer("Использование: <code>/set_game_setting KEY VALUE</code>\n\n" + await settings_text(gs))
        return
    key, raw = parts
    if key not in SPECS:
        await message.answer("❌ Неизвестная настройка.\n\n" + await settings_text(gs))
        return
    async def audit(t: Tx) -> None:
        await log_action(t, message.from_user.id, None, "set_game_setting", f"{key}={raw}")

    try:
        await gs.set(key, int(raw), audit=audit)
    except ValueError as exc:
        spec = SPECS[key]
        await message.answer(f"❌ Значение должно быть целым числом от {spec.minimum} до {spec.maximum}. ({escape(str(exc))})")
        return
    if key == "production_speed_multiplier_pct":
        await economy.clamp_timers(db, gs, now_ts())
    await message.answer(f"✅ Настройка <code>{key}</code> установлена: <b>{int(raw)}</b>.")


@router.message(cmd(r"тех(?P<sign>[+-])"), Staff(OWNER))
async def maintenance(message: Message, m: re.Match, db: Database, gs: GameSettings) -> None:
    enabled = m.group("sign") == "+"

    async def audit(t: Tx) -> None:
        await log_action(t, message.from_user.id, None, "maintenance", "on" if enabled else "off")

    await gs.set("maintenance_mode", int(enabled), audit=audit)
    await message.answer(
        "🛠 Технические работы включены. Бот доступен только владельцу."
        if enabled else "🟢 Технические работы завершены. Бот снова доступен всем."
    )
