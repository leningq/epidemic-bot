"""Чаты: правила, заметки, приветствия/прощания, никнеймы."""
from __future__ import annotations

from epidemic.db import Q, Row


async def get(q: Q, chat_id: int) -> Row | None:
    return await q.fetchone("SELECT * FROM chats WHERE chat_id = ?", (chat_id,))


async def set_greeting(q: Q, chat_id: int, kind: str, enabled: bool) -> None:
    column = {"join": "greet_join", "leave": "greet_leave"}[kind]
    await q.execute(f"UPDATE chats SET {column} = ? WHERE chat_id = ?", (int(enabled), chat_id))


async def set_rules(q: Q, chat_id: int, text: str | None) -> None:
    await q.execute("UPDATE chats SET rules = ? WHERE chat_id = ?", (text, chat_id))


async def counts(q: Q) -> tuple[int, int]:
    """(личных чатов, групп)."""
    row = await q.fetchone("SELECT SUM(is_private), SUM(1 - is_private) FROM chats")
    return int(row[0] or 0), int(row[1] or 0)


# --- Заметки ---

async def notes(q: Q, chat_id: int) -> list[Row]:
    return await q.fetchall("SELECT * FROM chat_notes WHERE chat_id = ? ORDER BY note_id", (chat_id,))


async def note(q: Q, chat_id: int, title_or_id: str, key: str) -> Row | None:
    """Заметка по названию или по номеру («Заметка (номер или название)»)."""
    if title_or_id.isdecimal():
        found = await q.fetchone(
            "SELECT * FROM chat_notes WHERE chat_id = ? AND note_id = ?", (chat_id, int(title_or_id))
        )
        if found:
            return found
    return await q.fetchone("SELECT * FROM chat_notes WHERE chat_id = ? AND title_key = ?", (chat_id, key))


async def add_note(q: Q, chat_id: int, title: str, key: str, text: str, now: int) -> None:
    await q.execute(
        """
        INSERT INTO chat_notes (chat_id, note_id, title, title_key, text, created_at)
        VALUES (?, (SELECT COALESCE(MAX(note_id), 0) + 1 FROM chat_notes WHERE chat_id = ?), ?, ?, ?, ?)
        """,
        (chat_id, chat_id, title, key, text, now),
    )


async def delete_note(q: Q, chat_id: int, note_id: int) -> None:
    await q.execute("DELETE FROM chat_notes WHERE chat_id = ? AND note_id = ?", (chat_id, note_id))


async def set_nickname(q: Q, user_id: int, nickname: str) -> None:
    await q.execute("UPDATE users SET nickname = ? WHERE user_id = ?", (nickname, user_id))
