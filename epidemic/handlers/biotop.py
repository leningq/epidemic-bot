"""Биотопы: общий и по чату; постраничный вывод кнопками."""
from __future__ import annotations

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from epidemic import keyboards as kb
from epidemic.db import Database
from epidemic.game import constants as C
from epidemic.handlers.common import PREFIX, cmd
from epidemic.repo import labs
from epidemic.utils.targets import is_group
from epidemic.views import corp as view

router = Router(name="biotop")


async def render(db: Database, kind: str, page: int, chat_id: int, private_user: int | None = None) -> str:
    """Страница биотопа. В личке «биотоп чата» — только сам игрок (как в оригинале)."""
    offset = (page - 1) * C.BIOTOP_PAGE_SIZE
    if kind == "chat" and private_user is not None:
        lab = await labs.get(db, private_user)
        rows = [lab] if lab and page == 1 else []
        return view.biotop(rows, offset + 1, lab["bio_exp"] if lab else 0, chat=True)
    scope = chat_id if kind == "chat" else None
    rows = await labs.biotop(db, offset, C.BIOTOP_PAGE_SIZE, scope)
    return view.biotop(rows, offset + 1, await labs.biotop_total(db, scope), chat=scope is not None)


def _private_user(message: Message) -> int | None:
    return None if is_group(message.chat) else message.from_user.id


async def _send(message: Message, db: Database, kind: str) -> None:
    text = await render(db, kind, 1, message.chat.id, _private_user(message))
    await message.answer(text, reply_markup=kb.biotop_pages(kind, 1, message.from_user.id))


@router.message(cmd(rf"{PREFIX}(?:биотоп|бт)"))
async def biotop_global(message: Message, db: Database) -> None:
    await _send(message, db, "lab")


@router.message(cmd(rf"{PREFIX}(?:биотоп\s+(?:чата|беседы)|бч)"))
async def biotop_chat(message: Message, db: Database) -> None:
    await _send(message, db, "chat")


@router.callback_query(kb.BiotopCb.filter())
async def biotop_page(call: CallbackQuery, callback_data: kb.BiotopCb, db: Database) -> None:
    if call.from_user.id != callback_data.owner:
        await call.answer("❌ Переключать страницы может только тот, кто вызвал команду!", show_alert=True)
        return
    if isinstance(call.message, Message):
        private = None if is_group(call.message.chat) else call.from_user.id
        text = await render(db, callback_data.kind, callback_data.page, call.message.chat.id, private)
        try:
            await call.message.edit_text(
                text, reply_markup=kb.biotop_pages(callback_data.kind, callback_data.page, callback_data.owner)
            )
        except TelegramBadRequest:
            pass  # та же страница — текст не изменился
    await call.answer()
