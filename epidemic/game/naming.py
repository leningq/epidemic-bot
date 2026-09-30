"""Проверка игровых названий: формат, запрет администрацией, уникальность."""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from html import escape

from epidemic.db import Database, Q, Tx
from epidemic.repo import admin as admin_repo
from epidemic.repo import corps, labs
from epidemic.utils import names

NAME_MUTED = "📕 У вас мут на изменения игровых наименований на {} дней"


async def name_mute_error(q: Q, user_id: int, now: int) -> str | None:
    """Текст оригинала, если игроку запрещено менять игровые названия («эпимут»)."""
    mute = await admin_repo.active_sanction(q, user_id, "name_mute", now)
    if mute is None:
        return None
    days = (mute["expires_at"] - now) // 86400 if mute["expires_at"] else 9999
    return NAME_MUTED.format(days)


TAKEN = {
    "lab": "📝 Это название лаборатории уже занято",
    "pathogen": "📝 Это имя патогена уже занято",
    "corp": "📝 Это имя корпорации уже занято",
}


async def check_name(
    q: Q, kind: str, raw: str, holder_id: int | None, strict: bool = True
) -> tuple[str | None, str | None, str | None]:
    """Возвращает (название, ключ, ошибка).

    holder_id — кто может сохранить название за собой (ID лаборатории или corp_id).
    strict=False — для администраторов: без проверки символов и запретов, только длина и уникальность.
    """
    name = names.normalize(raw)
    error = names.validate(kind, name, charset=strict)
    if error:
        return None, None, f"📝 {error}"
    key = names.name_key(name)
    if strict:
        ban = await admin_repo.banned_name(q, kind, key)
        if ban is not None:
            return None, None, f"🚫 Это название запрещено администрацией. Причина: {escape(ban['reason'])}"
    holder = await (corps.name_owner(q, key) if kind == "corp" else labs.name_owner(q, kind, key))
    if holder is not None and holder != holder_id:
        return None, None, TAKEN[kind]
    return name, key, None


async def claim_lab_name(
    db: Database,
    user_id: int,
    kind: str,
    raw: str,
    strict: bool = True,
    on_claim: Callable[[Tx, str], Awaitable[None]] | None = None,
) -> tuple[str | None, str | None]:
    """Проверяет и сохраняет название лаборатории/патогена в одной транзакции. Возвращает (название, ошибка).

    on_claim(t, название) вызывается в той же транзакции — для записи в журнал админа.
    """
    async with db.tx() as t:
        if strict and (muted := await name_mute_error(t, user_id, int(time.time()))):
            return None, muted
        name, key, error = await check_name(t, kind, raw, user_id, strict)
        if error:
            return None, error
        await labs.set_name(t, user_id, kind, name, key)
        if on_claim is not None:
            await on_claim(t, name)
        return name, None


def fallback_corp_name(corp_id: int) -> tuple[str, str]:
    """Название корпорации, когда исходное запрещено или занято."""
    name = f"Корпорация {corp_id}"
    return name, names.name_key(name)
