"""SwitchBot Lock Ultra motor speed and sound over local BLE."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import LockSettingsCoordinator

PLATFORMS = [Platform.SELECT, Platform.SWITCH]

type LockSpeedConfigEntry = ConfigEntry[LockSettingsCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LockSpeedConfigEntry) -> bool:
    entry.runtime_data = coordinator = LockSettingsCoordinator(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Initial read in the background: a busy lock must not block or fail the setup.
    entry.async_create_background_task(hass, coordinator.async_refresh(), f"{DOMAIN} initial read")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LockSpeedConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
