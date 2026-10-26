"""Motor speed select entity."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
try:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # Home Assistant before 2025.2
    from homeassistant.helpers.entity_platform import AddEntitiesCallback as AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import LockSpeedConfigEntry
from .ble import async_run_session
from .const import DOMAIN, MODE_VALUES, MODES
from .protocol import LockSpeedError, SpeedSession, WriteUncertainError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LockSpeedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LockSpeedSelect(entry)])


class LockSpeedSelect(SelectEntity):
    """Reads the speed on start-up and on request; the lock is not polled periodically."""

    _attr_has_entity_name = True
    _attr_translation_key = "speed"
    _attr_options = list(MODES.values())
    _attr_should_poll = False

    def __init__(self, entry: LockSpeedConfigEntry) -> None:
        self._entry = entry
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_speed"
        # default_* fields are deprecated (HA 2026.10 raises when core re-adds the entity,
        # e.g. after an entity ID rename), so use the plain fields.
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=entry.title,
            manufacturer="SwitchBot",
            model="Lock Ultra",
        )
        self._raw: str | None = None
        self._last_read: str | None = None
        self._last_error: str | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "raw_setting": self._raw,
            "last_read": self._last_read,
            "last_error": self._last_error,
        }

    async def async_added_to_hass(self) -> None:
        self._entry.async_create_background_task(
            self.hass, self._async_initial_read(), f"{DOMAIN} initial read"
        )

    async def _async_initial_read(self) -> None:
        await self.async_update()
        self.async_write_ha_state()

    async def _run(self, operation):
        async with self._entry.runtime_data:
            return await async_run_session(self.hass, self._entry.data, operation)

    def _apply(self, mode: int, raw: str | None) -> None:
        if raw is not None:
            self._raw = raw
            self._last_read = dt_util.utcnow().isoformat()
        self._last_error = None
        self._attr_current_option = MODES.get(mode)
        if self._attr_current_option is None:
            _LOGGER.warning("Unknown speed byte %02x in %s", mode, raw)

    async def async_update(self) -> None:
        """Called once after start-up and by homeassistant.update_entity."""
        try:
            mode, raw = await self._run(lambda s: s.read_mode())
        except LockSpeedError as err:
            self._last_error = str(err)
            _LOGGER.warning("Reading lock speed failed: %s", err)
            return
        self._apply(mode, raw)

    async def async_select_option(self, option: str) -> None:
        value = MODE_VALUES[option]

        async def write_then_read(session: SpeedSession) -> tuple[int, str | None]:
            await session.write_mode(value)
            try:
                return await session.read_mode()
            except LockSpeedError as err:
                # The write itself was acknowledged with ca00; only the confirmation read failed.
                _LOGGER.warning("Speed set, but the read-back failed: %s", err)
                return value, None

        try:
            mode, raw = await self._run(write_then_read)
        except WriteUncertainError as err:
            self._last_error = str(err)
            self.async_write_ha_state()
            raise HomeAssistantError(
                f"Speed command was sent but not confirmed ({err}). Check the SwitchBot app before trying again."
            ) from err
        except LockSpeedError as err:
            self._last_error = str(err)
            self.async_write_ha_state()
            raise HomeAssistantError(f"Speed not changed: {err}") from err
        self._apply(mode, raw)
        self.async_write_ha_state()
        if mode != value:
            raise HomeAssistantError(
                f"Lock accepted the command but reports speed byte {mode:02x} instead of {value:02x}"
            )
