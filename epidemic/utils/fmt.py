"""Форматирование: числа, ссылки на игроков, время, склонения."""
from __future__ import annotations

import re
import time
from datetime import datetime
from html import escape
from urllib.parse import quote
from zoneinfo import ZoneInfo

# Символы, которыми ломают вёрстку: управление направлением текста, невидимые разделители.
_BIDI_RE = re.compile("[‎‏‪-‮⁦-⁩  \u0000-\u0008\u000b-\u001f\u007f]")


MESSAGE_BUDGET = 3800  # лимит Telegram — 4096 символов; оставляем запас на заголовок


def now_ts() -> int:
    return int(time.time())


def join_limited(lines: list[str], budget: int = MESSAGE_BUDGET) -> str:
    """Склеивает строки, пока текст помещается в сообщение. Строки не режутся — HTML-теги остаются целыми."""
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 > budget:
            out.append(f"… и ещё {len(lines) - i}")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def num(value: int | float) -> str:
    """1234567 → «1 234 567» (как в оригинале — только досье «лаб» и «мл»)."""
    return f"{int(value):,}".replace(",", " ")


def comma(value: int | float) -> str:
    """1234567 → «1,234,567» (как intcomma в оригинале — все остальные сообщения)."""
    return f"{int(value):,}"


def ref_hms(seconds: int) -> str:
    """Формат времени горячки и таймера патогена из оригинала: «1 часов 5 минут 3 секунд».

    Склонения намеренно как в оригинале (клиенту нужен бот 1 в 1).
    """
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} часов {minutes} минут {secs} секунд"
    if minutes:
        return f"{minutes} минут {secs} секунд"
    return f"{secs} секунд"


def ref_hm(seconds: int) -> str:
    """Формат времени КД из оригинала: «2 часов 5 минут», «5 минут», «40 секунд»."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} часов {minutes} минут"
    if minutes:
        return f"{minutes} минут"
    return f"{secs} секунд"


def clean_name(name: str | None, fallback: str = "Безымянный", limit: int = 64) -> str:
    """Имя пользователя без управляющих символов, обрезанное по длине.

    Пробелы внутри имени сохраняются как есть — в оригинале «С ТИКТОКА  Lening123124» с двумя пробелами.
    """
    text = _BIDI_RE.sub("", name or "").strip()
    return text[:limit] or fallback


def mention(user_id: int, name: str) -> str:
    """Ссылка на игрока (как в оригинале — tg://openmessage)."""
    return f'<a href="tg://openmessage?user_id={int(user_id)}">{escape(name)}</a>'


def user_link(user_id: int, name: str) -> str:
    """Кликабельное упоминание (tg://user) — открывает профиль."""
    return f'<a href="tg://user?id={int(user_id)}">{escape(name)}</a>'


def cmd_link(bot_username: str, command: str, label: str | None = None) -> str:
    """Ссылка, которая подставляет команду в поле ввода чата с ботом."""
    label = escape(label if label is not None else command)
    return f'<a href="https://t.me/{bot_username}?text={quote(command)}">{label}</a>'


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(5, ('минута', 'минуты', 'минут')) → 'минут'."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


_H = ("час", "часа", "часов")
_M = ("минута", "минуты", "минут")
_S = ("секунда", "секунды", "секунд")
_D = ("день", "дня", "дней")


def duration(seconds: int) -> str:
    """Человекочитаемая длительность: старшая ненулевая единица и следующая за ней.

    «1 день 3 часа», «1 час 5 минут», «3 минуты 10 секунд», «40 секунд».
    """
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    units = [(days, _D), (hours, _H), (minutes, _M), (secs, _S)]
    for i, (value, forms) in enumerate(units[:-1]):
        if value:
            parts = [f"{value} {plural(value, forms)}"]
            next_value, next_forms = units[i + 1]
            if next_value:
                parts.append(f"{next_value} {plural(next_value, next_forms)}")
            return " ".join(parts)
    return f"{secs} {plural(secs, _S)}"


def date(ts: int, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m.%Y")


def datetime_str(ts: int, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m.%Y %H:%M")


def chance(value: float) -> str:
    """Шанс пробития: до 100 %, с точностью как в оригинале (4 знака)."""
    value = min(100.0, max(0.0, value))
    text = f"{value:.4f}"
    return text if float(text) > 0 else f"{value:.10f}"
