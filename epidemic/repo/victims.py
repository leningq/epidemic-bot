from __future__ import annotations

from epidemic.db import Q, Row, Tx


async def get(q: Q, owner_id: int, victim_id: int) -> Row | None:
    return await q.fetchone(
        "SELECT * FROM victims WHERE owner_id = ? AND victim_id = ?", (owner_id, victim_id)
    )


async def count_owned(q: Q, owner_id: int, now: int) -> int:
    return await q.fetchval(
        "SELECT COUNT(*) FROM victims WHERE owner_id = ? AND expires_at > ?", (owner_id, now), default=0
    )


async def count_illnesses(q: Q, victim_id: int, now: int) -> int:
    return await q.fetchval(
        "SELECT COUNT(*) FROM victims WHERE victim_id = ? AND expires_at > ?", (victim_id, now), default=0
    )


async def list_owned(q: Q, owner_id: int, now: int, limit: int) -> list[Row]:
    return await q.fetchall(
        """
        SELECT v.*, l.lab_name, u.full_name
        FROM victims v
        JOIN labs l ON l.user_id = v.victim_id
        JOIN users u ON u.user_id = v.victim_id
        WHERE v.owner_id = ? AND v.expires_at > ?
        ORDER BY v.infected_at DESC
        LIMIT ?
        """,
        (owner_id, now, limit),
    )


async def owned_stats(q: Q, owner_id: int, now: int) -> tuple[int, int]:
    """(активных жертв, сумма earn) одним проходом по покрывающему индексу."""
    row = await q.fetchone(
        "SELECT COUNT(*), COALESCE(SUM(earn), 0) FROM victims WHERE owner_id = ? AND expires_at > ?",
        (owner_id, now),
    )
    return int(row[0]), int(row[1])


async def list_illnesses(q: Q, victim_id: int, now: int, limit: int) -> list[Row]:
    return await q.fetchall(
        """
        SELECT * FROM victims WHERE victim_id = ? AND expires_at > ?
        ORDER BY infected_at DESC LIMIT ?
        """,
        (victim_id, now, limit),
    )


async def upsert(
    t: Tx,
    owner_id: int,
    victim_id: int,
    expires_at: int,
    infected_at: int,
    cooldown_until: int,
    earn: int,
    pathogen_name: str | None,
    ss_detect: bool,
) -> None:
    await t.execute(
        """
        INSERT INTO victims
            (owner_id, victim_id, expires_at, infected_at, cooldown_until, earn, pathogen_name, ss_detect)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner_id, victim_id) DO UPDATE SET
            expires_at     = excluded.expires_at,
            infected_at    = excluded.infected_at,
            cooldown_until = excluded.cooldown_until,
            earn           = excluded.earn,
            pathogen_name  = excluded.pathogen_name,
            ss_detect      = excluded.ss_detect
        """,
        (owner_id, victim_id, expires_at, infected_at, cooldown_until, earn, pathogen_name, int(ss_detect)),
    )


async def delete_expired(t: Tx, now: int) -> int:
    """Удаляет истёкшие заражения. Запись держится, пока не закончится и КД на эту цель."""
    return await t.execute("DELETE FROM victims WHERE expires_at <= ? AND cooldown_until <= ?", (now, now))


async def top_income(q: Q, owner_id: int, limit: int = 20) -> list[Row]:
    """«мж топ»: жертвы с наибольшим доходом (включая уже истёкшие записи — они помечаются ⚠️)."""
    return await q.fetchall(
        """
        SELECT v.victim_id, v.earn, v.expires_at, u.full_name
        FROM victims v LEFT JOIN users u ON u.user_id = v.victim_id
        WHERE v.owner_id = ? AND v.earn > 0
        ORDER BY v.earn DESC LIMIT ?
        """,
        (owner_id, limit),
    )


async def fallen_targets(q: Q, owner_id: int, now: int) -> list[Row]:
    """«Слетевшие» цели для «мф»: заражение истекло или жертва была в истории, но сейчас не активна."""
    return await q.fetchall(
        """
        SELECT DISTINCT t.victim_id, u.full_name, u.username
        FROM (
            SELECT victim_id FROM victims WHERE owner_id = :owner AND expires_at <= :now
            UNION
            SELECT h.victim_id FROM infection_log h
            WHERE h.attacker_id = :owner
              AND NOT EXISTS (SELECT 1 FROM victims v WHERE v.owner_id = :owner AND v.victim_id = h.victim_id)
        ) AS t
        JOIN labs l ON l.user_id = t.victim_id
        LEFT JOIN users u ON u.user_id = t.victim_id
        WHERE t.victim_id != :owner
        ORDER BY t.victim_id
        """,
        {"owner": owner_id, "now": now},
    )


async def count_active(q: Q, now: int) -> int:
    return await q.fetchval("SELECT COUNT(*) FROM victims WHERE expires_at > ?", (now,), default=0)
