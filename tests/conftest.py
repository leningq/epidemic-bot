from __future__ import annotations

import pytest_asyncio

from epidemic.db import Database
from epidemic.game.infection import ChanceAccumulator
from epidemic.game.settings import GameSettings
from epidemic.repo import labs, users
from tests.harness import running_harness

NOW = 1_800_000_000  # фиксированное «сейчас» для детерминированных тестов


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def gs(db):
    settings = GameSettings(db)
    await settings.load()
    return settings


@pytest_asyncio.fixture
async def h(tmp_path):
    """Бот с фейковым Telegram для сквозных сценариев (tests/harness.py)."""
    async with running_harness(tmp_path) as harness:
        yield harness


@pytest_asyncio.fixture
async def acc():
    return ChanceAccumulator()


async def make_player(db: Database, user_id: int, name: str = "Игрок", username: str | None = None, **fields):
    async with db.tx() as t:
        await users.upsert(t, user_id, name, username, False, NOW)
        await labs.ensure(t, user_id, NOW)
    if fields:
        await labs.set_fields(db, user_id, **fields)
    return await labs.get(db, user_id)
