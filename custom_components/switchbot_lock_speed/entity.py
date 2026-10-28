"""Common base for the lock settings entities."""
from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import LockSettingsCoordinator


class LockSettingsEntity(CoordinatorEntity[LockSettingsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LockSettingsCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_{key}"
        # default_* fields are deprecated (HA 2026.10 raises when core re-adds the entity,
        # e.g. after an entity ID rename), so use the plain fields.
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            name=entry.title,
            manufacturer="SwitchBot",
            model="Lock Ultra",
        )

    @property
    def available(self) -> bool:
        # A failed read (lock busy, out of range) keeps the last known value instead of
        # turning the entity unavailable; the reason is in `last_error`.
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "raw_setting": data.raw if data else None,
            "last_read": self.coordinator.last_read,
            "last_error": self.coordinator.last_error,
        }
