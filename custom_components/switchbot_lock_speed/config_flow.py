"""Config flow: reuse the key of an existing SwitchBot lock entry, or enter it by hand."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_SENSOR_TYPE
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .ble import async_run_session
from .const import (
    CONF_ENCRYPTION_KEY,
    CONF_KEY_ID,
    DOMAIN,
    SWITCHBOT_DOMAIN,
    SWITCHBOT_LOCK_ULTRA,
    SWITCHBOT_MANUFACTURER_ID,
)
from .protocol import LockSpeedError

_LOGGER = logging.getLogger(__name__)

CONF_SOURCE_ENTRY = "source_entry"
MANUAL = "manual"
ADDRESS_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
TEST_READ_TIMEOUT = 35


class SwitchbotLockSpeedConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._error_detail = ""

    def _switchbot_locks(self) -> dict[str, Any]:
        return {
            entry.entry_id: entry
            for entry in self.hass.config_entries.async_entries(SWITCHBOT_DOMAIN)
            if entry.data.get(CONF_SENSOR_TYPE) == SWITCHBOT_LOCK_ULTRA
            and entry.data.get(CONF_ADDRESS)
            and entry.data.get(CONF_KEY_ID)
            and entry.data.get(CONF_ENCRYPTION_KEY)
        }

    async def _async_validate_and_create(
        self, data: dict[str, Any], title: str
    ) -> ConfigFlowResult | str:
        """Create the entry after a successful read; return an error key otherwise."""
        await self.async_set_unique_id(data[CONF_ADDRESS])
        self._abort_if_unique_id_configured()
        try:
            await async_run_session(
                self.hass, data, lambda s: s.read_mode(), timeout=TEST_READ_TIMEOUT
            )
        except LockSpeedError as err:
            _LOGGER.warning("Test read of %s failed: %s", data[CONF_ADDRESS], err)
            self._error_detail = str(err)
            return "cannot_connect"
        return self.async_create_entry(title=title, data=data)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        locks = self._switchbot_locks()
        if not locks:
            return await self.async_step_manual()
        errors: dict[str, str] = {}
        if user_input is not None:
            choice = user_input[CONF_SOURCE_ENTRY]
            if choice == MANUAL:
                return await self.async_step_manual()
            source = locks[choice]
            result = await self._async_validate_and_create(
                {
                    CONF_ADDRESS: source.data[CONF_ADDRESS].upper(),
                    CONF_KEY_ID: source.data[CONF_KEY_ID].lower(),
                    CONF_ENCRYPTION_KEY: source.data[CONF_ENCRYPTION_KEY].lower(),
                },
                source.title,
            )
            if not isinstance(result, str):
                return result
            errors["base"] = result
        options = [
            SelectOptionDict(value=entry_id, label=f"{entry.title} ({entry.data[CONF_ADDRESS]})")
            for entry_id, entry in locks.items()
        ]
        options.append(SelectOptionDict(value=MANUAL, label="Manual / Ręcznie"))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_ENTRY): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"error": self._error_detail},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            key_id = user_input[CONF_KEY_ID].strip().lower()
            key = user_input[CONF_ENCRYPTION_KEY].strip().lower()
            if not ADDRESS_RE.match(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif not re.fullmatch(r"[0-9a-f]{2}", key_id):
                errors[CONF_KEY_ID] = "invalid_key_id"
            elif not re.fullmatch(r"[0-9a-f]{32}", key):
                errors[CONF_ENCRYPTION_KEY] = "invalid_key"
            else:
                result = await self._async_validate_and_create(
                    {CONF_ADDRESS: address, CONF_KEY_ID: key_id, CONF_ENCRYPTION_KEY: key},
                    f"SwitchBot Lock {address[-5:]}",
                )
                if not isinstance(result, str):
                    return result
                errors["base"] = result
        seen = sorted(
            {
                info.address.upper()
                for info in async_discovered_service_info(self.hass, connectable=True)
                if SWITCHBOT_MANUFACTURER_ID in info.manufacturer_data
            }
        )
        address_selector = (
            SelectSelector(SelectSelectorConfig(options=seen, custom_value=True, mode=SelectSelectorMode.DROPDOWN))
            if seen
            else TextSelector()
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): address_selector,
                    vol.Required(CONF_KEY_ID): TextSelector(),
                    vol.Required(CONF_ENCRYPTION_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"error": self._error_detail},
        )
