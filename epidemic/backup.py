"""Резервная копия базы вручную: python -m epidemic.backup

Копия согласованная (делается через SQLite backup API) и безопасна при работающем боте.
Файл кладётся в data/backups рядом с базой; хранятся последние 7 копий.
"""
from __future__ import annotations

import asyncio

from epidemic.config import load_config
from epidemic.db import Database
from epidemic.services.scheduler import make_backup


async def main() -> None:
    config = load_config()
    path = await make_backup(Database(config.db_path), config.db_path.parent / "backups", config)
    print(f"✅ Резервная копия: {path}")


if __name__ == "__main__":
    asyncio.run(main())
