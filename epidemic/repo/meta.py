"""Служебные значения в таблице settings (слот последней премии, кэш file_id картинок и т.п.)."""
from __future__ import annotations

from epidemic.db import Q


async def get(q: Q, key: str) -> str | None:
    return await q.fetchval("SELECT value FROM settings WHERE key = ?", (key,))


async def put(q: Q, key: str, value: str) -> None:
    await q.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
