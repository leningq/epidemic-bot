"""Доступ к боту: полный игнор, техработы, режим «только владелец»."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from epidemic import texts
from epidemic.config import Config
from epidemic.db import Database, Q
from epidemic.game.settings import GameSettings
from epidemic.repo import admin as admin_repo
from epidemic.utils.fmt import now_ts


class IgnoreList:
    """Кэш пользователей под полным игнором ({user_id: истекает или None})."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._items: dict[int, int | None] = {}

    async def load(self) -> None:
        self._items = await admin_repo.active_ignores(self.db, now_ts())

    async def ignore(
        self, q: Q, user_id: int, reason: str, by: int, now: int, until: int | None, kind: str = "ignore"
    ) -> None:
        """Записывает санкцию («ignore» — «+ас», «game_mute» — «эпиас») и сразу применяет её."""
        await admin_repo.add_sanction(q, user_id, kind, reason, by, now, until)
        await self._refresh(q, user_id)

    async def unignore(self, q: Q, user_id: int, kind: str = "ignore") -> None:
        """Снимает санкции одного вида; другой вид (например, игнор владельца) продолжает действовать."""
        await admin_repo.deactivate(q, user_id, kind)
        await self._refresh(q, user_id)

    async def _refresh(self, q: Q, user_id: int) -> None:
        state = await admin_repo.active_ignores(q, now_ts(), user_id)
        if user_id in state:
            self._items[user_id] = state[user_id]
        else:
            self._items.pop(user_id, None)

    def until(self, user_id: int) -> int | None:
        """До какого времени действует игнор (None — бессрочно). Только для тех, кто в списке."""
        return self._items[user_id]

    def is_ignored(self, user_id: int, now: int) -> bool:
        if user_id not in self._items:
            return False
        until = self._items[user_id]
        if until is not None and until <= now:
            del self._items[user_id]
            return False
        return True


class AccessMiddleware(BaseMiddleware):
    def __init__(self, config: Config, gs: GameSettings, ignores: IgnoreList) -> None:
        self.config = config
        self.gs = gs
        self.ignores = ignores

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id in self.config.owner_ids:
            return await handler(event, data)
        if self.ignores.is_ignored(user.id, now_ts()):
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None
        if self.gs.maintenance or self.gs.owner_only:
            text = texts.MAINTENANCE if self.gs.maintenance else texts.OWNER_ONLY
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
            return None
        return await handler(event, data)
