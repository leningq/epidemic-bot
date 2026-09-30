"""Регистрация игроков: каждый, кто пишет боту или в чат с ботом, получает лабораторию.

Так устроен оригинал: заразить можно любого участника чата, даже если он ни разу не писал боту.
LRU-кэши в памяти не дают писать в БД на каждое сообщение — запись только при изменениях.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, Generic, TypeVar

from aiogram import BaseMiddleware
from aiogram.types import Chat, ChatMemberUpdated, Message, TelegramObject, User

from epidemic.db import Database
from epidemic.repo import labs, users
from epidemic.utils.fmt import clean_name, now_ts
from epidemic.utils.targets import all_mentioned_users, is_group, reply_user

log = logging.getLogger(__name__)

LAST_SEEN_EVERY_SEC = 60 * 60

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class LRU(Generic[K, V]):
    """Ограниченный кэш: при переполнении вытесняется давно не встречавшийся ключ."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._data: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key: K, value: V) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.limit:
            self._data.popitem(last=False)

    def discard(self, key: K) -> None:
        self._data.pop(key, None)


class RegistrationMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self.db = db
        self._users: LRU[int, tuple[str, str | None]] = LRU(100_000)
        self._members: LRU[tuple[int, int], bool] = LRU(300_000)
        self._chats: LRU[int, str] = LRU(20_000)
        self._seen: LRU[int, int] = LRU(100_000)  # когда в последний раз писали last_seen

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            await self._register(event, data.get("event_from_user"), data.get("event_chat"))
        except Exception:
            log.exception("Не удалось зарегистрировать участника")
        return await handler(event, data)

    @staticmethod
    def _collect_users(event: TelegramObject, user: User | None) -> list[User]:
        found: list[User] = [user] if user is not None else []
        if isinstance(event, Message):
            found.extend(event.new_chat_members or ())
            replied = reply_user(event)
            if replied is not None:
                found.append(replied)
            found.extend(all_mentioned_users(event))
        elif isinstance(event, ChatMemberUpdated):
            found.append(event.new_chat_member.user)
        return found

    @staticmethod
    def _left_user(event: TelegramObject) -> int | None:
        """Кто покинул группу: служебное сообщение или обновление chat_member."""
        if isinstance(event, Message) and event.left_chat_member is not None:
            return event.left_chat_member.id
        if isinstance(event, ChatMemberUpdated) and event.new_chat_member.status in ("left", "kicked"):
            return event.new_chat_member.user.id
        return None

    async def _register(self, event: TelegramObject, user: User | None, chat: Chat | None) -> None:
        now = now_ts()
        people = self._collect_users(event, user)
        changed = [u for u in people if self._users.get(u.id) != (clean_name(u.full_name), u.username)]
        # last_seen автора обновляем не чаще раза в час — для статистики «активны за сутки»
        touch = (
            user is not None and all(u.id != user.id for u in changed)
            and now - (self._seen.get(user.id) or 0) >= LAST_SEEN_EVERY_SEC
        )
        group = is_group(chat)
        private = chat is not None and chat.type == "private"
        new_members: list[int] = []
        left_id: int | None = self._left_user(event) if group else None
        # название чата (для лички — имя собеседника); личные чаты нужны для «!стата»
        title = (chat.title or "") if group else clean_name(chat.full_name) if private else ""
        title_changed = (group or private) and self._chats.get(chat.id) != title
        if group:
            new_members = [
                u.id for u in people
                if not u.is_bot and u.id != left_id and self._members.get((chat.id, u.id)) is None
            ]
        if not (changed or new_members or title_changed or left_id or touch):
            return

        async with self.db.tx() as t:
            if touch:
                await t.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, user.id))
            for u in changed:
                await users.upsert(t, u.id, clean_name(u.full_name), u.username, u.is_bot, now)
                if not u.is_bot:
                    await labs.ensure(t, u.id, now)
            if title_changed:
                await t.execute(
                    "INSERT INTO chats (chat_id, title, updated_at, is_private) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at",
                    (chat.id, title, now, int(private)),
                )
            for uid in new_members:
                await t.execute("INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)", (chat.id, uid))
            if left_id is not None:
                await t.execute("DELETE FROM chat_members WHERE chat_id = ? AND user_id = ?", (chat.id, left_id))

        for u in changed:
            self._users.put(u.id, (clean_name(u.full_name), u.username))
            self._seen.put(u.id, now)
        if touch:
            self._seen.put(user.id, now)
        if group or private:
            self._chats.put(chat.id, title)
        if group:
            for uid in new_members:
                self._members.put((chat.id, uid), True)
            if left_id is not None:
                self._members.discard((chat.id, left_id))
