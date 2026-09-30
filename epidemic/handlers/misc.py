"""Пинг, помощь, список команд и ответ на устаревшие кнопки."""
from __future__ import annotations

import random
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from epidemic import keyboards as kb
from epidemic import texts
from epidemic.config import Config
from epidemic.handlers.common import PREFIX, cmd

router = Router(name="misc")

_PING_PAIRS = {"мяу": "мур", "мур": "мяу"}


@router.message(cmd(rf"{PREFIX}(?P<word>бот|мяу|мур)"))
async def ping(message: Message, m: re.Match) -> None:
    word = m.group("word").lower()
    await message.answer(_PING_PAIRS.get(word) or random.choice(texts.PING_REPLIES))


@router.message(Command("help", "помощь"))
@router.message(cmd(rf"{PREFIX}(?:помощь|help)"))
async def help_command(message: Message, config: Config, bot_username: str) -> None:
    """Как в оригинале: «помощь» показывает то же меню, что и повторный /start."""
    private = message.chat.type == "private"
    await message.answer(texts.start_menu(config), reply_markup=kb.start_menu(config, bot_username, private))


@router.message(cmd(rf"{PREFIX}команды"))
async def commands_list(message: Message, bot_username: str) -> None:
    await message.answer(texts.help_text(bot_username))


@router.callback_query()
async def unknown_button(call: CallbackQuery) -> None:
    """Любая кнопка, которую не обработали выше (старые сообщения, чужие админ-кнопки)."""
    await call.answer(texts.BUTTON_OUTDATED)
