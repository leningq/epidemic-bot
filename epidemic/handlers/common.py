"""Общие помощники хендлеров."""
from __future__ import annotations

import html
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Filter
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from epidemic.config import Config
from epidemic.db import Q
from epidemic.game.settings import GameSettings
from epidemic.repo import admin as admin_repo
from epidemic.repo import users
from epidemic.utils.fmt import mention
from epidemic.utils.parse import PREFIX

log = logging.getLogger(__name__)

__all__ = ["PREFIX", "Cmd", "PrivateChat", "cmd", "safe_send", "send_animation_if_exists", "send_picture",
           "staff_level", "user_mention"]

_CAPTION_LIMIT = 1000
_TAG_RE = re.compile(r"<[^>]+>")


class Cmd(Filter):
    """Текстовая команда: полное совпадение с шаблоном без учёта регистра. Совпадение — аргумент `m`.

    Асинхронный фильтр проверяется прямо в цикле событий. MagicFilter (F.text.regexp) aiogram
    выполняет через поток, а через эти фильтры проходит каждое сообщение группы.
    """

    def __init__(self, pattern: str) -> None:
        self.pattern = re.compile(pattern, re.IGNORECASE | re.DOTALL)

    async def __call__(self, message: Message) -> bool | dict[str, Any]:
        match = self.pattern.fullmatch(message.text or "")
        return {"m": match} if match else False


cmd = Cmd


class PrivateChat(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.chat.type == "private"


async def safe_send(bot: Bot, chat_id: int, text: str) -> bool:
    """Сообщение, которое может не дойти (игрок не запускал бота, бот удалён из чата)."""
    try:
        await bot.send_message(chat_id, text)
        return True
    except TelegramAPIError as exc:
        log.debug("Не удалось отправить в %s: %s", chat_id, exc)
        return False


async def user_mention(q: Q, user_id: int) -> str:
    user = await users.get(q, user_id)
    return mention(user_id, user["full_name"] if user else str(user_id))


def visible_len(html_text: str) -> int:
    return len(html.unescape(_TAG_RE.sub("", html_text)))


async def _send_cached(
    gs: GameSettings,
    config: Config,
    filename: str,
    send: Callable[[Any], Awaitable[Message]],
    file_id_of: Callable[[Message], str | None],
) -> bool:
    """Отправляет файл из media/ с кэшем file_id. False — файла нет.

    Время изменения файла входит в ключ кэша: замена файла приводит к новой загрузке.
    """
    path = config.media_dir / filename
    if not path.is_file():
        return False
    cache_key = f"file_id:{filename}:{int(path.stat().st_mtime)}"
    file_id = await gs.get_meta(cache_key)
    if file_id:
        try:
            await send(file_id)
            return True
        except TelegramBadRequest:
            log.warning("Кэш file_id для %s устарел, загружаю файл заново", filename)
    try:
        sent = await send(FSInputFile(path))
    except TelegramNetworkError as exc:  # медленная сеть: лучше текст без картинки, чем тишина
        log.warning("Не удалось загрузить %s (%s) — отправляю без картинки", filename, exc)
        return False
    new_id = file_id_of(sent)
    if new_id:
        await gs.set_meta(cache_key, new_id)
    return True


async def send_picture(
    message: Message,
    gs: GameSettings,
    config: Config,
    filename: str,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Картинка из media/ с подписью. Нет файла — просто текст. Длинная подпись — отдельным сообщением."""
    fits = visible_len(caption) <= _CAPTION_LIMIT
    sent = await _send_cached(
        gs, config, filename,
        lambda photo: message.answer_photo(
            photo, caption=caption if fits else None, reply_markup=reply_markup if fits else None
        ),
        lambda m: m.photo[-1].file_id if m.photo else None,
    )
    if not sent or not fits:
        await message.answer(caption, reply_markup=reply_markup)


async def send_animation_if_exists(message: Message, gs: GameSettings, config: Config, filename: str) -> None:
    await _send_cached(
        gs, config, filename, message.answer_animation, lambda m: m.animation.file_id if m.animation else None
    )


async def staff_level(q: Q, config: Config, user_id: int) -> int:
    """3 — владелец, 2 — старший админ, 1 — админ, 0 — игрок."""
    if user_id in config.owner_ids:
        return 3
    role = await admin_repo.role(q, user_id)
    return admin_repo.ROLE_LEVEL.get(role, 0) if role else 0
