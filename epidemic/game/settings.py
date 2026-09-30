"""Глобальные настройки игры (множители владельца) с кэшем в памяти."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from epidemic.db import Database, Tx
from epidemic.repo import meta


@dataclass(frozen=True)
class SettingSpec:
    default: int
    minimum: int
    maximum: int
    title: str


SPECS: dict[str, SettingSpec] = {
    "maintenance_mode": SettingSpec(0, 0, 1, "🔧 Техработы"),
    "owner_only_mode": SettingSpec(0, 0, 1, "🔒 Только владелец"),
    "xp_multiplier_pct": SettingSpec(100, 1, 10_000, "☣️ Опыт за заражение, %"),
    "daily_reward_multiplier_pct": SettingSpec(100, 0, 10_000, "💰 Ежедневная премия, %"),
    "upgrade_cost_multiplier_pct": SettingSpec(100, 1, 10_000, "🧬 Стоимость прокачки, %"),
    "production_speed_multiplier_pct": SettingSpec(100, 1, 10_000, "⚙️ Скорость производства, %"),
    "fever_multiplier_pct": SettingSpec(100, 1, 10_000, "🌡 Длительность горячки, %"),
    "infection_cooldown_minutes": SettingSpec(120, 0, 10_080, "⏱ КД заражения одной цели, мин"),
    "max_infection_gap": SettingSpec(221, 0, 10_000, "🛡 Макс. отставание заразности от иммунитета"),
}


class GameSettings:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._values: dict[str, int] = {key: spec.default for key, spec in SPECS.items()}

    async def load(self) -> None:
        rows = await self.db.fetchall("SELECT key, value FROM settings")
        for row in rows:
            spec = SPECS.get(row["key"])
            if spec is None:
                continue
            try:
                value = int(row["value"])
            except ValueError:
                continue
            # значение из базы (в т. ч. перенесённое из старого бота) приводим к допустимым границам:
            # например, множитель стоимости 0 сделал бы прокачку бесплатной
            self._values[row["key"]] = max(spec.minimum, min(spec.maximum, value))

    def get(self, key: str) -> int:
        return self._values[key]

    async def set(self, key: str, value: int, audit: Callable[[Tx], Awaitable[None]] | None = None) -> None:
        """Меняет настройку. audit(t) вызывается в той же транзакции — для записи в журнал админа."""
        spec = SPECS[key]
        if not spec.minimum <= value <= spec.maximum:
            raise ValueError(f"{key}: допустимо от {spec.minimum} до {spec.maximum}")
        async with self.db.tx() as t:
            await meta.put(t, key, str(value))
            if audit is not None:
                await audit(t)
        self._values[key] = value

    # Служебные значения (кэш file_id картинок, слот последней выплаты и т.п.)
    async def get_meta(self, key: str) -> str | None:
        return await meta.get(self.db, key)

    async def set_meta(self, key: str, value: str) -> None:
        await meta.put(self.db, key, value)

    # Удобные свойства
    @property
    def maintenance(self) -> bool:
        return bool(self._values["maintenance_mode"])

    @property
    def owner_only(self) -> bool:
        return bool(self._values["owner_only_mode"])

    @property
    def xp_pct(self) -> int:
        return self._values["xp_multiplier_pct"]

    @property
    def daily_pct(self) -> int:
        return self._values["daily_reward_multiplier_pct"]

    @property
    def cost_pct(self) -> int:
        return self._values["upgrade_cost_multiplier_pct"]

    @property
    def speed_pct(self) -> int:
        return self._values["production_speed_multiplier_pct"]

    @property
    def fever_pct(self) -> int:
        return self._values["fever_multiplier_pct"]

    @property
    def cooldown_sec(self) -> int:
        return self._values["infection_cooldown_minutes"] * 60

    @property
    def max_gap(self) -> int:
        return self._values["max_infection_gap"]
