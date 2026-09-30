"""Прокачка, понижение и административная установка уровней навыков."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from epidemic.db import Database, Q, Tx
from epidemic.game import constants as C
from epidemic.game import formulas as F
from epidemic.game.settings import GameSettings
from epidemic.repo import labs

OK = "ok"
NO_LAB = "no_lab"
DISABLED = "disabled"
TOO_MANY = "too_many"
MAX_LEVEL = "max_level"
MIN_LEVEL = "min_level"
NOT_ENOUGH = "not_enough"

# Поля, которые администратор может выставлять напрямую
LEVEL_FIELDS = (*C.SKILLS, "ready_pathogens")


@dataclass
class Quote:
    status: str
    skill: str
    levels: int
    from_lvl: int = 0
    to_lvl: int = 0
    price: int = 0
    resources: int = 0
    reason: str | None = None  # причина отключения лаборатории

    @property
    def missing(self) -> int:
        return max(0, self.price - self.resources)


async def quote(q: Q, gs: GameSettings, user_id: int, skill: str, levels: int | None, now: int) -> Quote:
    levels = 1 if levels is None else levels
    if not 1 <= levels <= C.MAX_LEVELS_PER_UPGRADE:
        return Quote(TOO_MANY, skill, levels)
    lab = await labs.get(q, user_id)
    if lab is None:
        return Quote(NO_LAB, skill, levels)
    from_lvl = lab[skill]
    result = Quote(OK, skill, levels, from_lvl, from_lvl + levels, resources=lab["bio_res"])
    if labs.is_disabled(lab, now):
        result.status, result.reason = DISABLED, lab["disabled_reason"]
        return result
    cap = F.skill_cap(skill)
    if cap is not None and result.to_lvl > cap:
        result.status = MAX_LEVEL
        return result
    result.price = F.upgrade_cost(skill, from_lvl, result.to_lvl, gs.cost_pct)
    if result.price > lab["bio_res"]:
        result.status = NOT_ENOUGH
    return result


async def apply(db: Database, gs: GameSettings, user_id: int, skill: str, levels: int | None, now: int) -> Quote:
    """Прокачивает навык, если хватает ресурсов. Проверка и списание — в одной транзакции."""
    if skill not in C.SKILLS:
        raise ValueError(skill)
    async with db.tx() as t:
        result = await quote(t, gs, user_id, skill, levels, now)
        if result.status != OK:
            return result
        # skill проверен по белому списку C.SKILLS выше
        if skill == "pathogens":
            # новые ячейки сразу заполнены готовыми патогенами
            extra, params = ", ready_pathogens = ready_pathogens + ?", (result.levels,)
        elif skill == "science":
            # ускорение производства сокращает уже идущий таймер
            interval = F.production_interval_sec(result.to_lvl, gs.speed_pct)
            extra, params = ", science_time = MIN(science_time, ?)", (now + interval,)
        else:
            extra, params = "", ()
        await t.execute(
            f"UPDATE labs SET {skill} = ?, bio_res = bio_res - ?{extra} WHERE user_id = ?",
            (result.to_lvl, result.price, *params, user_id),
        )
        result.resources -= result.price
        return result


@dataclass
class Downgrade:
    status: str
    skill: str
    levels: int
    from_lvl: int = 0
    to_lvl: int = 0
    refund: int = 0
    spent: int = 0
    reason: str | None = None


async def downgrade(db: Database, gs: GameSettings, user_id: int, skill: str, levels: int, now: int) -> Downgrade:
    """Понижает навык и возвращает 50 % стоимости снятых уровней."""
    if skill not in C.SKILLS:
        raise ValueError(skill)
    if levels < 1:
        return Downgrade(TOO_MANY, skill, levels)
    async with db.tx() as t:
        lab = await labs.get(t, user_id)
        if lab is None:
            return Downgrade(NO_LAB, skill, levels)
        from_lvl = lab[skill]
        result = Downgrade(OK, skill, levels, from_lvl, from_lvl - levels)
        if labs.is_disabled(lab, now):
            result.status, result.reason = DISABLED, lab["disabled_reason"]
            return result
        if result.to_lvl < 1:
            result.status = MIN_LEVEL
            return result
        result.spent = F.upgrade_cost(skill, result.to_lvl, from_lvl, gs.cost_pct)
        # Возврат не выше базовой цены: если владелец поднимет множитель цены (например, до 300 %),
        # понижение не должно стать способом «печатать» ресурсы.
        result.refund = F.downgrade_refund(skill, from_lvl, result.to_lvl, min(gs.cost_pct, 100))
        await t.execute("UPDATE labs SET bio_res = bio_res + ? WHERE user_id = ?", (result.refund, user_id))
        await _write_level(t, lab, skill, result.to_lvl)
        return result


async def set_level(
    db: Database,
    user_id: int,
    field: str,
    value: int,
    on_change: Callable[[Tx, int, int], Awaitable[None]] | None = None,
) -> tuple[int, int] | None:
    """Администратор выставляет уровень напрямую. Возвращает (было, стало) или None, если лаборатории нет.

    on_change(t, было, стало) вызывается в той же транзакции — для записи в журнал админа.
    """
    if field not in LEVEL_FIELDS:
        raise ValueError(field)
    async with db.tx() as t:
        lab = await labs.get(t, user_id)
        if lab is None:
            return None
        old, new = lab[field], await _write_level(t, lab, field, value)
        if on_change is not None:
            await on_change(t, old, new)
        return old, new


async def _write_level(q: Q, lab, field: str, value: int) -> int:
    """Единое место с границами навыков: минимум 1, разработка ≤ 60, готовые ≤ ёмкости.
    Если хранилище заполнилось, таймер производства сбрасывается."""
    if field == "ready_pathogens":
        value = max(0, min(value, lab["pathogens"]))
    else:
        value = max(1, value)
        cap = F.skill_cap(field)
        if cap is not None:
            value = min(value, cap)
    fields: dict[str, object] = {field: value}
    ready = value if field == "ready_pathogens" else lab["ready_pathogens"]
    capacity = value if field == "pathogens" else lab["pathogens"]
    if ready > capacity:
        fields["ready_pathogens"] = ready = capacity
    if ready >= capacity:
        fields["science_time"] = None
    await labs.set_fields(q, lab["user_id"], **fields)
    return value
