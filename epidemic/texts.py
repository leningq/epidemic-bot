"""Общие тексты бота и обучение. Цель — 1 в 1 с оригинальным «Эпидемик 2.0».

Тексты обучения лежат дословно в data/story.yml (как в оригинале). Опечатки и пунктуацию оригинала
не исправляем: клиенту нужен бот 1 в 1 (сверка — docs/REFERENCE_SPEC.md).
"""
from __future__ import annotations

import random
from functools import lru_cache, partial
from html import escape
from pathlib import Path

import yaml

from epidemic.config import Config
from epidemic.game import constants as C
from epidemic.utils.fmt import cmd_link, num

SEP = "❇️—❎—✳️—💚—✳️—❎—❇️"
REFUND_PCT = int(C.DOWNGRADE_REFUND * 100)
STORY_FILE = Path(__file__).parent / "data" / "story.yml"


def header(config: Config, tag: str) -> str:
    return f"🦠 <code>{escape(config.notify_title)}</code> | <b>#{tag}</b>"


# ============================ Обучение (/start) ============================

@lru_cache(maxsize=1)
def _story() -> dict[str, str]:
    with STORY_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["begin"]


def story(key: str, bot: str) -> str:
    """Текст обучения из оригинала; {bot} → username нашего бота."""
    return _story()[key].replace("{bot}", bot).strip()


def start_action(bot: str) -> str:
    return story("start_action", bot)


def tutorial_continue(bot: str) -> str:
    return story("tutorial_continue", bot)


def tutorial_discontinue(bot: str) -> str:
    return story("tutorial_discontinue", bot)


def tutorial_step(step: int, bot: str) -> str:
    """Шаги 2–6 экскурса — дословно из оригинала."""
    if not 2 <= step <= 6:
        raise ValueError(step)
    return story(f"tutorial_{step}", bot)


def useful_links(config: Config) -> str:
    links = (
        (config.guide_url, "Ознакомиться с полноценным гайдом "),
        (config.rules_url, "Правила проекта"),
        (config.chat_url, "Игровой чатик"),
        (config.channel_url, "Канал игры"),
    )
    return "\n\n".join(f'{title} — <a href="{escape(url)}">ТЫК</a>' for url, title in links if url)


def tutorial_final(config: Config, bot: str) -> str:
    """Финал экскурса. В оригинале финал с питомцем не работал — делаем в той же стилистике."""
    link = partial(cmd_link, bot)
    text = (
        f"{header(config, 'оповещение')} \n\n"
        "<b>Итак.. вот наш экскурс подошёл к концу.</b>\n\n"
        "Теперь в твоём распоряжении своя лаборатория и первые запасы реагентов. "
        "Развивай вирусы, заражай и поднимайся в биотопе.\n\n"
        f"{SEP}\n"
        f"<blockquote><b>В лаборатории уже готово:</b> {C.START_PATHOGENS} патогена, "
        f"{num(C.START_BIO_RES)} био-ресурсов и {num(C.START_BIO_EXP)} био-опыта.</blockquote>\n"
        f"{SEP}\n\n"
        f"Досье лаборатории — «{link('лаб')}», прокачка — «{link('+заразность', '+')}», "
        f"первое заражение — «{link('заразить =')}».\n"
    )
    links = useful_links(config)
    if links:
        text += f"\n<b>🦠 Полезные ссылки:</b>\n\n<blockquote>{links}</blockquote>\n"
    return text + "\n<b>~ Желаем приятной игры 💚</b>"


def start_menu(config: Config) -> str:
    """Меню для тех, кто уже прошёл обучение (структура оригинала)."""
    text = "<b>💚 Не идентифицируемый объект замечен!</b>\n\n"
    if config.guide_url:
        text += (
            "<i>📖 Перед началом твоего путешествия, "
            f"<b><a href='{escape(config.guide_url)}'>прочитай гайд по игре</a></b></i>\n"
        )
    extra = []
    if config.chat_url:
        extra.append(
            "✨ Красивый чатик на безопасной планете,\n"
            f"твои глазки засияют от увиденного <b><a href='{escape(config.chat_url)}'>Посетив чат игры</a></b>"
        )
    if config.channel_url:
        extra.append(
            f"а также не забудь <b><a href='{escape(config.channel_url)}'>Посетить канал игры с квестами</a></b>"
        )
    if extra:
        text += "<i>\n" + "\n".join(extra) + "\n</i>\n"
    if config.support:
        text += f"<b>📞 Комиссия поддержки Эпсилон</b>\n<b>> 🌐 Онлайн\n    {escape(config.support)} </b>\n"
    return text + "\n<i>В добрый путь играющий свою роль за ученого или вируса!</i>"


# ============================ Общие ============================

NOT_YOUR_BUTTON = (
    "Не для тебя моя кнопочка росла",
    "Ты слишком горяч! Дай кнопке передохнуть(",
    "Не насилуй кнопку, она итак даст",
)


def not_your_button() -> str:
    return random.choice(NOT_YOUR_BUTTON)


BUTTON_OUTDATED = "Кнопка устарела"
NO_INFO_ABOUT_USER = "📝 Данные о субъекте отсутствуют"
VICTIM_NOT_FOUND = "📝 Не удалось найти жертву, для заражения"
NOT_ENOUGH_RESOURCES = "📝 У вас нет столько био-ресурсов"
TOO_FAST = "Не так быстро 🙂"
MAINTENANCE = "🔧 Бот временно закрыт на технические работы."
OWNER_ONLY = "🔒 Бот сейчас работает только для владельца."


def lab_disabled(reason: str | None = None) -> str:
    text = "🚫 Ваша лаборатория отключена администрацией."
    return f"{text}\nПричина: {escape(reason)}" if reason else text


PING_REPLIES = (
    "💚 Бот в деле!",
    "💚 Привет, я на связи",
    "💚 Бот готов к работе",
    "💚 Слышу тебя громко и чётко",
    "💚 Ваш бот на посту",
    "💚 А вот и я!",
    "💚 Бот активирован",
    "💚 Всегда рядом",
    "💚 Бот к вашим услугам",
    "💚 Пинг принят, бот отвечает",
)

SMOKE_VACCINE = (
    "🚫 <b>Команда больше не работает!</b>\n\n"
    "🚬 Скурить вакцину больше нельзя.\n"
    "💡 Для покупки вакцины используйте команду: <code>!купить вакцину</code>"
)


def help_text(bot: str) -> str:
    link = partial(cmd_link, bot)
    return (
        "📖 <b>Команды</b>\n\n"
        "<b>🧪 Лаборатория</b>\n"
        f"{link('лаб')} — досье (ответом, @ или ID — чужое), {link('мл')} — коротко\n"
        "<code>+навык [N]</code> — цена прокачки, <code>++навык [N]</code> — прокачать сразу, "
        f"<code>-навык N</code> — понизить (возврат {REFUND_PCT} %)\n"
        "Навыки: <code>патоген</code>, <code>разработка</code>, <code>заразность</code> (<code>зз</code>), "
        "<code>иммунитет</code>, <code>летальность</code>, <code>безопасность</code> (<code>сб</code>)\n"
        "<code>+имя патогена …</code> / <code>-имя патогена</code>\n"
        "<code>+имя лаборатории …</code> / <code>-имя лаборатории</code>\n"
        "<code>+лаб</code> / <code>-лаб</code> — открыть/скрыть досье, <code>лаб эмоджи 🔥</code>\n\n"
        "<b>🦠 Заражение</b>\n"
        "<code>заразить @user [N]</code>, ответом: <code>заразить [N]</code>\n"
        f"{link('заразить +')} / {link('заразить =')} / {link('заразить -')} / {link('заразить рандом')}\n"
        f"{link('мои жертвы')} ({link('мж')}), {link('мж топ')}, {link('мои болезни')} ({link('мб')}), "
        "<code>чек @user</code>\n"
        f"{link('мф')} — массовое заражение слетевших жертв\n"
        f"{link('!купить вакцину')} ({link('кв')}) — снять горячку\n"
        f"{link('+вирусы')} / {link('-вирусы')} — уведомления о заражениях в этот чат\n\n"
        "<b>🏆 Топы</b>\n"
        f"{link('биотоп')} ({link('бт')}), {link('биотоп чата')} ({link('бч')}), {link('корп топ')}\n\n"
        "<b>🔆 Корпорации</b>\n"
        f"{link('.корп')}, <code>.корп КОД</code>, <code>.корп создать Название</code>\n"
        "<code>+корп КОД</code> — заявка, <code>-корп</code> — выйти\n"
        "<code>.корп заявки</code>, <code>.корп принять @user</code>, <code>.корп отказать @user</code>\n"
        "<code>.корп участники</code>, <code>.корп кик @user</code>, <code>.корп изменить Название</code>\n"
        "<code>+корп сорук @user</code> / <code>-корп сорук @user</code>, <code>.корп соруки</code>\n"
        "<code>+корп досье</code> / <code>-корп досье</code>, <code>.корп удалить</code>\n\n"
        "<b>💬 Чат</b>\n"
        f"{link('!ид')}, {link('!чат ид')}, {link('правила')}, {link('заметки')}, {link('кто админ')}\n"
        "<code>+правила</code> (текст с новой строки) / <code>-правила</code>, "
        "<code>±приветствия</code>, <code>±прощания</code> — для админов чата\n"
        "<code>+заметка Название</code> (текст с новой строки), <code>заметка Название</code>, "
        "<code>-заметка Название</code>\n"
        "<code>ник Имя</code>, РП: <code>обнять</code>, <code>кусь</code>, <code>погладить</code>… (ответом или @)"
    )
