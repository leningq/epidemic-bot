"""Роли администраторов, журнал действий, санкции и запрещённые названия."""
from __future__ import annotations

from epidemic.db import Q, Row, Tx

ROLE_LEVEL = {"admin": 1, "senior": 2}


async def role(q: Q, user_id: int) -> str | None:
    return await q.fetchval("SELECT role FROM admins WHERE user_id = ?", (user_id,))


async def set_role(q: Q, user_id: int, new_role: str, appointed_by: int, now: int) -> None:
    if new_role not in ROLE_LEVEL:
        raise ValueError(new_role)
    await q.execute(
        """
        INSERT INTO admins (user_id, role, appointed_by, created_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET role = excluded.role, appointed_by = excluded.appointed_by
        """,
        (user_id, new_role, appointed_by, now),
    )


async def remove_role(q: Q, user_id: int) -> None:
    await q.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))


async def list_admins(q: Q) -> list[Row]:
    return await q.fetchall(
        """
        SELECT a.*, u.full_name, u.username
        FROM admins a LEFT JOIN users u ON u.user_id = a.user_id
        ORDER BY a.role = 'senior' DESC, a.created_at
        """
    )


async def log(q: Q, actor_id: int, target_id: int | None, action: str, details: str, now: int) -> None:
    await q.execute(
        "INSERT INTO admin_log (actor_id, target_id, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
        (actor_id, target_id, action, details[:500], now),
    )


async def history(q: Q, limit: int) -> list[Row]:
    return await q.fetchall("SELECT * FROM admin_log ORDER BY id DESC LIMIT ?", (limit,))


# --- Санкции ---

async def add_sanction(
    q: Q, user_id: int, kind: str, reason: str, created_by: int, now: int, expires_at: int | None = None
) -> None:
    await q.execute(
        """
        INSERT INTO sanctions (user_id, kind, reason, created_by, created_at, expires_at, active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (user_id, kind, reason[:300], created_by, now, expires_at),
    )


async def deactivate(q: Q, user_id: int, kind: str) -> int:
    return await q.execute(
        "UPDATE sanctions SET active = 0 WHERE user_id = ? AND kind = ? AND active = 1", (user_id, kind)
    )


async def active_ignores(q: Q, now: int, user_id: int | None = None) -> dict[int, int | None]:
    """{user_id: до какого времени} для полного игнора («+ас») и игрового мута («эпиас»).

    Действует самый длинный из активных: бессрочный (NULL) не перекрывается временным.
    """
    rows = await q.fetchall(
        """
        SELECT user_id,
               CASE WHEN COUNT(*) = COUNT(expires_at) THEN MAX(expires_at) END AS until
        FROM sanctions
        WHERE kind IN ('ignore', 'game_mute') AND active = 1 AND (expires_at IS NULL OR expires_at > :now)
          AND (:user IS NULL OR user_id = :user)
        GROUP BY user_id
        """,
        {"now": now, "user": user_id},
    )
    return {r["user_id"]: r["until"] for r in rows}


async def active_sanction(q: Q, user_id: int, kind: str, now: int) -> Row | None:
    """Действующая санкция вида kind (последняя), с учётом срока."""
    return await q.fetchone(
        """
        SELECT * FROM sanctions
        WHERE user_id = ? AND kind = ? AND active = 1 AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY id DESC LIMIT 1
        """,
        (user_id, kind, now),
    )


async def active_issuers(q: Q, user_id: int, kind: str, now: int) -> list[int]:
    """Кто выдал игроку действующие санкции вида kind."""
    rows = await q.fetchall(
        """
        SELECT DISTINCT created_by FROM sanctions
        WHERE user_id = ? AND kind = ? AND active = 1 AND (expires_at IS NULL OR expires_at > ?)
        """,
        (user_id, kind, now),
    )
    return [r["created_by"] for r in rows]


async def active_list(q: Q, kind: str, now: int, limit: int = 50) -> list[Row]:
    """Список действующих санкций вида kind — для «!эпимут» / «!эпиас»."""
    return await q.fetchall(
        """
        SELECT s.*, u.full_name FROM sanctions s LEFT JOIN users u ON u.user_id = s.user_id
        WHERE s.kind = ? AND s.active = 1 AND (s.expires_at IS NULL OR s.expires_at > ?)
        ORDER BY s.id DESC LIMIT ?
        """,
        (kind, now, limit),
    )


async def sanctions_of(q: Q, user_id: int, limit: int = 20) -> list[Row]:
    return await q.fetchall(
        "SELECT * FROM sanctions WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
    )


# --- Запрещённые названия ---

async def banned_name(q: Q, kind: str, key: str) -> Row | None:
    return await q.fetchone("SELECT * FROM banned_names WHERE kind = ? AND name_key = ?", (kind, key))


async def ban_name(t: Tx, kind: str, name: str, key: str, reason: str, by: int, now: int) -> bool:
    inserted = await t.execute(
        """
        INSERT OR IGNORE INTO banned_names (kind, name, name_key, reason, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (kind, name, key, reason[:300], by, now),
    )
    return inserted > 0


async def unban_name(q: Q, kind: str, key: str) -> int:
    return await q.execute("DELETE FROM banned_names WHERE kind = ? AND name_key = ?", (kind, key))


async def banned_names(q: Q) -> list[Row]:
    return await q.fetchall("SELECT * FROM banned_names ORDER BY id DESC LIMIT 100")
