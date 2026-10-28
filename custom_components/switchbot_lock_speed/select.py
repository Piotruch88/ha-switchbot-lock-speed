"""Motor speed select entity."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant

try:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # Home Assistant before 2025.2
    from homeassistant.helpers.entity_platform import AddEntitiesCallback as AddConfigEntryEntitiesCallback

from . import LockSpeedConfigEntry
from .const import MODE_VALUES, MODES
from .entity import LockSettingsEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LockSpeedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LockSpeedSelect(entry.runtime_data)])


class LockSpeedSelect(LockSettingsEntity, SelectEntity):
    _attr_translation_key = "speed"
    _attr_options = list(MODES.values())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "speed")

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.speed is None:
            return None
        option = MODES.get(data.speed)
        if option is None:
            _LOGGER.warning("Unknown speed byte %02x in %s", data.speed, data.raw)
        return option

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_speed(MODE_VALUES[option])
