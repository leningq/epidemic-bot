"""Сообщения корпораций и биотопов — дословно по оригиналу «Эпидемик 2.0»."""
from __future__ import annotations

from html import escape

from epidemic import texts
from epidemic.db import Row
from epidemic.game import corps as svc
from epidemic.repo.labs import display_name
from epidemic.utils.fmt import comma, join_limited, mention


def card(corp: Row, leader: Row, leader_infected: int, exp: int, infected: int, labs: int) -> str:
    return (
        f"🔆 КОРПОРАЦИЯ «{escape(corp['name'])}» \n"
        f"<b>Руководитель:</b> {mention(leader['user_id'], leader['full_name'])} "
        f"☣️ {comma(leader['bio_exp'])} | {leader_infected}\n"
        "<b>———[ СТАТИСТИКА ]———</b>\n"
        f"«☣️» Био-опыт: {comma(exp)}\n"
        f"«🤒» Заражённых: {infected}\n"
        f"«🚸» Лабораторий: {labs}\n"
        "<b>——————————————</b>\n"
        f"<b>Код вступления:</b> <code>{corp['code']}</code>\n"
        f"<b>Досье корпорации:</b> {'открыто' if corp['dossier_open'] else 'засекречено'}"
    )


def _people(rows: list[Row]) -> str:
    return join_limited([
        f"{i}. {mention(r['user_id'], r['full_name'])} | {comma(r['bio_exp'])} опыт" for i, r in enumerate(rows, 1)
    ])


def members(corp: Row, rows: list[Row]) -> str:
    return f"🏢 УЧАСТНИКИ КОРПОРАЦИИ «{escape(corp['name'])}»\n{_people(rows)}"


def requests(corp: Row, rows: list[Row]) -> str:
    return f"🗓 Список заявок в корпорацию «{escape(corp['name'])}»\n{_people(rows)}"


def staff(corp: Row, rows: list[Row]) -> str:
    lines = [f"{i}. ⭐️ {mention(r['user_id'], r['full_name'])}" for i, r in enumerate(rows, 1)]
    return f"🗓 Соучредители корпорации «{escape(corp['name'])}»\n" + "\n".join(lines)


def created(name: str, code: str) -> str:
    return (
        f"✅ Поздравляем! Ваша корпорация <b>«{escape(name)}»</b> создана!\n\n"
        "<blockquote>— Желающие могут вступить, попросив владельца корпорации открыть <i>.корп</i> "
        "нажав на кнопку вступления</blockquote>\n"
        f"<b>🧩 Либо, используя команду «<code>+корп {code}</code>»</b>"
    )


def top(rows: list[Row]) -> str:
    lines = [f"{i}. {mention(r['leader_id'], r['name'])} | {comma(r['exp'])} опыт" for i, r in enumerate(rows, 1)]
    return "🌸 <b>Топ Корпораций по заражениям:</b>\n\n" + "\n".join(lines)


def biotop(rows: list[Row], start: int, total: int, chat: bool) -> str:
    title = "Топ Лабораторий чата по Био-опыту:" if chat else "Топ Лабораторий по био-опыту:"
    lines = [
        f"{start + i}. {mention(r['user_id'], display_name(r))} | {comma(r['bio_exp'])} опыт"
        for i, r in enumerate(rows)
    ]
    return f"🌸 <b>{title}</b>\n\n" + "\n".join(lines) + f"\n\nСуммарный био-опыт: {comma(total)}"


def already_in_corp(code: str, who: str | None = None) -> str:
    prefix = f"📝 {who} " if who else "📝 "
    return (
        f"{prefix}Вы уже создали свою Корпорацию.\n\n"
        f'💬 Руководители других Лабораторий могут вступать в неё командой "+корп {code}"'
    )


def request_sent(who: str, corp_name: str) -> str:
    return f"💚 {who}, вы подали заявку на вступление в корпорацию <b>«{escape(corp_name)}»</b>!"


def accepted(who: str) -> str:
    return (
        f"{who} Принят в корпорацию, наши поздравления, мы будем гордиться иметь вас в нашей корпорации. "
        "Добро пожаловать! 😇🥰"
    )


def accepted_pm(corp_name: str) -> str:
    return f"Поздравляем, вашу заявку в корпорацию {escape(corp_name)} приняли. Добро пожаловать! 😇🥰"


def left(corp_name: str) -> str:
    return f"❎ Ваша Лаборатория вышла из состава корпорации «{escape(corp_name)}»"


def kicked(who: str, corp_link: str) -> str:
    return f"❎ Лаборатория «{who}» исключена из корпорации «{corp_link}»"


def renamed(name: str) -> str:
    return f"✅ Название корпорации «{escape(name)}» обновлено"


def deleted(name: str) -> str:
    return f"❌ Корпорация <b>«{escape(name)}»</b> прекращает своё существование."


def admin_added(who: str) -> str:
    return f"✅ {who} назначен соучредителем Корпорации"


def admin_removed(who: str) -> str:
    return f"❎ {who} разжалован из соучредителей корпорации"


def already_admin(who: str) -> str:
    return f"📝 {who} уже является соучредителем Корпорации"


def not_admin(who: str) -> str:
    return f"📝 {who} не являлся соучредителем корпорации"


def button_pressed(who: str) -> str:
    return f"📝 {who} Активировал кнопку"


LAB_NOT_IN_CORP = "📝 Ваша Лаборатория не состоит ни в одной Корпорации"
NOT_IN_YOUR_CORP = "📝 Лаборатория не состояла в вашей Корпорации"
TARGET_HAS_CORP = "📝 Лаборатория уже находится в чужой Корпорации"
NOT_LEADER = "📝 Вы не являетесь главой ни одной Корпорации"
NOT_STAFF = "📝 Вы не являетесь главой или соучредителем ни одной корпорации"
CORP_NOT_FOUND = "📝 Такой Корпорации не существует"
ALREADY_REQUESTED = "📝 Вы уже подавали заявку на вступление в эту Корпорацию"
NO_REQUEST = "📝 Лаборатория не подавала заявку на вступление в вашу Корпорацию"
MEMBER_LIMIT = "📝 Достигнут максимальный лимит членов корпорации"
LEADER_CANT_LEAVE = "<b>🔻 Вы — владелец.</b> Покинуть корпорацию невозможно."
LEADER_SELF_KICK = "📝 Основатель корпорации не способен исключить себя из состава – это, пожалуй, слишком радикальный шаг."
KICK_RESTRICTED = "📝 Нельзя исключить админа одинакового или выше вас рангом из корпорации"
REQUEST_REJECTED = '❎ Ваш талант слишком уникален для нашей скромной компании, извините."'
DOSSIER_OPENED = "✅ Информация о вашей Корпорации теперь доступна для просмотра всем"
DOSSIER_HIDDEN = "❎ Информация о вашей Корпорации засекречена"
NAME_USAGE = "📝 Укажите название: <code>.корп создать Название</code>"
JOIN_USAGE = "📝 Укажите код Корпорации: <code>+корп код</code> (латинские буквы и цифры, например <code>+корп a1b2c3</code>)"
TARGET_USAGE = "📝 Укажите лабораторию: ответом на сообщение, @username или ID"


def status_text(result: svc.CorpResult, who: str | None = None) -> str:
    """Текст для статуса операции game/corps. who — упоминание игрока (для текстов «📝 {игрок} …»)."""
    if result.status == svc.DISABLED:
        return texts.lab_disabled(result.reason)
    if result.status == svc.NAME_ERROR:
        return result.error
    if result.status == svc.ALREADY_MEMBER and result.corp is not None:
        return already_in_corp(result.corp["code"], who)
    if result.status == svc.SECRET:
        return f"📝 {who} Информация о Корпорации засекречена" if who else "📝 Информация о Корпорации засекречена"
    if result.status == svc.NOT_FOUND and who:
        return f"📝 {who} Такой Корпорации не существует"
    return {
        svc.NO_LAB: texts.NO_INFO_ABOUT_USER,
        svc.NOT_FOUND: CORP_NOT_FOUND,
        svc.NOT_IN_CORP: LAB_NOT_IN_CORP,
        svc.NOT_STAFF: NOT_STAFF,
        svc.NOT_LEADER: NOT_LEADER,
        svc.LIMIT: MEMBER_LIMIT,
        svc.ALREADY_REQUESTED: ALREADY_REQUESTED,
        svc.NO_REQUEST: NO_REQUEST,
        svc.TARGET_HAS_CORP: TARGET_HAS_CORP,
        svc.TARGET_NOT_IN_CORP: NOT_IN_YOUR_CORP,
        svc.KICK_RESTRICTED: KICK_RESTRICTED,
        svc.LEADER_SELF_KICK: LEADER_SELF_KICK,
        svc.LEADER_CANT_LEAVE: LEADER_CANT_LEAVE,
        svc.BAD_TARGET: TARGET_USAGE,
    }.get(result.status, texts.BUTTON_OUTDATED)
