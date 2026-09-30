"""Чат-менеджер оригинала: ID, правила, заметки, админы, приветствия/прощания, РП-команды, ник.

Тексты — в views/chat.py (дословно из оригинала). Правила и переключатели приветствий доступны
только администраторам чата (как в оригинале — через getChatAdministrators).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter, Filter
from aiogram.types import ChatMemberUpdated, Message

from epidemic.config import Config
from epidemic.db import Database
from epidemic.handlers.common import PREFIX, cmd
from epidemic.repo import chats, users
from epidemic.utils import names
from epidemic.utils.fmt import now_ts
from epidemic.utils.parse import parse_target_token
from epidemic.utils.targets import is_group, mentioned_user, reply_user, resolve_arg, resolve_ref
from epidemic.views import chat as view

log = logging.getLogger(__name__)
router = Router(name="chat")

MAX_NOTES_PER_CHAT = 100
NOTES_LIMIT = "📌 В беседе уже слишком много заметок, удалите ненужные"


class GroupChat(Filter):
    async def __call__(self, message: Message) -> bool:
        return is_group(message.chat)


def _chat_title(message: Message) -> str:
    return message.chat.title or message.chat.full_name or str(message.chat.id)


async def _chat_admins(bot: Bot, chat_id: int) -> list[tuple[int, str]]:
    try:
        members = await bot.get_chat_administrators(chat_id)
    except TelegramAPIError as exc:
        log.debug("Не удалось получить админов %s: %s", chat_id, exc)
        return []
    return [(m.user.id, m.user.full_name) for m in members]


async def _is_chat_admin(message: Message, bot: Bot) -> bool:
    if message.sender_chat is not None and message.sender_chat.id == message.chat.id:
        return True  # анонимный администратор пишет от имени группы
    return any(uid == message.from_user.id for uid, _ in await _chat_admins(bot, message.chat.id))


# --- ID ---

@router.message(cmd(r"[!./](?:ид|id)(?:\s+(?P<target>\S+))?"))
async def user_id(message: Message, m: re.Match, db: Database) -> None:
    # как в оригинале: цель из ссылки/упоминания, иначе автор сообщения-ответа, иначе сам игрок
    target = await resolve_arg(db, message, m.group("target"))
    if target is None and not m.group("target"):
        target = message.from_user.id
    user = await users.get(db, target) if target is not None else None
    if user is None:
        await message.answer(view.t("get_id", "result_not_found"))
        return
    await message.answer(view.user_id_card(user))


@router.message(cmd(r"[!./](?:чат ид|chat id)"))
async def chat_id(message: Message) -> None:
    await message.answer(view.chat_id_card(_chat_title(message), message.chat.id))


# --- Правила ---

@router.message(cmd(r"\+правила[ \t]{0,4}\n(?P<body>.+)"), GroupChat())
async def rules_set(message: Message, bot: Bot, db: Database) -> None:
    title = _chat_title(message)
    if not await _is_chat_admin(message, bot):
        await message.answer(view.rules("not_admin", title))
        return
    body = message.html_text.split("\n", 1)[1].strip()
    if len(body) < 5:
        await message.answer(view.rules("rules_short", title))
        return
    await chats.set_rules(db, message.chat.id, body)
    await message.answer(view.rules("rules_added", title))


@router.message(cmd(rf"{PREFIX}правила"), GroupChat())
async def rules_show(message: Message, db: Database) -> None:
    chat = await chats.get(db, message.chat.id)
    title = _chat_title(message)
    if chat is None or not chat["rules"]:
        await message.answer(view.rules("rules_not_found", title))
        return
    await message.answer(view.rules("show_rules", title, chat["rules"]))


@router.message(cmd(r"-правила"), GroupChat())
async def rules_delete(message: Message, bot: Bot, db: Database) -> None:
    title = _chat_title(message)
    if not await _is_chat_admin(message, bot):
        await message.answer(view.rules("not_admin", title))
        return
    await chats.set_rules(db, message.chat.id, None)
    await message.answer(view.rules("rules_del", title))


# --- Заметки ---

@router.message(cmd(rf"{PREFIX}заметки"), GroupChat())
async def notes_show(message: Message, db: Database) -> None:
    await message.answer(view.notes_list(await chats.notes(db, message.chat.id)))


@router.message(cmd(rf"{PREFIX}\+заметка (?P<title>[^\n]{{1,64}})(?:\n.*)?"), GroupChat())
async def note_add(message: Message, m: re.Match, db: Database) -> None:
    title = m.group("title").strip()
    if not title:
        return
    chat_id = message.chat.id
    key = names.name_key(title)
    body = "\n".join(message.html_text.split("\n")[1:]).strip()
    async with db.tx() as t:
        if await chats.note(t, chat_id, title, key):
            status = "note_already_exist"
        elif not body:
            status = "note_not_has_text"
        elif len(await chats.notes(t, chat_id)) >= MAX_NOTES_PER_CHAT:
            status = "limit"
        else:
            await chats.add_note(t, chat_id, title, key, body, now_ts())
            status = "add_note"
    if status == "limit":
        await message.answer(NOTES_LIMIT)
        return
    await message.answer(view.note_status(status, title if status == "add_note" else None))


@router.message(cmd(rf"{PREFIX}заметка (?P<title>[^\n]{{1,64}})"), GroupChat())
async def note_show(message: Message, m: re.Match, db: Database, config: Config) -> None:
    title = m.group("title").strip()
    note = await chats.note(db, message.chat.id, title, names.name_key(title))
    if note is None:
        await message.answer(view.note_status("note_not_found"))
        return
    created = datetime.fromtimestamp(note["created_at"], config.tz).strftime("%Y.%m.%d")
    await message.answer(view.note_card(note, created))


@router.message(cmd(rf"{PREFIX}-заметка (?P<title>[^\n]{{1,64}})"), GroupChat())
async def note_delete(message: Message, m: re.Match, db: Database) -> None:
    title = m.group("title").strip()
    async with db.tx() as t:
        note = await chats.note(t, message.chat.id, title, names.name_key(title))
        if note is not None:
            await chats.delete_note(t, message.chat.id, note["note_id"])
    if note is None:
        await message.answer(view.note_status("note_not_found"))
        return
    await message.answer(view.note_status("del_note", note["title"]))


# --- Администраторы чата ---

@router.message(cmd(rf"{PREFIX}кто админ|кто эпик"), GroupChat())
async def chat_admins(message: Message, bot: Bot) -> None:
    await message.answer(view.admins_list(await _chat_admins(bot, message.chat.id)))


# --- Приветствия и прощания ---

@router.message(cmd(rf"{PREFIX}(?P<sign>[+-])(?P<kind>приветствия|прощания)"), GroupChat())
async def greetings_switch(message: Message, m: re.Match, bot: Bot, db: Database) -> None:
    title = _chat_title(message)
    if not await _is_chat_admin(message, bot):
        await message.answer(view.rules("not_admin", title))
        return
    kind = "join" if m.group("kind").lower() == "приветствия" else "leave"
    enabled = m.group("sign") == "+"
    await chats.set_greeting(db, message.chat.id, kind, enabled)
    await message.answer(view.greeting_switched(kind, enabled, title))


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def bot_added(event: ChatMemberUpdated) -> None:
    if not is_group(event.chat):
        return
    chat = view.chat_entity(event.chat.id, event.chat.title or "", event.chat.username)
    await event.answer(view.bot_joined(chat))


# Приветствие новичков в оригинале — пустая строка, поэтому бот молчит (переключатель «±приветствия»
# при этом работает и сохраняется, как там).

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def member_left(event: ChatMemberUpdated, db: Database) -> None:
    user = event.new_chat_member.user
    chat = await chats.get(db, event.chat.id)
    if is_group(event.chat) and not user.is_bot and (chat is None or chat["greet_leave"]):
        await event.answer(view.member_left(view.plain_entity(user)))


# --- РП-команды ---

_STRIP_RP = str.maketrans("", "", "./!")
_TAG_MARKS = ("tg://openmessage?", "tg://user?", "@", "https://t.me/", "http://t.me/")


class RpFilter(Filter):
    """«обнять @user», «кусь» ответом и т.п. Действие — первое слово (или два: «дать пять»)."""

    async def __call__(self, message: Message) -> bool | dict[str, Any]:
        words = (message.text or "").lower().translate(_STRIP_RP).split()
        if not words:
            return False
        actions = view.rp_actions()
        for size in (2, 1):
            action = " ".join(words[:size])
            if len(words) >= size and action in actions:
                return {"rp_action": action, "rp_size": size}
        return False


@router.message(RpFilter())
async def rp_command(message: Message, rp_action: str, rp_size: int, db: Database) -> None:
    text = message.text or ""
    rest = text.split()[rp_size:]
    tags = [word for word in rest if any(mark in word for mark in _TAG_MARKS)]
    comment = rest[1:] if rest and tags and rest[0] == tags[0] else rest
    receiver_id: int | None = None
    if (picked := mentioned_user(message)) is not None:
        receiver_id = picked.id
        comment = " ".join(comment).replace(_mention_fragment(message), "", 1).split()
    elif tags:
        receiver_id = await resolve_ref(db, parse_target_token(tags[0]))
    if receiver_id is None and (replied := reply_user(message)) is not None:
        receiver_id = replied.id
    receiver = await users.get(db, receiver_id) if receiver_id is not None else None
    sender = await users.get(db, message.from_user.id)
    if receiver is None or sender is None:
        return  # как в оригинале: без цели (ответа или упоминания) РП-команда молчит
    await message.answer(
        view.rp(rp_action, view.user_entity(sender), view.user_entity(receiver), " ".join(comment))
    )


def _mention_fragment(message: Message) -> str:
    """Текст упоминания без username (text_mention), чтобы не попал в комментарий."""
    for entity in message.entities or ():
        if entity.type == "text_mention":
            return entity.extract_from(message.text or "")
    return ""


# --- Чат-ник ---

@router.message(cmd(rf"{PREFIX}(?:мой ник|ник)\s{{1,3}}(?P<nick>[!._A-Za-zА-Яа-яё\d ]{{1,63}})"))
async def set_nickname(message: Message, m: re.Match, db: Database) -> None:
    nickname = " ".join(m.group("nick").split())
    if not nickname:
        return
    await chats.set_nickname(db, message.from_user.id, nickname)
    await message.answer(view.nickname_changed(nickname))
