"""Inline-клавиатуры и типизированные callback-данные."""
from __future__ import annotations

from typing import Annotated, Literal

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pydantic import Field

from epidemic.config import Config
from epidemic.game.constants import BIOTOP_PAGES, CORP_CODE_LEN, MAX_LEVELS_PER_UPGRADE, SKILL_ICON, SKILLS

ADD_TO_CHAT_RIGHTS = "delete_messages+pin_messages+invite_users"

# Поля callback-данных строго типизированы: подделанная или устаревшая кнопка не пройдёт фильтр
# и получит «Кнопка устарела» от общего обработчика в handlers/misc.py.
SkillName = Literal["pathogens", "science", "infect", "immunity", "lethality", "security"]
AdminSection = Literal["main", "labs", "economy", "moderation", "names", "admins", "settings", "stats", "history"]


class TutorialCb(CallbackData, prefix="tut"):
    step: Annotated[int, Field(ge=0, le=7)]  # 0 — отказ, 1..7 — шаги экскурса


class MenuCb(CallbackData, prefix="menu"):
    action: Literal["begin"]  # «Вернуться в начало» — первый экран /start


BEGIN_PAYLOAD = "begin"  # /start begin — тот же первый экран по ссылке (для меню в группе)


class UpgradeCb(CallbackData, prefix="up"):
    action: Literal["open", "confirm", "more"]
    skill: SkillName
    levels: Annotated[int, Field(ge=1, le=MAX_LEVELS_PER_UPGRADE)]
    owner: int


class BiotopCb(CallbackData, prefix="bt"):
    kind: Literal["lab", "chat"]
    page: Annotated[int, Field(ge=1, le=BIOTOP_PAGES)]
    owner: int


class CorpCb(CallbackData, prefix="corp"):
    action: Literal["members", "join"]
    code: Annotated[str, Field(pattern=rf"^[a-z0-9]{{1,{CORP_CODE_LEN}}}$")]


class InfectCb(CallbackData, prefix="inf"):
    target: int
    owner: int


class AdminCb(CallbackData, prefix="adm"):
    section: AdminSection


class FailCb(CallbackData, prefix="fail"):
    """Кнопки под провалом заражения: повторить с N патогенами или прокачать заразность на N."""
    action: Literal["repeat", "up"]
    target: int
    owner: int
    n: Annotated[int, Field(ge=1, le=MAX_LEVELS_PER_UPGRADE)]


class MassCb(CallbackData, prefix="mf"):
    action: Literal["page", "start", "all", "cancel", "noop"]
    page: Annotated[int, Field(ge=1)] = 1


def add_to_chat_url(bot_username: str) -> str:
    return f"https://t.me/{bot_username}?startgroup=start&admin={ADD_TO_CHAT_RIGHTS}"


def start_action(bot_username: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💚 Начать путешествие", callback_data=TutorialCb(step=1))
    kb.button(text="❎ Отказываюсь", callback_data=TutorialCb(step=0))
    kb.button(text="➕ Добавить бота в чат", url=add_to_chat_url(bot_username))
    kb.adjust(1)
    return kb.as_markup()


def tutorial_next(step: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Продолжить курс ❇️", callback_data=TutorialCb(step=step))
    return kb.as_markup()


def add_to_chat(bot_username: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить бота в чат", url=add_to_chat_url(bot_username))
    return kb.as_markup()


def start_menu(config: Config, bot_username: str, private: bool = True) -> InlineKeyboardMarkup:
    """Меню повторного /start и «помощь»: вернуться к первому экрану, гайд (если задан), добавить в чат.

    «Вернуться в начало» в личке показывает первый экран прямо здесь, а в группе открывает личку
    с ботом (/start begin) — чтобы обучение не шло посреди общего чата.
    """
    kb = InlineKeyboardBuilder()
    if private:
        kb.button(text="🔄 Вернуться в начало", callback_data=MenuCb(action="begin"))
    else:
        kb.button(text="🔄 Вернуться в начало", url=f"https://t.me/{bot_username}?start={BEGIN_PAYLOAD}")
    if config.guide_url:
        kb.button(text="📖 Гайд по игре", url=config.guide_url)
    kb.button(text="➕ Добавить бота в чат", url=add_to_chat_url(bot_username))
    kb.adjust(1)
    return kb.as_markup()


def lab_navigation(owner: int) -> InlineKeyboardMarkup:
    """Шесть кнопок под досье: открывают прокачку соответствующего навыка."""
    kb = InlineKeyboardBuilder()
    for skill in SKILLS:
        kb.button(text=SKILL_ICON[skill], callback_data=UpgradeCb(action="open", skill=skill, levels=1, owner=owner))
    kb.adjust(3)
    return kb.as_markup()


def upgrade_confirm(skill: str, levels: int, owner: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="Подтвердить улучшение",
        callback_data=UpgradeCb(action="confirm", skill=skill, levels=levels, owner=owner),
    )
    return kb.as_markup()


def upgrade_more(skill: str, owner: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in (1, 3, 5):
        kb.button(
            text=f"{n}x {SKILL_ICON[skill]}",
            callback_data=UpgradeCb(action="more", skill=skill, levels=n, owner=owner),
        )
    kb.adjust(3)
    return kb.as_markup()


def biotop_pages(kind: str, page: int, owner: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in range(1, BIOTOP_PAGES + 1):
        kb.button(text=f"• {n} •" if n == page else str(n), callback_data=BiotopCb(kind=kind, page=n, owner=owner))
    kb.adjust(BIOTOP_PAGES)
    return kb.as_markup()


def corp_navigation(code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Участники", callback_data=CorpCb(action="members", code=code))
    kb.button(text="Вступить", callback_data=CorpCb(action="join", code=code))
    kb.adjust(2)
    return kb.as_markup()


def infect_target(target: int, owner: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💥 Ебнуть", callback_data=InfectCb(target=target, owner=owner))  # текст как в оригинале
    return kb.as_markup()


def infect_fail(target: int, owner: int) -> InlineKeyboardMarkup:
    """Как в оригинале: повтор 1/5/9 патогенами и прокачка заразности +1/+3/+10."""
    kb = InlineKeyboardBuilder()
    for n, text in ((1, "🔁 1 пат"), (5, "🔁 5 патов"), (9, "🔁 9 патов")):
        kb.button(text=text, callback_data=FailCb(action="repeat", target=target, owner=owner, n=n))
    for n in (1, 3, 10):
        kb.button(text=f"🎯 +{n} ЗЗ", callback_data=FailCb(action="up", target=target, owner=owner, n=n))
    kb.adjust(3, 3)
    return kb.as_markup()


def mass_list(page: int, total_pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nav = []
    if page > 1:
        nav.append(("⬅️", MassCb(action="page", page=page - 1)))
    nav.append((f"{page}/{total_pages}", MassCb(action="noop", page=page)))
    if page < total_pages:
        nav.append(("➡️", MassCb(action="page", page=page + 1)))
    for text, data in nav:
        kb.button(text=text, callback_data=data)
    kb.button(text=f"☣️ Заразить всех (Стр. {page})", callback_data=MassCb(action="start", page=page))
    kb.button(text="🔥 Заразить ВСЕХ из списка", callback_data=MassCb(action="all"))
    kb.adjust(len(nav), 1, 1)
    return kb.as_markup()


def mass_cancel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Остановить заражение", callback_data=MassCb(action="cancel"))
    return kb.as_markup()


ADMIN_SECTIONS: tuple[tuple[str, str], ...] = (
    ("labs", "🧪 Лаборатории"),
    ("economy", "💰 Экономика"),
    ("moderation", "🚫 Модерация"),
    ("names", "📝 Названия"),
    ("admins", "👥 Администраторы"),
    ("settings", "⚙️ Глобальные настройки"),
    ("stats", "📊 Статистика"),
    ("history", "📋 История"),
)


def admin_panel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for section, title in ADMIN_SECTIONS:
        kb.button(text=title, callback_data=AdminCb(section=section))
    kb.adjust(2)
    return kb.as_markup()


def admin_back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Админ-панель", callback_data=AdminCb(section="main"))
    return kb.as_markup()
