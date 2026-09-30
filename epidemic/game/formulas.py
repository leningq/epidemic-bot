"""Чистые игровые формулы (без БД и Telegram) — их покрывают тесты."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from epidemic.game import constants as C


def apply_pct(value: float, pct: int) -> int:
    """Применяет процентный множитель админа (100 = без изменений)."""
    return int(value * pct / 100)


# --- Прокачка ---

def _raw_upgrade_sum(skill: str, from_lvl: int, to_lvl: int) -> int:
    k = C.SKILL_EXPONENT[skill]
    return int(sum((i + 1) ** k for i in range(from_lvl, to_lvl)))


def upgrade_cost(skill: str, from_lvl: int, to_lvl: int, cost_pct: int = 100) -> int:
    """Цена прокачки навыка с from_lvl до to_lvl: Σ (i+1)^k."""
    if to_lvl <= from_lvl:
        return 0
    return max(1, apply_pct(_raw_upgrade_sum(skill, from_lvl, to_lvl), cost_pct))


def skill_cap(skill: str) -> int | None:
    return C.SCIENCE_MAX if skill == "science" else None


def affordable_levels(skill: str, level: int, resources: int, cost_pct: int = 100) -> int:
    """Сколько уровней навыка можно купить прямо сейчас (не больше лимита за раз)."""
    k = C.SKILL_EXPONENT[skill]
    cap = skill_cap(skill)
    total = 0.0
    best = 0
    for i in range(1, C.MAX_LEVELS_PER_UPGRADE + 1):
        target = level + i
        if cap is not None and target > cap:
            break
        total += target ** k
        if max(1, apply_pct(int(total), cost_pct)) > resources:
            break
        best = i
    return best


def downgrade_refund(skill: str, from_lvl: int, to_lvl: int, cost_pct: int = 100) -> int:
    """Возврат ресурсов при понижении навыка с from_lvl до to_lvl."""
    return int(upgrade_cost(skill, to_lvl, from_lvl, cost_pct) * C.DOWNGRADE_REFUND)


# --- Производство патогенов ---

def science_minutes(science: int) -> int:
    """Минут на один патоген при данном уровне разработки (1 → 60, 60 → 1)."""
    return max(1, 61 - science)


def production_interval_sec(science: int, speed_pct: int = 100) -> int:
    seconds = science_minutes(science) * 60 * 100 / max(1, speed_pct)
    return max(C.MIN_PRODUCTION_INTERVAL_SEC, int(round(seconds)))


def produce(ready: int, capacity: int, timer: int | None, now: int, interval: int) -> tuple[int, int | None]:
    """Один шаг производства: возвращает (готовые патогены, новый таймер).

    Если бот был выключен, пропущенные интервалы догоняются сразу.
    """
    if ready >= capacity:
        return min(ready, capacity), None
    if timer is None:
        return ready, now + interval
    if timer > now:
        return ready, timer
    produced = 1 + (now - timer) // interval
    new_ready = min(capacity, ready + produced)
    if new_ready >= capacity:
        return new_ready, None
    return new_ready, timer + produced * interval


# --- Заражение ---

def base_chance(infect: int, immunity: int) -> float:
    """Базовый шанс пробития в процентах."""
    gap = immunity - infect
    if gap <= 0:
        return 100.0
    if gap < len(C.CHANCE_TABLE):
        return C.CHANCE_TABLE[gap]
    return C.CHANCE_BEYOND_TABLE


def pathogen_multiplier(spent: int) -> float:
    return 1.0 + (max(1, spent) - 1) * C.INFECT_MULT_STEP


def total_chance(base: float, spent: int, accumulated: float | None) -> float:
    """Итоговый шанс с учётом числа патогенов и накопления за повторные попытки."""
    mult = pathogen_multiplier(spent)
    if accumulated is None:
        return base * mult
    return accumulated + base / C.ACCUM_DIVISOR * mult


def infection_reward(victim_exp: int, attacker_infect: int, victim_immunity: int) -> int:
    """Био-опыт за успешное заражение (до множителя админа)."""
    earn = round(max(0, victim_exp) * C.INFECT_CLAIM_PERCENT)
    if victim_immunity > attacker_infect:
        earn = round(earn / (1 + (victim_immunity - attacker_infect) / 100))
    return max(1, int(earn))


def fever_minutes(attacker_lethality: int, fever_pct: int = 100) -> int:
    """Сколько минут горячки добавляет одно заражение (и пишется в сообщении).

    Как в оригинале, число в тексте не ограничено («Горячка на 222 минут»), а итоговая горячка
    жертвы всё равно не превышает часа — см. new_fever_until.
    """
    return max(1, apply_pct(max(1, attacker_lethality // 3), fever_pct))


def dossier_fever_minutes(lethality: int, fever_pct: int = 100) -> int:
    """Минуты горячки в строке летальности досье — формула оригинала: ÷3, 0 → 1, от 180 → 60."""
    minutes = lethality // 3
    minutes = 1 if minutes == 0 else (60 if minutes >= 180 else minutes)
    return max(1, apply_pct(minutes, fever_pct))


def new_fever_until(now: int, current_until: int | None, add_minutes: int) -> int:
    remaining = max(0, (current_until or 0) - now)
    return now + min(C.FEVER_MAX_SEC, remaining + add_minutes * 60)


def vaccine_price(immunity: int) -> int:
    return max(1, immunity * C.VACCINE_PRICE_PER_IMMUNITY)


def equal_exp_range(exp: int) -> tuple[int, int]:
    return int(math.floor(exp / C.EQUAL_EXP_RATIO)), int(math.ceil(exp * C.EQUAL_EXP_RATIO))


# --- Премия ---

def payout_slot(now_local: datetime) -> datetime:
    """Последний наступивший слот выплаты премии (00:00 или 12:00 локального времени)."""
    day = now_local.replace(minute=0, second=0, microsecond=0)
    past = [h for h in C.PAYOUT_HOURS if h <= now_local.hour]
    if past:
        return day.replace(hour=max(past))
    return (day - timedelta(days=1)).replace(hour=max(C.PAYOUT_HOURS))


def next_payout(now_local: datetime) -> datetime:
    day = now_local.replace(minute=0, second=0, microsecond=0)
    future = [h for h in C.PAYOUT_HOURS if h > now_local.hour]
    if future:
        return day.replace(hour=min(future))
    return (day + timedelta(days=1)).replace(hour=min(C.PAYOUT_HOURS))
