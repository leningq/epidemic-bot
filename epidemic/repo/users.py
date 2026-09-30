from __future__ import annotations

from epidemic.db import Q, Row, Tx


async def upsert(t: Tx, user_id: int, full_name: str, username: str | None, is_bot: bool, now: int) -> None:
    if username:
        # Username мог перейти к другому человеку — у прежнего владельца сбрасываем.
        await t.execute(
            "UPDATE users SET username = NULL WHERE username = ? COLLATE NOCASE AND user_id != ?",
            (username, user_id),
        )
    await t.execute(
        """
        INSERT INTO users (user_id, full_name, username, is_bot, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            full_name = excluded.full_name,
            username  = excluded.username,
            is_bot    = excluded.is_bot,
            last_seen = excluded.last_seen
        """,
        (user_id, full_name, username, int(is_bot), now, now),
    )


async def get(q: Q, user_id: int) -> Row | None:
    return await q.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))


async def id_by_username(q: Q, username: str) -> int | None:
    return await q.fetchval(
        "SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username.lstrip("@"),)
    )


async def set_tutorial_done(q: Q, user_id: int, done: bool) -> None:
    await q.execute("UPDATE users SET tutorial_done = ? WHERE user_id = ?", (int(done), user_id))


async def count(q: Q) -> int:
    return await q.fetchval("SELECT COUNT(*) FROM users WHERE is_bot = 0", default=0)
