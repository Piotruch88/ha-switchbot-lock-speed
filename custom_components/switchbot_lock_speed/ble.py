"""Short-lived BLE sessions with the lock through Home Assistant's Bluetooth stack."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import CONF_ENCRYPTION_KEY, CONF_KEY_ID
from .protocol import LockSpeedError, SpeedSession, WriteUncertainError

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

SESSION_TIMEOUT = 60
# The official SwitchBot integration holds the lock's single connection for a few seconds
# after each state change; keep retrying the connection (nothing is sent yet) meanwhile.
CONNECT_WINDOW = 45
CONNECT_PAUSE = 3
SESSION_RESERVE = 15  # time kept for init + command after connecting
INIT_ATTEMPTS = 2  # connect + session init; safe to repeat, no command is sent yet


async def _async_drop(client: BleakClientWithServiceCache, clear_cache: bool = False) -> None:
    """Disconnect, optionally forgetting cached GATT services; never raises Bleak errors."""
    try:
        if clear_cache:
            await client.clear_cache()
        await client.disconnect()
    except BleakError:
        pass


async def _async_connect(
    hass: HomeAssistant, address: str, ble_device: Any, deadline: float
) -> BleakClientWithServiceCache:
    attempt = 0
    while True:
        attempt += 1
        try:
            return await establish_connection(
                BleakClientWithServiceCache, ble_device, address, max_attempts=2
            )
        except BleakError as err:
            if time.monotonic() + CONNECT_PAUSE >= deadline:
                raise BleakError(
                    f"lock busy or unreachable after {attempt} connection attempt(s): {err}"
                ) from err
            _LOGGER.debug(
                "%s: connection attempt %s failed (%s), retrying in %s s",
                address, attempt, err, CONNECT_PAUSE,
            )
        await asyncio.sleep(CONNECT_PAUSE)
        ble_device = (
            bluetooth.async_ble_device_from_address(hass, address, connectable=True) or ble_device
        )


async def async_run_session(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    operation: Callable[[SpeedSession], Awaitable[T]],
    timeout: float = SESSION_TIMEOUT,
) -> T:
    """Connect, run one operation in a fresh encrypted session, always disconnect.

    Only the connection is retried (for up to CONNECT_WINDOW s); commands are never retried.
    Errors name the stage that failed, e.g. "connect: ..." or "session init: ...".
    """
    address = data[CONF_ADDRESS]
    started = time.monotonic()
    stage = "lookup"

    def enter(name: str) -> None:
        nonlocal stage
        stage = name
        _LOGGER.debug("%s: %s (%.1f s)", address, name, time.monotonic() - started)

    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise LockSpeedError(
            "lookup: lock not in range of a connectable Bluetooth adapter or proxy"
        )
    info = bluetooth.async_last_service_info(hass, address, connectable=True)
    if info is not None:
        _LOGGER.debug("%s: seen via %s, RSSI %s dBm", address, info.source, info.rssi)

    session: SpeedSession | None = None
    try:
        async with asyncio.timeout(timeout):
            deadline = started + min(CONNECT_WINDOW, timeout - SESSION_RESERVE)
            for attempt in range(1, INIT_ATTEMPTS + 1):
                enter("connect")
                client = await _async_connect(hass, address, ble_device, deadline)
                enter("session init")
                session = SpeedSession(
                    client, int(data[CONF_KEY_ID], 16), bytes.fromhex(data[CONF_ENCRYPTION_KEY])
                )
                try:
                    # Only notifications + IV request happen here; nothing changes on the lock.
                    await session.start()
                    break
                except BleakError as err:
                    # Typically a stale BlueZ object after another integration's connection
                    # ("UnknownObject ... StartNotify"): drop the service cache and reconnect.
                    session = None
                    await _async_drop(client, clear_cache=True)
                    if attempt == INIT_ATTEMPTS:
                        raise
                    _LOGGER.debug(
                        "%s: session init failed (%s), clearing service cache and reconnecting",
                        address, err,
                    )
                    await asyncio.sleep(CONNECT_PAUSE)
                except BaseException:
                    await _async_drop(client)
                    raise
            try:
                enter("command")
                result = await operation(session)
                enter("done")
                return result
            finally:
                await _async_drop(client)
    except WriteUncertainError:
        raise
    except LockSpeedError as err:
        raise LockSpeedError(f"{stage}: {err}") from err
    except (BleakError, TimeoutError) as err:
        detail = str(err) or (
            f"no result within {timeout:.0f} s" if isinstance(err, TimeoutError) else type(err).__name__
        )
        message = f"{stage}: {detail}"
        if session is not None and session.write_sent:
            raise WriteUncertainError(f"Write sent, result unknown: {message}") from err
        raise LockSpeedError(message) from err
