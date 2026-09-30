"""Заражение, проверка цели, вакцина, списки жертв и болезней, уведомления «+вирусы»."""
from __future__ import annotations

import re
from collections.abc import Callable

from aiogram import Bot, Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from epidemic import keyboards as kb
from epidemic import texts
from epidemic.config import Config
from epidemic.db import Database
from epidemic.game import constants as C
from epidemic.game import economy, infection, upgrade
from epidemic.game.infection import ChanceAccumulator, InfectResult
from epidemic.game.settings import GameSettings
from epidemic.handlers.common import PREFIX, cmd, safe_send
from epidemic.repo import labs, victims
from epidemic.utils.fmt import now_ts
from epidemic.utils.parse import InfectCommand, parse_infect
from epidemic.utils.targets import reply_user, resolve_arg, resolve_ref, with_mention_as_link
from epidemic.views import infect as view
from epidemic.views import lab as upgrade_view

router = Router(name="infect")

_INFECT_START = re.compile(rf"^{PREFIX}заразить", re.IGNORECASE)

# Ответ атакующему по статусу попытки
_REPLIES: dict[str, Callable[[InfectResult, GameSettings], str]] = {
    infection.SUCCESS: lambda r, gs: view.success(r),
    infection.FAIL: lambda r, gs: view.fail(r),
    infection.NO_LAB: lambda r, gs: texts.NO_INFO_ABOUT_USER,
    infection.VICTIM_NO_LAB: lambda r, gs: texts.NO_INFO_ABOUT_USER,
    infection.NO_TARGET: lambda r, gs: texts.VICTIM_NOT_FOUND,
    infection.VICTIM_BOT: lambda r, gs: view.INFECT_BOT,
    infection.SELF: lambda r, gs: view.SELF_INFECT,
    infection.DISABLED: lambda r, gs: texts.lab_disabled(r.attacker["disabled_reason"]),
    infection.VICTIM_DISABLED: lambda r, gs: view.VICTIM_DISABLED,
    infection.FEVER: lambda r, gs: view.fever(r),
    infection.COOLDOWN: lambda r, gs: view.cooldown(r),
    infection.NO_PATHOGENS: lambda r, gs: view.NO_PATHOGENS,
    infection.GAP: lambda r, gs: view.gap(r, gs.max_gap),
}


class InfectFilter(Filter):
    async def __call__(self, message: Message) -> bool | dict:
        text = message.text or ""
        if not _INFECT_START.match(text):
            return False
        parsed = parse_infect(with_mention_as_link(message))
        return {"infect_cmd": parsed} if parsed else False


async def run_infection(
    answer_to: Message,
    bot: Bot,
    db: Database,
    gs: GameSettings,
    acc: ChanceAccumulator,
    attacker_id: int,
    target_id: int | None,
    count: int,
    mode: str | None = None,
) -> InfectResult:
    if target_id == bot.id:
        r = InfectResult(infection.VICTIM_BOT)
    else:
        r = await infection.attempt(db, gs, acc, attacker_id, target_id, count, now_ts(), mode=mode)
    # как в оригинале: под провалом — повтор с 1/5/9 патогенами и прокачка заразности
    markup = kb.infect_fail(r.victim["user_id"], attacker_id) if r.status == infection.FAIL else None
    await answer_to.answer(_REPLIES[r.status](r, gs), reply_markup=markup)
    if r.notify_victim:
        chat_id = r.victim["notify_chat_id"]
        if chat_id and chat_id != answer_to.chat.id:
            await safe_send(bot, chat_id, view.victim_notice(r))
    return r


@router.message(InfectFilter())
async def infect_command(
    message: Message,
    infect_cmd: InfectCommand,
    bot: Bot,
    db: Database,
    gs: GameSettings,
    acc: ChanceAccumulator,
) -> None:
    target_id: int | None = None
    if infect_cmd.target is not None:
        target_id = await resolve_ref(db, infect_cmd.target)
        if target_id is None:
            await message.answer(texts.NO_INFO_ABOUT_USER)
            return
    elif infect_cmd.mode is None:
        replied = reply_user(message)
        if replied is None:
            return  # как в оригинале: «заразить» без цели и без ответа — не команда
        target_id = replied.id
    await run_infection(
        message, bot, db, gs, acc, message.from_user.id, target_id, infect_cmd.count, mode=infect_cmd.mode
    )


# --- Проверка цели ---

@router.message(cmd(rf"{PREFIX}(?:чек|ч)(?:\s+(?P<target>\S+))?"))
async def check_victim(message: Message, m: re.Match, bot: Bot, db: Database) -> None:
    owner_id = message.from_user.id
    target_id = await resolve_arg(db, message, m.group("target"))
    if target_id is None or target_id in (owner_id, bot.id):
        return
    record = await victims.get(db, owner_id, target_id)
    await message.reply(view.check_card(target_id, record), reply_markup=kb.infect_target(target_id, owner_id))


@router.callback_query(kb.InfectCb.filter())
async def infect_button(
    call: CallbackQuery,
    callback_data: kb.InfectCb,
    bot: Bot,
    db: Database,
    gs: GameSettings,
    acc: ChanceAccumulator,
) -> None:
    if call.from_user.id != callback_data.owner:
        await call.answer(texts.not_your_button())
        return
    await call.answer()
    if isinstance(call.message, Message):
        await run_infection(call.message, bot, db, gs, acc, call.from_user.id, callback_data.target, 1)


@router.callback_query(kb.FailCb.filter())
async def infect_fail_button(
    call: CallbackQuery,
    callback_data: kb.FailCb,
    bot: Bot,
    db: Database,
    gs: GameSettings,
    acc: ChanceAccumulator,
) -> None:
    data = callback_data
    if call.from_user.id != data.owner:
        await call.answer("❌ Это не твоя кнопка!", show_alert=True)
        return
    if not isinstance(call.message, Message):
        await call.answer()
        return
    if data.action == "repeat":
        await call.answer(f"🔁 Повтор: {data.n} пат. → цель {data.target}")
        await run_infection(call.message, bot, db, gs, acc, data.owner, data.target, data.n)
        return
    await call.answer(f"🎯 Прокачка +{data.n} ЗЗ")
    quote = await upgrade.quote(db, gs, data.owner, "infect", data.n, now_ts())
    if quote.status in (upgrade.OK, upgrade.NOT_ENOUGH):
        await call.message.reply(upgrade_view.upgrade_preview(quote), reply_markup=kb.upgrade_confirm("infect", data.n, data.owner))
    elif quote.status == upgrade.DISABLED:
        await call.message.reply(texts.lab_disabled(quote.reason))


@router.message(cmd(r"мж\s+топ|топ\s+мж|жертвы\s+топ"))
async def top_victims(message: Message, db: Database) -> None:
    rows = await victims.top_income(db, message.from_user.id)
    await message.answer(view.top_income(rows, now_ts()))


# --- Вакцина ---

@router.message(cmd(rf"{PREFIX}(?:купить\s+вакцину|кв)"))
async def buy_vaccine(message: Message, db: Database) -> None:
    status, price = await infection.buy_vaccine(db, message.from_user.id, now_ts())
    await message.answer({
        infection.SUCCESS: view.vaccine_done(price),
        "healthy": view.HAVE_NOT_FEVER,
        "not_enough": view.vaccine_not_enough(price),
    }.get(status, texts.NO_INFO_ABOUT_USER))


@router.message(cmd(rf"{PREFIX}курить\s+вакцину"))
async def smoke_vaccine(message: Message) -> None:
    await message.answer(texts.SMOKE_VACCINE)


# --- Списки ---

@router.message(cmd(rf"{PREFIX}(?:мои\s+жертвы|мж)"))
async def my_victims(message: Message, db: Database, gs: GameSettings, config: Config) -> None:
    owner_id, now = message.from_user.id, now_ts()
    rows = await victims.list_owned(db, owner_id, now, C.LIST_LIMIT)
    total, exp_sum, premium = await economy.expected_premium(db, gs, owner_id, now)
    await message.answer(view.victims_list(rows, total, exp_sum, premium, config.tz))


@router.message(cmd(rf"{PREFIX}(?:мои\s+болезни|мб|кто\s+заразил|заразившие)"))
async def my_illnesses(message: Message, db: Database, config: Config) -> None:
    rows = await victims.list_illnesses(db, message.from_user.id, now_ts(), C.LIST_LIMIT)
    await message.answer(view.illnesses_list(rows, config.tz))


# --- Уведомления ---

@router.message(cmd(r"\+вирусы(?:\s+(?P<pm>лс))?"))
async def virus_signal_on(message: Message, m: re.Match, db: Database) -> None:
    chat_id = message.from_user.id if m.group("pm") else message.chat.id
    await labs.set_fields(db, message.from_user.id, notify_chat_id=chat_id)
    await message.answer(view.VIRUS_SIGNAL_ON)


@router.message(cmd(r"-вирусы"))
async def virus_signal_off(message: Message, db: Database) -> None:
    await labs.set_fields(db, message.from_user.id, notify_chat_id=None)
    await message.answer(view.VIRUS_SIGNAL_OFF)
