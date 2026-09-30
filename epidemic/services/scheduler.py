"""Фоновые задачи: производство патогенов, ежедневная премия, резервные копии, heartbeat."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from epidemic.config import Config
from epidemic.db import Database
from epidemic.game import economy
from epidemic.game.constants import PRODUCTION_TICK_SEC
from epidemic.game.settings import GameSettings
from epidemic.utils.fmt import now_ts

log = logging.getLogger(__name__)

PAYOUT_CHECK_SEC = 20
BACKUP_EVERY_SEC = 24 * 60 * 60
BACKUP_CHECK_SEC = 60 * 60
BACKUPS_KEPT = 7
LAST_BACKUP_KEY = "last_backup_at"


class Scheduler:
    def __init__(self, db: Database, gs: GameSettings, config: Config) -> None:
        self.db = db
        self.gs = gs
        self.config = config
        self._tasks: list[asyncio.Task] = []
        data_dir = config.db_path.parent
        self.heartbeat_file = data_dir / ".heartbeat"
        self.backup_dir = data_dir / "backups"

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop("production", PRODUCTION_TICK_SEC, self._production)),
            asyncio.create_task(self._loop("payout", PAYOUT_CHECK_SEC, self._payout)),
            asyncio.create_task(self._loop("backup", BACKUP_CHECK_SEC, self._backup)),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _loop(self, name: str, interval: int, job: Callable[[], Awaitable[None]]) -> None:
        while True:
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Фоновая задача %s упала, повторю через %s с", name, interval)
            await asyncio.sleep(interval)

    async def _production(self) -> None:
        await economy.production_tick(self.db, self.gs, now_ts())
        self.heartbeat_file.touch()

    async def _payout(self) -> None:
        result = await economy.payout_if_due(self.db, self.gs, self.config.tz, now_ts())
        if result is not None:
            players, total = result
            log.info("Ежедневная премия: %s игроков получили %s био-ресурсов", players, total)

    async def _backup(self) -> None:
        """Раз в сутки. Время последней копии хранится в БД, поэтому частые перезапуски не мешают."""
        now = now_ts()
        last = await self.gs.get_meta(LAST_BACKUP_KEY)
        if last is not None and last.isdecimal() and now - int(last) < BACKUP_EVERY_SEC:
            return
        await make_backup(self.db, self.backup_dir, self.config)
        await self.gs.set_meta(LAST_BACKUP_KEY, str(now))


async def make_backup(db: Database, backup_dir: Path, config: Config) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(config.tz).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"epidemic-{stamp}.sqlite3"
    await db.backup_to(target)
    old = sorted(backup_dir.glob("epidemic-*.sqlite3"))[:-BACKUPS_KEPT]
    for path in old:
        path.unlink(missing_ok=True)
    log.info("Резервная копия БД: %s", target.name)
    return target
