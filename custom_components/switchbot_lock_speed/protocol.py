"""SwitchBot Lock Ultra settings register (motor speed, sound) over BLE, no Home Assistant imports.

Session framing follows pySwitchbot device.py (SHA 349f338749a0e925181651ed7471098f3e8176f1):
    IV request:  57 000000 0f2103 <key_id>          -> 01 00 00 00 <IV 16 B>
    command:     57 <key_id> <IV[0:2]> AES-128-CTR(key, IV, plaintext)
    response:    01 <key_id> <IV[0:2]> AES-128-CTR(key, IV, payload)
Settings register 0401, captured from the official SwitchBot app (HCI snoop log) and
confirmed on a real Lock Ultra:
    read  0f4f0401                         -> <flags> 00 <speed> 00 c0
    write 0f4e0401 00 <mask> <value> <speed> -> <flags after write> 00
Flags bit 0x40 is the sound (0xca = on, 0x8a = off). A write only changes the flag bits in
<mask> (set to <value>), and speed 0xff leaves the speed unchanged.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SERVICE_UUID = "cba20d00-224d-11e6-9fb8-0002a5d5c51b"
TX_UUID = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
RX_UUID = "cba20003-224d-11e6-9fb8-0002a5d5c51b"

READ_SETTINGS = bytes.fromhex("0f4f0401")
WRITE_SETTINGS_PREFIX = bytes.fromhex("0f4e0401")
SPEED_UNCHANGED = 0xFF
SOUND_FLAG = 0x40
VALID_MODES = (0x00, 0x01, 0x02)


class LockSpeedError(Exception):
    """Session or protocol failure; nothing was written."""


class WriteUncertainError(LockSpeedError):
    """The write command was sent but its effect is not confirmed."""


class GattClient(Protocol):
    async def start_notify(self, char: str, callback: Callable[[Any, bytearray], None]) -> None: ...
    async def write_gatt_char(self, char: str, data: bytes, response: bool = ...) -> None: ...


@dataclass(frozen=True)
class LockSettings:
    """Decoded settings register. `speed` is None when only a write reply is known."""

    flags: int
    speed: int | None
    raw: str | None = None

    @property
    def sound(self) -> bool:
        return bool(self.flags & SOUND_FLAG)


def _ctr(key: bytes, iv: bytes, data: bytes) -> bytes:
    ctx = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
    return ctx.update(data) + ctx.finalize()


def parse_settings(payload: bytes) -> LockSettings:
    """Decode a 0f4f0401 payload."""
    if len(payload) != 5:
        raise LockSpeedError(f"Setting read has {len(payload)} B ({payload.hex() or 'empty'}), expected 5 B")
    return LockSettings(flags=payload[0], speed=payload[2], raw=payload.hex())


class SpeedSession:
    """One encrypted session on an already connected client. Never retries a write."""

    def __init__(self, client: GattClient, key_id: int, key: bytes, timeout: float = 8.0) -> None:
        if len(key) != 16:
            raise ValueError("encryption key must be 16 bytes")
        self._client = client
        self._key_id = key_id
        self._key = key
        self._timeout = timeout
        self._iv: bytes | None = None
        self._pending: tuple[asyncio.Future[bytes], Callable[[bytes], bool]] | None = None
        self.write_sent = False

    def _on_notify(self, _char: Any, data: bytearray) -> None:
        if self._pending is None:
            return
        future, accept = self._pending
        if future.done():
            return
        value = bytes(data)
        if len(value) == 1 and value[0] in (0x07, 0x09):
            future.set_exception(LockSpeedError(f"Lock rejected authorization (code {value[0]})"))
        elif accept(value):
            future.set_result(value)

    async def _exchange(self, wire: bytes, accept: Callable[[bytes], bool]) -> bytes:
        if self._pending is not None:
            raise LockSpeedError("Another operation is in progress")
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._pending = (future, accept)
        try:
            await self._client.write_gatt_char(TX_UUID, wire, response=True)
            return await asyncio.wait_for(future, self._timeout)
        except TimeoutError as err:
            raise LockSpeedError("No complete response from the lock") from err
        finally:
            self._pending = None

    async def start(self) -> None:
        await self._client.start_notify(RX_UUID, self._on_notify)
        reply = await self._exchange(
            bytes.fromhex("570000000f2103") + bytes([self._key_id]),
            lambda v: len(v) >= 4 and v[0] == 0x01 and v[1] == 0x00 and v[3] == 0x00,
        )
        if reply[2] != 0x00:
            raise LockSpeedError("Lock reports an encryption mode other than AES-CTR")
        if len(reply) != 20:
            raise LockSpeedError(f"Unexpected IV response length {len(reply)} B")
        self._iv = reply[4:]

    async def _encrypted(self, plain: bytes) -> bytes:
        if self._iv is None:
            raise LockSpeedError("Session not started")
        iv = self._iv
        wire = bytes([0x57, self._key_id]) + iv[:2] + _ctr(self._key, iv, plain)
        reply = await self._exchange(
            wire,
            lambda v: len(v) >= 4 and v[0] == 0x01 and v[1] == self._key_id and v[2:4] == iv[:2],
        )
        return _ctr(self._key, iv, reply[4:]) if len(reply) > 4 else b""

    async def read_settings(self) -> LockSettings:
        return parse_settings(await self._encrypted(READ_SETTINGS))

    async def read_mode(self) -> tuple[int, str]:
        settings = await self.read_settings()
        return settings.speed, settings.raw

    async def _write_settings(self, mask: int, value: int, speed: int) -> int:
        """Send one settings write; return the flags byte the lock reports afterwards."""
        if self.write_sent:
            raise LockSpeedError("This session already sent its single write")
        self.write_sent = True
        try:
            reply = await self._encrypted(WRITE_SETTINGS_PREFIX + bytes([0x00, mask, value & mask, speed]))
        except LockSpeedError as err:
            raise WriteUncertainError(f"Write sent, result unknown: {err}") from err
        # Byte 0 is the current flags (0xca or 0x8a depending on sound), byte 1 the status.
        if len(reply) != 2 or reply[1] != 0x00:
            raise WriteUncertainError(f"Write reply {reply.hex() or 'empty'}, expected <flags>00")
        return reply[0]

    async def write_mode(self, mode: int) -> int:
        if mode not in VALID_MODES:
            raise ValueError(f"Unsupported speed mode {mode}")
        return await self._write_settings(0x00, 0x00, mode)

    async def write_sound(self, on: bool) -> int:
        flags = await self._write_settings(SOUND_FLAG, SOUND_FLAG if on else 0x00, SPEED_UNCHANGED)
        if bool(flags & SOUND_FLAG) != on:
            raise WriteUncertainError(f"Lock reports flags {flags:02x} after setting sound {'on' if on else 'off'}")
        return flags
