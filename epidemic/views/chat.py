"""Тексты чат-менеджера: ID, правила, заметки, админы, приветствия, РП, ник — дословно из оригинала.

Сами шаблоны лежат в data/chat.yml (выгружены из оригинала как есть, с его опечатками).
"""
from __future__ import annotations

import random
import re
import unicodedata
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

import yaml

from aiogram.types import User

from epidemic.db import Row

CHAT_FILE = Path(__file__).resolve().parent.parent / "data" / "chat.yml"
COMMENT_RP = "💬 <b>Прошептав:</b> <i>⌜{}⌟</i>"


@lru_cache(maxsize=1)
def _texts() -> dict[str, Any]:
    with CHAT_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def t(section: str, key: str) -> str:
    return _texts()[section][key]


def rp_actions() -> dict[str, list[str]]:
    return _texts()["rp"]


def entity(user_id: int, name: str, username: str | None = None) -> str:
    """Ссылка на игрока как в оригинале: через t.me/username, если он есть, иначе tg://openmessage."""
    href = f"https://t.me/{username}" if username else f"tg://openmessage?user_id={int(user_id)}"
    return f'<a href="{href}">{escape(name)}</a>'


def user_entity(user: Row) -> str:
    # как в оригинале: чат-ник сохраняется, но в ссылках показывается имя из Telegram
    return entity(user["user_id"], user["full_name"], user["username"])


_WORDS_RE = re.compile(r"[\d\w\s]+")
_NOT_PLAIN_RE = re.compile(r"[^ -~А-Яа-яЁё]")


def plain_name(full_name: str, username: str | None, user_id: int) -> str:
    """Имя без эмодзи и экзотических символов — как clear_name_universal в оригинале."""
    name = " ".join(_WORDS_RE.findall(full_name.title())) or username or str(user_id)
    name = _NOT_PLAIN_RE.sub("", unicodedata.normalize("NFKC", name))
    return name if name.strip() else (username or str(user_id))


def plain_entity(user: User) -> str:
    return entity(user.id, plain_name(user.full_name, user.username, user.id), user.username)


def chat_entity(chat_id: int, title: str, username: str | None) -> str:
    href = f"https://t.me/{username}" if username else f"tg://openmessage?user_id={chat_id}"
    return f'<a href="{href}">{escape(title)}</a>'


# --- ID ---

def user_id_card(user: Row) -> str:
    return t("get_id", "result_id").format(user["user_id"], user_entity(user))


def chat_id_card(title: str, chat_id: int) -> str:
    return t("get_id", "get_chat_id").format(escape(title), chat_id)


# --- Правила ---

def rules(key: str, title: str, body: str | None = None) -> str:
    text = t("rules", key)
    return text.format(escape(title), body) if body is not None else text.format(escape(title))


# --- Заметки ---

def notes_list(rows: list[Row]) -> str:
    if not rows:
        return t("notes", "show_notes_not")
    return t("notes", "show_notes").format("\n".join(f"{r['note_id']}. {escape(r['title'])}" for r in rows))


def note_card(note: Row, created: str) -> str:
    return t("notes", "show_note").format(escape(note["title"]), f"{note['text']}\n\n🕒 <i>{created}</i>")


def note_status(key: str, title: str | None = None) -> str:
    text = t("notes", key)
    return text.format(escape(title)) if title is not None else text


# --- Администраторы чата ---

def admins_list(admins: list[tuple[int, str]]) -> str:
    if not admins:
        return t("admins", "admins_not_found")
    lines = [
        f'{i}. <a href="tg://openmessage?user_id={uid}">{escape(name or "админ")}</a>'
        for i, (uid, name) in enumerate(admins, 1)
    ]
    return t("admins", "admin_list").format("\n".join(lines))


# --- Приветствия / прощания ---

def greeting_switched(kind: str, enabled: bool, title: str) -> str:
    key = {
        ("join", True): "new_members_include",
        ("join", False): "new_members_off",
        ("leave", True): "leave_members_include",
        ("leave", False): "leave_members_off",
    }[(kind, enabled)]
    return t("chat_members", key).format(escape(title))


def bot_joined(chat: str) -> str:
    return t("chat_update", "bot_join_chat").format(chat)


def member_left(who: str) -> str:
    return t("chat_update", "leave_chat").format(who)


# --- РП и ник ---

def rp(action: str, sender: str, receiver: str, comment: str, rng: random.Random | None = None) -> str:
    template = (rng or random).choice(rp_actions()[action])
    text = template.format(sender, receiver)
    return f"{text}\n\n{COMMENT_RP.format(escape(comment))}" if comment else text


def nickname_changed(nickname: str) -> str:
    return t("nickname", "successful_changed").format(escape(nickname))
