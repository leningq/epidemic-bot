"""Тексты «мф» — дословно по оригиналу (core/handlers/biowar/infects/mf.py)."""
from __future__ import annotations

from html import escape

from epidemic.db import Row
from epidemic.game.mass import PAGE_SIZE
from epidemic.utils.fmt import comma

EMPTY = "❌ У вас нет доступных слетевших целей!"
LIST_EMPTY = "❌ Список целей пуст!"
PAGE_EMPTY = "❌ На этой странице нет доступных целей!"
ALL_EMPTY = "❌ Список слетевших пуст!"
STALE = "❌ Сообщение устарело, откройте мф заново"
STARTING = "🚀 Запуск массовой атаки..."
STOPPED = "❌ <b>Массовое заражение остановлено!</b>"
NO_PATHOGENS = "⚠️ <b>Массовое заражение остановлено:</b> закончились патогены!"
CANCELLING = "❌ Остановка заражения..."


def target_name(row: Row) -> str:
    return escape(str(row["full_name"] or row["username"] or f"ID: {row['victim_id']}"))


def total_pages(count: int) -> int:
    return max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)


def page_rows(rows: list[Row], page: int) -> list[Row]:
    start = (page - 1) * PAGE_SIZE
    return rows[start:start + PAGE_SIZE]


def fallen_list(rows: list[Row], page: int) -> str:
    start = (page - 1) * PAGE_SIZE
    lines = [f"☣️ <b>Список слетевших целей (Страница {page}/{total_pages(len(rows))}):</b>\n"]
    lines += [f"{start + i}. {target_name(r)}" for i, r in enumerate(page_rows(rows, page), 1)]
    return "\n".join(lines)


def starting(total: int) -> str:
    return f"☣️ <b>Инициализация массового заражения...</b>\n🎯 Всего целей: <b>{total}</b>"


def starting_all(total: int) -> str:
    return f"🚀 Запуск массовой атаки на {total} целей..."


def result_line(success: bool, earn: int) -> str:
    return f"🟢 <b>ПРОБИТО!</b> (+{comma(earn)} XP)" if success else "🔴 <b>ПРОМАХ!</b>"


def _bar(idx: int, total: int) -> tuple[str, int]:
    percent = int(idx / total * 100)
    filled = percent // 10
    return "▓" * filled + "░" * (10 - filled), percent


def progress_page(idx: int, total: int, name: str, chance: float, left: int, result: str, ok: int, bad: int) -> str:
    bar, percent = _bar(idx, total)
    return (
        f"☣️ <b>Массовое заражение в процессе ({idx}/{total})...</b>\n\n"
        f"🎯 Цель: <b>{name}</b>\n"
        f"🎲 Шанс пробития: <b>{chance}%</b>\n"
        f"🧪 Оставшиеся патогены: <b>{left}</b>\n"
        f"Результат: {result}\n\n"
        f"📊 Прогресс: <code>[{bar}] {percent}%</code>\n"
        f"🟢 Успешно: <b>{ok}</b> | 🔴 Промахи: <b>{bad}</b>"
    )


def progress_all(idx: int, total: int, name: str, chance: float, left: int, result: str, ok: int, bad: int) -> str:
    bar, percent = _bar(idx, total)
    return (
        f"☣️ <b>Массовое заражение ({idx}/{total})...</b>\n\n"
        f"🎯 Цель: <b>{name}</b>\n"
        f"🎲 Шанс: <b>{chance}%</b>\n"
        f"🧪 Патогены: <b>{left}</b>\n"
        f"Результат: {result}\n\n"
        f"📊 <code>[{bar}] {percent}%</code>\n"
        f"🟢 {ok} | 🔴 {bad}"
    )


def report_page(
    page: int, processed: int, total: int, ok: list[tuple[str, int]], bad: list[str], fails: int, spent: int
) -> str:
    lines = [
        f"☣️ <b>Итоги массового заражения (Стр. {page}):</b>\n",
        f"🎯 Обработано целей: <b>{processed} / {total}</b>",
        f"🟢 Пробито целей: <b>{len(ok)}</b>",
        f"🔴 Не пробито: <b>{fails}</b>",
        f"🧪 Потрачено патогенов: <b>{spent}</b>\n",
        "📈 <b>Получено опыта:</b>",
        f"🧬 <b>+{comma(sum(exp for _, exp in ok))} XP</b>",
    ]
    if ok:
        lines.append("\n🟢 <b>Пробитые цели:</b>")
        lines += [f"  ✅ {name} — <b>+{comma(exp)} XP</b>" for name, exp in ok]
    if bad:
        lines.append("\n🔴 <b>Не пробитые:</b>")
        lines += [f"  ❌ {name}" for name in bad]
    return "\n".join(lines)


def report_all(
    processed: int, total: int, ok: list[tuple[str, int]], bad: list[str], fails: int, spent: int
) -> str:
    lines = [
        f"☣️ <b>Итоги массового заражения (ВСЕ {total}):</b>\n",
        f"🎯 Обработано: <b>{processed} / {total}</b>",
        f"🟢 Пробито: <b>{len(ok)}</b>",
        f"🔴 Не пробито: <b>{fails}</b>",
        f"🧪 Потрачено патогенов: <b>{spent}</b>\n",
        "📈 <b>Получено опыта:</b>",
        f"🧬 <b>+{comma(sum(exp for _, exp in ok))} XP</b>",
    ]
    if ok:
        lines.append("\n🟢 <b>Пробитые цели:</b>")
        lines += [f"  ✅ {name} — <b>+{comma(exp)} XP</b>" for name, exp in ok[:15]]
        if len(ok) > 15:
            lines.append(f"  <i>...и ещё {len(ok) - 15}</i>")
    if bad:
        lines.append("\n🔴 <b>Не пробитые:</b>")
        lines += [f"  ❌ {name}" for name in bad[:15]]
        if len(bad) > 15:
            lines.append(f"  <i>...и ещё {len(bad) - 15}</i>")
    return "\n".join(lines)
