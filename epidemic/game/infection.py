"""Сервис заражения: выбор цели, проверки, бросок шанса и запись результата — в одной транзакции."""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from epidemic.db import Database, Q, Row, Tx
from epidemic.game import constants as C
from epidemic.game import formulas as F
from epidemic.game.settings import GameSettings
from epidemic.repo import labs, users, victims


class ChanceAccumulator:
    """Накопленный шанс за повторные попытки по одной цели (живёт ACCUM_WINDOW_SEC)."""

    def __init__(self, window: int = C.ACCUM_WINDOW_SEC) -> None:
        self.window = window
        self._data: dict[tuple[int, int], tuple[float, int]] = {}

    def get(self, attacker_id: int, victim_id: int, now: int) -> float | None:
        item = self._data.get((attacker_id, victim_id))
        if item is None:
            return None
        value, expires = item
        if expires <= now:
            del self._data[(attacker_id, victim_id)]
            return None
        return value

    def put(self, attacker_id: int, victim_id: int, value: float, now: int) -> None:
        if len(self._data) > 50_000:
            self._data = {k: v for k, v in self._data.items() if v[1] > now}
        self._data[(attacker_id, victim_id)] = (value, now + self.window)

    def clear(self, attacker_id: int, victim_id: int) -> None:
        self._data.pop((attacker_id, victim_id), None)


# Возможные статусы
NO_LAB = "no_lab"
NO_TARGET = "no_target"
VICTIM_NO_LAB = "victim_no_lab"
VICTIM_BOT = "victim_bot"
SELF = "self"
DISABLED = "disabled"
VICTIM_DISABLED = "victim_disabled"
FEVER = "fever"
COOLDOWN = "cooldown"
NO_PATHOGENS = "no_pathogens"
GAP = "gap"
FAIL = "fail"
SUCCESS = "success"


@dataclass
class InfectResult:
    status: str
    attacker: Row | None = None
    victim: Row | None = None
    spent: int = 0
    pathogens_left: int = 0
    chance: float = 0.0
    earn: int = 0
    fever_minutes: int = 0
    days: int = 0
    is_new: bool = False
    ss_detect: bool = False
    wait: int = 0
    gap: int = 0
    quiet: bool = False  # «заразить -»: жертва не получает уведомление

    @property
    def notify_victim(self) -> bool:
        """Кому и когда сообщать жертве (правила оригинала)."""
        if self.status == SUCCESS:
            return not self.quiet
        # при провале СБ жертвы замечает только серьёзную попытку (от 2 патогенов)
        return self.status == FAIL and self.ss_detect and self.spent >= 2


async def pick_random_target(q: Q, gs: GameSettings, attacker: Row, mode: str, now: int) -> int | None:
    """Цель для «заразить +/=/-/рандом»."""
    exp = attacker["bio_exp"]
    low: int | None = None
    high: int | None = None
    if mode == "stronger":
        low = exp + 1
    elif mode == "equal":
        low, high = F.equal_exp_range(exp)
    elif mode == "weaker":
        high = max(0, exp - 1)
    return await labs.random_target(q, attacker["user_id"], attacker["infect"], low, high, gs.max_gap, now)


async def attempt(
    db: Database,
    gs: GameSettings,
    acc: ChanceAccumulator,
    attacker_id: int,
    victim_id: int | None,
    requested: int,
    now: int,
    rng: Callable[[], float] = random.random,
    mode: str | None = None,
) -> InfectResult:
    """Одна попытка заражения. victim_id=None и mode — случайная цель выбранного режима."""
    requested = max(1, min(C.INFECT_MAX_PATHOGENS, requested))
    quiet = mode == "weaker"
    async with db.tx() as t:
        attacker = await labs.get(t, attacker_id)
        if attacker is None:
            return InfectResult(NO_LAB)
        if labs.is_disabled(attacker, now):
            return InfectResult(DISABLED, attacker)
        if victim_id is None:
            victim_id = await pick_random_target(t, gs, attacker, mode or "random", now)
            if victim_id is None:
                return InfectResult(NO_TARGET, attacker)
        if attacker_id == victim_id:
            return InfectResult(SELF, attacker)
        victim = await labs.get(t, victim_id)
        if victim is None:
            user = await users.get(t, victim_id)
            return InfectResult(VICTIM_BOT if user and user["is_bot"] else VICTIM_NO_LAB, attacker)
        if labs.is_disabled(victim, now):
            return InfectResult(VICTIM_DISABLED, attacker, victim)

        fever = labs.fever_left(attacker, now)
        if fever:
            return InfectResult(FEVER, attacker, victim, wait=fever)

        record = await victims.get(t, attacker_id, victim_id)
        if record is not None and record["cooldown_until"] > now:
            return InfectResult(COOLDOWN, attacker, victim, wait=record["cooldown_until"] - now)

        ready = attacker["ready_pathogens"]
        spent = requested
        if ready < spent:
            if ready < 1:
                return InfectResult(NO_PATHOGENS, attacker, victim)
            spent = ready

        gap = victim["immunity"] - attacker["infect"]
        if gap > gs.max_gap:
            return InfectResult(GAP, attacker, victim, gap=gap)

        base = F.base_chance(attacker["infect"], victim["immunity"])
        chance = F.total_chance(base, spent, acc.get(attacker_id, victim_id, now))
        success = rng() * 100 <= chance
        left = ready - spent
        ss_detect = attacker["security"] < victim["security"]

        if not success:
            acc.put(attacker_id, victim_id, chance, now)
            await spend_pathogens(t, gs, attacker, left, now)
            return InfectResult(
                FAIL, attacker, victim, spent=spent, pathogens_left=left,
                chance=chance, ss_detect=ss_detect, gap=gap, quiet=quiet,
            )

        acc.clear(attacker_id, victim_id)
        fever_min = F.fever_minutes(attacker["lethality"], gs.fever_pct)
        is_new = record is None or record["expires_at"] <= now
        gain = await record_infection(
            t, gs, attacker, victim, left, now,
            cooldown_sec=gs.cooldown_sec, fever_minutes=fever_min, ss_detect=ss_detect,
        )
        return InfectResult(
            SUCCESS, attacker, victim, spent=spent, pathogens_left=left, chance=chance, earn=gain,
            fever_minutes=fever_min, days=attacker["lethality"], is_new=is_new, ss_detect=ss_detect,
            gap=gap, quiet=quiet,
        )


# --- Запись результата: общая для обычного заражения и «мф» (game/mass.py) ---

def _production_timer(gs: GameSettings, attacker: Row, now: int) -> int:
    """Если хранилище было полным (таймер стоял), производство начинается с момента траты."""
    timer = attacker["science_time"]
    return timer if timer is not None else now + F.production_interval_sec(attacker["science"], gs.speed_pct)


async def spend_pathogens(t: Tx, gs: GameSettings, attacker: Row, left: int, now: int) -> None:
    """Промах: патогены потрачены, награды нет."""
    await t.execute(
        "UPDATE labs SET ready_pathogens = ?, science_time = ? WHERE user_id = ?",
        (left, _production_timer(gs, attacker, now), attacker["user_id"]),
    )


async def record_infection(
    t: Tx,
    gs: GameSettings,
    attacker: Row,
    victim: Row,
    left: int,
    now: int,
    *,
    cooldown_sec: int,
    fever_minutes: int,
    ss_detect: bool,
) -> int:
    """Успешное заражение: опыт атакующему, потеря опыта жертвой (и горячка, если fever_minutes > 0),
    запись жертвы, журнал заражений. Возвращает опыт, который получил атакующий."""
    attacker_id, victim_id = attacker["user_id"], victim["user_id"]
    base_earn = F.infection_reward(victim["bio_exp"], attacker["infect"], victim["immunity"])
    gain = max(1, F.apply_pct(base_earn, gs.xp_pct))
    await t.execute(
        "UPDATE labs SET bio_exp = bio_exp + ?, ready_pathogens = ?, science_time = ? WHERE user_id = ?",
        (gain, left, _production_timer(gs, attacker, now), attacker_id),
    )
    if fever_minutes > 0:
        await t.execute(
            "UPDATE labs SET bio_exp = MAX(0, bio_exp - ?), fever_until = ?, fever_pathogen = ? WHERE user_id = ?",
            (
                base_earn,
                F.new_fever_until(now, victim["fever_until"], fever_minutes),
                attacker["pathogen_name"],
                victim_id,
            ),
        )
    else:
        await t.execute("UPDATE labs SET bio_exp = MAX(0, bio_exp - ?) WHERE user_id = ?", (base_earn, victim_id))
    await victims.upsert(
        t, attacker_id, victim_id,
        expires_at=now + attacker["lethality"] * 86400,
        infected_at=now,
        cooldown_until=now + cooldown_sec,
        earn=gain,
        pathogen_name=attacker["pathogen_name"],
        ss_detect=ss_detect,
    )
    await t.execute(
        "INSERT INTO infection_log (attacker_id, victim_id, created_at) VALUES (?, ?, ?)",
        (attacker_id, victim_id, now),
    )
    return gain


async def buy_vaccine(db: Database, user_id: int, now: int) -> tuple[str, int]:
    """Снимает горячку за иммунитет × 15 био-ресурсов. Возвращает (статус, цена)."""
    async with db.tx() as t:
        lab = await labs.get(t, user_id)
        if lab is None:
            return NO_LAB, 0
        if not labs.fever_left(lab, now):
            return "healthy", 0
        price = F.vaccine_price(lab["immunity"])
        if lab["bio_res"] < price:
            return "not_enough", price
        await t.execute(
            "UPDATE labs SET fever_until = NULL, fever_pathogen = NULL, bio_res = bio_res - ? WHERE user_id = ?",
            (price, user_id),
        )
        return SUCCESS, price
