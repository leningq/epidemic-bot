"""Доступ к SQLite.

Одно соединение aiosqlite на процесс. Все записи идут через транзакции под asyncio.Lock,
поэтому конкурентные корутины не перемешивают свои изменения.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import sqlite3
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import aiosqlite

from epidemic.schema import pending_scripts

log = logging.getLogger(__name__)

Row = aiosqlite.Row
Params = Sequence[Any] | dict[str, Any]

_in_tx: contextvars.ContextVar[bool] = contextvars.ContextVar("epidemic_in_tx", default=False)


class _Queries:
    """Общие методы чтения/записи для Database и Tx."""

    _conn: aiosqlite.Connection

    async def fetchone(self, sql: str, params: Params = ()) -> Row | None:
        rows = await self._conn.execute_fetchall(sql, params)
        return rows[0] if rows else None

    async def fetchall(self, sql: str, params: Params = ()) -> list[Row]:
        return list(await self._conn.execute_fetchall(sql, params))

    async def fetchval(self, sql: str, params: Params = (), default: Any = None) -> Any:
        row = await self.fetchone(sql, params)
        if row is None or row[0] is None:
            return default
        return row[0]


class Tx(_Queries):
    """Открытая транзакция. Получается только через Database.tx()."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: Params = ()) -> int:
        """Выполняет запрос, возвращает rowcount."""
        async with self._conn.execute(sql, params) as cur:
            return cur.rowcount

    async def insert(self, sql: str, params: Params = ()) -> int:
        """Выполняет INSERT, возвращает lastrowid."""
        async with self._conn.execute(sql, params) as cur:
            return cur.lastrowid or 0

    async def executemany(self, sql: str, seq: Iterable[Params]) -> None:
        await self._conn.executemany(sql, seq)


class Database(_Queries):
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None  # type: ignore[assignment]
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        for pragma in (
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA foreign_keys = ON",
            "PRAGMA busy_timeout = 5000",
        ):
            await self._conn.execute(pragma)
        await self._migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None  # type: ignore[assignment]

    async def _migrate(self) -> None:
        current = await self.fetchval("PRAGMA user_version", default=0)
        for version, script in pending_scripts(current):
            log.info("Применяю миграцию БД #%s", version)
            await self._conn.executescript(script)

    @asynccontextmanager
    async def tx(self) -> AsyncIterator[Tx]:
        if _in_tx.get():
            raise RuntimeError("Вложенная транзакция: используйте переданный объект Tx")
        async with self._lock:
            token = _in_tx.set(True)
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield Tx(self._conn)
            except BaseException:
                await self._conn.execute("ROLLBACK")
                raise
            else:
                try:
                    await self._conn.execute("COMMIT")
                except BaseException:
                    # COMMIT не прошёл (диск, I/O) — откатываем, иначе соединение застрянет в транзакции
                    with suppress(Exception):
                        await self._conn.execute("ROLLBACK")
                    raise
            finally:
                _in_tx.reset(token)

    async def execute(self, sql: str, params: Params = ()) -> int:
        """Одиночная запись в собственной транзакции. Возвращает rowcount."""
        async with self.tx() as t:
            return await t.execute(sql, params)

    async def insert(self, sql: str, params: Params = ()) -> int:
        async with self.tx() as t:
            return await t.insert(sql, params)

    async def backup_to(self, target: Path | str) -> None:
        """Копия базы через отдельное соединение: в режиме WAL это согласованный снимок,
        и игра не ждёт окончания копирования."""
        if self.path == ":memory:":
            raise RuntimeError("Резервное копирование базы в памяти не поддерживается")
        await asyncio.to_thread(_backup_file, self.path, str(target))


def _backup_file(source: str, target: str) -> None:
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        # одним шагом: по частям копирование начиналось бы заново после каждой записи игры
        # (запись идёт через другое соединение) и на живой базе могло не закончиться никогда
        src.backup(dst, pages=-1)
    finally:
        dst.close()
        src.close()


# Тип для функций репозитория: подходит и Database (чтение/одиночная запись), и Tx.
Q = Database | Tx
