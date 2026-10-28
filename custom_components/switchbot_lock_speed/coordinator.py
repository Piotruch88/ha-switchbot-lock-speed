"""One settings register feeds the speed select and the sound switch."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .ble import async_run_session
from .const import DOMAIN
from .protocol import LockSettings, LockSpeedError, SpeedSession, WriteUncertainError

_LOGGER = logging.getLogger(__name__)


class LockSettingsCoordinator(DataUpdateCoordinator[LockSettings]):
    """Reads on start-up and on request only; the lock is not polled (battery)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self._ble_lock = asyncio.Lock()  # one BLE session at a time per lock
        self.last_read: str | None = None
        self.last_error: str | None = None

    async def _run(self, operation: Callable[[SpeedSession], Awaitable[LockSettings]]) -> LockSettings:
        async with self._ble_lock:
            return await async_run_session(self.hass, self.config_entry.data, operation)

    def _store(self, settings: LockSettings) -> None:
        if settings.raw is not None:
            self.last_read = dt_util.utcnow().isoformat()
        self.last_error = None
        self.async_set_updated_data(settings)

    async def _async_update_data(self) -> LockSettings:
        try:
            settings = await self._run(lambda s: s.read_settings())
        except LockSpeedError as err:
            self.last_error = str(err)
            raise UpdateFailed(str(err)) from err
        self.last_read = dt_util.utcnow().isoformat()
        self.last_error = None
        return settings

    async def _async_write(
        self, what: str, write: Callable[[SpeedSession], Awaitable[int]], fallback: Callable[[int], LockSettings]
    ) -> LockSettings:
        async def write_then_read(session: SpeedSession) -> LockSettings:
            flags = await write(session)
            try:
                return await session.read_settings()
            except LockSpeedError as err:
                # The write itself was acknowledged; only the confirmation read failed.
                _LOGGER.warning("%s set, but the read-back failed: %s", what, err)
                return fallback(flags)

        try:
            settings = await self._run(write_then_read)
        except WriteUncertainError as err:
            self.last_error = str(err)
            self.async_update_listeners()
            raise HomeAssistantError(
                f"{what} command was sent but not confirmed ({err}). Check the SwitchBot app before trying again."
            ) from err
        except LockSpeedError as err:
            self.last_error = str(err)
            self.async_update_listeners()
            raise HomeAssistantError(f"{what} not changed: {err}") from err
        self._store(settings)
        return settings

    async def async_set_speed(self, mode: int) -> None:
        settings = await self._async_write(
            "Speed",
            lambda s: s.write_mode(mode),
            lambda flags: LockSettings(flags=flags, speed=mode),
        )
        if settings.speed != mode:
            raise HomeAssistantError(
                f"Lock accepted the command but reports speed byte {settings.speed:02x} instead of {mode:02x}"
            )

    async def async_set_sound(self, on: bool) -> None:
        previous = self.data
        settings = await self._async_write(
            "Sound",
            lambda s: s.write_sound(on),
            lambda flags: LockSettings(flags=flags, speed=previous.speed if previous else None),
        )
        if settings.sound != on:
            raise HomeAssistantError(
                f"Lock accepted the command but reports sound {'on' if settings.sound else 'off'}"
            )
