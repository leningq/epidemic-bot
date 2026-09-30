"""Досье лаборатории и сообщения прокачки — дословно по оригиналу «Эпидемик 2.0»."""
from __future__ import annotations

from html import escape

from epidemic.db import Row
from epidemic.game import constants as C
from epidemic.game import formulas as F
from epidemic.game.settings import GameSettings
from epidemic.game.upgrade import Downgrade, Quote
from epidemic.repo.labs import display_name, fever_left
from epidemic.utils.fmt import comma, mention, num, ref_hms


def _plus(lab: Row, skill: str, gs: GameSettings) -> str:
    n = F.affordable_levels(skill, lab[skill], lab["bio_res"], gs.cost_pct)
    return f" (+{n})" if n else ""


def pathogen_title(lab: Row) -> str:
    return escape(lab["pathogen_name"]) if lab["pathogen_name"] else "засекречено"


def dossier(lab: Row, corp: Row | None, infected: int, illnesses: int, gs: GameSettings, now: int) -> str:
    emoji = escape(lab["emoji"]) if lab["emoji"] else ""
    lethality = lab["lethality"]
    corp_text = f"В составе Корпорации — «{mention(corp['leader_id'], corp['name'])}»\n\n" if corp else "\n"
    new_pathogen = "\n"
    if lab["science_time"] and lab["ready_pathogens"] < lab["pathogens"]:
        new_pathogen = f"<i>⏳ Новый патоген через {ref_hms(lab['science_time'] - now)}</i>\n\n"
    fever = fever_left(lab, now)
    fever_line = f"😓 Ученый в состоянии горячки ещё {ref_hms(fever)}" if fever else ""
    return (
        f"<b>📩 Досье лаборатории {escape(display_name(lab))}:</b>\n"
        f"Руководитель — {mention(lab['user_id'], lab['full_name'])} {emoji}\n"
        f"{corp_text}"
        f"🏷 <b>Имя патогена:</b> {pathogen_title(lab)}\n"
        f"🧪 <b>Готовых патогенов:</b> {lab['ready_pathogens']}/{lab['pathogens']}{_plus(lab, 'pathogens', gs)}\n"
        f"🧑‍🎤 <b>Квалификация учёных:</b> {lab['science']} ур "
        f"({F.science_minutes(lab['science'])} мин.){_plus(lab, 'science', gs)}\n"
        f"{new_pathogen}"
        "<blockquote><b>——[ Характеристика]——</b>\n"
        f"💉 Заразность: {lab['infect']} ур{_plus(lab, 'infect', gs)}\n"
        f"🪬 Иммунитет: {lab['immunity']} ур{_plus(lab, 'immunity', gs)}\n"
        f"💊 Летальность: {lethality} ур ({F.dossier_fever_minutes(lethality, gs.fever_pct)} мин | {lethality} дн)"
        f"{_plus(lab, 'lethality', gs)}\n"
        f"🕵️‍♂️ Служба безопасности: {lab['security']} ур{_plus(lab, 'security', gs)}</blockquote>\n"
        "<b>——————————————</b>\n"
        f"ID лаборатории: <code>{lab['user_id']}</code>\n"
        "<b>——————————————</b>\n"
        "<blockquote><b>—[Запасы — реагентов]—</b>\n"
        f"☣️ Опыт: {num(lab['bio_exp'])}\n"
        f"🧬 Ресурсы: {num(lab['bio_res'])}\n"
        "⏱ <i>Ежедневная премия через: Каждый день в 12.00 и 00.00</i>\n"
        f"{fever_line}</blockquote>\n"
        f"🤒 Заражённых: {infected}\n"
        f"😷 Своих болезней: {illnesses}\n\n"
    )


def mini(lab: Row, corp: Row | None) -> str:
    corp_text = mention(corp["leader_id"], corp["name"]) if corp else "Нет корпорации"
    return (
        "<blockquote>"
        f"👤 Руководитель: {mention(lab['user_id'], lab['full_name'])}\n"
        f"🏛 В составе Корпорации — «{corp_text}»\n"
        f"🧪 Готовых патогенов: {lab['ready_pathogens']}/{lab['pathogens']}\n"
        f"☣️ Опыт: {num(lab['bio_exp'])}\n"
        f"🧬 Ресурсы: {num(lab['bio_res'])}"
        "</blockquote>"
    )


NO_LAB_MINI = "❌ У вас нет лаборатории!"
DOSSIER_SECRET = (
    "📝 Объект засекретил досье о своей лаборатории\n\n"
    '💬 Вы можете попросить его открыть досье командой "+лаб"'
)


def dossier_toggled(is_open: bool, who: str) -> str:
    if is_open:
        return f"❇️Внимание, лаборатория рассекречена, {who}.\n<b>Лаборатория — видна.</b>"
    return f"‼️Внимание, лаборатория засекречена, {who}.\n<b>Лаборатория — скрыта.</b>"


# --- Эмодзи лаборатории ---

def emoji_set(value: str) -> str:
    return f"💞 Вы установили кастомное эмоджи, для вашей лабы {escape(value)}"


def emoji_removed(value: str) -> str:
    return f"❎ Эмоджи {escape(value)} убрана из вашей лаборатории"


EMOJI_WRONG = "📝 Предложенный вариант не является эмоджи"
EMOJI_NONE = (
    "❎ Вы не имеете кастомного эмоджи\n\n\n"
    "<i>Воспользуйтесь командой <code>лаб эмоджи (ваш эмоджи)</code> для установления эмоджи</i>"
)


# --- Прокачка (тексты и окончания «био-ресурс/-а/-ов» — как в оригинале по каждому навыку) ---

_PREVIEW = {
    "pathogens": "🗓 <b>Увеличение количества ячеек с патогеном на {n} (до {to})</b>\n🧬 <b>Стоимость:</b> {price} био-ресурсов",
    "science": "✅ Ускорение производства патогена на {n} уровень (до {minutes} мин.)\n🧬 <b>Стоимость:</b> {price} био-ресурсов",
    "infect": "✅ Усиление заразности патогена на {n} ур (до {to})\n🧬 <b>Стоимость:</b> {price} био-ресурсов",
    "immunity": "✅ Укрепление иммунитета на {n} ур (до {to})\n🧬 <b>Стоимость:</b> {price} био-ресурсов",
    "lethality": "✅ Усиление летальности патогена на {n} (до {to})\n🧬 <b>Стоимость:</b> {price} био-ресурса",
    "security": "✅ Укрепление службы безопасности на {n} ур (до {to})\n🧬 <b>Стоимость:</b> {price} био-ресурсов",
}

_DONE = {
    "pathogens": "✅ Количество ячеек для производства патогенов увеличено на {n} (до {to})\n🧾 Потрачено: 🧬 {price} био-ресурс",
    "science": "✅ Ускорение производства патогена на {n} уровень (до {minutes} мин.) выполнено\n🧾 Потрачено: 🧬 {price} био-ресурсов",
    "infect": "✅ Усиление заразности патогена на {n} ур (до {to}) выполнено\n🧾 Потрачено: 🧬 {price} био-ресурсов",
    "immunity": "✅ Укрепление иммунитета на {n} ур (до {to}) выполнено\n🧾 Потрачено: 🧬 {price} био-ресурса",
    "lethality": "✅ Усиление летальности патогена на {n} (до {to}) выполнено\n🧾 Потрачено: 🧬 {price} био-ресурсов",
    "security": "✅ Укрепление службы безопасности на {n} ур (до {to}) выполнено\n🧾 Потрачено: 🧬 {price} био-ресурсов",
}


def _fill(template: str, q: Quote) -> str:
    return template.format(n=q.levels, to=q.to_lvl, minutes=F.science_minutes(q.to_lvl), price=comma(q.price))


def upgrade_preview(q: Quote) -> str:
    return (
        f"<blockquote>{_fill(_PREVIEW[q.skill], q)}</blockquote>\n\n"
        f"<b>Команда:</b> «<code>++{C.SKILL_COMMAND[q.skill]} {q.levels}</code>» "
    )


def upgrade_done(q: Quote) -> str:
    return _fill(_DONE[q.skill], q)


def upgrade_toast(levels: int) -> str:
    return f"Улучшение на {levels} уровней"


def max_level(skill: str) -> str:
    return f"‼️Навык <b>«{C.SKILL_COMMAND[skill]}»</b> достиг максимального уровня прокачки"


# --- Понижение («-зз 3») ---

def downgrade_done(d: Downgrade) -> str:
    return (
        f"📉 <b>{C.SKILL_TITLE[d.skill]} -{d.levels} ур.</b>\n\n"
        f"Было: <b>{d.from_lvl}</b> → Стало: <b>{d.to_lvl}</b>\n"
        f"💰 Потрачено было: <b>{comma(d.spent)}</b> 🧬\n"
        f"💸 Возвращено ({int(C.DOWNGRADE_REFUND * 100)}%): <b>+{comma(d.refund)}</b> 🧬"
    )


DOWNGRADE_USAGE = "❌ Формат: <code>-зз 3</code> (отнять 3 уровня)"


def downgrade_min(d: Downgrade) -> str:
    return f"❌ Нельзя опустить уровень ниже 1! Сейчас: <b>{d.from_lvl}</b>"
