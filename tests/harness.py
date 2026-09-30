"""Фейковый Telegram для сквозных тестов: апдейты идут через настоящий Dispatcher,
а запросы к Bot API перехватывает FakeSession."""
from __future__ import annotations

import html
import itertools
import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery, Chat, ChatMemberLeft, ChatMemberMember, ChatMemberOwner, ChatMemberUpdated, Message,
    MessageEntity, Update, User,
)

from epidemic.app import build_app, default_properties
from epidemic.config import Config
from epidemic.db import Database

OWNER = User(id=100, is_bot=False, first_name="Владелец", username="owner_user")
ALICE = User(id=201, is_bot=False, first_name="Алиса", username="alice_lab")
BOB = User(id=202, is_bot=False, first_name="Боб", username="bob_lab")
GROUP = Chat(id=-1001, type="supergroup", title="Био-чат")

_TAG_RE = re.compile(r"<[^>]+>")


def visible(html_text: str) -> str:
    """Текст так, как его видит игрок: без HTML-тегов."""
    return html.unescape(_TAG_RE.sub("", html_text))


def joined(texts: list[str]) -> str:
    return "\n".join(texts)


class FakeSession(BaseSession):
    """Сессия без сети: запоминает вызовы API и возвращает правдоподобные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.chat_admins: dict[int, list[User]] = {}
        self._ids = itertools.count(10_000)

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return User(id=bot.id, is_bot=True, first_name="Epidemic", username="test_bot")
        if name in ("SendMessage", "SendPhoto", "SendAnimation", "EditMessageText"):
            chat_id = getattr(method, "chat_id", None) or 0
            return Message(
                message_id=next(self._ids),
                date=datetime.now(),
                chat=Chat(id=int(chat_id), type="private"),
                text=getattr(method, "text", None) or getattr(method, "caption", None),
            ).as_(bot)  # как настоящий ответ API: у сообщения можно вызвать edit_text/reply
        if name == "GetChatAdministrators":
            return [ChatMemberOwner(user=u, is_anonymous=False) for u in self.chat_admins.get(method.chat_id, [])]
        return True

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    async def close(self) -> None:
        pass


class Harness:
    def __init__(self, app, bot: Bot, session: FakeSession, db: Database) -> None:
        self.app, self.bot, self.session, self.db = app, bot, session, db
        self._ids = itertools.count(1)

    def outgoing(self, start: int = 0) -> list[TelegramMethod]:
        return [
            c for c in self.session.calls[start:]
            if type(c).__name__ in ("SendMessage", "EditMessageText", "SendPhoto")
        ]

    def texts_since(self, start: int) -> list[str]:
        return [getattr(c, "text", None) or getattr(c, "caption", None) or "" for c in self.outgoing(start)]

    def message(self, user: User, text: str, chat: Chat = GROUP, reply_to: Message | None = None,
                entities: list[MessageEntity] | None = None) -> Message:
        return Message(
            message_id=next(self._ids), date=datetime.now(), chat=chat, from_user=user,
            text=text, reply_to_message=reply_to, entities=entities,
        )

    async def send(self, user: User, text: str, chat: Chat = GROUP, **kwargs: Any) -> list[str]:
        start = len(self.session.calls)
        msg = self.message(user, text, chat, **kwargs)
        await self.app.dp.feed_update(self.bot, Update(update_id=next(self._ids), message=msg))
        return self.texts_since(start)

    async def click(self, user: User, data: str, chat: Chat = GROUP) -> list[str]:
        start = len(self.session.calls)
        origin = Message(message_id=next(self._ids), date=datetime.now(), chat=chat, text="…")
        call = CallbackQuery(id=str(next(self._ids)), from_user=user, chat_instance="ci", data=data, message=origin)
        await self.app.dp.feed_update(self.bot, Update(update_id=next(self._ids), callback_query=call))
        return self.texts_since(start)

    async def member_update(self, user: User, joined: bool, chat: Chat = GROUP, mine: bool = False) -> list[str]:
        """Обновление chat_member (или my_chat_member для самого бота): вход или выход из группы."""
        start = len(self.session.calls)
        left, member = ChatMemberLeft(user=user), ChatMemberMember(user=user)
        event = ChatMemberUpdated(
            chat=chat, from_user=user, date=datetime.now(),
            old_chat_member=left if joined else member, new_chat_member=member if joined else left,
        )
        kind = "my_chat_member" if mine else "chat_member"
        await self.app.dp.feed_update(self.bot, Update(update_id=next(self._ids), **{kind: event}))
        return self.texts_since(start)

    def calls_named(self, name: str, start: int = 0) -> list[TelegramMethod]:
        return [c for c in self.session.calls[start:] if type(c).__name__ == name]

    def last_markup(self):
        return self.outgoing()[-1].reply_markup

    def buttons(self) -> list[str]:
        return [b.text for row in self.last_markup().inline_keyboard for b in row]

    def sent_to(self, chat_id: int) -> list[str]:
        return [c.text for c in self.calls_named("SendMessage") if c.chat_id == chat_id]


@asynccontextmanager
async def running_harness(tmp_path: Path) -> AsyncIterator[Harness]:
    config = Config(
        bot_token="42:TEST", owner_ids=frozenset({OWNER.id}), tz=ZoneInfo("Europe/Moscow"),
        db_path=tmp_path / "db.sqlite3", media_dir=tmp_path / "media",
        game_name="Эпидемик", notify_title="𝐄𝐩𝐢𝐝𝐞𝐦𝐢𝐜 𝐍𝐨𝐭𝐢𝐟𝐲",
        guide_url="https://example.com/guide", chat_url="", channel_url="", rules_url="",
        support="@support", log_level="INFO",
    )
    db = Database(":memory:")
    await db.connect()
    session = FakeSession()
    bot = Bot(config.bot_token, session=session, default=default_properties())
    app = await build_app(config, db, "test_bot", throttling=False)
    try:
        yield Harness(app, bot, session, db)
    finally:
        await db.close()
