"""Схема БД. Каждая миграция применяется один раз, версия — в PRAGMA user_version."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator

MIGRATIONS: list[str] = [
    # 1 — базовая схема
    """
    CREATE TABLE users (
        user_id       INTEGER PRIMARY KEY,
        full_name     TEXT    NOT NULL,
        username      TEXT,
        is_bot        INTEGER NOT NULL DEFAULT 0,
        tutorial_done INTEGER NOT NULL DEFAULT 0,
        created_at    INTEGER NOT NULL,
        last_seen     INTEGER NOT NULL
    );
    CREATE UNIQUE INDEX idx_users_username ON users(username COLLATE NOCASE)
        WHERE username IS NOT NULL;

    CREATE TABLE labs (
        user_id         INTEGER PRIMARY KEY REFERENCES users(user_id),
        lab_name        TEXT,
        lab_key         TEXT,
        pathogen_name   TEXT,
        pathogen_key    TEXT,
        emoji           TEXT,
        pathogens       INTEGER NOT NULL DEFAULT 4,
        ready_pathogens INTEGER NOT NULL DEFAULT 4,
        science         INTEGER NOT NULL DEFAULT 1,
        science_time    INTEGER,
        infect          INTEGER NOT NULL DEFAULT 1,
        immunity        INTEGER NOT NULL DEFAULT 1,
        lethality       INTEGER NOT NULL DEFAULT 1,
        security        INTEGER NOT NULL DEFAULT 1,
        bio_exp         INTEGER NOT NULL DEFAULT 1000,
        bio_res         INTEGER NOT NULL DEFAULT 15000,
        fever_until     INTEGER,
        fever_pathogen  TEXT,
        notify_chat_id  INTEGER,
        dossier_open    INTEGER NOT NULL DEFAULT 1,
        hidden          INTEGER NOT NULL DEFAULT 0,
        disabled        INTEGER NOT NULL DEFAULT 0,
        disabled_reason TEXT,
        disabled_until  INTEGER,
        created_at      INTEGER NOT NULL
    );
    CREATE UNIQUE INDEX idx_labs_lab_key ON labs(lab_key) WHERE lab_key IS NOT NULL;
    CREATE UNIQUE INDEX idx_labs_pathogen_key ON labs(pathogen_key) WHERE pathogen_key IS NOT NULL;
    CREATE INDEX idx_labs_exp ON labs(bio_exp DESC);
    -- производство патогенов: тик читает только лаборатории с наступившим таймером
    -- и те, что ждут запуска таймера, не сканируя всю таблицу
    CREATE INDEX idx_labs_timer ON labs(science_time) WHERE science_time IS NOT NULL;
    CREATE INDEX idx_labs_idle ON labs(user_id) WHERE science_time IS NULL AND ready_pathogens < pathogens;

    CREATE TABLE victims (
        owner_id       INTEGER NOT NULL,
        victim_id      INTEGER NOT NULL,
        expires_at     INTEGER NOT NULL,
        infected_at    INTEGER NOT NULL,
        cooldown_until INTEGER NOT NULL,
        earn           INTEGER NOT NULL,
        pathogen_name  TEXT,
        ss_detect      INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (owner_id, victim_id)
    );
    -- покрывающие индексы для «мж», «мб», счётчиков досье и премии
    CREATE INDEX idx_victims_owner ON victims(owner_id, expires_at, earn);
    CREATE INDEX idx_victims_victim ON victims(victim_id, expires_at);
    CREATE INDEX idx_victims_expires ON victims(expires_at);

    CREATE TABLE corporations (
        corp_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        code         TEXT    NOT NULL UNIQUE,
        name         TEXT    NOT NULL,
        name_key     TEXT    NOT NULL UNIQUE,
        leader_id    INTEGER NOT NULL UNIQUE,
        dossier_open INTEGER NOT NULL DEFAULT 1,
        created_at   INTEGER NOT NULL
    );

    CREATE TABLE corp_members (
        user_id   INTEGER PRIMARY KEY,
        corp_id   INTEGER NOT NULL REFERENCES corporations(corp_id) ON DELETE CASCADE,
        role      TEXT    NOT NULL CHECK (role IN ('leader', 'admin', 'member')),
        joined_at INTEGER NOT NULL
    );
    CREATE INDEX idx_corp_members_corp ON corp_members(corp_id);

    CREATE TABLE corp_requests (
        corp_id    INTEGER NOT NULL REFERENCES corporations(corp_id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (corp_id, user_id)
    );

    CREATE TABLE chats (
        chat_id    INTEGER PRIMARY KEY,
        title      TEXT,
        updated_at INTEGER NOT NULL
    );

    CREATE TABLE chat_members (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        PRIMARY KEY (chat_id, user_id)
    );

    CREATE TABLE infection_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        attacker_id INTEGER NOT NULL,
        victim_id   INTEGER NOT NULL,
        created_at  INTEGER NOT NULL
    );
    CREATE INDEX idx_infection_log_created ON infection_log(created_at);

    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE admins (
        user_id      INTEGER PRIMARY KEY,
        role         TEXT    NOT NULL CHECK (role IN ('admin', 'senior')),
        appointed_by INTEGER NOT NULL,
        created_at   INTEGER NOT NULL
    );

    CREATE TABLE admin_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id   INTEGER NOT NULL,
        target_id  INTEGER,
        action     TEXT    NOT NULL,
        details    TEXT,
        created_at INTEGER NOT NULL
    );

    CREATE TABLE sanctions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        kind       TEXT    NOT NULL CHECK (kind IN ('warning', 'ignore', 'lab_disabled')),
        reason     TEXT    NOT NULL,
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER,
        active     INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX idx_sanctions_user ON sanctions(user_id, kind, active);

    CREATE TABLE banned_names (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT    NOT NULL CHECK (kind IN ('lab', 'pathogen', 'corp')),
        name       TEXT    NOT NULL,
        name_key   TEXT    NOT NULL,
        reason     TEXT    NOT NULL,
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        UNIQUE (kind, name_key)
    );
    """,
    # 2 — служебный аккаунт Telegram (777000) с лабораторией: пример «заразить @777000» из обучения
    # работает, как в оригинале. Уведомления ему не шлются (notify_chat_id = NULL).
    """
    INSERT OR IGNORE INTO users (user_id, full_name, username, is_bot, tutorial_done, created_at, last_seen)
    VALUES (777000, 'Telegram', NULL, 0, 1, CAST(strftime('%s', 'now') AS INTEGER), CAST(strftime('%s', 'now') AS INTEGER));
    INSERT OR IGNORE INTO labs (user_id, pathogens, ready_pathogens, bio_exp, bio_res, notify_chat_id, created_at)
    VALUES (777000, 4, 4, 1000, 15000, NULL, CAST(strftime('%s', 'now') AS INTEGER));
    """,
    # 3 — групповые команды оригинала (правила, заметки, приветствия, ник), личные чаты в статистике,
    # запрет на игровые названия («эпимут») и игровой мут («эпиас»), быстрый поиск «слетевших» жертв для «мф»
    """
    ALTER TABLE chats ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE chats ADD COLUMN greet_join INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE chats ADD COLUMN greet_leave INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE chats ADD COLUMN rules TEXT;
    ALTER TABLE users ADD COLUMN nickname TEXT;

    CREATE TABLE chat_notes (
        chat_id    INTEGER NOT NULL,
        note_id    INTEGER NOT NULL,
        title      TEXT    NOT NULL,
        title_key  TEXT    NOT NULL,
        text       TEXT    NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (chat_id, note_id)
    );
    CREATE UNIQUE INDEX idx_chat_notes_title ON chat_notes(chat_id, title_key);

    CREATE TABLE sanctions_new (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        kind       TEXT    NOT NULL CHECK (kind IN ('warning', 'ignore', 'lab_disabled', 'name_mute', 'game_mute')),
        reason     TEXT    NOT NULL,
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER,
        active     INTEGER NOT NULL DEFAULT 1
    );
    INSERT INTO sanctions_new SELECT * FROM sanctions;
    DROP TABLE sanctions;
    ALTER TABLE sanctions_new RENAME TO sanctions;
    CREATE INDEX idx_sanctions_user ON sanctions(user_id, kind, active);

    CREATE INDEX idx_infection_log_attacker ON infection_log(attacker_id, victim_id);
    """,
]


def pending_scripts(current_version: int) -> Iterator[tuple[int, str]]:
    """Готовые к executescript миграции новее current_version: (версия, SQL-скрипт)."""
    for version, sql in enumerate(MIGRATIONS, start=1):
        if version > current_version:
            yield version, f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;"


def apply_migrations_sync(conn: sqlite3.Connection) -> int:
    """Применяет недостающие миграции к синхронному соединению. Возвращает итоговую версию."""
    for _, script in pending_scripts(conn.execute("PRAGMA user_version").fetchone()[0]):
        conn.executescript(script)
    return conn.execute("PRAGMA user_version").fetchone()[0]
