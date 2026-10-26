"""SwitchBot Lock Ultra motor speed (Max / Standard / Low) over local BLE."""
from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.SELECT]

type LockSpeedConfigEntry = ConfigEntry[asyncio.Lock]


async def async_setup_entry(hass: HomeAssistant, entry: LockSpeedConfigEntry) -> bool:
    entry.runtime_data = asyncio.Lock()  # one BLE session at a time per lock
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LockSpeedConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
