"""«мф» — массовое заражение «слетевших» жертв (как в оригинале core/handlers/biowar/infects/mf.py).

Отличия от обычного заражения — тоже из оригинала: своя, более мягкая таблица шансов, 1 патоген на цель,
КД на пару — 1 час, жертва не получает горячку и уведомление, горячка атакующего не мешает.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from epidemic.db import Database
from epidemic.game import infection
from epidemic.game.infection import ChanceAccumulator
from epidemic.game.settings import GameSettings
from epidemic.repo import labs

PAGE_SIZE = 20
MF_COOLDOWN_SEC = 60 * 60
MF_CHANCE: dict[int, float] = {
    1: 50.0, 2: 35.0, 3: 25.0, 4: 18.0, 5: 12.0, 6: 8.0, 7: 5.0, 8: 3.0, 9: 2.0, 10: 1.0,
    11: 0.8, 12: 0.6, 13: 0.4, 14: 0.3, 15: 0.3,
    **{gap: 0.2 for gap in range(16, 21)},
    **{gap: 0.1 for gap in range(21, 30)},
}
MF_DEFAULT_CHANCE = 0.1

SUCCESS, FAIL, SKIP, NO_PATHOGENS, STOP = "success", "fail", "skip", "no_pathogens", "stop"


def mf_base_chance(infect: int, immunity: int) -> float:
    gap = immunity - infect
    return 100.0 if gap <= 0 else MF_CHANCE.get(gap, MF_DEFAULT_CHANCE)


def mf_step(infect: int, immunity: int, base: float) -> float:
    """Прибавка к шансу после промаха (живёт 60 с)."""
    return 0.05 if immunity - infect >= 30 else base / 3.0


@dataclass
class MassStep:
    status: str
    chance: float = 0.0
    earn: int = 0
    pathogens_left: int = 0


async def attempt(
    db: Database,
    gs: GameSettings,
    bonus: ChanceAccumulator,
    attacker_id: int,
    victim_id: int,
    now: int,
    rng: Callable[[], float] = random.random,
) -> MassStep:
    async with db.tx() as t:
        attacker = await labs.get(t, attacker_id)
        if attacker is None or labs.is_disabled(attacker, now):
            return MassStep(STOP)
        ready = attacker["ready_pathogens"]
        if ready < 1:
            return MassStep(NO_PATHOGENS)
        victim = await labs.get(t, victim_id)
        if victim is None or victim["is_bot"] or labs.is_disabled(victim, now) or victim_id == attacker_id:
            return MassStep(SKIP, pathogens_left=ready)

        left = ready - 1
        base = mf_base_chance(attacker["infect"], victim["immunity"])
        accumulated = bonus.get(attacker_id, victim_id, now) or 0.0
        chance = round(min(100.0, base + accumulated), 2)

        if rng() * 100 > chance:
            bonus.put(attacker_id, victim_id, accumulated + mf_step(attacker["infect"], victim["immunity"], base), now)
            await infection.spend_pathogens(t, gs, attacker, left, now)
            return MassStep(FAIL, chance, pathogens_left=left)

        bonus.clear(attacker_id, victim_id)
        # как в оригинале: без горячки жертве, без службы безопасности, КД на пару — 1 час
        gain = await infection.record_infection(
            t, gs, attacker, victim, left, now, cooldown_sec=MF_COOLDOWN_SEC, fever_minutes=0, ss_detect=False,
        )
        return MassStep(SUCCESS, chance, gain, left)
