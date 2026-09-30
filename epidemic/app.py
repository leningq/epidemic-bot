"""Сборка приложения: диспетчер, middleware, зависимости. Отдельно от запуска — для тестов."""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from epidemic.config import Config
from epidemic.db import Database
from epidemic.game.infection import ChanceAccumulator
from epidemic.game.settings import GameSettings
from epidemic.handlers import build_router
from epidemic.middlewares.access import AccessMiddleware, IgnoreList
from epidemic.middlewares.registration import RegistrationMiddleware
from epidemic.middlewares.throttling import ThrottlingMiddleware


REQUEST_TIMEOUT_SEC = 20


def default_properties() -> DefaultBotProperties:
    return DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)


@dataclass
class App:
    dp: Dispatcher
    gs: GameSettings


async def build_app(config: Config, db: Database, bot_username: str, throttling: bool = True) -> App:
    gs = GameSettings(db)
    await gs.load()
    ignores = IgnoreList(db)
    await ignores.load()

    dp = Dispatcher(
        config=config,
        db=db,
        gs=gs,
        acc=ChanceAccumulator(),
        mf_acc=ChanceAccumulator(),  # накопленный бонус «мф» живёт отдельно от обычного заражения
        ignores=ignores,
        bot_username=bot_username,
    )

    registration = RegistrationMiddleware(db)
    dp.message.outer_middleware(registration)
    dp.callback_query.outer_middleware(registration)
    dp.chat_member.outer_middleware(registration)
    dp.my_chat_member.outer_middleware(registration)

    access = AccessMiddleware(config, gs, ignores)
    dp.message.middleware(access)
    dp.callback_query.middleware(access)

    if throttling:
        throttle = ThrottlingMiddleware()
        dp.message.middleware(throttle)
        dp.callback_query.middleware(throttle)

    dp.include_router(build_router())
    return App(dp=dp, gs=gs)


def make_bot(config: Config) -> Bot:
    # Таймаут запроса к Telegram. По умолчанию в aiogram 60 с: зависшее соединение (обрыв сети)
    # замечалось только через ~70 с, и всё это время бот не получал сообщений. С 20 с —
    # через ~30 с (20 + 10 с long polling), после чего aiogram сам переподключается.
    return Bot(config.bot_token, session=AiohttpSession(timeout=REQUEST_TIMEOUT_SEC), default=default_properties())
