from __future__ import annotations

from epidemic.db import Q, Row, Tx

CORP_SELECT = (
    "SELECT c.*, u.full_name AS leader_name "
    "FROM corporations c JOIN users u ON u.user_id = c.leader_id"
)


async def by_code(q: Q, code: str) -> Row | None:
    return await q.fetchone(f"{CORP_SELECT} WHERE c.code = ?", (code.lower(),))


async def by_id(q: Q, corp_id: int) -> Row | None:
    return await q.fetchone(f"{CORP_SELECT} WHERE c.corp_id = ?", (corp_id,))


async def membership(q: Q, user_id: int) -> Row | None:
    """Корпорация игрока вместе с его ролью (или None)."""
    return await q.fetchone(
        """
        SELECT c.*, u.full_name AS leader_name, m.role
        FROM corp_members m
        JOIN corporations c ON c.corp_id = m.corp_id
        JOIN users u ON u.user_id = c.leader_id
        WHERE m.user_id = ?
        """,
        (user_id,),
    )


async def code_exists(q: Q, code: str) -> bool:
    return bool(await q.fetchval("SELECT 1 FROM corporations WHERE code = ?", (code,)))


async def name_owner(q: Q, key: str) -> int | None:
    return await q.fetchval("SELECT corp_id FROM corporations WHERE name_key = ?", (key,))


async def create(t: Tx, leader_id: int, name: str, key: str, code: str, now: int) -> int:
    corp_id = await t.insert(
        "INSERT INTO corporations (code, name, name_key, leader_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (code, name, key, leader_id, now),
    )
    await t.execute(
        "INSERT INTO corp_members (user_id, corp_id, role, joined_at) VALUES (?, ?, 'leader', ?)",
        (leader_id, corp_id, now),
    )
    await t.execute("DELETE FROM corp_requests WHERE user_id = ?", (leader_id,))
    return corp_id


async def delete(t: Tx, corp_id: int) -> None:
    await t.execute("DELETE FROM corp_requests WHERE corp_id = ?", (corp_id,))
    await t.execute("DELETE FROM corp_members WHERE corp_id = ?", (corp_id,))
    await t.execute("DELETE FROM corporations WHERE corp_id = ?", (corp_id,))


async def rename(q: Q, corp_id: int, name: str, key: str) -> None:
    await q.execute("UPDATE corporations SET name = ?, name_key = ? WHERE corp_id = ?", (name, key, corp_id))


async def set_dossier(q: Q, corp_id: int, is_open: bool) -> None:
    await q.execute("UPDATE corporations SET dossier_open = ? WHERE corp_id = ?", (int(is_open), corp_id))


async def member_count(q: Q, corp_id: int) -> int:
    return await q.fetchval("SELECT COUNT(*) FROM corp_members WHERE corp_id = ?", (corp_id,), default=0)


async def members(q: Q, corp_id: int) -> list[Row]:
    return await q.fetchall(
        """
        SELECT m.user_id, m.role, l.bio_exp, l.lab_name, u.full_name
        FROM corp_members m
        JOIN labs l ON l.user_id = m.user_id
        JOIN users u ON u.user_id = m.user_id
        WHERE m.corp_id = ?
        ORDER BY l.bio_exp DESC
        """,
        (corp_id,),
    )


async def staff(q: Q, corp_id: int) -> list[Row]:
    return await q.fetchall(
        """
        SELECT m.user_id, m.role, u.full_name
        FROM corp_members m JOIN users u ON u.user_id = m.user_id
        WHERE m.corp_id = ? AND m.role IN ('leader', 'admin')
        ORDER BY m.role = 'leader' DESC, m.joined_at
        """,
        (corp_id,),
    )


async def stats(q: Q, corp_id: int, now: int) -> tuple[int, int, int]:
    """(суммарный био-опыт, активных заражённых, лабораторий)."""
    row = await q.fetchone(
        """
        SELECT
            COALESCE(SUM(l.bio_exp), 0) AS exp,
            COUNT(*) AS labs,
            COALESCE(SUM((SELECT COUNT(*) FROM victims v
                          WHERE v.owner_id = m.user_id AND v.expires_at > :now)), 0) AS infected
        FROM corp_members m JOIN labs l ON l.user_id = m.user_id
        WHERE m.corp_id = :corp
        """,
        {"corp": corp_id, "now": now},
    )
    return int(row["exp"]), int(row["infected"]), int(row["labs"])


async def top(q: Q, limit: int) -> list[Row]:
    return await q.fetchall(
        """
        SELECT c.corp_id, c.name, c.leader_id, COALESCE(SUM(l.bio_exp), 0) AS exp
        FROM corporations c
        JOIN corp_members m ON m.corp_id = c.corp_id
        JOIN labs l ON l.user_id = m.user_id
        GROUP BY c.corp_id
        ORDER BY exp DESC
        LIMIT ?
        """,
        (limit,),
    )


async def add_member(t: Tx, corp_id: int, user_id: int, now: int) -> None:
    await t.execute(
        "INSERT INTO corp_members (user_id, corp_id, role, joined_at) VALUES (?, ?, 'member', ?)",
        (user_id, corp_id, now),
    )
    await t.execute("DELETE FROM corp_requests WHERE user_id = ?", (user_id,))


async def remove_member(q: Q, user_id: int) -> None:
    await q.execute("DELETE FROM corp_members WHERE user_id = ? AND role != 'leader'", (user_id,))


async def set_role(q: Q, user_id: int, role: str) -> None:
    if role not in ("admin", "member"):
        raise ValueError(role)
    await q.execute("UPDATE corp_members SET role = ? WHERE user_id = ? AND role != 'leader'", (role, user_id))


async def member_role(q: Q, corp_id: int, user_id: int) -> str | None:
    return await q.fetchval(
        "SELECT role FROM corp_members WHERE corp_id = ? AND user_id = ?", (corp_id, user_id)
    )


async def has_request(q: Q, corp_id: int, user_id: int) -> bool:
    return bool(await q.fetchval(
        "SELECT 1 FROM corp_requests WHERE corp_id = ? AND user_id = ?", (corp_id, user_id)
    ))


async def add_request(q: Q, corp_id: int, user_id: int, now: int) -> None:
    await q.execute(
        "INSERT OR IGNORE INTO corp_requests (corp_id, user_id, created_at) VALUES (?, ?, ?)",
        (corp_id, user_id, now),
    )


async def delete_request(q: Q, corp_id: int, user_id: int) -> None:
    await q.execute("DELETE FROM corp_requests WHERE corp_id = ? AND user_id = ?", (corp_id, user_id))


async def requests(q: Q, corp_id: int) -> list[Row]:
    return await q.fetchall(
        """
        SELECT r.user_id, l.bio_exp, l.lab_name, u.full_name
        FROM corp_requests r
        JOIN labs l ON l.user_id = r.user_id
        JOIN users u ON u.user_id = r.user_id
        WHERE r.corp_id = ?
        ORDER BY r.created_at
        """,
        (corp_id,),
    )


async def count(q: Q) -> int:
    return await q.fetchval("SELECT COUNT(*) FROM corporations", default=0)
