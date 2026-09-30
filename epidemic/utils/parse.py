"""Разбор текстовых команд игроков."""
from __future__ import annotations

import re
from dataclasses import dataclass

from epidemic.game.constants import INFECT_MAX_PATHOGENS, RANDOM_MODES, SKILL_ALIASES

PREFIX = r"[!./]?"

_SKILL_ALT = "|".join(sorted(map(re.escape, SKILL_ALIASES), key=len, reverse=True))
SKILL_CMD_RE = re.compile(
    rf"^(?P<op>\+\+|\+|-)\s?(?P<skill>{_SKILL_ALT})(?:\s+(?P<n>\d{{1,4}}))?$", re.IGNORECASE
)

_INFECT_RE = re.compile(rf"^{PREFIX}заразить(?:\s+(?P<rest>.+))?$", re.IGNORECASE | re.DOTALL)

_TG_ID_RE = re.compile(r"^tg://(?:openmessage\?user_id=|user\?id=)(\d{3,20})$", re.IGNORECASE)
_TME_RE = re.compile(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z0-9_]{4,32})/?$", re.IGNORECASE)
_USERNAME_RE = re.compile(r"^@([A-Za-z0-9_]{4,32})$")


@dataclass(frozen=True)
class SkillCommand:
    op: str          # "+", "++" или "-"
    skill: str       # ключ навыка (infect, immunity, ...)
    levels: int | None


def parse_skill_command(text: str) -> SkillCommand | None:
    m = SKILL_CMD_RE.match(text.strip())
    if not m:
        return None
    n = m.group("n")
    return SkillCommand(m.group("op"), SKILL_ALIASES[m.group("skill").lower()], int(n) if n else None)


@dataclass(frozen=True)
class TargetRef:
    user_id: int | None = None
    username: str | None = None


def parse_target_token(token: str) -> TargetRef | None:
    """@username, t.me/username, tg://openmessage?user_id=…, tg://user?id=… или числовой ID."""
    token = token.strip()
    if m := _TG_ID_RE.match(token):
        return TargetRef(user_id=int(m.group(1)))
    if m := _TME_RE.match(token):
        return TargetRef(username=m.group(1))
    if m := _USERNAME_RE.match(token):
        name = m.group(1)
        # «@777000» — в оригинале это ID (так в примере из обучения)
        return TargetRef(user_id=int(name)) if name.isdecimal() else TargetRef(username=name)
    if token.isdecimal() and 3 <= len(token) <= 20:
        return TargetRef(user_id=int(token))
    return None


@dataclass(frozen=True)
class InfectCommand:
    mode: str | None            # stronger / equal / weaker / random или None
    count: int                  # сколько патогенов потратить (1..10)
    target: TargetRef | None    # явная цель из текста


def parse_infect(text: str) -> InfectCommand | None:
    """«заразить @user 3», «заразить 3 @user», «заразить + 2», «заразить 5» (ответом) и т.п."""
    m = _INFECT_RE.match(text.strip())
    if not m:
        return None
    mode: str | None = None
    count: int | None = None
    target: TargetRef | None = None
    for token in (m.group("rest") or "").split():
        low = token.lower()
        if low in RANDOM_MODES and mode is None and target is None:
            mode = RANDOM_MODES[low]
            continue
        if token.isdecimal() and len(token) <= 2 and count is None:
            count = int(token)
            continue
        ref = parse_target_token(token)
        if ref is not None and target is None and mode is None:
            target = ref
            continue
        return None
    if count is not None and count < 1:
        count = 1
    return InfectCommand(mode, min(INFECT_MAX_PATHOGENS, count or 1), target)


_DURATION_RE = re.compile(r"^(\d{1,5})([mhdмчд])$", re.IGNORECASE)
_DURATION_UNITS = {"m": 60, "м": 60, "h": 3600, "ч": 3600, "d": 86400, "д": 86400}


def parse_duration(token: str) -> int | None:
    """«30m», «12h», «7d» (или по-русски «7д») → секунды."""
    m = _DURATION_RE.match(token.strip())
    if not m:
        return None
    return int(m.group(1)) * _DURATION_UNITS[m.group(2).lower()]
