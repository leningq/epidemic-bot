"""Перенос игроков из базы старого бота (bot.py «BioWars») в новую базу.

Запускать при остановленном боте:

    python -m tools.migrate_from_biowars OLD.sqlite3 [NEW.sqlite3] [--force]

NEW.sqlite3 по умолчанию берётся из DB_PATH. Новая база должна быть пустой (без лабораторий),
иначе нужен --force: тогда записи с теми же ID обновляются, а конфликтующие названия и username
у переносимых игроков сбрасываются (чужие записи не трогаются).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from epidemic.config import load_config
from epidemic.game import constants as C
from epidemic.game.naming import fallback_corp_name
from epidemic.schema import apply_migrations_sync
from epidemic.utils.fmt import clean_name
from epidemic.utils.names import name_key, normalize, validate

OLD_TZ = ZoneInfo("Europe/Riga")  # старый бот хранил локальное время Риги без зоны
OLD_DEFAULT_LAB = "моя лаборатория"
OLD_DEFAULT_PATHOGEN = "неизвестный патоген"
OLD_SETTING_DEFAULTS = {
    "maintenance_mode": 0, "owner_only_mode": 0, "xp_multiplier_pct": 100,
    "daily_reward_multiplier_pct": 100, "upgrade_cost_multiplier_pct": 100,
    "production_speed_multiplier_pct": 100, "fever_multiplier_pct": 100,
    "infection_cooldown_minutes": 120, "max_infection_gap": 200,
}
SANCTION_KINDS = {"account_ignore": "ignore", "lab_disabled": "lab_disabled", "manual": "warning"}


def ts(value: str | int | float | None) -> int | None:
    """Дата старой базы → unix-время. None — пусто или не удалось разобрать.

    Понимает «2025-05-01 12:00:00», с долями секунды, с «T», с часовым поясом и unix-число.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or str(value).strip().isdecimal():
        return int(float(value))
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=OLD_TZ)
    return int(parsed.timestamp())


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT * FROM {table}").fetchall() if table in tables(conn) else []


class Migrator:
    def __init__(self, old: sqlite3.Connection, new: sqlite3.Connection) -> None:
        self.old = old
        self.new = new
        self.now = int(time.time())
        self.stats: dict[str, int] = {}
        self.user_ids: set[int] = {r[0] for r in new.execute("SELECT user_id FROM users")}
        self.lab_ids: set[int] = {r[0] for r in new.execute("SELECT user_id FROM labs")}
        # Занятые ключи уникальности: ключ → владелец (для лабораторий — user_id, для корпораций — corp_id)
        self._taken: dict[str, dict[str, int]] = {"lab": {}, "pathogen": {}, "corp": {}, "username": {}}
        for uid, lab_key, pathogen_key in new.execute("SELECT user_id, lab_key, pathogen_key FROM labs"):
            if lab_key:
                self._taken["lab"][lab_key] = uid
            if pathogen_key:
                self._taken["pathogen"][pathogen_key] = uid
        for uid, username in new.execute("SELECT user_id, username FROM users WHERE username IS NOT NULL"):
            self._taken["username"][username.lower()] = uid
        self._corp_codes = {r[0]: r[1] for r in new.execute("SELECT code, corp_id FROM corporations")}
        self._corp_leaders = {r[0]: r[1] for r in new.execute("SELECT leader_id, corp_id FROM corporations")}
        for corp_id, key in new.execute("SELECT corp_id, name_key FROM corporations"):
            self._taken["corp"][key] = corp_id

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def _claim(self, kind: str, key: str, owner: int) -> bool:
        holder = self._taken[kind].get(key)
        if holder is not None and holder != owner:
            return False
        self._taken[kind][key] = owner
        return True

    def _deadline(self, value: str | None) -> int | None:
        """Срок окончания наказания. Пусто — бессрочно (как в старой базе).

        Неразборчивая дата считается уже истёкшей: иначе временное наказание стало бы вечным.
        """
        if value is None or value == "":
            return None
        parsed = ts(value)
        if parsed is None:
            self._count("unparsed_deadlines")
            return self.now
        return parsed

    def _fallback_corp_name(self, corp_id: int) -> tuple[str, str]:
        """«Корпорация N», а если такое название уже занято — «Корпорация N-2» и т. д."""
        base, key = fallback_corp_name(corp_id)
        name, n = base, 1
        while not self._claim("corp", key, corp_id):
            n += 1
            name = f"{base}-{n}"
            key = name_key(name)
        return name, key

    def _unique_name(self, kind: str, raw: str | None, owner: int, default_key: str | None = None) -> tuple[str | None, str | None]:
        if not raw:
            return None, None
        name = normalize(raw)
        key = name_key(name)
        if key == default_key or validate(kind, name) or not self._claim(kind, key, owner):
            return None, None
        return name, key

    def run(self) -> dict[str, int]:
        self.users()
        self.labs()
        self.corporations()
        self.victims()
        self.admin_data()
        self.chats()
        return self.stats

    # --- Пользователи и лаборатории ---

    def users(self) -> None:
        for r in rows(self.old, "users"):
            uid = r["user_id"]
            username = r["username"]
            if username and not self._claim("username", username.lower(), uid):
                username = None
            created = ts(r["created_at"]) or self.now
            self.new.execute(
                """
                INSERT INTO users (user_id, full_name, username, is_bot, tutorial_done, created_at, last_seen)
                VALUES (?, ?, ?, 0, 1, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    full_name = excluded.full_name, username = excluded.username, last_seen = excluded.last_seen
                """,
                (uid, clean_name(r["display_name"] or username or str(uid)), username, created, ts(r["last_seen"]) or created),
            )
            self.user_ids.add(uid)
            self._count("users")

    def _ensure_user(self, user_id: int) -> None:
        if user_id not in self.user_ids:
            self.new.execute(
                "INSERT OR IGNORE INTO users (user_id, full_name, created_at, last_seen, tutorial_done) "
                "VALUES (?, ?, ?, ?, 1)",
                (user_id, str(user_id), self.now, self.now),
            )
            self.user_ids.add(user_id)

    def _ensure_lab(self, user_id: int) -> None:
        """Лаборатория со стартовыми значениями — для участников корпораций, у которых её не было."""
        self._ensure_user(user_id)
        if user_id not in self.lab_ids:
            self.new.execute(
                "INSERT OR IGNORE INTO labs (user_id, pathogens, ready_pathogens, bio_exp, bio_res, notify_chat_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, C.START_PATHOGENS, C.START_PATHOGENS, C.START_BIO_EXP, C.START_BIO_RES, user_id, self.now),
            )
            self.lab_ids.add(user_id)

    def labs(self) -> None:
        notify = {r["user_id"]: r["chat_id"] for r in rows(self.old, "chat_notify") if r["enabled"]}
        for r in rows(self.old, "labs"):
            uid = r["user_id"]
            self._ensure_user(uid)
            lab_name, lab_key = self._unique_name("lab", r["lab_name"], uid, OLD_DEFAULT_LAB)
            pathogen, pathogen_key = self._unique_name("pathogen", r["pathogen_name"], uid, OLD_DEFAULT_PATHOGEN)
            capacity = max(C.START_PATHOGENS, int(r["storage"] or 0))
            values = {
                "user_id": uid, "lab_name": lab_name, "lab_key": lab_key,
                "pathogen_name": pathogen, "pathogen_key": pathogen_key,
                "pathogens": capacity, "ready_pathogens": min(capacity, max(0, int(r["pathogens"] or 0))),
                "science": min(C.SCIENCE_MAX, max(1, int(r["qualification"] or 1))),
                "infect": max(1, int(r["infectivity"] or 1)), "immunity": max(1, int(r["immunity"] or 1)),
                "lethality": max(1, int(r["lethality"] or 1)), "security": max(1, int(r["security"] or 1)),
                "bio_exp": max(0, int(r["bio_exp"] or 0)), "bio_res": max(0, int(r["bio_resources"] or 0)),
                "notify_chat_id": notify.get(uid, uid), "dossier_open": int(bool(r["public_lab"])),
                "disabled": int(bool(r["disabled"])), "disabled_reason": r["disabled_reason"],
                "disabled_until": self._deadline(r["disabled_until"]), "created_at": ts(r["created_at"]) or self.now,
            }
            columns = ", ".join(values)
            updates = ", ".join(f"{c} = excluded.{c}" for c in values if c != "user_id")
            self.new.execute(
                f"INSERT INTO labs ({columns}) VALUES ({', '.join('?' * len(values))}) "
                f"ON CONFLICT(user_id) DO UPDATE SET {updates}",
                tuple(values.values()),
            )
            self.lab_ids.add(uid)
            self._count("labs")

    # --- Корпорации ---

    def corporations(self) -> None:
        members_by_corp: dict[int, list[sqlite3.Row]] = {}
        for m in rows(self.old, "corp_members"):
            members_by_corp.setdefault(m["corp_id"], []).append(m)
        placed: set[int] = set()
        for c in rows(self.old, "corporations"):
            corp_id, leader, code = c["id"], c["leader_id"], str(c["code"]).lower()
            if self._corp_codes.get(code, corp_id) != corp_id or self._corp_leaders.get(leader, corp_id) != corp_id:
                self._count("corporations_skipped")  # код или лидер уже заняты другой корпорацией
                continue
            name, key = self._unique_name("corp", c["name"], corp_id)
            if name is None:
                name, key = self._fallback_corp_name(corp_id)
            self._ensure_lab(leader)
            self.new.execute(
                """
                INSERT INTO corporations (corp_id, code, name, name_key, leader_id, dossier_open, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(corp_id) DO UPDATE SET
                    code = excluded.code, name = excluded.name, name_key = excluded.name_key,
                    leader_id = excluded.leader_id, dossier_open = excluded.dossier_open
                """,
                (corp_id, code, name, key, leader, int(bool(c["member_list_public"])), ts(c["created_at"]) or self.now),
            )
            self._corp_codes[code] = corp_id
            self._corp_leaders[leader] = corp_id
            self._count("corporations")
            old_roles = {m["user_id"]: m["role"] for m in members_by_corp.get(corp_id, [])}
            old_roles[leader] = "leader"
            for uid, old_role in old_roles.items():
                # участник одной корпорации — один раз; но лидер всегда записывается в свою,
                # даже если раньше попал рядовым в другую (иначе корпорация осталась бы без лидера)
                if uid in placed and uid != leader:
                    continue
                self._ensure_lab(uid)
                role = "leader" if uid == leader else ("member" if old_role in (None, "member", "leader") else "admin")
                self.new.execute(
                    """
                    INSERT INTO corp_members (user_id, corp_id, role, joined_at) VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET corp_id = excluded.corp_id, role = excluded.role
                    """,
                    (uid, corp_id, role, self.now),
                )
                placed.add(uid)
                self._count("corp_members")

    # --- Заражения ---

    def victims(self) -> None:
        cooldowns = {
            (r["attacker_id"], r["victim_id"]): ts(r["next_available"]) or 0
            for r in rows(self.old, "infection_cooldowns")
        }
        infections = sorted(rows(self.old, "infections"), key=lambda r: r["started_at"] or "")
        for r in infections:
            expires = ts(r["ends_at"])
            if not r["active"] or not expires or expires <= self.now:
                continue
            if r["attacker_id"] not in self.lab_ids or r["victim_id"] not in self.lab_ids:
                continue
            self.new.execute(
                """
                INSERT INTO victims
                    (owner_id, victim_id, expires_at, infected_at, cooldown_until, earn, pathogen_name, ss_detect)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(owner_id, victim_id) DO UPDATE SET
                    expires_at = excluded.expires_at, infected_at = excluded.infected_at,
                    cooldown_until = excluded.cooldown_until, earn = excluded.earn,
                    pathogen_name = excluded.pathogen_name
                """,
                (r["attacker_id"], r["victim_id"], expires, ts(r["started_at"]) or self.now,
                 cooldowns.get((r["attacker_id"], r["victim_id"]), 0), max(1, int(r["daily_reward"] or 1)),
                 r["pathogen_name"]),
            )
            self._count("victims")

    # --- Админка ---

    def admin_data(self) -> None:
        for r in rows(self.old, "admins"):
            if r["role"] in ("admin", "senior"):
                self.new.execute(
                    """
                    INSERT INTO admins (user_id, role, appointed_by, created_at) VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET role = excluded.role
                    """,
                    (r["user_id"], r["role"], r["appointed_by"], ts(r["created_at"]) or self.now),
                )
                self._count("admins")
        for r in rows(self.old, "banned_names"):
            if r["kind"] in ("lab", "pathogen"):
                self.new.execute(
                    """
                    INSERT OR IGNORE INTO banned_names (kind, name, name_key, reason, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (r["kind"], r["name"], name_key(r["name"]), r["reason"], r["created_by"],
                     ts(r["created_at"]) or self.now),
                )
                self._count("banned_names")
        for r in rows(self.old, "sanctions"):
            kind = SANCTION_KINDS.get(r["kind"])
            if kind is None:
                continue
            # повторный запуск с --force не должен удваивать историю наказаний
            created = ts(r["created_at"]) or self.now
            inserted = self.new.execute(
                """
                INSERT INTO sanctions (user_id, kind, reason, created_by, created_at, expires_at, active)
                SELECT ?, ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM sanctions
                    WHERE user_id = ? AND kind = ? AND reason = ? AND created_by = ? AND created_at = ?
                )
                """,
                (r["user_id"], kind, r["reason"], r["created_by"], created,
                 self._deadline(r["expires_at"]), int(bool(r["active"])),
                 r["user_id"], kind, r["reason"], r["created_by"], created),
            ).rowcount
            if inserted:
                self._count("sanctions")
        for r in rows(self.old, "settings"):
            key = r["key"]
            if key not in OLD_SETTING_DEFAULTS:
                continue
            try:
                value = int(r["value"])
            except (TypeError, ValueError):
                continue
            if value != OLD_SETTING_DEFAULTS[key]:
                self.new.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )
                self._count("settings")

    def chats(self) -> None:
        for r in rows(self.old, "chat_participants"):
            if r["user_id"] in self.user_ids:
                self.new.execute(
                    "INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)", (r["chat_id"], r["user_id"])
                )
                self._count("chat_members")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Перенос данных из базы старого bot.py")
    parser.add_argument("old", help="путь к старой базе (biowars.sqlite3)")
    parser.add_argument("new", nargs="?", help="путь к новой базе (по умолчанию DB_PATH)")
    parser.add_argument("--force", action="store_true", help="разрешить перенос в непустую базу")
    args = parser.parse_args(argv)

    new_path = args.new or str(load_config().db_path)
    old = sqlite3.connect(f"file:{args.old}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    new = sqlite3.connect(new_path, isolation_level=None)
    new.row_factory = sqlite3.Row
    try:
        if "labs" not in tables(old):
            print("❌ В старой базе нет таблицы labs — это точно база bot.py?")
            return 1
        apply_migrations_sync(new)
        # служебная лаборатория Telegram (777000) создаётся схемой и игроком не считается
        existing = new.execute("SELECT COUNT(*) FROM labs WHERE user_id != ?", (C.TELEGRAM_SERVICE_ID,)).fetchone()[0]
        if existing and not args.force:
            print(f"❌ В новой базе уже {existing} лабораторий. Остановите бота и запустите с --force.")
            return 1
        new.execute("PRAGMA foreign_keys = ON")
        new.execute("BEGIN")
        stats = Migrator(old, new).run()
        new.execute("COMMIT")
    except Exception:
        if new.in_transaction:
            new.execute("ROLLBACK")
        raise
    finally:
        old.close()
        new.close()
    print("✅ Перенос завершён:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
