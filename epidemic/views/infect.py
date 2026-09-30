"""Сообщения заражения, горячки, вакцины и списков — дословно по оригиналу «Эпидемик 2.0»."""
from __future__ import annotations

import time
from html import escape
from zoneinfo import ZoneInfo

from epidemic.db import Row
from epidemic.game import infection
from epidemic.game.infection import InfectResult
from epidemic.repo.labs import display_name
from epidemic.utils.fmt import chance, comma, date, join_limited, mention, num, ref_hm, ref_hms, user_link


def pathogen_phrase(name: str | None) -> str:
    """Как в оригинале: «Чума» в кавычках, без названия — «неизвестным патогеном»."""
    return f"«{escape(name)}»" if name else "неизвестным патогеном"


def _victim_new(earn: int) -> str:
    return (
        "✨<i> Жертва заражена новой мутацией вируса, это принесло вам ценные генетические данные "
        f"и последующую прибыль от исследований <b>+{comma(earn)}</b> био-ресурса</i>"
    )


def _hidden_victim_link(victim: Row) -> str:
    """Невидимая ссылка на жертву (по ней юзерботы записывают жертв, как в оригинале)."""
    href = f"https://t.me/{victim['username']}" if victim["username"] else f"tg://openmessage?user_id={victim['user_id']}"
    return f'<a href="{href}">‎ </a>'


def success(r: InfectResult) -> str:
    a, v = r.attacker, r.victim
    text = (
        f"🦠 {mention(a['user_id'], a['full_name'])} подверг заражению патогеном "
        f"{pathogen_phrase(a['pathogen_name'])} {mention(v['user_id'], v['full_name'])}\n"
        f"☠️ Горячка на {r.fever_minutes} минут\n"
        f"🤒 Заражение на {r.days} дней\n"
        f"☣️ +{comma(r.earn)} био-опыта{_hidden_victim_link(v)}"
    )
    return text + (f"\n\n{_victim_new(r.earn)}" if r.is_new else "")


def _security_header(r: InfectResult, attempt_word: str) -> str:
    a, v = r.attacker, r.victim
    return (
        f"🕵️‍♂️ Служба безопасности лаборатории {mention(v['user_id'], v['full_name'])} докладывает:\n"
        f"Была произведена как минимум {r.spent} попытка {attempt_word} заражения\n"
        f"Организатор заражения: {mention(a['user_id'], a['full_name'])}\n\n"
    )


def victim_notice(r: InfectResult) -> str:
    """Уведомление жертве. С именем атакующего — только если СБ жертвы выше."""
    a, v = r.attacker, r.victim
    if r.status == infection.FAIL:
        return _security_header(r, "Вашего") + (
            f"🥽 Иммунитет объекта «{user_link(v['user_id'], v['full_name'])}» оказался стойким к вашему патогену.\n"
            "Антитела смогли справиться с заражением."
        )
    if r.ss_detect:
        text = _security_header(r, "вашего") + (
            f"🦠 {mention(a['user_id'], a['full_name'])} подверг заражению патогеном "
            f"{pathogen_phrase(a['pathogen_name'])} {user_link(v['user_id'], v['full_name'])}\n"
            f"☠️ Горячка на {r.fever_minutes} минут\n"
            f"🤒 Заражение на {r.days} дней\n"
            f"☣️ +{comma(r.earn)} био-опыта"
        )
        return text + (f"\n\n{_victim_new(r.earn)}" if r.is_new else "")
    return (
        f"🦠 Кто-то подверг заражению {pathogen_phrase(a['pathogen_name'])} {user_link(v['user_id'], v['full_name'])}\n"
        f"☠️ Горячка на {r.fever_minutes} минут\n"
        f"🤒 Заражение на {r.days} дней"
    )


def fail(r: InfectResult) -> str:
    v = r.victim
    return (
        f"🪬 Иммунитет объекта «{mention(v['user_id'], v['full_name'])}» оказался стойким к вашему патогену.\n"
        "Антитела смогли справиться с заражением.\n"
        f"🧪 Осталось патогенов: {r.pathogens_left}\n"
        f" Шкала пробития: {chance(r.chance)}% "
    )


def fever(r: InfectResult) -> str:
    return (
        f"🤒 У вас горячка, вызванная {pathogen_phrase(r.attacker['fever_pathogen'])} "
        "Придётся отлежаться, пока не пройдёт\n"
        f"Время выздоровления {ref_hms(r.wait)}\n\n"
        "💉 Для быстрого выздоровления нужно купить вакцину: ☣️, команда «<code>!купить вакцину</code>»"
    )


def cooldown(r: InfectResult) -> str:
    return (
        "🤒 Недавно Вы уже подвергали заражению выбранный объект.\n"
        f"⏱ Следующая возможность появится через {ref_hm(r.wait)}"
    )


def gap(r: InfectResult, max_gap: int) -> str:
    return (
        f"❌ Вы не можете пробить, ведь у вас большая разница ({r.gap}).\n"
        f"Бить сможете, когда разница будет меньше {max_gap + 1}."
    )


NO_PATHOGENS = "📝 Недостаточно патогенов для заражения жертвы"
SELF_INFECT = (
    "📝 Вы стремились к эксперименту на пределе, допустимости, но ваш организм решил, что вместо этого "
    "будет заняться более увлекательными занятиями, такими как выживание, например."
)
INFECT_BOT = "📝 Попробуйте заразить сущность умеющую дышать"
VICTIM_DISABLED = "📝 Лаборатория этого объекта отключена администрацией"
HAVE_NOT_FEVER = "<b>❤️‍🩹 Вы здоровы.</b> Нет горячки — нет нужды в вакцине."


def vaccine_done(price: int) -> str:
    return (
        "<blockquote>💉 <b>Вы излечились от горячки.</b>\n"
        f"🧬 <b>Затраты на лечение:</b> {comma(price)} био-ресурсов</blockquote>"
    )


def vaccine_not_enough(price: int) -> str:
    return f"❌ Недостаточно био-ресурсов! Нужно <b>{comma(price)}</b> 🧬"


VIRUS_SIGNAL_ON = "✅ Локация для уведомлений о вирусных атаках установлена"
VIRUS_SIGNAL_OFF = "❎ Вы отключили оповещения вирусов от Эпидемик"


def victims_list(rows: list[Row], total: int, exp_sum: int, premium: int, tz: ZoneInfo) -> str:
    lines = [
        f"{i}. {mention(r['victim_id'], display_name(r))} | +{comma(r['earn'])} | до {date(r['expires_at'], tz)}"
        for i, r in enumerate(rows, 1)
    ]
    body = join_limited(lines) if lines else "\nУ вас пока нет жертв\n"
    return (
        f"💉 Список больных вашим патогеном:\n{body}\n\n"
        f"📊 Итого: {total} заражённых и {exp_sum} био-опыта\n"
        f"🧬 Ежедневная премия: {comma(premium)} био-ресурсов"
    )


def illnesses_list(rows: list[Row], tz: ZoneInfo) -> str:
    lines = []
    for i, r in enumerate(rows, 1):
        # название видно всем, а ссылка на атакующего — только если служба безопасности его вычислила
        name = f"«{r['pathogen_name']}»" if r["pathogen_name"] else "неизвестным патогеном"
        title = mention(r["owner_id"], name) if r["ss_detect"] else escape(name)
        lines.append(f"{i}. {title} | до {date(r['expires_at'], tz)}")
    return "🤒 Список ваших болезней:\n" + join_limited(lines)


def top_income(rows: list[Row], now: int) -> str:
    """«мж топ» — как в оригинале."""
    if not rows:
        return "📭 У вас нет жертв, которые приносят доход!"
    medals = ("🥇", "🥈", "🥉")
    lines = ["📊 <b>ТОП ЖЕРТВ ПО ДОХОДУ</b>\n"]
    for i, r in enumerate(rows, 1):
        left = r["expires_at"] - now
        if left <= 0:
            expire = "⚠️"
        elif left < 86400:
            expire = f"⏳ {left // 3600}ч {(left % 3600) // 60}м"
        else:
            expire = f"⏳ {left // 86400}д"
        prefix = medals[i - 1] if i <= len(medals) else f"{i}."
        name = r["full_name"] or f"ID {r['victim_id']}"
        lines.append(f"{prefix} {mention(r['victim_id'], name)} — <b>{comma(r['earn'])}</b> био/тик {expire}")
    return "\n".join(lines)


def check_card(target_id: int, record: Row | None) -> str:
    """Карточка «чек» — как в оригинале."""
    earn = record["earn"] if record else 0
    left = (record["expires_at"] - int(time.time())) if record else 0
    if left <= 0:
        time_str = "Срок истек или не заражен"
    else:
        days, rest = divmod(left, 86400)
        hours, rest = divmod(rest, 3600)
        parts = [f"{days}д"] if days else []
        if hours or days:
            parts.append(f"{hours}ч")
        parts.append(f"{rest // 60}м")
        time_str = " ".join(parts)
    return (
        f"🧬 Жертва: <a href='tg://openmessage?user_id={target_id}'>ссылка на игрока</a>\n"
        f"💰 Приносит: {num(earn)} био-ресурсов.\n"
        f"⏳ Осталось: {time_str}."
    )
