"""Системы оригинала, добавленные после полной сверки: «мф», кнопки под провалом, «мж топ»,
чат-менеджер (ID, правила, заметки, админы, прощания, РП, ник) и модерация (эпимут, эпиас, !чек, !стата)."""
from __future__ import annotations

import re

import pytest
from aiogram.types import Chat, User

from epidemic.game import infection, mass, upgrade
from epidemic.handlers import mass as mass_handler
from epidemic.keyboards import FailCb, MassCb
from epidemic.repo import admin as admin_repo
from epidemic.repo import labs, users, victims
from epidemic.utils.fmt import now_ts
from tests.harness import ALICE, BOB, GROUP, OWNER, Harness, joined, visible

CAROL = User(id=203, is_bot=False, first_name="Кэрол", username="carol_lab")


@pytest.fixture(autouse=True)
def fast_mass(monkeypatch):
    monkeypatch.setattr(mass_handler, "STEP_DELAY_SEC", 0)


def fixed_rng(monkeypatch, module, value: float) -> None:
    """Подменяет бросок кубика у сервиса заражения (0.0 — всегда успех, 0.99999 — промах при шансе < 100)."""
    real = module.attempt
    monkeypatch.setattr(module, "attempt", lambda *a, **k: real(*a, rng=lambda: value, **k))


async def register(h: Harness, *people: User) -> None:
    for user in people:
        await h.send(user, "привет")


async def make_fallen(h: Harness, owner: User, victim: User) -> None:
    """Жертва, чьё заражение истекло, — «слетевшая» цель для «мф»."""
    now = now_ts()
    async with h.db.tx() as t:
        await victims.upsert(
            t, owner.id, victim.id, expires_at=now - 10, infected_at=now - 100, cooldown_until=now - 50,
            earn=5, pathogen_name=None, ss_detect=False,
        )


def alerts(h: Harness, start: int) -> list[tuple[str, bool]]:
    return [(c.text, bool(c.show_alert)) for c in h.calls_named("AnswerCallbackQuery", start) if c.text]


# --- «мф» ---

async def test_mass_infection_page(h: Harness, monkeypatch):
    await register(h, ALICE, BOB)
    assert joined(await h.send(ALICE, "мф")) == "❌ У вас нет доступных слетевших целей!"
    await make_fallen(h, ALICE, BOB)

    assert visible(joined(await h.send(ALICE, "мф"))) == "☣️ Список слетевших целей (Страница 1/1):\n\n1. Боб"
    assert h.buttons() == ["1/1", "☣️ Заразить всех (Стр. 1)", "🔥 Заразить ВСЕХ из списка"]

    fixed_rng(monkeypatch, mass, 0.0)
    start = len(h.session.calls)
    out = [visible(t) for t in await h.click(ALICE, MassCb(action="start", page=1).pack())]
    assert alerts(h, start) == [("🚀 Запуск массовой атаки...", False)]
    assert out[0] == "☣️ Инициализация массового заражения...\n🎯 Всего целей: 1"
    assert "☣️ Массовое заражение в процессе (1/1)...\n\n🎯 Цель: Боб\n🎲 Шанс пробития: 100.0%\n🧪 Оставшиеся патогены: 3" in out[2]
    assert "📊 Прогресс: [▓▓▓▓▓▓▓▓▓▓] 100%\n🟢 Успешно: 1 | 🔴 Промахи: 0" in out[2]
    assert re.fullmatch(
        r"☣️ Итоги массового заражения \(Стр\. 1\):\n\n🎯 Обработано целей: 1 / 1\n🟢 Пробито целей: 1\n"
        r"🔴 Не пробито: 0\n🧪 Потрачено патогенов: 1\n\n📈 Получено опыта:\n🧬 \+\d+ XP\n\n"
        r"🟢 Пробитые цели:\n  ✅ Боб — \+\d+ XP",
        out[-1],
    )
    # пробитая цель снова в «мж», из «мф» она ушла
    assert joined(await h.send(ALICE, "мф")) == "❌ У вас нет доступных слетевших целей!"


async def test_mass_infection_all_is_limited_by_pathogens(h: Harness, monkeypatch):
    await register(h, ALICE, BOB, CAROL)
    await make_fallen(h, ALICE, BOB)
    await make_fallen(h, ALICE, CAROL)
    await labs.set_fields(h.db, ALICE.id, ready_pathogens=1)
    lab = await labs.get(h.db, ALICE.id)
    await upgrade.set_level(h.db, BOB.id, "immunity", lab["infect"] + 3)  # шанс «мф» — 25 %
    fixed_rng(monkeypatch, mass, 0.99999)

    start = len(h.session.calls)
    out = [visible(t) for t in await h.click(ALICE, MassCb(action="all").pack())]
    assert alerts(h, start) == [("🚀 Запуск массовой атаки на 2 целей...", False)]
    assert out[0] == "☣️ Инициализация массового заражения...\n🎯 Всего целей: 2"
    assert "☣️ Массовое заражение (1/1)...\n\n🎯 Цель: Боб\n🎲 Шанс: 25.0%\n🧪 Патогены: 0\nРезультат: 🔴 ПРОМАХ!" in out[2]
    assert out[-1] == (
        "☣️ Итоги массового заражения (ВСЕ 1):\n\n🎯 Обработано: 1 / 1\n🟢 Пробито: 0\n🔴 Не пробито: 1\n"
        "🧪 Потрачено патогенов: 1\n\n📈 Получено опыта:\n🧬 +0 XP\n\n🔴 Не пробитые:\n  ❌ Боб"
    )


async def test_mass_infection_buttons(h: Harness):
    await register(h, ALICE, BOB)
    start = len(h.session.calls)
    await h.click(ALICE, MassCb(action="start", page=1).pack())
    await h.click(ALICE, MassCb(action="cancel").pack())
    assert alerts(h, start) == [("❌ На этой странице нет доступных целей!", True), ("❌ Остановка заражения...", True)]


# --- Кнопки под провалом и «мж топ» ---

async def test_failed_infection_offers_retry_and_upgrade(h: Harness, monkeypatch):
    await register(h, ALICE, BOB)
    lab = await labs.get(h.db, ALICE.id)
    await upgrade.set_level(h.db, BOB.id, "immunity", lab["infect"] + 3)
    fixed_rng(monkeypatch, infection, 0.99999)

    assert "оказался стойким к вашему патогену" in joined(await h.send(ALICE, "заразить @bob_lab"))
    assert h.buttons() == ["🔁 1 пат", "🔁 5 патов", "🔁 9 патов", "🎯 +1 ЗЗ", "🎯 +3 ЗЗ", "🎯 +10 ЗЗ"]

    start = len(h.session.calls)
    assert await h.click(BOB, FailCb(action="repeat", target=BOB.id, owner=ALICE.id, n=1).pack()) == []
    assert alerts(h, start) == [("❌ Это не твоя кнопка!", True)]

    start = len(h.session.calls)
    out = await h.click(ALICE, FailCb(action="up", target=BOB.id, owner=ALICE.id, n=3).pack())
    assert alerts(h, start) == [("🎯 Прокачка +3 ЗЗ", False)]
    assert visible(joined(out)).startswith("✅ Усиление заразности патогена на 3 ур")  # превью прокачки
    assert h.buttons() == ["Подтвердить улучшение"]

    start = len(h.session.calls)
    out = await h.click(ALICE, FailCb(action="repeat", target=BOB.id, owner=ALICE.id, n=1).pack())
    assert alerts(h, start)[0] == (f"🔁 Повтор: 1 пат. → цель {BOB.id}", False)
    assert out


async def test_top_victims_by_income(h: Harness, monkeypatch):
    await register(h, ALICE, BOB)
    assert joined(await h.send(ALICE, "мж топ")) == "📭 У вас нет жертв, которые приносят доход!"
    fixed_rng(monkeypatch, infection, 0.0)
    await h.send(ALICE, "заразить @bob_lab")
    text = visible(joined(await h.send(ALICE, "мж топ")))
    assert re.fullmatch(r"📊 ТОП ЖЕРТВ ПО ДОХОДУ\n\n🥇 Боб — [\d,]+ био/тик ⏳ \d+д", text)


# --- Чат-менеджер ---

async def test_ids(h: Harness):
    await register(h, BOB)
    assert visible(joined(await h.send(ALICE, "!ид"))) == "🌀 Генетический код @201 игрока «Алиса»"
    out = joined(await h.send(ALICE, "!ид @bob_lab"))
    assert visible(out) == "🌀 Генетический код @202 игрока «Боб»" and 'href="https://t.me/bob_lab"' in out
    assert joined(await h.send(ALICE, "!ид @nobody_here")) == "📝 Пользователь не найден"
    assert visible(joined(await h.send(ALICE, "!чат ид"))) == "🆔 беседы «Био-чат» равен @-1001"


async def test_rules_are_for_chat_admins(h: Harness):
    assert visible(joined(await h.send(BOB, "+правила\nНе флудить"))) == "📝 Вы не являетесь администратором чата «Био-чат»"
    h.session.chat_admins[GROUP.id] = [ALICE]
    assert visible(joined(await h.send(ALICE, "+правила\nabc"))) == (
        "📝 Данный обьем правил не соответсвует обьему. Он должен содержать от 5 символов"
    )
    assert visible(joined(await h.send(ALICE, "+правила\nНе флудить в чате"))) == (
        "✅ Правила для чата «Био-чат» были успешно обновлены"
    )
    assert visible(joined(await h.send(BOB, "правила"))) == "📝 Правила для чата «Био-чат»\n\nНе флудить в чате"
    assert visible(joined(await h.send(ALICE, "-правила"))) == "✅ Правила для чата «Био-чат» были успешно удалены"
    assert visible(joined(await h.send(BOB, "правила"))) == "📝 Правила для чата «Био-чат» не найдены"


async def test_notes(h: Harness):
    empty = visible(joined(await h.send(ALICE, "заметки")))
    assert empty.startswith("«Ой, здесь пока пусто... желаете добавить заметку?»")
    assert joined(await h.send(ALICE, "+заметка Ссылки\nhttps://example.com")) == "📌 Заметка с названием «Ссылки» добавлена"
    assert joined(await h.send(ALICE, "+заметка ссылки\nещё")) == "📌 Заметка с таким названием уже сущевствует."
    assert joined(await h.send(ALICE, "+заметка Пусто")) == "📝 Заметка не содержит текст"
    assert visible(joined(await h.send(BOB, "заметки"))) == (
        "🔍 Заметки беседы:\n1. Ссылки\n\n📌 Чтобы открыть заметку, используйте команду:\n«Заметка (номер или название)»"
    )
    card = visible(joined(await h.send(BOB, "заметка 1")))
    assert re.fullmatch(r"📌 Заметка: «Ссылки»\n\nhttps://example\.com\n\n🕒 \d{4}\.\d{2}\.\d{2}", card)
    assert joined(await h.send(BOB, "-заметка ссылки")) == "📌 Заметка с названием «Ссылки» удалена"
    assert joined(await h.send(BOB, "заметка Ссылки")) == "📌 такой заметки нет"
    private = Chat(id=ALICE.id, type="private", first_name="Алиса")
    assert await h.send(ALICE, "заметки", chat=private) == []


async def test_chat_admins_greetings_and_leave(h: Harness):
    h.session.chat_admins[GROUP.id] = [ALICE, OWNER]
    assert visible(joined(await h.send(BOB, "кто админ"))) == "🥋 Список администраторов этого чата\n1. Алиса\n2. Владелец"
    assert visible(joined(await h.send(BOB, "-прощания"))) == "📝 Вы не являетесь администратором чата «Био-чат»"

    assert await h.member_update(CAROL, joined=True) == []  # приветствие в оригинале пустое
    assert await labs.get(h.db, CAROL.id) is not None      # но лаборатория у новичка уже есть
    left = await h.member_update(BOB, joined=False)
    assert visible(joined(left)) == "До скорого, путник Боб Надеюсь, звёзды вновь сведут нас!"
    assert 'href="https://t.me/bob_lab"' in joined(left)

    assert visible(joined(await h.send(ALICE, "-прощания"))) == "✅ Прощания участников чата «Био-чат» выключены"
    assert await h.member_update(CAROL, joined=False) == []
    assert visible(joined(await h.send(ALICE, "+прощания"))) == "✅ Прощания участников чата «Био-чат» включены"
    assert visible(joined(await h.send(ALICE, "-приветствия"))) == (
        "✅ Приветсвия вступления новых участников чата «Био-чат» выключены"
    )


async def test_bot_added_to_group(h: Harness):
    me = User(id=h.bot.id, is_bot=True, first_name="Epidemic", username="test_bot")
    out = await h.member_update(me, joined=True, mine=True)
    assert visible(joined(out)) == (
        "Рада присутствовать в вашем прекрасном чате, надеюсь он засияет новыми красками "
        "с приключенским ботом Био-чат 💚"
    )


async def test_rp_commands(h: Harness):
    await register(h, BOB)
    assert await h.send(ALICE, "обнять") == []  # без цели РП молчит
    hug = visible(joined(await h.send(ALICE, "обнять", reply_to=h.message(BOB, "hi"))))
    assert hug.startswith("⌈") and "Алиса" in hug and hug.endswith("Боб")
    kiss = visible(joined(await h.send(ALICE, "поцеловать @bob_lab на удачу")))
    assert kiss.endswith("Боб\n\n💬 Прошептав: ⌜на удачу⌟")
    five = visible(joined(await h.send(ALICE, "дать пять @bob_lab")))
    assert "Алиса" in five and five.endswith("Боб")


async def test_nickname(h: Harness):
    out = visible(joined(await h.send(ALICE, "мой ник Доктор Хаус")))
    assert out == "📝 Ваш чат никнейм был изменен, теперь вы Доктор Хаус."
    assert (await users.get(h.db, ALICE.id))["nickname"] == "Доктор Хаус"


async def test_help_is_start_menu(h: Harness):
    for command in ("помощь", "/help", ".помощь"):
        assert "💚 Не идентифицируемый объект замечен!" in joined(await h.send(ALICE, command))


# --- Модерация оригинала ---

async def test_name_mute(h: Harness):
    await register(h, OWNER, BOB)
    async with h.db.tx() as t:
        await labs.set_name(t, BOB.id, "lab", "Био", "био")
        await labs.set_name(t, BOB.id, "pathogen", "Чума", "чума")

    assert await h.send(ALICE, "эпимут 3 @bob_lab спам") == []  # не админ — тишина
    out = await h.send(OWNER, "эпимут 3 @bob_lab спам названиями")
    assert visible(out[0]) == "Игроку Боб выдан мут на изменение игровых имен на 3 дней\nПричина: спам названиями"
    assert h.sent_to(BOB.id)[-1] == (
        "Вам выдан мут на изменение игровых наименований на 3 дней\n\n"
        "<b>Причина:</b><i> спам названиями</i>\n<b>Кем выдан:</b> Telegram"
    )
    lab = await labs.get(h.db, BOB.id)
    assert lab["lab_name"] is None and lab["pathogen_name"] is None
    assert joined(await h.send(BOB, "+имя патогена Чума")).startswith("📕 У вас мут на изменения игровых наименований")

    listing = visible(joined(await h.send(OWNER, "!эпимут")))
    assert re.fullmatch(
        r"Список игроков с биомутом\n1\. «Боб» \| до \d\d\.\d\d\.\d{4} \d\d:\d\d \| выдан Владелец \| спам названиями",
        listing,
    )
    check = visible(joined(await h.send(OWNER, "!чек @bob_lab")))
    assert check.startswith("Биомут\nКем выдан: Владелец\nПричина: спам названиями")

    assert visible((await h.send(OWNER, "-эпимут @bob_lab"))[0]) == "Игроку Боб был снят мут на наименования"
    assert h.sent_to(BOB.id)[-1] == "Вам был снят мут на наименования"
    assert joined(await h.send(OWNER, "!чек @bob_lab")) == "У игрока нету ограничений"


async def test_game_mute(h: Harness):
    await register(h, OWNER, BOB)
    out = await h.send(OWNER, "эпиас 2 @bob_lab флуд")
    assert visible(out[0]) == "Игроку Боб выдан игровой мут на 2 дней\nПричина: флуд"
    assert h.sent_to(BOB.id)[-1].startswith(
        "Вам выдан игровой мут на <b>2</b> дней(игровые команды не будут на вас реагировать)"
    )
    assert await h.send(BOB, "лаб") == []
    assert "«Боб»" in visible(joined(await h.send(OWNER, "!эпиас")))
    assert visible(joined(await h.send(OWNER, "!чек @bob_lab"))).startswith("Эпиас\nКем выдан: Владелец\nПричина: флуд")
    assert visible((await h.send(OWNER, "-эпиас @bob_lab"))[0]) == "Игроку Боб был снят игровой мут"
    assert await h.send(BOB, "лаб") != []


async def test_admin_cannot_mute_owner(h: Harness):
    await register(h, OWNER, ALICE)
    await admin_repo.set_role(h.db, ALICE.id, "admin", OWNER.id, now_ts())
    assert "Нельзя применять" in joined(await h.send(ALICE, "эпиас 5 @owner_user просто так"))


async def test_bot_stats_and_search(h: Harness):
    await register(h, OWNER, BOB)
    await h.send(OWNER, "привет", chat=Chat(id=OWNER.id, type="private", first_name="Владелец"))
    async with h.db.tx() as t:
        await labs.set_name(t, BOB.id, "pathogen", "Чума", "чума")
    total = await labs.total_exp(h.db)
    assert visible(joined(await h.send(OWNER, "!стата"))) == (
        f"📊 Статистика бота\nЛичек с ботом: 1\nПубличных чатов: 1\nОпыт игры: {total:,}"
    )
    assert joined(await h.send(OWNER, "/game_exp")) == f"{total:,}"
    assert visible(joined(await h.send(OWNER, "/search_pathogen ЧУМ"))) == (
        '📝 Список людей содержащие в имени патогена "ЧУМ":\n1. Боб: Чума'
    )
    assert joined(await h.send(OWNER, "/search_pathogen оспа")) == "❌ Ни у кого нет такого патогена"


async def test_admin_game_unmute_keeps_owner_ignore(h: Harness):
    """«-эпиас» от обычного админа снимает только игровой мут — полный игнор владельца («+ас») остаётся."""
    await register(h, OWNER, ALICE, BOB)
    await admin_repo.set_role(h.db, ALICE.id, "admin", OWNER.id, now_ts())
    await h.send(OWNER, "+ас @bob_lab")
    await h.send(ALICE, "эпиас 1 @bob_lab флуд")
    await h.send(ALICE, "-эпиас @bob_lab")
    assert await h.send(BOB, "лаб") == []
    history = visible(joined(await h.send(OWNER, "/sanctions @bob_lab")))
    assert "🔇 эпиас (игровой мут) (снято): флуд" in history and "🔇 игнор" in history


async def test_mass_infection_rejects_parallel_start(h: Harness):
    await register(h, ALICE, BOB)
    await make_fallen(h, ALICE, BOB)
    mass_handler._running[ALICE.id] = True  # МФ уже идёт
    try:
        assert await h.click(ALICE, MassCb(action="start", page=1).pack()) == []
    finally:
        mass_handler._running.pop(ALICE.id, None)
