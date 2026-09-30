"""Анти-флуд: не чаще одной команды в 0.3 с и одного нажатия кнопки в 0.5 с на игрока."""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from epidemic import texts


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, message_rate: float = 0.3, callback_rate: float = 0.5) -> None:
        self.message_rate = message_rate
        self.callback_rate = callback_rate
        self._last: dict[tuple[bool, int], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        is_callback = isinstance(event, CallbackQuery)
        rate = self.callback_rate if is_callback else self.message_rate
        key = (is_callback, user.id)
        now = time.monotonic()
        if now - self._last.get(key, 0.0) < rate:
            if is_callback:
                await event.answer(texts.TOO_FAST)
            return None
        self._last[key] = now
        if len(self._last) > 100_000:
            self._last = {k: v for k, v in self._last.items() if now - v < 60}
        return await handler(event, data)
