"""Lock sound switch (flag 0x40 of the settings register)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant

try:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # Home Assistant before 2025.2
    from homeassistant.helpers.entity_platform import AddEntitiesCallback as AddConfigEntryEntitiesCallback

from . import LockSpeedConfigEntry
from .entity import LockSettingsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LockSpeedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LockSoundSwitch(entry.runtime_data)])


class LockSoundSwitch(LockSettingsEntity, SwitchEntity):
    _attr_translation_key = "sound"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sound")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.sound

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_sound(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_sound(False)
