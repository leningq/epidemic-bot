"""Перенос данных из базы старого bot.py (схема взята из его init_db)."""
import sqlite3
from datetime import datetime, timedelta

from tools.migrate_from_biowars import main

OLD_SCHEMA = """
CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, started INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE labs (user_id INTEGER PRIMARY KEY, lab_name TEXT NOT NULL DEFAULT 'Моя лаборатория',
  pathogen_name TEXT NOT NULL DEFAULT 'Неизвестный патоген', corporation_id INTEGER,
  bio_exp INTEGER NOT NULL DEFAULT 10000, bio_resources INTEGER NOT NULL DEFAULT 10000,
  infectivity INTEGER NOT NULL DEFAULT 1, immunity INTEGER NOT NULL DEFAULT 1, lethality INTEGER NOT NULL DEFAULT 1,
  security INTEGER NOT NULL DEFAULT 1, qualification INTEGER NOT NULL DEFAULT 1, development INTEGER NOT NULL DEFAULT 1,
  storage INTEGER NOT NULL DEFAULT 10, pathogens INTEGER NOT NULL DEFAULT 10, infected_count INTEGER NOT NULL DEFAULT 0,
  public_lab INTEGER NOT NULL DEFAULT 1, disabled INTEGER NOT NULL DEFAULT 0, disabled_reason TEXT, disabled_until TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE infection_cooldowns (attacker_id INTEGER NOT NULL, victim_id INTEGER NOT NULL, next_available TEXT NOT NULL,
  PRIMARY KEY(attacker_id, victim_id));
CREATE TABLE infections (id INTEGER PRIMARY KEY AUTOINCREMENT, attacker_id INTEGER NOT NULL, victim_id INTEGER NOT NULL,
  pathogen_name TEXT NOT NULL, started_at TEXT NOT NULL, ends_at TEXT NOT NULL, daily_reward INTEGER NOT NULL,
  first_infection INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE corporations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, code TEXT UNIQUE NOT NULL,
  leader_id INTEGER NOT NULL, member_list_public INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE corp_members (corp_id INTEGER, user_id INTEGER PRIMARY KEY, role TEXT NOT NULL DEFAULT 'member', joined_at TEXT NOT NULL);
CREATE TABLE banned_names (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL, normalized TEXT NOT NULL,
  reason TEXT NOT NULL, created_by INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(kind, normalized));
CREATE TABLE sanctions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, kind TEXT NOT NULL, reason TEXT NOT NULL,
  created_by INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE admins (user_id INTEGER PRIMARY KEY, role TEXT NOT NULL, appointed_by INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE chat_participants (chat_id INTEGER, user_id INTEGER, PRIMARY KEY(chat_id,user_id));
CREATE TABLE chat_notify (user_id INTEGER PRIMARY KEY, chat_id INTEGER, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
"""


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_old_db(path) -> None:
    now = datetime.now()
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    for uid, name, username in [(1, "Анна", "anna_x"), (2, "Иван", None), (3, "Олег", "oleg_y")]:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, 1, ?, ?)", (uid, username, name, fmt(now), fmt(now)))
    conn.execute(
        "INSERT INTO labs (user_id, lab_name, pathogen_name, bio_exp, bio_resources, infectivity, qualification, "
        "storage, pathogens, created_at) VALUES (1, 'Бункер', 'Чума', 5000, 7000, 12, 80, 15, 9, ?)",
        (fmt(now),),
    )
    conn.execute("INSERT INTO labs (user_id, created_at) VALUES (2, ?)", (fmt(now),))
    conn.execute(
        "INSERT INTO labs (user_id, lab_name, pathogen_name, created_at) VALUES (3, 'бункер', 'чума', ?)", (fmt(now),)
    )
    conn.execute("INSERT INTO corporations VALUES (1, 'Альфа', 'ABC123', 1, 0, ?)", (fmt(now),))
    conn.execute("INSERT INTO corp_members VALUES (1, 1, 'leader', ?)", (fmt(now),))
    conn.execute("INSERT INTO corp_members VALUES (1, 2, 'co', ?)", (fmt(now),))  # соучредитель
    # корпорация, лидер которой никогда не создавал лабораторию
    conn.execute("INSERT INTO users VALUES (4, NULL, 'Без лабы', 1, ?, ?)", (fmt(now), fmt(now)))
    conn.execute("INSERT INTO corporations VALUES (2, 'Бета', 'zzz999', 4, 1, ?)", (fmt(now),))
    conn.execute(
        "INSERT INTO infections (attacker_id, victim_id, pathogen_name, started_at, ends_at, daily_reward) "
        "VALUES (1, 2, 'Чума', ?, ?, 250)",
        (fmt(now), fmt(now + timedelta(days=3))),
    )
    conn.execute(
        "INSERT INTO infections (attacker_id, victim_id, pathogen_name, started_at, ends_at, daily_reward) "
        "VALUES (1, 3, 'Чума', ?, ?, 99)",
        (fmt(now - timedelta(days=5)), fmt(now - timedelta(days=1))),
    )
    conn.execute("INSERT INTO admins VALUES (3, 'senior', 1, ?)", (fmt(now),))
    conn.execute("INSERT INTO sanctions (user_id, kind, reason, created_by, created_at) VALUES (2, 'account_ignore', 'спам', 1, ?)", (fmt(now),))
    conn.execute("INSERT INTO chat_notify VALUES (1, -500, 1)")
    conn.execute("INSERT INTO settings VALUES ('xp_multiplier_pct', '150')")
    conn.execute("INSERT INTO settings VALUES ('max_infection_gap', '200')")
    conn.commit()
    conn.close()


def test_migration(tmp_path, capsys):
    old, new = tmp_path / "old.sqlite3", tmp_path / "new.sqlite3"
    build_old_db(old)
    assert main([str(old), str(new)]) == 0

    conn = sqlite3.connect(new)
    conn.row_factory = sqlite3.Row
    anna = conn.execute("SELECT * FROM labs WHERE user_id = 1").fetchone()
    assert (anna["lab_name"], anna["pathogen_name"]) == ("Бункер", "Чума")
    assert (anna["science"], anna["infect"], anna["pathogens"], anna["ready_pathogens"]) == (60, 12, 15, 9)
    assert (anna["bio_exp"], anna["bio_res"], anna["notify_chat_id"]) == (5000, 7000, -500)

    ivan = conn.execute("SELECT * FROM labs WHERE user_id = 2").fetchone()
    assert ivan["lab_name"] is None and ivan["pathogen_name"] is None  # старые значения по умолчанию
    oleg = conn.execute("SELECT * FROM labs WHERE user_id = 3").fetchone()
    assert oleg["lab_name"] is None and oleg["pathogen_name"] is None  # дубликаты названий сброшены

    corp = conn.execute("SELECT * FROM corporations WHERE corp_id = 1").fetchone()
    assert (corp["code"], corp["name"], corp["dossier_open"]) == ("abc123", "Альфа", 0)
    roles = dict(conn.execute("SELECT user_id, role FROM corp_members WHERE corp_id = 1").fetchall())
    assert roles == {1: "leader", 2: "admin"}
    # лидер без лаборатории получил стартовую — карточка корпорации не упадёт
    assert conn.execute("SELECT bio_res FROM labs WHERE user_id = 4").fetchone()[0] == 15_000

    victims = conn.execute("SELECT * FROM victims").fetchall()
    assert [(v["owner_id"], v["victim_id"], v["earn"]) for v in victims] == [(1, 2, 250)]
    assert conn.execute("SELECT role FROM admins WHERE user_id = 3").fetchone()[0] == "senior"
    assert conn.execute("SELECT kind FROM sanctions").fetchone()[0] == "ignore"
    settings = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    assert settings == {"xp_multiplier_pct": "150"}  # значение по умолчанию (200) не переносится
    conn.close()

    # повторный запуск в непустую базу без --force запрещён
    assert main([str(old), str(new)]) == 1


def test_migration_force_keeps_other_players(tmp_path):
    old, new = tmp_path / "old.sqlite3", tmp_path / "new.sqlite3"
    build_old_db(old)
    # в новой базе уже играет посторонний игрок с тем же названием лаборатории и username
    conn = sqlite3.connect(new)
    from epidemic.schema import apply_migrations_sync

    apply_migrations_sync(conn)
    conn.execute("INSERT INTO users (user_id, full_name, username, created_at, last_seen) VALUES (99, 'Чужой', 'anna_x', 0, 0)")
    conn.execute("INSERT INTO labs (user_id, lab_name, lab_key, created_at) VALUES (99, 'Бункер', 'бункер', 0)")
    conn.commit()
    conn.close()

    assert main([str(old), str(new), "--force"]) == 0
    assert main([str(old), str(new), "--force"]) == 0  # повторный запуск тоже безопасен

    conn = sqlite3.connect(new)
    assert conn.execute("SELECT lab_name FROM labs WHERE user_id = 99").fetchone()[0] == "Бункер"
    assert conn.execute("SELECT username FROM users WHERE user_id = 99").fetchone()[0] == "anna_x"
    assert conn.execute("SELECT lab_name FROM labs WHERE user_id = 1").fetchone()[0] is None
    assert conn.execute("SELECT username FROM users WHERE user_id = 1").fetchone()[0] is None
    assert conn.execute("SELECT pathogen_name FROM labs WHERE user_id = 1").fetchone()[0] == "Чума"
    conn.close()
