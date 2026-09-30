"""Экономика: ежедневная премия и производство патогенов."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from epidemic.db import Database, Q
from epidemic.game import formulas as F
from epidemic.game.settings import GameSettings
from epidemic.repo import labs, meta, victims
from epidemic.repo.labs import ACTIVE_SQL

LAST_PAYOUT_KEY = "last_payout_slot"
INFECTION_LOG_KEEP_SEC = 30 * 86400

_LAB_TIMER_COLUMNS = "l.user_id, l.science, l.pathogens, l.ready_pathogens, l.science_time"


async def pay_premium(db: Database, gs: GameSettings, now: int, slot_key: str | None = None) -> tuple[int, int]:
    """Начисляет премию по активным жертвам и чистит истёкшие. Возвращает (игроков, сумма)."""
    async with db.tx() as t:
        rows = await t.fetchall(
            f"""
            SELECT v.owner_id, SUM(v.earn) AS total
            FROM victims v JOIN labs l ON l.user_id = v.owner_id
            WHERE v.expires_at > :now AND {ACTIVE_SQL}
            GROUP BY v.owner_id
            """,
            {"now": now},
        )
        payouts = [(F.apply_pct(r["total"], gs.daily_pct), r["owner_id"]) for r in rows]
        payouts = [p for p in payouts if p[0] > 0]
        await t.executemany("UPDATE labs SET bio_res = bio_res + ? WHERE user_id = ?", payouts)
        await victims.delete_expired(t, now)
        await t.execute("DELETE FROM infection_log WHERE created_at < ?", (now - INFECTION_LOG_KEEP_SEC,))
        if slot_key is not None:
            await meta.put(t, LAST_PAYOUT_KEY, slot_key)
    return len(payouts), sum(amount for amount, _ in payouts)


async def expected_premium(q: Q, gs: GameSettings, owner_id: int, now: int) -> tuple[int, int, int]:
    """(активных жертв, сумма опыта с них, ближайшая премия) — то же правило, что в pay_premium."""
    count, earn = await victims.owned_stats(q, owner_id, now)
    lab = await labs.get(q, owner_id)
    premium = 0 if lab is None or labs.is_disabled(lab, now) else F.apply_pct(earn, gs.daily_pct)
    return count, earn, premium


async def payout_if_due(db: Database, gs: GameSettings, tz: ZoneInfo, now: int) -> tuple[int, int] | None:
    """Выплачивает премию, если наступил новый слот (00:00/12:00). Пропущенный слот догоняется один раз."""
    slot = F.payout_slot(datetime.fromtimestamp(now, tz))
    last_raw = await gs.get_meta(LAST_PAYOUT_KEY)
    if last_raw is None:
        # Первый запуск: не платим задним числом, просто запоминаем текущий слот.
        await gs.set_meta(LAST_PAYOUT_KEY, slot.isoformat())
        return None
    try:
        last = datetime.fromisoformat(last_raw)
    except ValueError:
        last = None
    if last is not None and last >= slot:
        return None
    return await pay_premium(db, gs, now, slot_key=slot.isoformat())


async def production_tick(db: Database, gs: GameSettings, now: int) -> int:
    """Выдаёт готовые патогены. Читает только лаборатории с наступившим таймером
    и те, у которых таймер ещё не запущен (оба запроса идут по частичным индексам)."""
    async with db.tx() as t:
        params = {"now": now}
        due = await t.fetchall(
            f"SELECT {_LAB_TIMER_COLUMNS} FROM labs l "
            f"WHERE l.science_time IS NOT NULL AND l.science_time <= :now AND {ACTIVE_SQL}",
            params,
        )
        idle = await t.fetchall(
            f"SELECT {_LAB_TIMER_COLUMNS} FROM labs l "
            f"WHERE l.science_time IS NULL AND l.ready_pathogens < l.pathogens AND {ACTIVE_SQL}",
            params,
        )
        updates = []
        for r in (*due, *idle):
            interval = F.production_interval_sec(r["science"], gs.speed_pct)
            ready, timer = F.produce(r["ready_pathogens"], r["pathogens"], r["science_time"], now, interval)
            if ready != r["ready_pathogens"] or timer != r["science_time"]:
                updates.append((ready, timer, r["user_id"]))
        if updates:
            await t.executemany("UPDATE labs SET ready_pathogens = ?, science_time = ? WHERE user_id = ?", updates)
    return len(updates)


async def clamp_timers(db: Database, gs: GameSettings, now: int) -> int:
    """После ускорения производства таймеры не должны ждать дольше нового интервала."""
    async with db.tx() as t:
        rows = await t.fetchall(
            "SELECT user_id, science, science_time FROM labs WHERE science_time IS NOT NULL AND science_time > ?",
            (now,),
        )
        updates = [
            (now + interval, r["user_id"])
            for r in rows
            if r["science_time"] > now + (interval := F.production_interval_sec(r["science"], gs.speed_pct))
        ]
        if updates:
            await t.executemany("UPDATE labs SET science_time = ? WHERE user_id = ?", updates)
    return len(updates)
