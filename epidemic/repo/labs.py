from __future__ import annotations

from epidemic.db import Q, Row, Tx
from epidemic.game import constants as C

LAB_SELECT = (
    "SELECT l.*, u.full_name, u.username, u.is_bot "
    "FROM labs l JOIN users u ON u.user_id = l.user_id"
)

# SQL-двойник is_disabled(): лаборатория активна (параметр :now). Используется с алиасом l.
ACTIVE_SQL = "(l.disabled = 0 OR (l.disabled_until IS NOT NULL AND l.disabled_until <= :now))"

# Лаборатории, которые видны в биотопах и доступны как случайные цели.
_VISIBLE_SQL = "l.hidden = 0 AND u.is_bot = 0"
_IN_CHAT_SQL = "(:chat IS NULL OR EXISTS (SELECT 1 FROM chat_members cm WHERE cm.chat_id = :chat AND cm.user_id = l.user_id))"

# Колонки названий: вид → (название, ключ уникальности)
NAME_COLUMNS: dict[str, tuple[str, str]] = {
    "lab": ("lab_name", "lab_key"),
    "pathogen": ("pathogen_name", "pathogen_key"),
}

# Колонки, которые разрешено менять через set_fields (защита от подстановки имён колонок).
EDITABLE = frozenset({
    "lab_name", "lab_key", "pathogen_name", "pathogen_key", "emoji",
    "pathogens", "ready_pathogens", "science", "science_time",
    "infect", "immunity", "lethality", "security",
    "bio_exp", "bio_res", "fever_until", "fever_pathogen",
    "notify_chat_id", "dossier_open", "hidden",
    "disabled", "disabled_reason", "disabled_until",
})


def display_name(row: Row) -> str:
    """Название лаборатории; если не задано — имя владельца."""
    return row["lab_name"] or row["full_name"]


def is_disabled(lab: Row, now: int) -> bool:
    if not lab["disabled"]:
        return False
    until = lab["disabled_until"]
    return until is None or until > now


def fever_left(lab: Row, now: int) -> int:
    until = lab["fever_until"]
    return max(0, until - now) if until else 0


async def ensure(t: Tx, user_id: int, now: int) -> bool:
    """Создаёт лабораторию, если её нет. Возвращает True, если создана."""
    created = await t.execute(
        """
        INSERT OR IGNORE INTO labs
            (user_id, pathogens, ready_pathogens, bio_exp, bio_res, notify_chat_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, C.START_PATHOGENS, C.START_PATHOGENS, C.START_BIO_EXP, C.START_BIO_RES, user_id, now),
    )
    return created > 0


async def get(q: Q, user_id: int) -> Row | None:
    return await q.fetchone(f"{LAB_SELECT} WHERE l.user_id = ?", (user_id,))


async def set_fields(q: Q, user_id: int, **fields: object) -> None:
    unknown = set(fields) - EDITABLE
    if unknown:
        raise ValueError(f"Недопустимые поля лаборатории: {unknown}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    await q.execute(f"UPDATE labs SET {assignments} WHERE user_id = ?", (*fields.values(), user_id))


async def add_resources(q: Q, user_id: int, delta: int) -> None:
    await q.execute("UPDATE labs SET bio_res = MAX(0, bio_res + ?) WHERE user_id = ?", (delta, user_id))


async def add_exp(q: Q, user_id: int, delta: int) -> None:
    await q.execute("UPDATE labs SET bio_exp = MAX(0, bio_exp + ?) WHERE user_id = ?", (delta, user_id))


# --- Названия ---

async def name_owner(q: Q, kind: str, key: str) -> int | None:
    _, key_col = NAME_COLUMNS[kind]
    return await q.fetchval(f"SELECT user_id FROM labs WHERE {key_col} = ?", (key,))


async def set_name(q: Q, user_id: int, kind: str, name: str | None, key: str | None) -> None:
    name_col, key_col = NAME_COLUMNS[kind]
    await q.execute(f"UPDATE labs SET {name_col} = ?, {key_col} = ? WHERE user_id = ?", (name, key, user_id))


async def reset_names(q: Q, kind: str, key: str) -> int:
    """Сбрасывает запрещённое название у всех, кто его носит."""
    name_col, key_col = NAME_COLUMNS[kind]
    return await q.execute(f"UPDATE labs SET {name_col} = NULL, {key_col} = NULL WHERE {key_col} = ?", (key,))


# --- Биотопы ---

async def biotop(q: Q, offset: int, limit: int, chat_id: int | None = None) -> list[Row]:
    """Топ по био-опыту: общий или только участников чата."""
    return await q.fetchall(
        f"{LAB_SELECT} WHERE {_VISIBLE_SQL} AND {_IN_CHAT_SQL} "
        "ORDER BY l.bio_exp DESC, l.user_id LIMIT :limit OFFSET :offset",
        {"chat": chat_id, "limit": limit, "offset": offset},
    )


async def biotop_total(q: Q, chat_id: int | None = None) -> int:
    return await q.fetchval(
        "SELECT SUM(l.bio_exp) FROM labs l JOIN users u ON u.user_id = l.user_id "
        f"WHERE {_VISIBLE_SQL} AND {_IN_CHAT_SQL}",
        {"chat": chat_id},
        default=0,
    )


async def random_target(
    q: Q,
    attacker_id: int,
    attacker_infect: int,
    exp_low: int | None,
    exp_high: int | None,
    max_gap: int,
    now: int,
) -> int | None:
    """Случайная доступная цель: не сам игрок, не на КД, пробиваемая, активная."""
    return await q.fetchval(
        f"""
        SELECT l.user_id FROM labs l JOIN users u ON u.user_id = l.user_id
        WHERE l.user_id != :attacker AND {_VISIBLE_SQL} AND {ACTIVE_SQL}
          AND (:low IS NULL OR l.bio_exp >= :low)
          AND (:high IS NULL OR l.bio_exp <= :high)
          AND l.immunity - :infect <= :max_gap
          AND NOT EXISTS (
              SELECT 1 FROM victims v
              WHERE v.owner_id = :attacker AND v.victim_id = l.user_id AND v.cooldown_until > :now
          )
        ORDER BY RANDOM() LIMIT 1
        """,
        {
            "attacker": attacker_id,
            "infect": attacker_infect,
            "low": exp_low,
            "high": exp_high,
            "max_gap": max_gap,
            "now": now,
        },
    )


async def count(q: Q) -> int:
    return await q.fetchval("SELECT COUNT(*) FROM labs", default=0)


async def total_exp(q: Q) -> int:
    return await q.fetchval("SELECT SUM(bio_exp) FROM labs", default=0) or 0


async def search_pathogen(q: Q, key: str, limit: int = 50) -> list[Row]:
    """Лаборатории, в названии патогена которых есть key — ключ names.name_key (для «/search_pathogen»).

    Ищем по ключу, а не по названию: LIKE в SQLite не различает регистр только у латиницы.
    """
    escaped = key.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return await q.fetchall(
        f"{LAB_SELECT} WHERE l.pathogen_key LIKE ? ESCAPE '!' ORDER BY l.user_id LIMIT ?",
        (f"%{escaped}%", limit),
    )
