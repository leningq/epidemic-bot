"""Запуск бота: python -m epidemic"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, User

from epidemic.app import build_app, make_bot
from epidemic.config import load_config
from epidemic.db import Database
from epidemic.services.scheduler import Scheduler

log = logging.getLogger("epidemic")

STARTUP_RETRY_MAX_SEC = 60


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать игру / меню"),
            BotCommand(command="help", description="Меню и помощь"),
            BotCommand(command="restart_tutorial", description="Пройти обучение заново"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )


async def wait_for_telegram(bot: Bot) -> User:
    """getMe с повторами: при старте сеть до Telegram может ненадолго пропасть (так бывает у
    провайдеров в РФ) — бот ждёт и пробует снова, а не падает. Неверный токен — не сетевая
    ошибка, он по-прежнему останавливает запуск сразу."""
    delay = 5
    while True:
        try:
            return await bot.get_me()
        except TelegramNetworkError as exc:
            log.warning("Нет связи с Telegram (%s) — повтор через %s с", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, STARTUP_RETRY_MAX_SEC)


async def main() -> None:
    config = load_config()
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    if not config.bot_token:
        log.error("BOT_TOKEN не задан — заполните файл .env")
        sys.exit(1)
    if not config.owner_ids:
        log.warning("ADMIN_ID не задан — админ-панель будет недоступна")

    db = Database(config.db_path)
    await db.connect()
    bot = make_bot(config)
    scheduler: Scheduler | None = None
    try:
        me = await wait_for_telegram(bot)
        app = await build_app(config, db, me.username)
        try:
            await set_commands(bot)
        except TelegramNetworkError as exc:  # меню команд — не критично, бот работает и без него
            log.warning("Не удалось обновить меню команд: %s", exc)
        scheduler = Scheduler(db, app.gs, config)
        scheduler.start()
        log.info("Бот @%s запущен, база: %s", me.username, config.db_path)
        await app.dp.start_polling(bot, allowed_updates=app.dp.resolve_used_update_types())
    finally:
        if scheduler is not None:
            await scheduler.stop()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
