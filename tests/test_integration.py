"""Home Assistant tests: config flow, select entity and ble.py with a simulated lock."""
import os
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

import custom_components.switchbot_lock_speed.ble  # noqa: F401  (patch targets)
import custom_components.switchbot_lock_speed.config_flow  # noqa: F401
from custom_components.switchbot_lock_speed.const import CONF_ENCRYPTION_KEY, CONF_KEY_ID, DOMAIN

from test_protocol import FakeLock

ADDRESS = "AA:BB:CC:DD:EE:FF"
ENTITY = "select.switchbot_lock_ee_ff_motor_speed"
SOUND = "switch.switchbot_lock_ee_ff_sound"


class FakeClient(FakeLock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.disconnects = 0
        self.cache_clears = 0
        self.notify_failures = 0  # how many start_notify calls fail like a stale BlueZ object

    async def disconnect(self):
        self.disconnects += 1

    async def clear_cache(self):
        self.cache_clears += 1
        return True

    async def start_notify(self, char, callback):
        if self.notify_failures:
            from bleak.exc import BleakError

            self.notify_failures -= 1
            raise BleakError(
                '[org.freedesktop.DBus.Error.UnknownObject] Method "StartNotify" with signature "" '
                'on interface "org.bluez.GattCharacteristic1" doesn\'t exist'
            )
        await super().start_notify(char, callback)


@pytest.fixture
def key():
    return os.urandom(16)


@pytest.fixture
def lock(key):
    return FakeClient(key)


@pytest.fixture
def ble(lock):
    """Patch HA's Bluetooth lookup and bleak connection with the simulated lock."""
    async def connect(*args, **kwargs):
        return lock

    with (
        patch("custom_components.switchbot_lock_speed.ble.bluetooth.async_ble_device_from_address", return_value=object()) as find,
        patch("custom_components.switchbot_lock_speed.ble.bluetooth.async_last_service_info", return_value=None),
        patch("custom_components.switchbot_lock_speed.ble.establish_connection", side_effect=connect),
        patch("custom_components.switchbot_lock_speed.config_flow.async_discovered_service_info", return_value=[]),
    ):
        yield find


@pytest.fixture(autouse=True)
def bluetooth_loaded(hass, enable_custom_integrations):
    hass.config.components.add("bluetooth")


def data(key):
    return {CONF_ADDRESS: ADDRESS, CONF_KEY_ID: "77", CONF_ENCRYPTION_KEY: key.hex()}


async def setup(hass, key):
    entry = MockConfigEntry(domain=DOMAIN, data=data(key), unique_id=ADDRESS, title="SwitchBot Lock EE:FF")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_flow_reuses_switchbot_entry(hass, key, lock, ble):
    MockConfigEntry(domain="switchbot", title="Drzwi", data={**data(key), "sensor_type": "lock_ultra"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    source = next(o["value"] for o in result["data_schema"].schema["source_entry"].config["options"] if o["value"] != "manual")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"source_entry": source})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Drzwi"
    assert result["data"] == data(key)
    await hass.async_block_till_done(wait_background_tasks=True)
    # test read in the flow + the entity's initial read after setup; never a write
    assert lock.plain == ["0f4f0401", "0f4f0401"]
    assert lock.disconnects == 2


async def test_flow_ignores_other_switchbot_models(hass, key, ble):
    MockConfigEntry(domain="switchbot", title="Old lock", data={**data(key), "sensor_type": "lock_pro"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "manual"  # no Lock Ultra to offer


async def test_flow_test_read_failure(hass, key, ble):
    ble.return_value = None  # lock not in range
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data(key))
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "cannot_connect"}
    assert result["description_placeholders"]["error"].startswith("lookup: lock not in range")


async def test_flow_shows_connect_stage(hass, key, ble):
    from bleak.exc import BleakError

    with (
        patch(
            "custom_components.switchbot_lock_speed.ble.establish_connection",
            side_effect=BleakError("AA:BB:CC:DD:EE:FF - No backend with an available connection slot"),
        ) as connect,
        patch("custom_components.switchbot_lock_speed.ble.CONNECT_PAUSE", 0.05),
        patch("custom_components.switchbot_lock_speed.ble.CONNECT_WINDOW", 0.3),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data(key))
    assert result["errors"] == {"base": "cannot_connect"}
    error = result["description_placeholders"]["error"]
    assert error.startswith("connect: lock busy or unreachable after ") and "No backend" in error
    assert connect.call_count > 1


async def test_stale_bluez_object_reconnects_once(hass, key, lock, ble):
    await setup(hass, key)
    lock.notify_failures = 1
    with patch("custom_components.switchbot_lock_speed.ble.CONNECT_PAUSE", 0.01):
        await hass.services.async_call("select", "select_option", {"entity_id": ENTITY, "option": "low"}, blocking=True)
    assert hass.states.get(ENTITY).state == "low"
    assert lock.cache_clears == 1
    assert sum(p.startswith("0f4e") for p in lock.plain) == 1


async def test_stale_bluez_object_twice_fails_without_command(hass, key, lock, ble):
    await setup(hass, key)
    lock.notify_failures = 2
    with (
        patch("custom_components.switchbot_lock_speed.ble.CONNECT_PAUSE", 0.01),
        pytest.raises(HomeAssistantError, match="Speed not changed: session init: .*UnknownObject"),
    ):
        await hass.services.async_call("select", "select_option", {"entity_id": ENTITY, "option": "low"}, blocking=True)
    assert lock.cache_clears == 2
    assert not any(p.startswith("0f4e") for p in lock.plain)


async def test_busy_lock_is_retried_before_sending(hass, key, lock, ble):
    """Lock held by another connection twice, then free: one command, success."""
    from bleak.exc import BleakError

    await setup(hass, key)
    calls = 0

    async def busy_then_free(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise BleakError("[org.bluez.Error.InProgress] In Progress")
        return lock

    with (
        patch("custom_components.switchbot_lock_speed.ble.establish_connection", side_effect=busy_then_free),
        patch("custom_components.switchbot_lock_speed.ble.CONNECT_PAUSE", 0.01),
    ):
        await hass.services.async_call("select", "select_option", {"entity_id": ENTITY, "option": "standard"}, blocking=True)
    assert calls == 3
    assert hass.states.get(ENTITY).state == "standard"
    assert sum(p.startswith("0f4e") for p in lock.plain) == 1


async def test_flow_manual_validation(hass, ble):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS, CONF_KEY_ID: "77", CONF_ENCRYPTION_KEY: "abc"}
    )
    assert result["errors"] == {CONF_ENCRYPTION_KEY: "invalid_key"}


async def test_initial_read_and_set(hass, key, lock, ble):
    assert await async_setup_component(hass, "homeassistant", {})
    await setup(hass, key)
    state = hass.states.get(ENTITY)
    assert state.state == "max"
    assert state.attributes["options"] == ["max", "standard", "low"]
    assert state.attributes["raw_setting"] == "ca000000c0"

    await hass.services.async_call("select", "select_option", {"entity_id": ENTITY, "option": "standard"}, blocking=True)
    assert hass.states.get(ENTITY).state == "standard"
    assert lock.plain == ["0f4f0401", "0f4e040100000001", "0f4f0401"]
    assert lock.disconnects == 2

    lock.mode = 0x02  # changed in the SwitchBot app
    await hass.services.async_call("homeassistant", "update_entity", {"entity_id": ENTITY}, blocking=True)
    assert hass.states.get(ENTITY).state == "low"


async def test_uncertain_write_is_not_retried(hass, key, lock, ble):
    await setup(hass, key)
    lock.scenario = "write_bad"
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        await hass.services.async_call("select", "select_option", {"entity_id": ENTITY, "option": "low"}, blocking=True)
    assert sum(p.startswith("0f4e") for p in lock.plain) == 1
    assert "expected <flags>00" in hass.states.get(ENTITY).attributes["last_error"]


async def test_lock_out_of_range(hass, key, lock, ble):
    ble.return_value = None
    await setup(hass, key)
    state = hass.states.get(ENTITY)
    assert state.state == "unknown"
    assert "not in range" in state.attributes["last_error"]
    with pytest.raises(HomeAssistantError, match="Speed not changed"):
        await hass.services.async_call("select", "select_option", {"entity_id": ENTITY, "option": "low"}, blocking=True)
    assert lock.writes == []


async def test_sound_switch(hass, key, lock, ble):
    await setup(hass, key)
    lock.mode = 0x01  # changed elsewhere; the sound write must not change it back
    assert hass.states.get(SOUND).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": SOUND}, blocking=True)
    assert hass.states.get(SOUND).state == "off"
    assert lock.plain[-2:] == ["0f4e0401004000ff", "0f4f0401"]
    assert lock.mode == 0x01
    assert hass.states.get(ENTITY).state == "standard", "speed select refreshed from the same read"
    await hass.services.async_call("switch", "turn_on", {"entity_id": SOUND}, blocking=True)
    assert hass.states.get(SOUND).state == "on"
    assert lock.plain[-2] == "0f4e0401004040ff"
    assert sum(p.startswith("0f4e") for p in lock.plain) == 2


async def test_speed_change_with_sound_off(hass, key, lock, ble):
    """Regression for v0.2.0: with sound off the lock answers 8a00 and the change is still confirmed."""
    lock.flags = 0x8A
    await setup(hass, key)
    assert hass.states.get(SOUND).state == "off"
    await hass.services.async_call("select", "select_option", {"entity_id": ENTITY, "option": "low"}, blocking=True)
    assert hass.states.get(ENTITY).state == "low"
    assert hass.states.get(SOUND).state == "off"


async def test_sound_not_applied_raises(hass, key, lock, ble):
    await setup(hass, key)
    lock.scenario = "flags_ignored"
    with pytest.raises(HomeAssistantError, match="Sound command was sent but not confirmed"):
        await hass.services.async_call("switch", "turn_off", {"entity_id": SOUND}, blocking=True)
    assert sum(p.startswith("0f4e") for p in lock.plain) == 1


async def test_refresh_updates_both_entities(hass, key, lock, ble):
    assert await async_setup_component(hass, "homeassistant", {})
    await setup(hass, key)
    lock.flags, lock.mode = 0x8A, 0x02  # changed in the SwitchBot app
    await hass.services.async_call("homeassistant", "update_entity", {"entity_id": SOUND}, blocking=True)
    assert hass.states.get(SOUND).state == "off"
    assert hass.states.get(ENTITY).state == "low"
