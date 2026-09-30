import asyncio
from datetime import datetime

from epidemic.game import economy, upgrade
from epidemic.game import formulas as F
from epidemic.repo import labs, victims
from tests.conftest import NOW, make_player


# --- Прокачка ---

async def test_quote_and_apply(db, gs):
    await make_player(db, 1)
    q = await upgrade.quote(db, gs, 1, "infect", 3, NOW)
    assert q.status == upgrade.OK
    assert (q.from_lvl, q.to_lvl, q.price) == (1, 4, F.upgrade_cost("infect", 1, 4))
    r = await upgrade.apply(db, gs, 1, "infect", 3, NOW)
    assert r.status == upgrade.OK
    lab = await labs.get(db, 1)
    assert lab["infect"] == 4
    assert lab["bio_res"] == 15_000 - q.price


async def test_not_enough_resources(db, gs):
    await make_player(db, 1, bio_res=3)
    r = await upgrade.apply(db, gs, 1, "immunity", 1, NOW)
    assert r.status == upgrade.NOT_ENOUGH
    assert (await labs.get(db, 1))["immunity"] == 1


async def test_science_cap(db, gs):
    await make_player(db, 1, science=59, bio_res=10**9)
    assert (await upgrade.apply(db, gs, 1, "science", 2, NOW)).status == upgrade.MAX_LEVEL
    assert (await upgrade.apply(db, gs, 1, "science", 1, NOW)).status == upgrade.OK


async def test_pathogen_capacity_also_adds_ready(db, gs):
    await make_player(db, 1, ready_pathogens=1)
    await upgrade.apply(db, gs, 1, "pathogens", 2, NOW)
    lab = await labs.get(db, 1)
    assert (lab["pathogens"], lab["ready_pathogens"]) == (6, 3)


async def test_cost_multiplier(db, gs):
    await gs.set("upgrade_cost_multiplier_pct", 50)
    await make_player(db, 1)
    q = await upgrade.quote(db, gs, 1, "infect", 10, NOW)
    assert q.price == F.upgrade_cost("infect", 1, 11, 50)


async def test_disabled_lab_cannot_upgrade(db, gs):
    await make_player(db, 1, disabled=1)
    assert (await upgrade.apply(db, gs, 1, "infect", 1, NOW)).status == upgrade.DISABLED


async def test_downgrade_refunds_half(db, gs):
    await make_player(db, 1, infect=11, bio_res=0)
    d = await upgrade.downgrade(db, gs, 1, "infect", 1, NOW)
    assert d.status == upgrade.OK and d.refund == F.upgrade_cost("infect", 10, 11) // 2
    lab = await labs.get(db, 1)
    assert (lab["infect"], lab["bio_res"]) == (10, d.refund)
    assert (await upgrade.downgrade(db, gs, 1, "infect", 10, NOW)).status == upgrade.MIN_LEVEL


async def test_downgrade_refund_never_exceeds_base_price(db, gs):
    await gs.set("upgrade_cost_multiplier_pct", 300)
    await make_player(db, 1, infect=11, bio_res=0)
    d = await upgrade.downgrade(db, gs, 1, "infect", 1, NOW)
    assert d.refund == F.upgrade_cost("infect", 10, 11) // 2  # как при 100 %, а не 150 %


async def test_downgrade_pathogens_trims_ready(db, gs):
    await make_player(db, 1, pathogens=6, ready_pathogens=6)
    await upgrade.downgrade(db, gs, 1, "pathogens", 2, NOW)
    lab = await labs.get(db, 1)
    assert (lab["pathogens"], lab["ready_pathogens"]) == (4, 4)


async def test_concurrent_upgrades_do_not_double_spend(db, gs):
    price = F.upgrade_cost("infect", 1, 2)
    await make_player(db, 1, bio_res=price)
    results = await asyncio.gather(*(upgrade.apply(db, gs, 1, "infect", 1, NOW) for _ in range(5)))
    assert sum(r.status == upgrade.OK for r in results) == 1
    lab = await labs.get(db, 1)
    assert (lab["infect"], lab["bio_res"]) == (2, 0)


# --- Премия ---

async def _victim(db, owner, victim, earn, expires):
    async with db.tx() as t:
        await victims.upsert(t, owner, victim, expires, NOW, NOW, earn, None, False)


async def test_pay_premium(db, gs):
    for uid in (1, 2, 3, 4):
        await make_player(db, uid, bio_res=0)
    await labs.set_fields(db, 4, disabled=1)
    await _victim(db, 1, 2, 100, NOW + 100)
    await _victim(db, 1, 3, 50, NOW + 100)
    await _victim(db, 1, 4, 999, NOW - 1)      # истекла — не платится и удаляется
    await _victim(db, 4, 1, 500, NOW + 100)    # владелец отключён — не платится
    players, total = await economy.pay_premium(db, gs, NOW)
    assert (players, total) == (1, 150)
    assert (await labs.get(db, 1))["bio_res"] == 150
    assert (await labs.get(db, 4))["bio_res"] == 0
    assert await victims.get(db, 1, 4) is None


async def test_expired_infection_keeps_cooldown_record(db, gs):
    await make_player(db, 1)
    await make_player(db, 2)
    async with db.tx() as t:  # заражение уже кончилось, а КД ещё идёт
        await victims.upsert(t, 1, 2, NOW - 1, NOW - 100, NOW + 3600, 100, None, False)
    await economy.pay_premium(db, gs, NOW)
    assert (await victims.get(db, 1, 2))["cooldown_until"] == NOW + 3600
    assert (await labs.get(db, 1))["bio_res"] == 15_000  # истёкшая жертва премию не приносит


async def test_premium_multiplier(db, gs):
    await gs.set("daily_reward_multiplier_pct", 200)
    await make_player(db, 1, bio_res=0)
    await make_player(db, 2)
    await _victim(db, 1, 2, 100, NOW + 100)
    await economy.pay_premium(db, gs, NOW)
    assert (await labs.get(db, 1))["bio_res"] == 200


async def test_payout_slots_are_paid_once(db, gs):
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Moscow")
    await make_player(db, 1, bio_res=0)
    await make_player(db, 2)
    await _victim(db, 1, 2, 100, NOW + 10 * 86400)

    t0 = int(datetime(2027, 1, 15, 10, 0, tzinfo=tz).timestamp())
    assert await economy.payout_if_due(db, gs, tz, t0) is None          # первый запуск — только запоминаем
    assert await economy.payout_if_due(db, gs, tz, t0 + 600) is None    # тот же слот
    noon = int(datetime(2027, 1, 15, 12, 0, 10, tzinfo=tz).timestamp())
    assert await economy.payout_if_due(db, gs, tz, noon) == (1, 100)
    assert await economy.payout_if_due(db, gs, tz, noon + 60) is None
    # бот лежал сутки — догоняем один пропущенный слот
    later = noon + 30 * 3600
    assert await economy.payout_if_due(db, gs, tz, later) == (1, 100)
    assert (await labs.get(db, 1))["bio_res"] == 200


# --- Резервная копия ---

async def test_backup_is_consistent_copy(tmp_path, gs):
    import sqlite3
    from zoneinfo import ZoneInfo

    from epidemic.config import Config
    from epidemic.db import Database
    from epidemic.services.scheduler import make_backup

    db = Database(tmp_path / "live.sqlite3")
    await db.connect()
    await make_player(db, 1, bio_res=777)
    config = Config("", frozenset(), ZoneInfo("Europe/Moscow"), tmp_path / "live.sqlite3", tmp_path, "", "", "", "", "", "", "", "INFO")
    path = await make_backup(db, tmp_path / "backups", config)
    await db.close()
    copy = sqlite3.connect(path)
    assert copy.execute("SELECT bio_res FROM labs WHERE user_id = 1").fetchone()[0] == 777
    copy.close()


# --- Производство ---

async def test_production_tick(db, gs):
    await make_player(db, 1, ready_pathogens=0, science=1)
    await economy.production_tick(db, gs, NOW)
    assert (await labs.get(db, 1))["science_time"] == NOW + 3600
    await economy.production_tick(db, gs, NOW + 3600)
    lab = await labs.get(db, 1)
    assert (lab["ready_pathogens"], lab["science_time"]) == (1, NOW + 7200)
    await economy.production_tick(db, gs, NOW + 10 * 3600)  # долгий простой — догоняем до ёмкости
    lab = await labs.get(db, 1)
    assert (lab["ready_pathogens"], lab["science_time"]) == (4, None)


async def test_production_speed_change_pulls_timer_in(db, gs):
    await make_player(db, 1, ready_pathogens=0, science=1, science_time=NOW + 3600)
    await gs.set("production_speed_multiplier_pct", 400)
    assert await economy.clamp_timers(db, gs, NOW) == 1
    assert (await labs.get(db, 1))["science_time"] == NOW + 900


async def test_science_upgrade_shortens_running_timer(db, gs):
    await make_player(db, 1, ready_pathogens=0, science=1, science_time=NOW + 3600, bio_res=10**9)
    await upgrade.apply(db, gs, 1, "science", 30, NOW)  # 31 ур → 30 минут на патоген
    assert (await labs.get(db, 1))["science_time"] == NOW + 30 * 60


async def test_production_tick_reads_only_due_labs(db, gs):
    """Тик не трогает лаборатории, чей таймер ещё не наступил (частичные индексы)."""
    await make_player(db, 1, ready_pathogens=0, science_time=NOW + 100)
    await make_player(db, 2, ready_pathogens=0, science_time=NOW - 1)
    assert await economy.production_tick(db, gs, NOW) == 1
    plan = " ".join(r[3] for r in await db.fetchall(
        "EXPLAIN QUERY PLAN SELECT user_id FROM labs l WHERE l.science_time IS NOT NULL AND l.science_time <= 1"
    ))
    assert "idx_labs_timer" in plan


async def test_admin_set_level_keeps_invariants(db, gs):
    await make_player(db, 1, pathogens=10, ready_pathogens=8, science_time=NOW + 100)
    assert await upgrade.set_level(db, 1, "pathogens", 5) == (10, 5)
    lab = await labs.get(db, 1)
    assert (lab["pathogens"], lab["ready_pathogens"], lab["science_time"]) == (5, 5, None)
    assert await upgrade.set_level(db, 1, "science", 999) == (1, 60)
    assert await upgrade.set_level(db, 1, "ready_pathogens", 50) == (5, 5)
    assert await upgrade.set_level(db, 404, "infect", 5) is None
