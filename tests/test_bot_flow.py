"""Сквозные сценарии: апдейты идут через настоящий Dispatcher, а запросы к Telegram перехватывает фейковая сессия."""
from __future__ import annotations

from aiogram.types import Chat, MessageEntity, User

from epidemic import texts
from epidemic.keyboards import MenuCb, TutorialCb, UpgradeCb
from epidemic.repo import corps, labs, users
from tests.harness import ALICE, BOB, GROUP, OWNER, Harness, joined


# --- /start и обучение ---

async def test_tutorial_flow(h: Harness):
    private = Chat(id=ALICE.id, type="private")
    out = joined(await h.send(ALICE, "/start", chat=private))
    assert "Добро пожаловать в мир" in out
    buttons = [b.text for row in h.last_markup().inline_keyboard for b in row]
    assert buttons == ["💚 Начать путешествие", "❎ Отказываюсь", "➕ Добавить бота в чат"]

    assert "Мудрое решение" in joined(await h.click(ALICE, TutorialCb(step=1).pack(), private))
    for step in range(2, 7):
        assert "#обучение" in joined(await h.click(ALICE, TutorialCb(step=step).pack(), private))
    assert "экскурс подошёл к концу" in joined(await h.click(ALICE, TutorialCb(step=7).pack(), private))
    assert (await users.get(h.db, ALICE.id))["tutorial_done"] == 1
    assert "Не идентифицируемый объект" in joined(await h.send(ALICE, "/start", chat=private))


async def test_decline_tutorial(h: Harness):
    private = Chat(id=BOB.id, type="private")
    await h.send(BOB, "/start", chat=private)
    assert "/restart_tutorial" in joined(await h.click(BOB, TutorialCb(step=0).pack(), private))
    assert (await users.get(h.db, BOB.id))["tutorial_done"] == 1


# --- Лаборатория и прокачка ---

async def test_any_chat_member_gets_a_lab(h: Harness):
    await h.send(BOB, "всем привет")
    lab = await labs.get(h.db, BOB.id)
    assert lab is not None and lab["bio_res"] == 15_000 and lab["ready_pathogens"] == 4


async def test_lab_dossier_and_privacy(h: Harness):
    out = joined(await h.send(ALICE, "лаб"))
    assert "Досье лаборатории Алиса" in out and "15 000" in out and "ID лаборатории" in out
    await h.send(BOB, "-лаб")
    assert "засекретил досье" in joined(await h.send(ALICE, "лаб @bob_lab"))
    await h.send(BOB, "+лаб")
    assert "Досье лаборатории Боб" in joined(await h.send(ALICE, "лаб @bob_lab"))


async def test_upgrade_commands(h: Harness):
    await h.send(ALICE, "лаб")
    assert "выполнено" in joined(await h.send(ALICE, "++зз 2"))
    assert (await labs.get(h.db, ALICE.id))["infect"] == 3

    preview = joined(await h.send(ALICE, "+иммун"))
    assert "Стоимость" in preview and "++иммунитет 1" in preview
    confirm = h.last_markup().inline_keyboard[0][0].callback_data
    assert "выполнено" in joined(await h.click(ALICE, confirm))
    assert (await labs.get(h.db, ALICE.id))["immunity"] == 2

    # чужая кнопка
    await h.click(BOB, UpgradeCb(action="more", skill="immunity", levels=5, owner=ALICE.id).pack())
    assert (await labs.get(h.db, ALICE.id))["immunity"] == 2


async def test_names(h: Harness):
    assert "изменён" in joined(await h.send(ALICE, "+имя патогена Чума"))
    assert "уже занято" in joined(await h.send(BOB, "+имя патогена чума"))
    assert "только буквы" in joined(await h.send(BOB, "+имя патогена <b>x</b>"))
    assert "Бункер" in joined(await h.send(ALICE, "+имя лаборатории Бункер"))
    assert "Досье лаборатории Бункер" in joined(await h.send(ALICE, "лаб"))


# --- Заражение ---

async def test_infect_by_username_and_lists(h: Harness):
    await h.send(BOB, "привет")
    out = joined(await h.send(ALICE, "заразить @bob_lab"))
    assert "подверг заражению" in out and "+100 био-опыта" in out
    # уведомление жертве в ЛС (по умолчанию), без имени атакующего — СБ равны
    assert any("Кто-то подверг заражению" in t for t in h.sent_to(BOB.id))

    assert "Недавно Вы уже подвергали" in joined(await h.send(ALICE, "заразить @bob_lab"))
    assert "горячка" in joined(await h.send(BOB, "заразить @alice_lab"))
    assert "Боб" in joined(await h.send(ALICE, "мж")) and "Ежедневная премия" in joined(await h.send(ALICE, "мж"))
    assert "Список ваших болезней" in joined(await h.send(BOB, "мб"))
    assert "излечились" in joined(await h.send(BOB, "!купить вакцину"))


async def test_infect_by_reply_and_bot_target(h: Harness):
    original = h.message(BOB, "я тут")
    await h.send(BOB, "я тут")
    assert "подверг заражению" in joined(await h.send(ALICE, "заразить", reply_to=original))
    bot_msg = h.message(User(id=42, is_bot=True, first_name="Epidemic"), "бот")
    assert "умеющую дышать" in joined(await h.send(ALICE, "заразить", reply_to=bot_msg))
    assert await h.send(ALICE, "заразить") == []  # как в оригинале: без цели — не команда


async def test_infect_by_text_mention(h: Harness):
    no_username = User(id=303, is_bot=False, first_name="Вика")
    await h.send(no_username, "привет")
    entity = MessageEntity(type="text_mention", offset=9, length=4, user=no_username)
    assert "подверг заражению" in joined(await h.send(ALICE, "заразить Вика", entities=[entity]))


async def test_vaccine_when_healthy_and_joke(h: Harness):
    assert "Вы здоровы" in joined(await h.send(ALICE, "кв"))
    assert "🚬" in joined(await h.send(ALICE, "курить вакцину"))


async def test_virus_signal(h: Harness):
    await h.send(BOB, "+вирусы")
    assert (await labs.get(h.db, BOB.id))["notify_chat_id"] == GROUP.id
    await h.send(BOB, "-вирусы")
    assert (await labs.get(h.db, BOB.id))["notify_chat_id"] is None


# --- Биотоп ---

async def test_biotop(h: Harness):
    await h.send(ALICE, "привет")
    await h.send(BOB, "привет")
    out = joined(await h.send(ALICE, "биотоп"))
    assert "Топ Лабораторий по био-опыту" in out and "Алиса" in out and "Боб" in out
    assert "Топ Лабораторий чата" in joined(await h.send(ALICE, "бч"))


# --- Корпорации ---

async def test_corporation_lifecycle(h: Harness):
    await h.send(BOB, "привет")
    assert "создана" in joined(await h.send(ALICE, ".корп создать Альфа"))
    corp = await corps.membership(h.db, ALICE.id)
    code = corp["code"]

    assert "подали заявку" in joined(await h.send(BOB, f"+корп {code}"))
    assert "Боб" in joined(await h.send(ALICE, ".корп заявки"))
    assert "Принят в корпорацию" in joined(await h.send(ALICE, ".корп принять @bob_lab"))

    card = joined(await h.send(BOB, ".корп"))
    assert "КОРПОРАЦИЯ «Альфа»" in card and "Лабораторий: 2" in card
    assert "назначен соучредителем" in joined(await h.send(ALICE, "+корп сорук @bob_lab"))
    assert "Покинуть корпорацию невозможно" in joined(await h.send(ALICE, "-корп"))
    assert "вышла из состава" in joined(await h.send(BOB, "-корп"))
    assert "Альфа" in joined(await h.send(BOB, "корп топ"))
    assert "прекращает своё существование" in joined(await h.send(ALICE, ".корп удалить"))
    assert await corps.membership(h.db, ALICE.id) is None


# --- Админка ---

async def test_admin_permissions_and_economy(h: Harness):
    await h.send(ALICE, "привет")
    assert await h.send(ALICE, f"/give_res {BOB.id} 1000") == []  # игрок — тишина
    assert "Доступ запрещён" in joined(await h.send(ALICE, "/admin"))

    assert "Панель управления" in joined(await h.send(OWNER, "/admin"))
    assert "16 000" in joined(await h.send(OWNER, f"/give_res {ALICE.id} 1000"))
    assert "назначен администратором" in joined(await h.send(OWNER, "+админ @alice_lab"))
    # обычный админ не выдаёт ресурсы (нужен старший), но видит статистику
    assert await h.send(ALICE, f"/give_res {ALICE.id} 1000") == []
    assert "Статистика" in joined(await h.send(ALICE, "/stats"))
    history = joined(await h.send(OWNER, "/admin_history"))
    assert "give_bio_res" in history and "appoint_admin" in history


async def test_maintenance_and_ignore(h: Harness):
    await h.send(ALICE, "привет")
    await h.send(OWNER, "тех+")
    assert "технические работы" in joined(await h.send(ALICE, "лаб"))
    assert await h.send(ALICE, "просто болтаю") == []  # на обычные сообщения бот молчит
    await h.send(OWNER, "тех-")
    assert "Досье" in joined(await h.send(ALICE, "лаб"))

    await h.send(OWNER, "+ас @alice_lab")
    assert await h.send(ALICE, "лаб") == []
    await h.send(OWNER, "-ас @alice_lab")
    assert "Досье" in joined(await h.send(ALICE, "лаб"))


async def test_disable_lab_and_settings(h: Harness):
    await h.send(ALICE, "привет")
    await h.send(BOB, "привет")
    out = joined(await h.send(OWNER, f"/disable_lab {BOB.id} 1d мультиаккаунт"))
    assert "отключена" in out
    assert "отключена администрацией" in joined(await h.send(BOB, "заразить @alice_lab"))
    await h.send(OWNER, f"/enable_lab {BOB.id}")
    assert not (await labs.get(h.db, BOB.id))["disabled"]

    assert "установлена" in joined(await h.send(OWNER, "/set_game_setting xp_multiplier_pct 150"))
    assert h.app.gs.xp_pct == 150
    assert "от 1 до" in joined(await h.send(OWNER, "/set_game_setting xp_multiplier_pct 0"))


async def test_admin_cannot_punish_equal_or_higher_staff(h: Harness):
    for user in (ALICE, BOB):
        await h.send(user, "привет")
    await h.send(OWNER, "+админ @alice_lab")
    await h.send(OWNER, "+старший @bob_lab")
    assert "Нельзя применять" in joined(await h.send(ALICE, f"/disable_lab {BOB.id} злоупотребление"))
    assert "Нельзя применять" in joined(await h.send(ALICE, f"/sanction {OWNER.id} тест"))
    assert "Нельзя применять" in joined(await h.send(BOB, f"/give_res {OWNER.id} -1000"))
    assert "Нельзя применять" in joined(await h.send(BOB, f"/set_skill {OWNER.id} infect 1"))
    assert "Нельзя применять" in joined(await h.send(ALICE, f"/enable_lab {ALICE.id}"))
    assert not (await labs.get(h.db, BOB.id))["disabled"]
    assert "отключена" in joined(await h.send(BOB, f"/disable_lab {ALICE.id} тест"))


async def test_moderation_by_reply_keeps_term_and_reason(h: Harness):
    target_msg = h.message(BOB, "спам")
    await h.send(BOB, "спам")
    await h.send(OWNER, "/disable_lab 7d мультиаккаунт", reply_to=target_msg)
    lab = await labs.get(h.db, BOB.id)
    assert lab["disabled"] and lab["disabled_until"] is not None and lab["disabled_reason"] == "мультиаккаунт"

    await h.send(OWNER, "+ас 30m флуд", reply_to=target_msg)
    sanction = await h.db.fetchone("SELECT * FROM sanctions WHERE user_id = ? AND kind = 'ignore'", (BOB.id,))
    assert sanction["expires_at"] is not None and sanction["reason"] == "флуд"


async def test_timed_ignore_does_not_shorten_permanent(h: Harness):
    await h.send(BOB, "привет")
    await h.send(OWNER, "+ас @bob_lab навсегда")
    await h.send(OWNER, "+ас @bob_lab 1m ещё раз")
    assert h.app.dp["ignores"].is_ignored(BOB.id, 2**40)  # далеко после истечения временного


async def test_long_admin_lists_fit_one_message(h: Harness):
    for i in range(120):
        await h.send(OWNER, f"/ban_name pathogen Плохое имя номер {i} | очень длинная причина запрета {'x' * 40}")
    out = joined(await h.send(OWNER, "/names"))
    assert len(out) < 4096 and "… и ещё" in out


async def test_ban_name_resets_existing(h: Harness):
    await h.send(ALICE, "+имя патогена Плохое")
    await h.send(OWNER, "/ban_name pathogen плохое | оскорбление")
    assert (await labs.get(h.db, ALICE.id))["pathogen_name"] is None
    assert "запрещено" in joined(await h.send(BOB, "+имя патогена Плохое"))


async def test_help_and_ping(h: Harness):
    # как в оригинале: «помощь» — меню повторного /start; наш список команд — «команды»
    assert "Не идентифицируемый объект замечен" in joined(await h.send(ALICE, "помощь"))
    assert h.buttons() == ["🔄 Вернуться в начало", "📖 Гайд по игре", "➕ Добавить бота в чат"]
    assert "Команды" in joined(await h.send(ALICE, "команды"))
    assert "💚" in joined(await h.send(ALICE, "бот"))
    assert joined(await h.send(ALICE, "мяу")) == "мур"


async def test_corp_join_with_bad_code_explains(h: Harness):
    """«+корп код» (слово вместо кода) и «+корп» без кода не молчат; досье и соруки не перехвачены."""
    assert joined(await h.send(ALICE, "+корп код")) == "📝 Такой Корпорации не существует"
    assert joined(await h.send(ALICE, "+корп abcdefgh")) == "📝 Такой Корпорации не существует"
    assert "+корп код" in joined(await h.send(ALICE, "+корп"))
    assert joined(await h.send(ALICE, "+корп досье")) == "📝 Вы не являетесь главой ни одной Корпорации"


async def test_menu_back_to_begin(h: Harness):
    """«🔄 Вернуться в начало» показывает первый экран /start; пройденное обучение не сбрасывается."""
    private = Chat(id=ALICE.id, type="private", first_name="Алиса")
    first_screen = [texts.start_action("test_bot")]  # в тестах нет картинки — приходит текст
    first_buttons = ["💚 Начать путешествие", "❎ Отказываюсь", "➕ Добавить бота в чат"]
    await h.send(ALICE, "/start", chat=private)
    await users.set_tutorial_done(h.db, ALICE.id, True)
    await h.send(ALICE, "/start", chat=private)
    assert h.buttons() == ["🔄 Вернуться в начало", "📖 Гайд по игре", "➕ Добавить бота в чат"]

    start = len(h.session.calls)
    assert await h.click(ALICE, MenuCb(action="begin").pack(), chat=private) == first_screen
    assert h.calls_named("DeleteMessage", start)  # меню сменилось первым экраном
    assert h.buttons() == first_buttons
    assert (await users.get(h.db, ALICE.id))["tutorial_done"]

    # в группе кнопка ведёт в личку: /start begin открывает тот же первый экран
    await h.send(ALICE, "помощь")
    assert h.last_markup().inline_keyboard[0][0].url == "https://t.me/test_bot?start=begin"
    assert await h.send(ALICE, "/start begin", chat=private) == first_screen
