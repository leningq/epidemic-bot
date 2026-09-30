"""Корпорации: права ролей, лимит участников, заявки. Проверки и запись — в одной транзакции."""
from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass

from epidemic.db import Database, Q, Row, Tx
from epidemic.game import constants as C
from epidemic.game.naming import check_name, name_mute_error
from epidemic.repo import corps, labs

OK = "ok"
NO_LAB = "no_lab"
DISABLED = "disabled"
NOT_FOUND = "not_found"
SECRET = "secret"
NOT_IN_CORP = "not_in_corp"
NOT_STAFF = "not_staff"
NOT_LEADER = "not_leader"
ALREADY_MEMBER = "already_member"
LIMIT = "limit"
ALREADY_REQUESTED = "already_requested"
NO_REQUEST = "no_request"
TARGET_HAS_CORP = "target_has_corp"
TARGET_NOT_IN_CORP = "target_not_in_corp"
KICK_RESTRICTED = "kick_restricted"
LEADER_SELF_KICK = "leader_self_kick"
LEADER_CANT_LEAVE = "leader_cant_leave"
NAME_ERROR = "name_error"
ALREADY_ADMIN = "already_admin"
NOT_ADMIN = "not_admin"
BAD_TARGET = "bad_target"

STAFF_ROLES = ("leader", "admin")


@dataclass
class CorpResult:
    status: str
    corp: Row | None = None
    name: str | None = None      # новое название (создание/переименование)
    code: str | None = None      # код вступления новой корпорации
    error: str | None = None     # текст ошибки названия
    reason: str | None = None    # причина отключения лаборатории


def _new_code() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(C.CORP_CODE_LEN))


async def _active_lab(q: Q, user_id: int, now: int) -> CorpResult | None:
    """None — лаборатория есть и активна, иначе результат с ошибкой."""
    lab = await labs.get(q, user_id)
    if lab is None:
        return CorpResult(NO_LAB)
    if labs.is_disabled(lab, now):
        return CorpResult(DISABLED, reason=lab["disabled_reason"])
    return None


async def _staff_corp(q: Q, user_id: int, leader_only: bool = False) -> CorpResult:
    corp = await corps.membership(q, user_id)
    if corp is None:
        return CorpResult(NOT_LEADER if leader_only else NOT_IN_CORP)
    if leader_only and corp["role"] != "leader":
        return CorpResult(NOT_LEADER)
    if not leader_only and corp["role"] not in STAFF_ROLES:
        return CorpResult(NOT_STAFF)
    return CorpResult(OK, corp)


async def visible(q: Q, viewer_id: int, code: str | None) -> CorpResult:
    """Корпорация по коду (с учётом скрытого досье) или своя."""
    if not code:
        corp = await corps.membership(q, viewer_id)
        return CorpResult(OK, corp) if corp else CorpResult(NOT_IN_CORP)
    corp = await corps.by_code(q, code)
    if corp is None:
        return CorpResult(NOT_FOUND)
    if not corp["dossier_open"]:
        own = await corps.membership(q, viewer_id)
        if own is None or own["corp_id"] != corp["corp_id"]:
            return CorpResult(SECRET)
    return CorpResult(OK, corp)


async def create(db: Database, user_id: int, raw_name: str, now: int) -> CorpResult:
    async with db.tx() as t:
        if muted := await name_mute_error(t, user_id, now):
            return CorpResult(NAME_ERROR, error=muted)
        if error := await _active_lab(t, user_id, now):
            return error
        if (own := await corps.membership(t, user_id)) is not None:
            return CorpResult(ALREADY_MEMBER, own)
        name, key, name_error = await check_name(t, "corp", raw_name, None)
        if name_error:
            return CorpResult(NAME_ERROR, error=name_error)
        code = _new_code()
        while await corps.code_exists(t, code):
            code = _new_code()
        await corps.create(t, user_id, name, key, code, now)
        return CorpResult(OK, name=name, code=code)


async def request(db: Database, user_id: int, code: str, now: int) -> CorpResult:
    async with db.tx() as t:
        corp = await corps.by_code(t, code)
        if corp is None:
            return CorpResult(NOT_FOUND)
        if error := await _active_lab(t, user_id, now):
            return error
        if (own := await corps.membership(t, user_id)) is not None:
            return CorpResult(ALREADY_MEMBER, own)
        if await corps.member_count(t, corp["corp_id"]) >= C.CORP_MAX_MEMBERS:
            return CorpResult(LIMIT)
        if await corps.has_request(t, corp["corp_id"], user_id):
            return CorpResult(ALREADY_REQUESTED)
        await corps.add_request(t, corp["corp_id"], user_id, now)
        return CorpResult(OK, corp)


async def _answer_request(t: Tx, staff_id: int, target_id: int) -> CorpResult:
    result = await _staff_corp(t, staff_id)
    if result.status != OK:
        return result
    if not await corps.has_request(t, result.corp["corp_id"], target_id):
        return CorpResult(NO_REQUEST)
    return result


async def accept(db: Database, staff_id: int, target_id: int, now: int) -> CorpResult:
    async with db.tx() as t:
        result = await _answer_request(t, staff_id, target_id)
        if result.status != OK:
            return result
        corp_id = result.corp["corp_id"]
        if await corps.membership(t, target_id) is not None:
            await corps.delete_request(t, corp_id, target_id)
            return CorpResult(TARGET_HAS_CORP)
        if await corps.member_count(t, corp_id) >= C.CORP_MAX_MEMBERS:
            return CorpResult(LIMIT)
        await corps.add_member(t, corp_id, target_id, now)
        return result


async def reject(db: Database, staff_id: int, target_id: int) -> CorpResult:
    async with db.tx() as t:
        result = await _answer_request(t, staff_id, target_id)
        if result.status == OK:
            await corps.delete_request(t, result.corp["corp_id"], target_id)
        return result


async def leave(db: Database, user_id: int) -> CorpResult:
    async with db.tx() as t:
        corp = await corps.membership(t, user_id)
        if corp is None:
            return CorpResult(NOT_IN_CORP)
        if corp["role"] == "leader":
            return CorpResult(LEADER_CANT_LEAVE)
        await corps.remove_member(t, user_id)
        return CorpResult(OK, corp)


async def kick(db: Database, staff_id: int, target_id: int) -> CorpResult:
    async with db.tx() as t:
        result = await _staff_corp(t, staff_id)
        if result.status != OK:
            return result
        corp = result.corp
        if target_id == staff_id:
            return CorpResult(LEADER_SELF_KICK if corp["role"] == "leader" else BAD_TARGET)
        target_role = await corps.member_role(t, corp["corp_id"], target_id)
        if target_role is None:
            return CorpResult(TARGET_NOT_IN_CORP)
        # админ может исключить только рядового участника, лидер — любого, кроме себя
        if target_role == "leader" or (target_role == "admin" and corp["role"] != "leader"):
            return CorpResult(KICK_RESTRICTED)
        await corps.remove_member(t, target_id)
        return result


async def set_admin(db: Database, leader_id: int, target_id: int, promote: bool) -> CorpResult:
    async with db.tx() as t:
        # Так в оригинале (deladd_corporation_admin): при «эпимуте» лидер не может ни назначать,
        # ни снимать соруков. Выглядит странно, но это не ошибка переноса — не убирать без клиента.
        if muted := await name_mute_error(t, leader_id, int(time.time())):
            return CorpResult(NAME_ERROR, error=muted)
        result = await _staff_corp(t, leader_id, leader_only=True)
        if result.status != OK:
            return result
        if target_id == leader_id:
            return CorpResult(BAD_TARGET)
        role = await corps.member_role(t, result.corp["corp_id"], target_id)
        if role is None:
            return CorpResult(TARGET_NOT_IN_CORP)
        if promote and role == "admin":
            return CorpResult(ALREADY_ADMIN)
        if not promote and role != "admin":
            return CorpResult(NOT_ADMIN)
        await corps.set_role(t, target_id, "admin" if promote else "member")
        return result


async def set_dossier(db: Database, leader_id: int, is_open: bool) -> CorpResult:
    async with db.tx() as t:
        result = await _staff_corp(t, leader_id, leader_only=True)
        if result.status == OK:
            await corps.set_dossier(t, result.corp["corp_id"], is_open)
        return result


async def rename(db: Database, staff_id: int, raw_name: str) -> CorpResult:
    async with db.tx() as t:
        if muted := await name_mute_error(t, staff_id, int(time.time())):
            return CorpResult(NAME_ERROR, error=muted)
        result = await _staff_corp(t, staff_id)
        if result.status != OK:
            return result
        name, key, name_error = await check_name(t, "corp", raw_name, result.corp["corp_id"])
        if name_error:
            return CorpResult(NAME_ERROR, error=name_error)
        await corps.rename(t, result.corp["corp_id"], name, key)
        result.name = name
        return result


async def delete(db: Database, leader_id: int) -> CorpResult:
    async with db.tx() as t:
        result = await _staff_corp(t, leader_id, leader_only=True)
        if result.status == OK:
            await corps.delete(t, result.corp["corp_id"])
        return result
