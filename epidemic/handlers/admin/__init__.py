from aiogram import Router

from epidemic.handlers.admin import manage, mutes, panel, roles

router = Router(name="admin")
router.include_routers(panel.router, roles.router, manage.router, mutes.router)
