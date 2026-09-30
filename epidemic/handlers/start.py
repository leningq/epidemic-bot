"""/start, экскурс по механикам (7 шагов) и меню для вернувшихся игроков.

Как в оригинале: каждый шаг экскурса — новое сообщение, предыдущее удаляется.
"""
from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from epidemic import keyboards as kb
from epidemic import texts
from epidemic.config import Config
from epidemic.db import Database
from epidemic.game.settings import GameSettings
from epidemic.handlers.common import PrivateChat, send_animation_if_exists, send_picture
from epidemic.repo import users

router = Router(name="start")
router.message.filter(PrivateChat())

TUTORIAL_BEGIN_IMG = "tutorial_begin.jpg"
TUTORIAL_END_IMG = "tutorial_end.jpg"
TUTORIAL_END_GIF = "tutorial_end.mp4"
LAST_STEP = 7


async def _send_start_action(message: Message, gs: GameSettings, config: Config, bot_username: str) -> None:
    await send_picture(
        message, gs, config, TUTORIAL_BEGIN_IMG, texts.start_action(bot_username), kb.start_action(bot_username)
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message, command: CommandObject, db: Database, gs: GameSettings, config: Config, bot_username: str
) -> None:
    user = await users.get(db, message.from_user.id)
    # «/start begin» — ссылка «Вернуться в начало» из меню в группе
    if user is None or not user["tutorial_done"] or command.args == kb.BEGIN_PAYLOAD:
        await _send_start_action(message, gs, config, bot_username)
        return
    await message.answer(texts.start_menu(config), reply_markup=kb.start_menu(config, bot_username))


@router.message(Command("restart_tutorial"))
async def cmd_restart_tutorial(
    message: Message, db: Database, gs: GameSettings, config: Config, bot_username: str
) -> None:
    await users.set_tutorial_done(db, message.from_user.id, False)
    await _send_start_action(message, gs, config, bot_username)


async def _safe_delete(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


@router.callback_query(kb.MenuCb.filter())
async def back_to_begin(call: CallbackQuery, gs: GameSettings, config: Config, bot_username: str) -> None:
    """«Вернуться в начало»: меню сменяется первым экраном /start. Пройденное обучение не сбрасывается."""
    await call.answer()
    if not isinstance(call.message, Message):
        return
    await _safe_delete(call.message)
    await _send_start_action(call.message, gs, config, bot_username)


@router.callback_query(kb.TutorialCb.filter())
async def tutorial_step(
    call: CallbackQuery,
    callback_data: kb.TutorialCb,
    db: Database,
    gs: GameSettings,
    config: Config,
    bot_username: str,
) -> None:
    await call.answer()
    message = call.message
    if not isinstance(message, Message):
        return
    step = callback_data.step
    await _safe_delete(message)

    if step == 0:
        await users.set_tutorial_done(db, call.from_user.id, True)
        await message.answer(texts.tutorial_discontinue(bot_username))
    elif step == 1:
        await message.answer(texts.tutorial_continue(bot_username), reply_markup=kb.tutorial_next(2))
    elif step < LAST_STEP:
        await message.answer(texts.tutorial_step(step, bot_username), reply_markup=kb.tutorial_next(step + 1))
    else:
        await users.set_tutorial_done(db, call.from_user.id, True)
        await send_picture(
            message, gs, config, TUTORIAL_END_IMG,
            texts.tutorial_final(config, bot_username), kb.add_to_chat(bot_username),
        )
        await asyncio.sleep(1)
        await send_animation_if_exists(message, gs, config, TUTORIAL_END_GIF)
