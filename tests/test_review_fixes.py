"""Регрессии по итогам полной проверки кода: ввод игроков, права админов, журнал, «мф», перенос старой базы."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from aiogram.types import Chat, Message, MessageEntity, User

from epidemic.handlers import mass as mass_handler
from epidemic.keyboards import MassCb
from epidemic.repo import admin as admin_repo
from epidemic.repo import labs, victims
from epidemic.schema import apply_migrations_sync
from epidemic.utils.fmt import now_ts
from epidemic.utils.names import name_key
from epidemic.utils.parse import parse_infect, parse_target_token
from epidemic.utils.targets import with_mention_as_link
from tests.harness import ALICE, BOB, GROUP, OWNER, Harness, joined, visible
from tests.test_migration import build_old_db, fmt
from tools.migrate_from_biowars import Migrator, main, ts


async def register(h: Harness, *people) -> None:
    for user in people:
        await h.send(user, "привет")


# --- Необычные цифры в командах не роняют обработку ---

def test_superscript_digits_are_not_numbers():
    assert parse_target_token("¹²³") is None
    parse_infect("заразить ²")  # раньше: ValueError внутри фильтра на каждое такое сообщение


async def test_superscript_digits_in_chat_are_ignored(h: Harness):
    await register(h, OWNER)
    for text in ("лаб ¹²³", "чек ¹²³", "заразить ²", "заметка ²"):
        await h.send(ALICE, text)  # не падает
    await h.send(OWNER, "/admin_history ²")  # не падает: неразборчивое число — обычный лимит


# --- Опечатка в цели не бьёт по автору сообщения, на которое ответили ---

async def test_typo_target_does_not_fall_back_to_reply(h: Harness):
    await register(h, BOB)
    reply = h.message(BOB, "привет")
    assert await h.send(ALICE, "чек @ab", reply_to=reply) == []
    assert "Жертва" in joined(await h.send(ALICE, "чек", reply_to=reply))


# --- Наказание от старшего не снять и не сократить младшему ---

async def test_admin_cannot_undo_owner_sanctions(h: Harness):
    await register(h, OWNER, ALICE, BOB)
    await admin_repo.set_role(h.db, ALICE.id, "admin", OWNER.id, now_ts())

    await h.send(OWNER, f"/disable_lab {BOB.id} читы")
    assert "выше вас" in joined(await h.send(ALICE, f"/enable_lab {BOB.id}"))
    assert "выше вас" in joined(await h.send(ALICE, f"/disable_lab {BOB.id} 1d помягче"))
    lab = await labs.get(h.db, BOB.id)
    assert lab["disabled"] and lab["disabled_until"] is None  # бессрочное отключение владельца на месте

    await h.send(OWNER, "эпиас 365 @bob_lab флуд")
    assert "выше вас" in joined(await h.send(ALICE, "эпиас 1 @bob_lab помягче"))
    assert "выше вас" in joined(await h.send(ALICE, "-эпиас @bob_lab"))
    await h.send(OWNER, "эпимут 30 @bob_lab названия")
    assert "выше вас" in joined(await h.send(ALICE, "-эпимут @bob_lab"))

    assert "включена" in joined(await h.send(OWNER, f"/enable_lab {BOB.id}"))  # владельцу можно


# --- Действие админа и запись в журнал — одна транзакция ---

async def test_admin_actions_are_logged(h: Harness):
    await register(h, OWNER, ALICE, BOB)
    await h.send(OWNER, "+админ @alice_lab")
    await h.send(OWNER, f"/set_skill {BOB.id} заразность 5")
    await h.send(OWNER, f"/force_rename {BOB.id} lab Новая база")
    await h.send(OWNER, "/set_game_setting xp_multiplier_pct 120")
    await h.send(OWNER, "тех+")
    await h.send(OWNER, "тех-")
    await h.send(OWNER, "-админ @alice_lab")
    actions = [r["action"] for r in await h.db.fetchall("SELECT action FROM admin_log ORDER BY id")]
    assert actions == [
        "appoint_admin", "set_skill", "force_rename", "set_game_setting", "maintenance", "maintenance", "remove_admin",
    ]


# --- «мф»: в отчёте только цели, по которым была попытка ---

async def test_mass_report_counts_only_attempted(h: Harness, monkeypatch):
    monkeypatch.setattr(mass_handler, "STEP_DELAY_SEC", 0)
    await register(h, ALICE, BOB)
    now = now_ts()
    async with h.db.tx() as t:
        await victims.upsert(t, ALICE.id, BOB.id, expires_at=now - 10, infected_at=now - 100,
                             cooldown_until=now - 50, earn=5, pathogen_name=None, ss_detect=False)
    await labs.set_fields(h.db, ALICE.id, ready_pathogens=0)
    out = [visible(t) for t in await h.click(ALICE, MassCb(action="start", page=1).pack())]
    assert any("закончились патогены" in t for t in out)
    assert "Обработано целей: 0 / 1" in out[-1]


# --- Перенос старой базы ---

def test_old_dates_are_parsed_in_any_common_form():
    assert ts("2025-05-01 12:00:00") == ts("2025-05-01T12:00:00") == ts("2025-05-01 12:00:00.123456")
    assert ts("1700000000") == 1700000000
    assert ts("") is None and ts(None) is None and ts("не дата") is None


def test_unreadable_deadline_is_expired_not_forever(tmp_path):
    new = sqlite3.connect(tmp_path / "new.sqlite3")
    apply_migrations_sync(new)
    m = Migrator(sqlite3.connect(":memory:"), new)
    assert m._deadline("") is None  # пусто — бессрочно, как в старой базе
    assert m._deadline("мусор") == m.now and m.stats["unparsed_deadlines"] == 1
    m._claim("corp", name_key("Корпорация 7"), 5)  # другая корпорация уже называется «Корпорация 7»
    assert m._fallback_corp_name(7) == ("Корпорация 7-2", name_key("Корпорация 7-2"))


def test_leader_who_was_member_elsewhere_leads_own_corp(tmp_path):
    old, new = tmp_path / "old.sqlite3", tmp_path / "new.sqlite3"
    build_old_db(old)
    conn = sqlite3.connect(old)
    # Иван (2) — соучредитель «Альфы» и одновременно лидер «Гаммы»
    conn.execute("INSERT INTO corporations VALUES (3, 'Гамма', 'ggg333', 2, 1, ?)", (fmt(datetime.now()),))
    conn.commit()
    conn.close()
    assert main([str(old), str(new)]) == 0
    conn = sqlite3.connect(new)
    assert conn.execute("SELECT corp_id, role FROM corp_members WHERE user_id = 2").fetchone() == (3, "leader")
    conn.close()


async def test_private_chat_is_registered_for_stats(h: Harness):
    await h.send(OWNER, "привет", chat=Chat(id=OWNER.id, type="private", first_name="Владелец"))
    row = await h.db.fetchone("SELECT is_private FROM chats WHERE chat_id = ?", (OWNER.id,))
    assert row["is_private"] == 1


# --- Запуск при плохой сети ---

async def test_startup_waits_for_telegram(monkeypatch):
    """getMe при старте повторяется, пока сеть до Telegram не появится; неверный токен не повторяется."""
    from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
    from aiogram.methods import GetMe
    from aiogram.types import User

    import epidemic.__main__ as entry

    async def no_sleep(_):
        return None

    monkeypatch.setattr(entry.asyncio, "sleep", no_sleep)
    me = User(id=1, is_bot=True, first_name="Epidemic", username="test_bot")
    answers = [TelegramNetworkError(GetMe(), "timeout"), TelegramNetworkError(GetMe(), "timeout"), me]

    class FlakyBot:
        async def get_me(self):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

    assert await entry.wait_for_telegram(FlakyBot()) is me

    class WrongTokenBot:
        async def get_me(self):
            raise TelegramUnauthorizedError(GetMe(), "Unauthorized")

    with pytest.raises(TelegramUnauthorizedError):
        await entry.wait_for_telegram(WrongTokenBot())


# --- Вторая проверка перед коммитом ---

async def test_timed_ignore_reports_longer_one_in_effect(h: Harness):
    await register(h, OWNER, BOB)
    await h.send(OWNER, "+ас @bob_lab навсегда")
    assert "уже действует бессрочно" in joined(await h.send(OWNER, "+ас @bob_lab 1d ещё раз"))


async def test_mass_stops_with_right_reason_when_lab_disabled(h: Harness, monkeypatch):
    monkeypatch.setattr(mass_handler, "STEP_DELAY_SEC", 0)
    await register(h, ALICE, BOB)
    now = now_ts()
    async with h.db.tx() as t:
        await victims.upsert(t, ALICE.id, BOB.id, expires_at=now - 10, infected_at=now - 100,
                             cooldown_until=now - 50, earn=5, pathogen_name=None, ss_detect=False)
    await labs.set_fields(h.db, ALICE.id, disabled=1, disabled_reason="тест")
    out = [visible(t) for t in await h.click(ALICE, MassCb(action="start", page=1).pack())]
    assert "❌ Массовое заражение остановлено!" in out
    assert not any("закончились патогены" in t for t in out)


def test_text_mentions_are_replaced_in_place():
    def msg(text, *mentions):
        entities = [MessageEntity(type="text_mention", offset=o, length=n, user=User(id=uid, is_bot=False, first_name="x"))
                    for o, n, uid in mentions]
        return Message(message_id=1, date=datetime.now(), chat=GROUP, text=text, entities=entities)

    # имя «5» совпадает с числом патогенов — заменяется именно упоминание, а не первое «5»
    assert with_mention_as_link(msg("заразить 5 5", (11, 1, 777))) == "заразить 5 tg://user?id=777"
    # два упоминания и эмодзи впереди (в UTF-16 он занимает 2 позиции)
    assert with_mention_as_link(msg("🔥 заразить Аня Боб", (12, 3, 1), (16, 3, 2))) == (
        "🔥 заразить tg://user?id=1 tg://user?id=2"
    )


async def test_settings_from_db_are_clamped(h: Harness):
    await h.db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upgrade_cost_multiplier_pct', '0')")
    await h.app.gs.load()
    assert h.app.gs.get("upgrade_cost_multiplier_pct") == 1  # не бесплатная прокачка


def test_forced_reimport_does_not_duplicate_sanctions(tmp_path):
    old, new = tmp_path / "old.sqlite3", tmp_path / "new.sqlite3"
    build_old_db(old)
    assert main([str(old), str(new)]) == 0
    assert main([str(old), str(new), "--force"]) == 0
    conn = sqlite3.connect(new)
    assert conn.execute("SELECT COUNT(*) FROM sanctions").fetchone()[0] == 1
    conn.close()
