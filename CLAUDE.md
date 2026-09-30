# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Эпидемик" — a text-based Telegram game ("bio-wars") for group chats: a clone of the core of the
«Эпидемик 2.0» bot (@epidemic2_bot) plus the client's owner/admin panel. Python 3.12, aiogram 3, SQLite
(aiosqlite), deployed to the client's server with Docker Compose. All player-facing text is Russian.
Game numbers (chance table, upgrade exponents, start values) were taken from the original bot's source
and must stay 1:1 unless the user asks otherwise — see `docs/ARCHITECTURE.md` §4.

The client requires the bot to be **1:1 with the original, including texts**. Player-facing texts are copied
verbatim from the original — typos, odd punctuation and grammar included («Ты все таки», «Улучшение на 1
уровней», «жертву, для заражения»). Do not "fix" them. The tutorial lives in `epidemic/data/story.yml`
(original YAML with folded blocks, `{bot}` = our username); the chat-manager texts (RP templates, notes,
rules, leave/bot-join messages) are an automated export of the original in `epidemic/data/chat.yml`;
other texts are in `views/*.py` and `texts.py`.
`docs/REFERENCE_SPEC.md` is the screen-by-screen spec from the client's screenshots, and
`tests/test_reference_texts.py` pins each screen character by character. Number formats follow the
original: commas (`6,991,031`) in messages, spaces only in the «лаб»/«мл» dossiers.

## Commands

```bash
pip install -r requirements-dev.txt
pytest                                   # all tests (pytest.ini: asyncio_mode=auto, pythonpath=.)
pytest tests/test_infection.py -k cooldown   # single test
python -m epidemic                       # run the bot locally (reads .env: BOT_TOKEN, ADMIN_ID, ...)
docker compose up -d --build             # production run; data lives in the `epidemic_data` volume
python -m tools.migrate_from_biowars OLD.sqlite3 [NEW.sqlite3] [--force]   # import the client's old bot.py DB
python -m tools.build_archive            # dist/epidemic-bot.tar.gz for the client (no .env, tests, docs)
```

`docs/HANDOFF.md` is the plain-language handoff for the next developer: what is left before release,
where things live, and what not to touch.

On the author's Windows machine `venv` creation fails (missing `venvlauncher.exe`), so dependencies are
installed into `.pydeps/` instead. Run tests from PowerShell with
`$env:PYTHONPATH = "<repo>\.pydeps;<repo>"` and the full path to Python 3.11
(`C:\Users\Максим\AppData\Local\Programs\Python\Python311\python.exe -m pytest`). `pyflakes` is installed
there too for unused-import checks. Docker is not installed locally.

## Architecture

Layers, top to bottom — keep logic at the lowest layer that can own it:

- `handlers/` — parse the command, call one game service, map the returned **status constant** to text.
  Handlers hold no game rules. Pattern: `result = await svc.op(...)` → `view.status_text(result)` or a
  `{status: text}` table (see `handlers/infect.py::_REPLIES`, `handlers/upgrade.py::_status_text`).
- `views/` + `texts.py` — all message text. `texts.py` holds static strings and the tutorial;
  `views/*.py` render DB rows. Numbers in text come from `game/constants.py`, never hard-coded.
- `game/` — rules. `formulas.py` is pure (unit-tested); `infection.py`, `upgrade.py`, `corps.py`,
  `economy.py`, `naming.py` are services that do **all checks and writes inside one `db.tx()`**.
- `repo/` — SQL only. Column names in f-string SQL must come from a whitelist
  (`labs.EDITABLE`, `labs.NAME_COLUMNS`, `C.SKILLS`).
- `db.py` — one aiosqlite connection per process; every write goes through `Database.tx()` under an
  `asyncio.Lock`. Inside a transaction use the `Tx` object passed in: calling `db.execute()`/`db.tx()`
  again raises (nested-transaction guard). Never do Telegram network I/O inside a transaction.

Cross-cutting behaviour that is easy to miss:

- **Every group message goes through all filters**, so command filters must be async `Filter`
  subclasses (`handlers/common.Cmd` via `cmd(pattern)`), not `F.text.regexp(...)`: aiogram runs sync
  callables (including MagicFilter) in `asyncio.to_thread`.
- `middlewares/registration.py` (outer, also on `chat_member`/`my_chat_member`) upserts every user it
  sees — sender, reply target, text_mention, joining member — and auto-creates a lab (15 000 🧬 / 1 000 ☣️ /
  4 pathogens). That is why any chat member can be infected. It also records chats (private chats with
  `is_private=1`, used by «!стата») and chat membership. It is LRU-cached to avoid a DB write per message.
- `middlewares/access.py` (inner, runs only when a handler matched): ignore list, maintenance and
  owner-only modes. The ignore list covers two sanction kinds: `ignore` («+ас», owner only) and
  `game_mute` («эпиас», any admin) — kept separate so an admin cannot lift an owner's ignore. `throttling.py`: 0.3 s per message, 0.5 s per button.
- Callback data classes in `keyboards.py` use `Literal`/bounded `int` fields, so forged or stale buttons
  fail the filter and fall through to `misc.unknown_button` ("Кнопка устарела"). Buttons that belong to
  one player carry `owner` and are checked in the handler.
- Router order is set in `handlers/__init__.py` (admin first, `chat` late: its RP filter looks at the
  first word of every message). «мф» (`handlers/mass.py`) runs its loop inside the callback handler;
  a per-user `_running` flag, set before the first `await`, blocks a second parallel run. The root router is a singleton;
  `build_router()` resets its parent so tests can attach it to a fresh Dispatcher per test.
- Background jobs (`services/scheduler.py`): pathogen production tick every 15 s (reads only due timers
  via partial indexes `idx_labs_timer` / `idx_labs_idle`), daily premium at 00:00 and 12:00 in `TZ`
  (idempotent: the paid slot is stored in `settings` inside the payout transaction), daily DB backup
  to `data/backups` (last 7), and a `data/.heartbeat` touch used by the Docker healthcheck.
- Invariant: a lab whose `ready_pathogens >= pathogens` has `science_time = NULL`. Level changes go
  through `game/upgrade._write_level`, which enforces this and the skill bounds (science ≤ 60).
- Admin roles: owner (`ADMIN_ID`, comma-separated) = 3, senior = 2, admin = 1 (`handlers/admin/base.Staff`).
  Economy commands need senior; punishing staff of equal or higher rank is refused (`outranks`).
  Every admin action is written to `admin_log` in the same transaction as the change.
- Schema lives in `schema.py` as an ordered `MIGRATIONS` list tracked by `PRAGMA user_version`.
  Once a version has shipped, add a new migration instead of editing an old one.

## Tests

`tests/harness.py` runs real updates through the Dispatcher with a `FakeSession` that records Telegram
API calls; the `h` fixture (conftest) gives each test a fresh bot. Use it for end-to-end scenarios
(`tests/test_bot_flow.py`) and screen-exact checks (`tests/test_reference_texts.py`, compare `visible(text)`).
Service tests use an in-memory DB with a fixed `NOW` from `tests/conftest.py` and
`make_player(db, id, **lab_fields)`. Migration 2 seeds the Telegram service lab (777000), so random-target
tests hide it. The harness also fakes `getChatAdministrators` (`h.session.chat_admins[chat_id] = [users]`)
and feeds join/leave events (`h.member_update(user, joined=…, mine=…)`). For deterministic rolls, wrap
`infection.attempt` / `mass.attempt` with a fixed `rng` via monkeypatch (see `tests/test_original_systems.py`).

## Project workflow

The user wants these skills used in this project: `/sc:design` (and `/sc:brainstorm`) before new
mechanics, `/sc:implement` for features, `/sc:test` for formula/game-logic tests, `simplify` for
refactoring, `security-review` (SQL, admin commands, abuse, flood) and `code-review` before commits,
`/sc:troubleshoot` for errors, `understand-explain` for code analysis. Do not use design/UI skills
(frontend-design, impeccable, ui-ux-pro-max, shadcn, gsap). `security-review` needs a git remote/commits;
without them, review the code paths manually or run `code-review` with a path target.
