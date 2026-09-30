"""Эталонные тесты: видимый текст каждого экрана со скриншотов клиента (папка REFTGBOT,
docs/REFERENCE_SPEC.md) — посимвольно. Если тест упал, бот перестал быть 1 в 1 с оригиналом."""
from __future__ import annotations

from aiogram.types import Chat, User

from epidemic.keyboards import TutorialCb, UpgradeCb
from epidemic.repo import labs
from tests.harness import ALICE, Harness, joined, visible

SEP = "❇️—❎—✳️—💚—✳️—❎—❇️"
HEADER = "🦠 𝐄𝐩𝐢𝐝𝐞𝐦𝐢𝐜 𝐍𝐨𝐭𝐢𝐟𝐲 |"
TIKTOK = User(id=301, is_bot=False, first_name="С ТИКТОКА ", last_name="Lening123124")  # два пробела, как на скрине
HUSE = User(id=302, is_bot=False, first_name="Huse")


def private(user: User) -> Chat:
    return Chat(id=user.id, type="private")


def seen(texts: list[str]) -> str:
    return visible(joined(texts))


# --- 212934 / 170832: /start ---

async def test_start_screen(h: Harness):
    out = seen(await h.send(TIKTOK, "/start", chat=private(TIKTOK)))
    assert out == (
        f"{HEADER} #оповещение\n\n"
        "Добро пожаловать в мир Эпидемика – место, где распространение заражений решает всё! 💚\n\n"
        f"{SEP}\n"
        "В твоём распоряжении будет находиться небольшая лаборатория, а цель – развиваться в этой гонке на "
        "выживание. Управляй лабораторией, развивай вирусы и проверь, сможешь ли ты покорить этот мир. "
        "Перед этим стоит пройти небольшое обучение по базовым механикам.\n"
        f"{SEP}\n\n"
        "Желаете начать экскурс?\n"
        "(Два выбора инлайн кнопки) ✅ ❌"
    )
    assert h.buttons() == ["💚 Начать путешествие", "❎ Отказываюсь", "➕ Добавить бота в чат"]


# --- 170841: «Мудрое решение» — новое сообщение, старое удаляется ---

async def test_wise_decision_screen(h: Harness):
    await h.send(TIKTOK, "/start", chat=private(TIKTOK))
    start = len(h.session.calls)
    out = seen(await h.click(TIKTOK, TutorialCb(step=1).pack(), private(TIKTOK)))
    assert out == (
        f"🦠 Мудрое решение! \n\n{SEP}\n\n"
        "Ты все таки решаешь обучиться, а значит, у тебя больше шансов на быстрое развитие. "
        "Тогда приступим к основам!\n\n"
        "Надеемся, что материал окажется полезным и понятным для вас 💚"
    )
    assert h.buttons() == ["Продолжить курс ❇️"]
    assert h.calls_named("DeleteMessage", start) and not h.calls_named("EditMessageText", start)


# --- 170846 / 170851 / 170858 / 170903 / 170906: шаги экскурса ---

async def test_tutorial_steps_match_screens(h: Harness):
    chat = private(TIKTOK)
    step = {n: seen(await h.click(TIKTOK, TutorialCb(step=n).pack(), chat)) for n in range(2, 7)}

    assert step[2].startswith(f"{HEADER} #обучение\n\nЗдесь вы можете ознакомиться с характеристиками своей "
                              "лаборатории. По ключевым словам ниже, сможете прокачать то что вам необходимо.")
    assert "— «Безопасности» – выявляет тех, кто пытается заразить твою лабораторию." in step[2]
    assert "— «Разработка» - квалификация учёных ускоряет создание новых патогенов." in step[2]
    assert step[2].endswith("Посмотреть возможные усиления умений, можно командой «+». Команда «++» подтвердит "
                            "действия прокачки.\nПример: ++летальность /  ++разработка и т.д.")

    assert ("Раз в сутки 12:00 по МСК начисляется сумма накопленного био-опыта. Летальность влияет на время "
            "нахождения заражённых в списке ежедневной премии.") in step[3]
    assert step[3].endswith("Список своих жертв можно получить с помощью команды «мои жертвы», также там можно "
                            "посмотреть ежедневную премию.")

    assert step[4] == (
        f"{HEADER} #обучение\n\n"
        "Попробуйте заразить кого-то и посмотреть, что с этого получится.\n\n"
        f"{SEP}\n\n"
        "Доступные команды — «заразить +» – для сильного заражения.\n"
        "— «заразить =» – для обычного заражения.\n"
        "— «заразить -» – для ослабленного заражения.\n\n"
        "Также, можете заразить по юзернейму или айди пользователя.\n"
        "Напишите «заразить @777000»\n\n"
        "🦠 Команда «биотоп» открывает список пользователей с наибольшим количеством био-опыта. "
        "С помощью него вы можете заражать потенциально прибыльных жертв. \n\n"
        f"{SEP}"
    )

    assert "— «.корп создать \"название\"» - ваша личная корпорация." in step[5]
    assert "— «- или +корп досье» - скрыть/открыть список участников корпорации." in step[5]
    assert step[5].endswith("У каждой корпорации свои взгляды на развитие и продвижение по топу, от вас зависит "
                            "где вы будете состоять и на какую роль претендовать.")

    assert step[6].startswith(f"{HEADER} #обучение\n\nЮзербот – это инструмент, который автоматизирует "
                              "некоторые процессы в Эпидемике.")
    assert "Злоупотребление полной автоматизацией процесса. В этот пункт входит АО — АвтоОтвет" in step[6]


# --- 171225 / 171232 / 171242: прокачка ---

async def test_upgrade_screens(h: Harness):
    await h.send(TIKTOK, "привет")
    start = len(h.session.calls)
    out = seen(await h.send(TIKTOK, "++летальность"))
    assert out == "✅ Усиление летальности патогена на 1 (до 2) выполнено\n🧾 Потрачено: 🧬 3 био-ресурсов"
    assert h.buttons() == ["1x 💊", "3x 💊", "5x 💊"]
    assert h.calls_named("SendMessage", start)[0].reply_parameters is not None  # бот отвечает reply

    await labs.set_fields(h.db, TIKTOK.id, lethality=3)
    start = len(h.session.calls)
    out = seen(await h.click(TIKTOK, UpgradeCb(action="more", skill="lethality", levels=3, owner=TIKTOK.id).pack()))
    assert out == "✅ Усиление летальности патогена на 3 (до 6) выполнено\n🧾 Потрачено: 🧬 70 био-ресурсов"
    assert h.calls_named("AnswerCallbackQuery", start)[0].text == "Улучшение на 3 уровней"

    out = seen(await h.send(TIKTOK, "++разработка"))
    assert out == "✅ Ускорение производства патогена на 1 уровень (до 59 мин.) выполнено\n🧾 Потрачено: 🧬 5 био-ресурсов"
    await labs.set_fields(h.db, TIKTOK.id, science=13)
    out = seen(await h.send(TIKTOK, "++разработка"))
    assert out == "✅ Ускорение производства патогена на 1 уровень (до 47 мин.) выполнено\n🧾 Потрачено: 🧬 733 био-ресурсов"


# --- 171253: «мои жертвы» пусто ---

async def test_empty_victims_screen(h: Harness):
    out = seen(await h.send(TIKTOK, "мои жертвы"))
    assert out == (
        "💉 Список больных вашим патогеном:\n\n"
        "У вас пока нет жертв\n\n\n"
        "📊 Итого: 0 заражённых и 0 био-опыта\n"
        "🧬 Ежедневная премия: 0 био-ресурсов"
    )


# --- 171302 / 171316: успешное заражение ---

async def test_infect_success_screen(h: Harness):
    await h.send(HUSE, "привет")
    await h.send(TIKTOK, "привет")
    await labs.set_fields(h.db, TIKTOK.id, lethality=6)
    await labs.set_fields(h.db, HUSE.id, bio_exp=1080)
    out = visible((await h.send(TIKTOK, f"заразить {HUSE.id}"))[0])  # [1] — уведомление жертве в ЛС
    assert out == (
        "🦠 С ТИКТОКА  Lening123124 подверг заражению патогеном неизвестным патогеном Huse\n"
        "☠️ Горячка на 2 минут\n"
        "🤒 Заражение на 6 дней\n"
        "☣️ +108 био-опыта‎ \n\n"
        "✨ Жертва заражена новой мутацией вируса, это принесло вам ценные генетические данные и последующую "
        "прибыль от исследований +108 био-ресурса"
    )


# --- 171035: анонимное уведомление жертве (горячка в тексте не обрезается) ---

async def test_anonymous_victim_notice_screen(h: Harness):
    await h.send(TIKTOK, "привет")
    await h.send(ALICE, "привет")
    await labs.set_fields(h.db, ALICE.id, lethality=666)
    await h.send(ALICE, f"заразить {TIKTOK.id}")
    notices = [visible(t) for t in h.sent_to(TIKTOK.id)]
    assert notices == [
        "🦠 Кто-то подверг заражению неизвестным патогеном С ТИКТОКА  Lening123124\n"
        "☠️ Горячка на 222 минут\n"
        "🤒 Заражение на 666 дней"
    ]


# --- 171324 / 171333: «заразить -» без цели и «заразить @777000» ---

async def test_infect_weaker_not_found_and_telegram_account(h: Harness):
    await h.send(TIKTOK, "привет")
    assert seen(await h.send(TIKTOK, "заразить -")) == "📝 Не удалось найти жертву, для заражения"
    out = seen(await h.send(TIKTOK, "заразить @777000"))
    assert out.startswith("🦠 С ТИКТОКА  Lening123124 подверг заражению патогеном неизвестным патогеном Telegram\n")


# --- 171341: биотоп ---

async def test_biotop_screen(h: Harness):
    top_player = User(id=303, is_bot=False, first_name="Игрок")
    await h.send(top_player, "привет")
    await labs.set_fields(h.db, top_player.id, lab_name="ТаПкА вИрУс", bio_exp=6_991_031)
    out = seen(await h.send(ALICE, "биотоп"))
    lines = out.split("\n")
    assert lines[0] == "🌸 Топ Лабораторий по био-опыту:"
    assert lines[2] == "1. ТаПкА вИрУс | 6,991,031 опыт"
    assert lines[-1] == "Суммарный био-опыт: 6,993,031"  # + лаборатории Алисы и Telegram по 1,000
    assert h.buttons() == ["• 1 •", "2"]


# --- 171451 / 171458: корпорации ---

async def test_corporation_screens(h: Harness):
    leader = User(id=304, is_bot=False, first_name="Лидер")
    await h.send(leader, ".корп создать рвём туза")
    await labs.set_fields(h.db, leader.id, bio_exp=16_638_003)
    assert seen(await h.send(ALICE, ".корп топ")) == "🌸 Топ Корпораций по заражениям:\n\n1. рвём туза | 16,638,003 опыт"
    assert seen(await h.send(ALICE, ".корп")) == "📝 Ваша Лаборатория не состоит ни в одной Корпорации"
    assert seen(await h.send(ALICE, "+корп досье")) == "📝 Вы не являетесь главой ни одной Корпорации"


# --- Досье (скрина нет — сверка с исходным кодом оригинала) ---

async def test_dossier_layout_from_original(h: Harness):
    await h.send(TIKTOK, "привет")
    out = seen(await h.send(ALICE, f"лаб {TIKTOK.id}"))
    assert out.startswith("📩 Досье лаборатории С ТИКТОКА  Lening123124:\nРуководитель — С ТИКТОКА  Lening123124 \n\n")
    assert "——[ Характеристика]——\n💉 Заразность: 1 ур" in out
    assert "💊 Летальность: 1 ур (1 мин | 1 дн)" in out
    assert "—[Запасы — реагентов]—\n☣️ Опыт: 1 000\n🧬 Ресурсы: 15 000\n" in out
    assert "⏱ Ежедневная премия через: Каждый день в 12.00 и 00.00" in out
    # как в оригинале, кнопки прокачки видны и под чужим досье
    assert h.buttons() == ["🧪", "🧑‍🎤", "💉", "🪬", "💊", "🕵️‍♂️"]
