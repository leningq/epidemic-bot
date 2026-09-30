"""Сборка роутеров. Порядок важен: админские команды — раньше игровых."""
from __future__ import annotations

from aiogram import Router

from epidemic.handlers import admin, biotop, chat, corp, infect, lab, mass, misc, start, upgrade

_root: Router | None = None


def build_router() -> Router:
    """Дерево роутеров собирается один раз (роутеры модулей — синглтоны).

    Привязка к диспетчеру сбрасывается, чтобы тот же корень можно было подключить к новому
    Dispatcher — это нужно тестам, где на каждый сценарий создаётся свой диспетчер.
    """
    global _root
    if _root is None:
        _root = Router(name="root")
        _root.include_routers(
            admin.router,
            start.router,
            upgrade.router,
            lab.router,
            infect.router,
            mass.router,
            biotop.router,
            corp.router,
            chat.router,  # после игровых: РП-фильтр смотрит на первое слово любого сообщения
            misc.router,
        )
    _root._parent_router = None  # noqa: SLF001
    return _root
