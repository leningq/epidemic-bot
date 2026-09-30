"""Прокачка навыков: «+навык [N]» (цена), «++навык [N]» (сразу), «-навык N» (понижение), кнопки.

Поведение как в оригинале: на команду бот отвечает reply; уровень за раз молча ограничивается 1..50;
кнопка «Подтвердить улучшение» и 1x/3x/5x редактируют сообщение.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from epidemic import keyboards as kb
from epidemic import texts
from epidemic.db import Database
from epidemic.game import constants as C
from epidemic.game import upgrade
from epidemic.game.settings import GameSettings
from epidemic.utils.fmt import now_ts
from epidemic.utils.parse import SkillCommand, parse_skill_command
from epidemic.views import lab as view

router = Router(name="upgrade")


class SkillCommandFilter(Filter):
    async def __call__(self, message: Message) -> bool | dict:
        parsed = parse_skill_command(message.text or "")
        return {"skill_cmd": parsed} if parsed else False


def _status_text(status: str, skill: str, reason: str | None = None) -> str:
    return {
        upgrade.NO_LAB: texts.NO_INFO_ABOUT_USER,
        upgrade.DISABLED: texts.lab_disabled(reason),
        upgrade.MAX_LEVEL: view.max_level(skill),
        upgrade.NOT_ENOUGH: texts.NOT_ENOUGH_RESOURCES,
    }.get(status, texts.BUTTON_OUTDATED)


def _clamp(levels: int | None) -> int:
    """Как в оригинале: без числа — 1 уровень, больше 50 — молча 50."""
    return max(1, min(C.MAX_LEVELS_PER_UPGRADE, levels or 1))


@router.message(SkillCommandFilter())
async def skill_command(message: Message, skill_cmd: SkillCommand, db: Database, gs: GameSettings) -> None:
    user_id, skill, now = message.from_user.id, skill_cmd.skill, now_ts()

    if skill_cmd.op == "-":
        if skill_cmd.levels is None:
            await message.reply(view.DOWNGRADE_USAGE)
            return
        result = await upgrade.downgrade(db, gs, user_id, skill, skill_cmd.levels, now)
        if result.status == upgrade.OK:
            await message.reply(view.downgrade_done(result))
        elif result.status == upgrade.MIN_LEVEL:
            await message.reply(view.downgrade_min(result))
        elif result.status == upgrade.TOO_MANY:
            await message.reply("❌ Число должно быть больше 0")
        else:
            await message.reply(_status_text(result.status, skill, result.reason))
        return

    levels = _clamp(skill_cmd.levels)
    if skill_cmd.op == "+":
        quote = await upgrade.quote(db, gs, user_id, skill, levels, now)
        if quote.status in (upgrade.OK, upgrade.NOT_ENOUGH):
            await message.reply(view.upgrade_preview(quote), reply_markup=kb.upgrade_confirm(skill, levels, user_id))
        else:
            await message.reply(_status_text(quote.status, skill, quote.reason))
        return

    result = await upgrade.apply(db, gs, user_id, skill, levels, now)
    if result.status == upgrade.OK:
        await message.reply(view.upgrade_done(result), reply_markup=kb.upgrade_more(skill, user_id))
    else:
        await message.reply(_status_text(result.status, skill, result.reason))


@router.callback_query(kb.UpgradeCb.filter())
async def upgrade_button(call: CallbackQuery, callback_data: kb.UpgradeCb, db: Database, gs: GameSettings) -> None:
    data = callback_data
    if call.from_user.id != data.owner:
        await call.answer(texts.not_your_button())
        return
    message = call.message
    if not isinstance(message, Message):
        await call.answer(texts.BUTTON_OUTDATED)
        return
    now = now_ts()

    if data.action == "open":  # кнопка под досье — цена +1 уровня новым сообщением
        quote = await upgrade.quote(db, gs, data.owner, data.skill, data.levels, now)
        if quote.status in (upgrade.OK, upgrade.NOT_ENOUGH):
            await message.answer(view.upgrade_preview(quote), reply_markup=kb.upgrade_confirm(data.skill, data.levels, data.owner))
        else:
            await message.answer(_status_text(quote.status, data.skill, quote.reason))
        await call.answer()
        return

    result = await upgrade.apply(db, gs, data.owner, data.skill, data.levels, now)
    if result.status == upgrade.OK:
        await message.edit_text(view.upgrade_done(result), reply_markup=kb.upgrade_more(data.skill, data.owner))
        await call.answer(view.upgrade_toast(data.levels) if data.action == "more" else None)
    elif result.status == upgrade.NOT_ENOUGH and data.action == "confirm":
        # оригинал: при нехватке ресурсов сообщение с ценой превращается в «нет столько био-ресурсов»
        await message.edit_text(texts.NOT_ENOUGH_RESOURCES, reply_markup=kb.upgrade_more(data.skill, data.owner))
        await call.answer()
    else:
        await message.answer(_status_text(result.status, data.skill, result.reason))
        await call.answer()
