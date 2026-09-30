import pytest

from epidemic.game import constants as C
from epidemic.game import infection
from epidemic.repo import labs, victims
from tests.conftest import NOW, make_player

ALWAYS = lambda: 0.0  # noqa: E731 — бросок всегда удачный
NEVER = lambda: 0.999999  # noqa: E731 — бросок всегда неудачный (если шанс < 100 %)


async def test_success_transfers_exp_and_sets_fever(db, gs, acc):
    await make_player(db, 1, "Атакующий")
    await make_player(db, 2, "Жертва")

    r = await infection.attempt(db, gs, acc, 1, 2, 1, NOW, rng=NEVER)  # 1 vs 1 → шанс 100 %

    assert r.status == infection.SUCCESS
    assert (r.earn, r.fever_minutes, r.days, r.spent, r.pathogens_left, r.is_new) == (100, 1, 1, 1, 3, True)
    attacker, victim = await labs.get(db, 1), await labs.get(db, 2)
    assert attacker["bio_exp"] == 1100
    assert attacker["ready_pathogens"] == 3
    assert attacker["science_time"] == NOW + 3600
    assert victim["bio_exp"] == 900
    assert victim["fever_until"] == NOW + 60
    record = await victims.get(db, 1, 2)
    assert record["expires_at"] == NOW + 86400
    assert record["cooldown_until"] == NOW + gs.cooldown_sec
    assert record["earn"] == 100
    assert await db.fetchval("SELECT COUNT(*) FROM infection_log") == 1


async def test_cooldown_blocks_same_target(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2)
    await infection.attempt(db, gs, acc, 1, 2, 1, NOW)
    r = await infection.attempt(db, gs, acc, 1, 2, 1, NOW + 60)
    assert r.status == infection.COOLDOWN
    assert r.wait == gs.cooldown_sec - 60


async def test_fever_blocks_victim_from_attacking(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2)
    await infection.attempt(db, gs, acc, 1, 2, 1, NOW)
    r = await infection.attempt(db, gs, acc, 2, 1, 1, NOW + 10)
    assert r.status == infection.FEVER
    assert r.wait == 50


async def test_failure_spends_pathogens_and_accumulates_chance(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2, immunity=11)  # отставание 10 → базовый шанс 6 %

    first = await infection.attempt(db, gs, acc, 1, 2, 2, NOW, rng=NEVER)
    assert first.status == infection.FAIL
    assert first.spent == 2 and first.pathogens_left == 2
    assert first.chance == pytest.approx(6.0 * 1.2722)

    second = await infection.attempt(db, gs, acc, 1, 2, 1, NOW + 5, rng=NEVER)
    assert second.chance == pytest.approx(first.chance + 6.0 / 4)
    assert (await labs.get(db, 1))["ready_pathogens"] == 1
    assert await victims.get(db, 1, 2) is None  # провал не ставит КД


async def test_accumulation_expires_after_window(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2, immunity=11)
    await infection.attempt(db, gs, acc, 1, 2, 1, NOW, rng=NEVER)
    later = await infection.attempt(db, gs, acc, 1, 2, 1, NOW + 61, rng=NEVER)
    assert later.chance == pytest.approx(6.0)


async def test_spends_only_available_pathogens(db, gs, acc):
    await make_player(db, 1, ready_pathogens=3)
    await make_player(db, 2)
    r = await infection.attempt(db, gs, acc, 1, 2, 5, NOW)
    assert r.spent == 3 and r.pathogens_left == 0


async def test_no_pathogens(db, gs, acc):
    await make_player(db, 1, ready_pathogens=0)
    await make_player(db, 2)
    assert (await infection.attempt(db, gs, acc, 1, 2, 1, NOW)).status == infection.NO_PATHOGENS


async def test_gap_limit(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2, immunity=1 + gs.max_gap + 1)
    r = await infection.attempt(db, gs, acc, 1, 2, 1, NOW)
    assert r.status == infection.GAP and r.gap == gs.max_gap + 1
    assert (await labs.get(db, 1))["ready_pathogens"] == 4  # патогены не тратятся


async def test_invalid_targets(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2, disabled=1, disabled_reason="тест")
    await make_player(db, 3)
    assert (await infection.attempt(db, gs, acc, 1, 1, 1, NOW)).status == infection.SELF
    assert (await infection.attempt(db, gs, acc, 1, 999, 1, NOW)).status == infection.VICTIM_NO_LAB
    assert (await infection.attempt(db, gs, acc, 1, 2, 1, NOW)).status == infection.VICTIM_DISABLED
    assert (await infection.attempt(db, gs, acc, 2, 3, 1, NOW)).status == infection.DISABLED
    assert (await infection.attempt(db, gs, acc, 404, 3, 1, NOW)).status == infection.NO_LAB


async def test_temporary_disable_expires(db, gs, acc):
    await make_player(db, 1, disabled=1, disabled_until=NOW - 1)
    await make_player(db, 2)
    assert (await infection.attempt(db, gs, acc, 1, 2, 1, NOW)).status == infection.SUCCESS


async def test_xp_multiplier_rewards_attacker_only(db, gs, acc):
    await gs.set("xp_multiplier_pct", 200)
    await make_player(db, 1)
    await make_player(db, 2)
    r = await infection.attempt(db, gs, acc, 1, 2, 1, NOW)
    assert r.earn == 200
    assert (await labs.get(db, 1))["bio_exp"] == 1200
    assert (await labs.get(db, 2))["bio_exp"] == 900


async def test_security_detection_and_lethality(db, gs, acc):
    await make_player(db, 1, lethality=9, pathogen_name="Чума", pathogen_key="чума")
    await make_player(db, 2, security=5)
    r = await infection.attempt(db, gs, acc, 1, 2, 1, NOW)
    assert r.ss_detect is True
    assert (r.fever_minutes, r.days) == (3, 9)
    victim = await labs.get(db, 2)
    assert victim["fever_pathogen"] == "Чума"
    assert (await victims.get(db, 1, 2))["expires_at"] == NOW + 9 * 86400


async def test_reinfection_after_cooldown_is_not_new(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2)
    await infection.attempt(db, gs, acc, 1, 2, 1, NOW)
    r = await infection.attempt(db, gs, acc, 1, 2, 1, NOW + gs.cooldown_sec + 1)
    assert r.status == infection.SUCCESS and r.is_new is False


async def test_random_target_modes(db, gs, acc):
    await labs.set_fields(db, C.TELEGRAM_SERVICE_ID, hidden=1)  # служебная лаба не должна мешать выборке
    attacker = await make_player(db, 1, bio_exp=1000)
    await make_player(db, 2, bio_exp=5000)   # сильнее
    await make_player(db, 3, bio_exp=1200)   # равный
    await make_player(db, 4, bio_exp=100)    # слабее
    assert await infection.pick_random_target(db, gs, attacker, "stronger", NOW) in (2, 3)
    assert await infection.pick_random_target(db, gs, attacker, "equal", NOW) == 3  # 667..1500
    assert await infection.pick_random_target(db, gs, attacker, "weaker", NOW) == 4
    assert await infection.pick_random_target(db, gs, attacker, "random", NOW) in (2, 3, 4)


async def test_random_target_skips_cooldown_hidden_and_unreachable(db, gs, acc):
    await labs.set_fields(db, C.TELEGRAM_SERVICE_ID, hidden=1)
    attacker = await make_player(db, 1, bio_exp=1000)
    await make_player(db, 2, bio_exp=5000, hidden=1)
    await make_player(db, 3, bio_exp=6000, immunity=500)
    await make_player(db, 4, bio_exp=7000)
    await infection.attempt(db, gs, acc, 1, 4, 1, NOW)
    attacker = await labs.get(db, 1)
    assert await infection.pick_random_target(db, gs, attacker, "stronger", NOW) is None


async def test_buy_vaccine(db, gs, acc):
    await make_player(db, 1)
    await make_player(db, 2, immunity=10)
    assert await infection.buy_vaccine(db, 2, NOW) == ("healthy", 0)
    await infection.attempt(db, gs, acc, 1, 2, 1, NOW, rng=ALWAYS)
    # 1 vs 10 → шанс ≈ 7.8 %, но rng=ALWAYS гарантирует успех
    await labs.set_fields(db, 2, bio_res=10)
    assert await infection.buy_vaccine(db, 2, NOW) == ("not_enough", 150)
    await labs.set_fields(db, 2, bio_res=1000)
    assert await infection.buy_vaccine(db, 2, NOW) == (infection.SUCCESS, 150)
    victim = await labs.get(db, 2)
    assert victim["fever_until"] is None and victim["bio_res"] == 850
