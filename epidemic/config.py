"""Настройки из переменных окружения (или файла .env рядом с проектом)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env: не перетирает уже заданные переменные."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _ids(raw: str) -> frozenset[int]:
    result = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdecimal():
            result.add(int(part))
    return frozenset(result)


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_ids: frozenset[int]
    tz: ZoneInfo
    db_path: Path
    media_dir: Path
    game_name: str
    notify_title: str
    guide_url: str
    chat_url: str
    channel_url: str
    rules_url: str
    support: str
    log_level: str

    @property
    def tz_label(self) -> str:
        return "по МСК" if self.tz.key == "Europe/Moscow" else f"({self.tz.key})"


def load_config(env_file: Path | None = None) -> Config:
    _load_dotenv(env_file or PROJECT_ROOT / ".env")
    env = os.environ.get
    db_path = Path(env("DB_PATH", str(PROJECT_ROOT / "data" / "epidemic.sqlite3")))
    media_dir = Path(env("MEDIA_DIR", str(PROJECT_ROOT / "media")))
    return Config(
        bot_token=env("BOT_TOKEN", "").strip(),
        owner_ids=_ids(env("ADMIN_ID", "")),
        tz=ZoneInfo(env("TZ", "Europe/Moscow") or "Europe/Moscow"),
        db_path=db_path,
        media_dir=media_dir,
        game_name=env("GAME_NAME", "Эпидемик"),
        notify_title=env("NOTIFY_TITLE", "𝐄𝐩𝐢𝐝𝐞𝐦𝐢𝐜 𝐍𝐨𝐭𝐢𝐟𝐲"),
        guide_url=env("GUIDE_URL", "").strip(),
        chat_url=env("CHAT_URL", "").strip(),
        channel_url=env("CHANNEL_URL", "").strip(),
        rules_url=env("RULES_URL", "").strip(),
        support=env("SUPPORT", "").strip(),
        log_level=env("LOG_LEVEL", "INFO").upper(),
    )
