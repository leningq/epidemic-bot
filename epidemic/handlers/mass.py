"""«мф» — массовое заражение «слетевших» жертв с прогрессом и отменой (как в оригинале)."""
from __future__ import annotations

import asyncio
import time

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message

from epidemic import keyboards as kb
from epidemic.db import Database, Row
from epidemic.game import mass
from epidemic.game.infection import ChanceAccumulator
from epidemic.game.settings import GameSettings
from epidemic.handlers.common import cmd
from epidemic.repo import labs, victims
from epidemic.utils.fmt import now_ts
from epidemic.views import mass as view

router = Router(name="mass")

STEP_DELAY_SEC = 0.3      # пауза между целями, как в оригинале
EDIT_EVERY_SEC = 2.0      # прогресс обновляется не чаще раза в 2 секунды

_running: dict[int, bool] = {}   # user_id → идёт ли МФ (False — нажата «Остановить»)


async def _edit(message: Message, text: str, markup=None) -> bool:
    try:
        await message.edit_text(text, reply_markup=markup)
        return True
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
    except TelegramBadRequest:
        pass
    return False


@router.message(cmd(r"мф"))
async def mass_list(message: Message, db: Database) -> None:
    rows = await victims.fallen_targets(db, message.from_user.id, now_ts())
    if not rows:
        await message.answer(view.EMPTY)
        return
    await message.answer(view.fallen_list(rows, 1), reply_markup=kb.mass_list(1, view.total_pages(len(rows))))


async def _run(
    call: CallbackQuery,
    db: Database,
    gs: GameSettings,
    bonus: ChanceAccumulator,
    targets: list[Row],
    shown_total: int,
    page: int | None,
) -> None:
    """Проходит по целям: 1 патоген на цель, прогресс, отмена, итоговый отчёт."""
    user_id = call.from_user.id
    total = len(targets)
    status = await call.message.answer(view.starting(shown_total))
    await _edit(status, view.starting(shown_total), kb.mass_cancel())

    ok: list[tuple[str, int]] = []
    missed: list[str] = []
    fails = spent = processed = 0
    last_edit = 0.0
    progress = view.progress_page if page is not None else view.progress_all
    for idx, target in enumerate(targets, 1):
        if not _running.get(user_id, True):
            await _edit(status, view.STOPPED)
            break
        name = view.target_name(target)
        step = await mass.attempt(db, gs, bonus, user_id, target["victim_id"], now_ts())
        if step.status == mass.NO_PATHOGENS:
            await status.reply(view.NO_PATHOGENS)
            break
        if step.status == mass.STOP:  # лабораторию отключили во время МФ — причина не в патогенах
            await status.reply(view.STOPPED)
            break
        processed = idx  # в отчёт — только цели, по которым действительно была попытка
        if step.status == mass.SKIP:
            fails += 1  # как в оригинале: считается промахом, но в список не попадает
            continue
        spent += 1
        success = step.status == mass.SUCCESS
        if success:
            ok.append((name, step.earn))
        else:
            fails += 1
            missed.append(name)
        if time.monotonic() - last_edit >= EDIT_EVERY_SEC or idx == total:
            text = progress(idx, total, name, step.chance, step.pathogens_left,
                            view.result_line(success, step.earn), len(ok), fails)
            await _edit(status, text, kb.mass_cancel())
            last_edit = time.monotonic()
        await asyncio.sleep(STEP_DELAY_SEC)

    report = (
        view.report_page(page, processed, total, ok, missed, fails, spent) if page is not None
        else view.report_all(processed, total, ok, missed, fails, spent)
    )
    if not await _edit(status, report):
        await call.message.answer(report)


async def _show_page(call: CallbackQuery, db: Database, page: int) -> None:
    rows = await victims.fallen_targets(db, call.from_user.id, now_ts())
    if not rows:
        await call.answer(view.LIST_EMPTY, show_alert=True)
        return
    pages = view.total_pages(len(rows))
    page = min(page, pages)
    try:
        await call.message.edit_text(view.fallen_list(rows, page), reply_markup=kb.mass_list(page, pages))
        await call.answer()
    except TelegramBadRequest:
        await call.answer(view.STALE, show_alert=True)


async def _start(
    call: CallbackQuery, callback_data: kb.MassCb, db: Database, gs: GameSettings, mf_acc: ChanceAccumulator
) -> None:
    rows = await victims.fallen_targets(db, call.from_user.id, now_ts())
    if callback_data.action == "start":
        targets = view.page_rows(rows, callback_data.page)
        if not targets:
            await call.answer(view.PAGE_EMPTY, show_alert=True)
            return
        await call.answer(view.STARTING)
        await _run(call, db, gs, mf_acc, targets, len(targets), callback_data.page)
        return
    # «Заразить ВСЕХ из списка»: как в оригинале, целей не больше, чем готовых патогенов
    if not rows:
        await call.answer(view.ALL_EMPTY, show_alert=True)
        return
    await call.answer(view.starting_all(len(rows)))
    lab = await labs.get(db, call.from_user.id)
    ready = lab["ready_pathogens"] if lab else 0
    await _run(call, db, gs, mf_acc, rows[:max(0, ready)], len(rows), None)


@router.callback_query(kb.MassCb.filter())
async def mass_button(
    call: CallbackQuery, callback_data: kb.MassCb, db: Database, gs: GameSettings, mf_acc: ChanceAccumulator
) -> None:
    # Как в оригинале, кнопки работают для нажавшего: у каждого свой список «слетевших».
    user_id = call.from_user.id
    action = callback_data.action
    if action == "noop" or not isinstance(call.message, Message):
        await call.answer()
        return
    if action == "cancel":
        if user_id in _running:
            _running[user_id] = False
        await call.answer(view.CANCELLING, show_alert=True)
        return
    if action == "page":
        await _show_page(call, db, callback_data.page)
        return
    if user_id in _running:  # второй МФ параллельно не запускаем
        await call.answer()
        return
    _running[user_id] = True  # слот занимается до первого await — двойной клик не запустит второй МФ
    try:
        await _start(call, callback_data, db, gs, mf_acc)
    finally:
        _running.pop(user_id, None)
