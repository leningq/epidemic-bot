"""Общее для админских хендлеров: фильтр ролей, журнал, имена."""
from __future__ import annotations

from typing import Any

from aiogram.filters import CommandObject, Filter
from aiogram.types import TelegramObject

from epidemic.config import Config
from epidemic.db import Database, Q
from epidemic.handlers.common import staff_level, user_mention
from epidemic.repo import admin as admin_repo
from epidemic.utils.fmt import duration, now_ts

ADMIN, SENIOR, OWNER = 1, 2, 3


class Staff(Filter):
    """Пропускает только персонал с уровнем не ниже заданного. Остальным — тишина."""

    def __init__(self, level: int = ADMIN) -> None:
        self.level = level

    async def __call__(self, event: TelegramObject, db: Database, config: Config, **_: Any) -> bool | dict:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        level = await staff_level(db, config, user.id)
        return {"staff_lvl": level} if level >= self.level else False


async def outranks(db: Database, config: Config, actor_level: int, target_id: int) -> bool:
    """Наказывать можно только тех, кто ниже по должности (владелец — всех, кроме владельцев)."""
    target_level = await staff_level(db, config, target_id)
    return target_level < actor_level or (actor_level == OWNER and target_level < OWNER)


async def issued_by_higher(q: Q, config: Config, actor_level: int, user_id: int, kind: str) -> bool:
    """Есть ли у игрока действующая санкция вида kind от того, кто выше actor по должности.

    Снимать или заменять (в том числе сокращать) такую санкцию нельзя: иначе админ отменил бы
    наказание, выданное владельцем.
    """
    for issuer in await admin_repo.active_issuers(q, user_id, kind, now_ts()):
        if await staff_level(q, config, issuer) > actor_level:
            return True
    return False


NOT_OUTRANKED = "⛔ Нельзя применять это к администратору вашего уровня или выше."
ISSUED_BY_HIGHER = "⛔ Это наказание выдал администратор выше вас по должности — изменить его может только он или выше."
MAX_AMOUNT = 10**12       # предел выдачи ресурсов/опыта за раз (защита от переполнения INTEGER)
MAX_SKILL_LEVEL = 1_000_000


def arg(command: CommandObject) -> str | None:
    """Аргументы команды одной строкой или None."""
    return (command.args or "").strip() or None


def term(seconds: int | None) -> str:
    return f"на {duration(seconds)}" if seconds else "бессрочно"


async def log_action(q: Q, actor_id: int, target_id: int | None, action: str, details: str = "") -> None:
    await admin_repo.log(q, actor_id, target_id, action, details, now_ts())


async def who(q: Q, user_id: int) -> str:
    return f"{await user_mention(q, user_id)} (<code>{user_id}</code>)"
