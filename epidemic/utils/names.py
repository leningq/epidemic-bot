"""Проверка игровых названий (лаборатория, патоген, корпорация)."""
from __future__ import annotations

import re

from epidemic.game.constants import NAME_LIMITS

# Как в оригинале: буквы, цифры, пробел и . ! _ плюс дефис.
_ALLOWED = re.compile(r"^[!._\-A-Za-zА-Яа-яЁё0-9 ]+$")
_KIND_GENITIVE = {"pathogen": "патогена", "lab": "лаборатории", "corp": "корпорации"}


def name_key(name: str) -> str:
    """Ключ уникальности: без регистра, лишних пробелов и различия е/ё."""
    return " ".join(name.split()).casefold().replace("ё", "е")


def normalize(name: str) -> str:
    return " ".join(name.split())


def validate(kind: str, name: str, charset: bool = True) -> str | None:
    """Возвращает текст ошибки или None, если название подходит.

    charset=False — только длина (админские переименования).
    """
    limit = NAME_LIMITS[kind]
    if not name:
        return "Название не может быть пустым."
    if len(name) > limit:
        return f"Название {_KIND_GENITIVE[kind]} не должно превышать более {limit} символов"  # текст оригинала
    if charset and not _ALLOWED.match(name):
        return "В названии можно использовать только буквы, цифры, пробел и символы . ! _ -"
    return None
