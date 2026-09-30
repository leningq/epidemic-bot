"""Тексты модерации оригинала: эпимут (запрет на названия), эпиас (игровой мут), списки, «!чек», «!стата»."""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from epidemic.config import Config
from epidemic.db import Row
from epidemic.repo.labs import display_name
from epidemic.utils.fmt import comma, mention


def _appeal(config: Config, lead: str = "") -> str:
    """Хвост личного сообщения: ссылки на правила и чат для апелляций (если заданы в .env)."""
    parts = []
    if config.rules_url:
        parts.append(f'{lead}<a href="{escape(config.rules_url)}">Правила игры</a>')
    if config.chat_url:
        parts.append(f'чтобы подать апеляцию пишите админам <a href="{escape(config.chat_url)}">здесь</a>')
    return "\n\n" + " ".join(parts) if parts else ""


# --- эпимут: запрет на игровые названия ---

def name_mute_done(user_id: int, name: str, days: int, reason: str) -> str:
    return (
        f"Игроку {mention(user_id, name)} выдан мут на изменение игровых имен на {days} дней\n"
        f"Причина: {escape(reason)}"
    )


def name_mute_pm(days: int, reason: str, config: Config) -> str:
    return (
        f"Вам выдан мут на изменение игровых наименований на {days} дней\n\n"
        f"<b>Причина:</b><i> {escape(reason)}</i>\n"
        "<b>Кем выдан:</b> Telegram" + _appeal(config)
    )


def name_unmute_done(user_id: int, name: str) -> str:
    return f"Игроку {mention(user_id, name)} был снят мут на наименования"


def name_unmute_pm(config: Config) -> str:
    return "Вам был снят мут на наименования" + _appeal(config, "Пожалуйста прочтите ")


# --- эпиас: игровой мут ---

def game_mute_done(user_id: int, name: str, days: int, reason: str) -> str:
    return (
        f"Игроку {mention(user_id, name)} выдан игровой мут на {days} дней\n"
        f"Причина: {escape(reason)}"
    )


def game_mute_pm(days: int, reason: str, config: Config) -> str:
    return (
        f"Вам выдан игровой мут на <b>{days}</b> дней(игровые команды не будут на вас реагировать)\n"
        f"<b>Причина:</b><i> {escape(reason)}</i>\n"
        "<b>Кем выдан:</b> Telegram" + _appeal(config)
    )


def game_unmute_done(user_id: int, name: str) -> str:
    return f"Игроку {mention(user_id, name)} был снят игровой мут"


def game_unmute_pm(config: Config) -> str:
    return "Вам был снят игровой мут" + _appeal(config, "Пожалуйста прочтите ")


# --- списки и проверка ---

def _admin_entity(admin: Row | None, admin_id: int) -> str:
    if admin is None:
        return mention(admin_id, str(admin_id))
    href = f"https://t.me/{admin['username']}" if admin["username"] else f"tg://openmessage?user_id={admin_id}"
    return f'<a href="{href}">{escape(admin["full_name"])}</a>'


def mute_list(title: str, rows: list[Row], admins: dict[int, Row], tz: ZoneInfo) -> str:
    lines = [f"<b>{title}</b>"]
    for i, r in enumerate(rows, 1):
        until = datetime.fromtimestamp(r["expires_at"], tz).strftime("%d.%m.%Y %H:%M") if r["expires_at"] else "навсегда"
        name = escape(r["full_name"] or str(r["user_id"]))
        lines.append(
            f'{i}. <a href="tg://openmessage?user_id={r["user_id"]}">«{name}»</a> | до {until} | '
            f"выдан {_admin_entity(admins.get(r['created_by']), r['created_by'])} | {escape(r['reason'])}"
        )
    return "\n".join(lines)


BIOMUTE_LIST = "Список игроков с биомутом"
GAMEMUTE_LIST = "Список игроков с эпиасом"
NO_LIMITS = "У игрока нету ограничений"


def mute_check(name_mute: Row | None, game_mute: Row | None, admins: dict[int, Row]) -> str:
    if not name_mute and not game_mute:
        return NO_LIMITS
    text = ""
    if name_mute:
        text += (
            "<b>Биомут</b>\n"
            f"Кем выдан: {_admin_entity(admins.get(name_mute['created_by']), name_mute['created_by'])}\n"
            f"Причина: <i>{escape(name_mute['reason'])}</i>\n\n"
        )
    if game_mute:
        text += (
            "<b>Эпиас</b>\n"
            f"Кем выдан: {_admin_entity(admins.get(game_mute['created_by']), game_mute['created_by'])}\n"
            f"Причина: <i>{escape(game_mute['reason'])}</i>"
        )
    return text


def bot_stats(private_chats: int, groups: int, game_exp: int) -> str:
    return (
        "<b>📊 Статистика бота</b>\n"
        f"Личек с ботом: <b>{private_chats}</b>\n"
        f"Публичных чатов: <b>{groups}</b>\n"
        f"Опыт игры: <b>{comma(game_exp)}</b>"
    )


PATHOGEN_NOT_FOUND = "❌ Ни у кого нет такого патогена"


def pathogen_search(query: str, rows: list[Row]) -> str:
    if not rows:
        return PATHOGEN_NOT_FOUND
    text = f'📝 Список людей содержащие в имени патогена "{escape(query)}":'
    for i, r in enumerate(rows, 1):
        text += f"\n{i}. {mention(r['user_id'], display_name(r))}: {escape(r['pathogen_name'])}"
    return text
