---
name: epidemic-bot
description: >
  Project guide for the «Эпидемик» Telegram bio-wars game bot in this repo (aiogram 3 + SQLite + Docker
  Compose). Use it whenever you add or change anything in this bot — a new game mechanic or command,
  balance numbers or formulas (chance, upgrade cost, reward, fever, premium), bot message texts, inline
  buttons, admin-panel commands, group-chat behaviour, corporations, the tutorial, the DB schema, or the
  Docker deployment — even if the request is phrased casually ("добавь команду…", "поменяй баланс",
  "почему бот молчит в группе", "сделай как в эпидемике"). It explains where each kind of change lives,
  the balance rules taken from the original «Эпидемик 2.0», the message style players expect, and the
  group-chat rules that are easy to break.
---

# Эпидемик: как вносить изменения

The bot is a clone of the core of «Эпидемик 2.0». Players judge it against the original, so numbers,
wording and command names should feel identical unless the user explicitly asks for something new.
`CLAUDE.md` has the commands and the architecture map; this skill is the "how to change it safely" part.

## 1. Adding or changing a mechanic — go through the layers

Work bottom-up. Each layer has one job, and skipping one is what produced most of the bugs found in review
(rules duplicated between a text command and its button, checks outside the write transaction, texts
drifting from the numbers).

1. **Numbers** → `epidemic/game/constants.py`. Anything the owner may want to tune live goes into
   `game/settings.py::SPECS` instead (it becomes a `/set_game_setting` key and shows in `/admin`).
2. **Pure math** → `epidemic/game/formulas.py`, with unit tests in `tests/test_formulas.py`.
   Keep it free of DB and Telegram so it stays trivially testable.
3. **Schema** → append a new SQL string to `MIGRATIONS` in `epidemic/schema.py`. Never edit a migration
   that has shipped: `PRAGMA user_version` would skip it on the client's live database.
   Add indexes for anything the 15-second production tick or per-message paths will query.
4. **SQL** → `epidemic/repo/*.py`. Parameters always go through `?`/`:name`. If a column name must be
   interpolated, take it from a whitelist (`labs.EDITABLE`, `labs.NAME_COLUMNS`, `C.SKILLS`).
5. **Rules** → a service in `epidemic/game/` that does every check *and* every write inside one
   `async with db.tx() as t:` and returns a small dataclass with a `status` string constant
   (see `game/corps.py`, `game/infection.py`). Put permission checks, limits and "is the lab active"
   here, not in handlers — then the text command and the inline button cannot disagree.
6. **Text** → static strings in `epidemic/texts.py`, row rendering in `epidemic/views/*.py`
   (style in §3). Also update `texts.help_text` and the tutorial if players need to learn the command.
7. **Handler** → `epidemic/handlers/*.py`: parse, call the service, map `status → text` with a dict.
   Filters must be async (`cmd(pattern)` or a `Filter` subclass). See §4 for why.
8. **Buttons** → a `CallbackData` class in `epidemic/keyboards.py` with `Literal` / bounded-`int` fields.
   If only one player may press it, add an `owner: int` field and check it in the handler.
9. **Tests** → service tests with the in-memory DB (`make_player(db, id, **fields)`, fixed `NOW`) and an
   end-to-end scenario in `tests/test_bot_flow.py` through the real Dispatcher and `FakeSession`.
10. **Docs** → `docs/ARCHITECTURE.md` §4 for formulas, `README.md` for new commands or `.env` keys.

Run `pytest` and `python -m pyflakes epidemic tools tests` before calling the change done.

## 2. Balance

The core numbers come from the original bot and are covered by tests that compare them to the original
formula. Changing them changes the game players already know, so change them only on explicit request.
For temporary tuning ("double XP weekend"), use the owner's multipliers in `settings.SPECS`.

Quick reference (full tables and worked examples: `references/balance.md`):

| Mechanic | Rule |
|---|---|
| New lab | 15 000 🧬, 1 000 ☣️, 4/4 pathogens, all skills 1 |
| Upgrade price | Σ (lvl+1)^k; k: pathogens 2.0, science 2.5, infect 2.55, immunity 2.5, lethality 1.95, security 2.1 |
| Limits | science ≤ 60, ≤ 50 levels per command, downgrade refunds 50 % (at most the base price) |
| Production | 1 pathogen per (61 − science) min |
| Chance | infect ≥ immunity → 100 %, else `CHANCE_TABLE[gap]`; ×(1 + 0.2722·(N−1)) for N pathogens; +base/4 per retry within 60 s |
| Reward | 10 % of victim XP, ÷ (1 + gap/100) if immunity is higher; the victim loses the same base amount |
| Fever | attacker lethality // 3 min (≥ 1), stacks up to 60 min, blocks attacking |
| Infection | lasts attacker-lethality days; cooldown per pair 120 min; max gap 221 |
| Premium | 00:00 and 12:00 (TZ): Σ earn of active victims |
| Vaccine | immunity × 15 🧬 |

When a formula changes, keep three things in sync: `formulas.py`, the tests, and any text that shows
the number (texts build numbers from constants such as `C.INFECT_MAX_PATHOGENS` and `PAYOUT_TIMES`).

## 3. Message style

Players recognise the original by its look, and the client requires it **1:1**. Existing texts are copied
verbatim from the original bot — keep its typos and punctuation («Ты все таки», «Улучшение на 3 уровней»,
«Не удалось найти жертву, для заражения»). The tutorial is `epidemic/data/story.yml` (the original YAML;
folded `>` blocks decide the line breaks). When you add a *new* message, match the style below; when you
touch an *existing* one, compare with `docs/REFERENCE_SPEC.md` and keep `tests/test_reference_texts.py` green.

- **Announcements** start with the header `texts.header(config, "оповещение" | "обучение")` →
  `🦠 <code>𝐄𝐩𝐢𝐝𝐞𝐦𝐢𝐜 𝐍𝐨𝐭𝐢𝐟𝐲</code> | <b>#тег</b>`, use `texts.SEP` (`❇️—❎—✳️—💚—✳️—❎—❇️`) around the
  body, and put explanations in `<blockquote>`.
- **Stat cards** (dossier, corporation) use `<b>——[ Заголовок ]——</b>` section lines and a
  `<blockquote>` per block.
- **One emoji per concept, always the same:** 🧪 pathogens, 🧑‍🎤 science, 💉 infect, 🪬 immunity,
  💊 lethality, 🕵️‍♂️ security, ☣️ bio-XP, 🧬 bio-resources, 🤒 infected, 😷 illnesses, ☠️ fever,
  ⏱ time, 🌸 tops, 🔆 corporation. Refusals start with 📝, success with ✅, removal with ❎,
  bans with 🚫, admin panels with 🔐.
- **Formatting helpers** (`epidemic/utils/fmt.py`), chosen per the original:
  - numbers: `comma()` (`6,991,031`) in all game messages; `num()` (`15 000`) only in «лаб» and «мл»;
  - time: `ref_hms()` («1 часов 5 минут 3 секунд») for fever and the pathogen timer, `ref_hm()` for
    cooldowns — the original's grammar; `duration()` (correct plurals) only in admin/own texts;
  - names: `mention()` (tg://openmessage, escapes HTML), `user_link()` (tg://user) where the original used it;
  - `cmd_link()` for tappable commands.
  Never put a user-supplied string into a message without `escape()` or `mention()`.
- **Length:** Telegram rejects text over 4096 characters and photo captions over 1024. Build lists with
  `join_limited(lines)` (it never cuts inside an HTML tag) and cap list queries (`C.LIST_LIMIT`).
- **Tone:** playful sci-fi, second person, short. «Иммунитет объекта оказался стойким к вашему патогену.»
  rather than «Заражение не удалось, повторите попытку.»

## 4. Group-chat rules

The bot lives in busy groups, so behaviour that is harmless in a private chat becomes spam or load there.

- **Everyone gets a lab automatically** via `middlewares/registration.py`, including reply targets and
  text-mentions. Never require `/start` before a player can be infected; `/start` is only the tutorial.
- **Privacy mode must be off** (or the bot must be admin), otherwise Telegram does not deliver
  «лаб»/«заразить» at all. If a user reports "бот молчит в группе", check this first.
- **Commands are full-match regexes with an optional `[!./]` prefix** and must stay silent on ordinary
  chat text. A pattern that matches common words («бот», «ч») is a spam risk. Keep such commands
  exact and silent when their argument doesn't resolve.
- **Filters run for every message:** use async filters (`cmd()`, `Filter` subclasses). aiogram sends
  `F.text.regexp(...)` and other sync callables to a thread, which costs about 10× CPU per message.
- **Throttling** is 0.3 s per command and 0.5 s per button (`middlewares/throttling.py`). Maintenance
  and ignore checks run only on matched commands, so the bot never answers plain chatter.
- **Notifications to victims** go to `labs.notify_chat_id` (the player's private chat by default,
  changed with `+вирусы`/`-вирусы`). Send them only if that chat differs from the current one, and only
  through `safe_send` — the player may never have opened the bot.
- **Targets:** resolve with `utils/targets.py` (reply → text_mention → @username / t.me / tg:// / ID).
  In forum topics every message "replies" to the topic root; `reply_user()` already ignores that.
  Bots can never be infected.
- **Buttons in groups** can be pressed by anyone: bind them to `owner` and answer others with
  `texts.not_your_button()` (the infect-fail buttons use the original's «❌ Это не твоя кнопка!»).
  «мф» buttons carry no owner on purpose: as in the original, each presser works on their own list.
- **Two kinds of "admin":** chat admins (rules, greetings — checked live with `getChatAdministrators`
  in `handlers/chat.py`; anonymous admins pass via `sender_chat`) and game staff (`Staff` filter in
  `handlers/admin/`). Never gate game moderation on chat-admin status or the reverse.
- **RP commands** are matched by `RpFilter` on the first word (or two, «дать пять») of every message, so
  new RP verbs must not collide with game commands. Templates live in `data/chat.yml`.

## 5. Things that break silently

- Calling `db.execute()` or `db.tx()` inside an open transaction raises (it would deadlock on the lock).
  Pass the `Tx` object down instead.
- Holding a transaction across `await bot.send_message(...)` blocks every other write in the bot.
  Return data from the transaction, send messages afterwards.
- A lab with `ready_pathogens >= pathogens` must have `science_time = NULL`. Change levels through
  `game/upgrade._write_level` / `set_level`, which keep this invariant and the skill bounds.
- Admin actions must write the change, the sanction and `admin_log` in one transaction, and check
  `outranks()` before punishing another staff member. Change the ignore list only through `IgnoreList`
  (`ignore`/`unignore` with the right `kind`), which refreshes its in-memory cache from the same transaction.
- The daily premium is idempotent only because the paid slot is stored inside the payout transaction.
  Keep that in the same `db.tx()` when touching `economy.pay_premium`.
