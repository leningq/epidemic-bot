from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from epidemic.game import constants as C
from epidemic.game import formulas as F

MSK = ZoneInfo("Europe/Moscow")


def reference_cost(skill: str, from_lvl: int, to_lvl: int) -> int:
    """Формула оригинала (core/func.py lvl_up_calc)."""
    price = 0
    for i in range(from_lvl, to_lvl):
        price += (i + 1) ** C.SKILL_EXPONENT[skill]
    return int(price)


# --- Таблица шансов ---

def test_chance_table_covers_0_to_200_and_never_grows():
    assert len(C.CHANCE_TABLE) == 201
    assert all(a >= b for a, b in zip(C.CHANCE_TABLE, C.CHANCE_TABLE[1:]))


@pytest.mark.parametrize(
    ("infect", "immunity", "expected"),
    [
        (10, 5, 100.0), (5, 5, 100.0), (1, 2, 75.0), (1, 3, 50.0), (1, 6, 15.0),
        (1, 11, 6.0), (1, 51, 1.0), (1, 101, 0.1), (1, 146, 0.01), (1, 201, 0.001), (1, 400, 0.001),
    ],
)
def test_base_chance_matches_original_table(infect, immunity, expected):
    assert F.base_chance(infect, immunity) == expected


def test_pathogen_multiplier_and_accumulation():
    assert F.pathogen_multiplier(1) == 1.0
    assert F.pathogen_multiplier(10) == pytest.approx(1 + 9 * 0.2722)
    assert F.total_chance(50.0, 1, None) == 50.0
    assert F.total_chance(50.0, 1, 50.0) == pytest.approx(62.5)
    assert F.total_chance(6.0, 3, None) == pytest.approx(6.0 * (1 + 2 * 0.2722))


# --- Прокачка ---

@pytest.mark.parametrize("skill", C.SKILLS)
@pytest.mark.parametrize(("from_lvl", "to_lvl"), [(1, 2), (1, 10), (10, 11), (57, 60), (100, 150)])
def test_upgrade_cost_equals_original(skill, from_lvl, to_lvl):
    assert F.upgrade_cost(skill, from_lvl, to_lvl) == max(1, reference_cost(skill, from_lvl, to_lvl))


def test_upgrade_cost_examples_and_multiplier():
    assert F.upgrade_cost("infect", 1, 2) == 5
    assert F.upgrade_cost("infect", 10, 11) == 452
    assert F.upgrade_cost("pathogens", 4, 5) == 25
    assert F.upgrade_cost("infect", 10, 11, cost_pct=200) == 904
    assert F.upgrade_cost("infect", 5, 5) == 0


def test_affordable_levels():
    price3 = F.upgrade_cost("immunity", 10, 13)
    assert F.affordable_levels("immunity", 10, price3) == 3
    assert F.affordable_levels("immunity", 10, price3 - 1) == 2
    assert F.affordable_levels("immunity", 10, 0) == 0
    assert F.affordable_levels("science", 58, 10**12) == 2  # потолок разработки — 60
    assert F.affordable_levels("infect", 1, 10**15) == C.MAX_LEVELS_PER_UPGRADE


def test_downgrade_refund_is_half():
    assert F.downgrade_refund("infect", 11, 10) == F.upgrade_cost("infect", 10, 11) // 2


# --- Производство ---

def test_science_minutes_and_interval():
    assert F.science_minutes(1) == 60
    assert F.science_minutes(60) == 1
    assert F.production_interval_sec(1) == 3600
    assert F.production_interval_sec(60) == 60
    assert F.production_interval_sec(1, speed_pct=200) == 1800
    assert F.production_interval_sec(60, speed_pct=10_000) == C.MIN_PRODUCTION_INTERVAL_SEC


def test_produce_steps():
    now, interval = 10_000, 600
    assert F.produce(4, 4, None, now, interval) == (4, None)
    assert F.produce(1, 4, None, now, interval) == (1, now + interval)
    assert F.produce(1, 4, now + 5, now, interval) == (1, now + 5)
    # таймер истёк 2.5 интервала назад → 3 патогена, следующий таймер сдвинут на 3 интервала
    timer = now - int(2.5 * interval)
    assert F.produce(0, 10, timer, now, interval) == (3, timer + 3 * interval)
    # догон упирается в ёмкость — таймер сбрасывается
    assert F.produce(3, 4, now - 10 * interval, now, interval) == (4, None)


# --- Заражение ---

def test_infection_reward():
    assert F.infection_reward(1000, 5, 5) == 100
    assert F.infection_reward(1000, 10, 5) == 100
    assert F.infection_reward(1000, 1, 101) == 50
    assert F.infection_reward(0, 1, 1) == 1
    assert F.infection_reward(5, 1, 1) == 1


def test_fever_minutes_and_stacking():
    assert F.fever_minutes(1) == 1
    assert F.fever_minutes(9) == 3
    assert F.fever_minutes(300) == 100  # в тексте как в оригинале («Горячка на 222 минут»)
    assert F.fever_minutes(9, fever_pct=200) == 6
    assert (F.dossier_fever_minutes(1), F.dossier_fever_minutes(300), F.dossier_fever_minutes(540)) == (1, 100, 60)
    assert F.new_fever_until(1000, None, 5) == 1300
    assert F.new_fever_until(1000, 1000 + 3500, 5) == 1000 + 3600  # не больше часа
    assert F.new_fever_until(1000, 500, 2) == 1120  # старая горячка уже прошла


def test_vaccine_and_equal_range():
    assert F.vaccine_price(10) == 150
    assert F.vaccine_price(0) == 1
    assert F.equal_exp_range(1500) == (1000, 2250)


# --- Слоты премии ---

@pytest.mark.parametrize(
    ("now", "slot"),
    [
        (datetime(2026, 1, 1, 0, 0, 5, tzinfo=MSK), datetime(2026, 1, 1, 0, 0, tzinfo=MSK)),
        (datetime(2026, 1, 1, 11, 59, tzinfo=MSK), datetime(2026, 1, 1, 0, 0, tzinfo=MSK)),
        (datetime(2026, 1, 1, 12, 0, tzinfo=MSK), datetime(2026, 1, 1, 12, 0, tzinfo=MSK)),
        (datetime(2026, 1, 1, 23, 59, tzinfo=MSK), datetime(2026, 1, 1, 12, 0, tzinfo=MSK)),
    ],
)
def test_payout_slot(now, slot):
    assert F.payout_slot(now) == slot


def test_next_payout():
    assert F.next_payout(datetime(2026, 1, 1, 11, 59, tzinfo=MSK)) == datetime(2026, 1, 1, 12, 0, tzinfo=MSK)
    assert F.next_payout(datetime(2026, 1, 1, 12, 0, tzinfo=MSK)) == datetime(2026, 1, 2, 0, 0, tzinfo=MSK)
