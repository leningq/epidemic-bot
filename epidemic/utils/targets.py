"""Определение игрока-цели из сообщения: ответ, упоминание, @username, ссылка или ID."""
from __future__ import annotations

from collections.abc import Iterator

from aiogram.types import Chat, Message, User

from epidemic.db import Q
from epidemic.repo import users
from epidemic.utils.parse import TargetRef, parse_target_token

GROUP_CHAT_TYPES = frozenset({"group", "supergroup"})


def is_group(chat: Chat | None) -> bool:
    return chat is not None and chat.type in GROUP_CHAT_TYPES


def reply_user(message: Message) -> User | None:
    """Автор сообщения, на которое ответили (без учёта служебного корня темы форума)."""
    reply = message.reply_to_message
    if reply is None or reply.forum_topic_created is not None:
        return None
    return reply.from_user


def all_mentioned_users(message: Message) -> Iterator[User]:
    """Пользователи из text_mention (упоминания без username, выбранные из списка)."""
    for entity in message.entities or ():
        if entity.type == "text_mention" and entity.user is not None:
            yield entity.user


def mentioned_user(message: Message) -> User | None:
    return next(all_mentioned_users(message), None)


def with_mention_as_link(message: Message) -> str:
    """Текст сообщения, где text_mention заменён на tg://user?id=… (чтобы его понял парсер).

    Замена идёт ровно по позиции упоминания (Telegram считает её в UTF-16) и с конца текста, чтобы
    не сдвигать позиции следующих: иначе при двух упоминаниях второе читалось бы не оттуда, а имя
    «5» в «заразить 5 5» заменялось бы в числе патогенов.
    """
    text = message.text or ""
    mentions = [e for e in message.entities or () if e.type == "text_mention" and e.user is not None]
    if not mentions:
        return text
    encoded = text.encode("utf-16-le")
    for entity in sorted(mentions, key=lambda e: e.offset, reverse=True):
        start, end = entity.offset * 2, (entity.offset + entity.length) * 2
        encoded = encoded[:start] + f"tg://user?id={entity.user.id}".encode("utf-16-le") + encoded[end:]
    return encoded.decode("utf-16-le")


async def resolve_ref(q: Q, ref: TargetRef | None) -> int | None:
    if ref is None:
        return None
    if ref.user_id is not None:
        return ref.user_id
    if ref.username:
        return await users.id_by_username(q, ref.username)
    return None


async def resolve_arg(q: Q, message: Message, token: str | None) -> int | None:
    """Цель для команд вида «.корп принять @user» / «/labinfo 123»: токен → упоминание → ответ.

    Если цель написана, но не распознана (опечатка «@ab»), ответ на сообщение не подставляется:
    иначе команда молча ударила бы по автору того сообщения. Упоминание без username (text_mention)
    остаётся — там в тексте стоит имя, а не @username.
    """
    if token:
        ref = parse_target_token(token)
        if ref is not None:
            return await resolve_ref(q, ref)
    mention = mentioned_user(message)
    if mention is not None:
        return mention.id
    if token:
        return None
    replied = reply_user(message)
    return replied.id if replied is not None else None
