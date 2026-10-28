"""Protocol tests against a simulated Lock Ultra (random key, no Home Assistant needed)."""
import asyncio
import importlib.util
import os
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_PATH = pathlib.Path(__file__).parents[1] / "custom_components" / "switchbot_lock_speed" / "protocol.py"
_spec = importlib.util.spec_from_file_location("lock_speed_protocol", _PATH)
protocol = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = protocol  # dataclasses look the module up while decorating
_spec.loader.exec_module(protocol)

IV = bytes.fromhex("00112233445566778899aabbccddeeff")


def ctr(key, data):
    c = Cipher(algorithms.AES(key), modes.CTR(IV)).encryptor()
    return c.update(data) + c.finalize()


class FakeLock:
    """Answers like the recorded lock: settings register 0401 = `flags` (0xca: sound on) + `mode`."""

    def __init__(self, key, scenario="ok"):
        self.key, self.scenario, self.mode, self.flags = key, scenario, 0x00, 0xCA
        self.callback, self.writes, self.plain = None, [], []

    async def start_notify(self, char, callback):
        assert char == protocol.RX_UUID
        self.callback = callback

    async def write_gatt_char(self, char, data, response=False):
        assert char == protocol.TX_UUID and response is True
        data = bytes(data)
        self.writes.append(data)
        loop = asyncio.get_running_loop()
        if data[:4] == bytes.fromhex("57000000"):
            loop.call_soon(self.callback, None, bytearray(b"\x01\x00\x00\x00" + IV))
            return
        plain = ctr(self.key, data[4:])
        self.plain.append(plain.hex())
        if self.scenario == "auth":
            loop.call_soon(self.callback, None, bytearray(b"\x07"))
            return
        if plain == bytes.fromhex("0f4f0401"):
            payload = bytes([self.flags, 0x00, self.mode, 0x00, 0xC0])
        elif plain[:4] == bytes.fromhex("0f4e0401") and len(plain) == 8:
            if self.scenario == "write_silent":
                return
            _, mask, value, speed = plain[4:]
            if self.scenario != "flags_ignored":
                self.flags = (self.flags & ~mask & 0xFF) | (value & mask)
            if speed != 0xFF:
                self.mode = speed
            payload = bytes([self.flags, 0x01 if self.scenario == "write_bad" else 0x00])
        else:
            return  # unknown command, e.g. wrong key: the lock stays silent
        # unrelated push first: must be ignored by the session
        loop.call_soon(self.callback, None, bytearray(b"\x0f" + data[1:4] + b"\xaa\xbb"))
        loop.call_soon(self.callback, None, bytearray(b"\x01" + data[1:4] + ctr(self.key, payload)))


@pytest.fixture
def key():
    return os.urandom(16)


async def started(lock, key, timeout=0.3):
    session = protocol.SpeedSession(lock, 0x77, key, timeout=timeout)
    await session.start()
    return session


async def test_read_mode(key):
    lock = FakeLock(key)
    lock.mode = 0x01
    session = await started(lock, key)
    assert await session.read_mode() == (1, "ca000100c0")
    assert lock.writes[0].hex() == "570000000f210377"
    assert lock.plain == ["0f4f0401"]
    assert lock.writes[1][:4] == bytes([0x57, 0x77, IV[0], IV[1]])


async def test_write_matches_recorded_command(key):
    lock = FakeLock(key)
    session = await started(lock, key)
    await session.write_mode(1)
    assert await session.read_mode() == (1, "ca000100c0")
    assert lock.plain == ["0f4e040100000001", "0f4f0401"]


@pytest.mark.parametrize("mode", [0, 1, 2])
async def test_all_modes_encode(key, mode):
    lock = FakeLock(key)
    session = await started(lock, key)
    await session.write_mode(mode)
    assert lock.plain == [f"0f4e04010000000{mode}"]


async def test_invalid_mode_sends_nothing(key):
    lock = FakeLock(key)
    session = await started(lock, key)
    with pytest.raises(ValueError):
        await session.write_mode(3)
    assert lock.plain == []


async def test_single_write_per_session(key):
    lock = FakeLock(key)
    session = await started(lock, key)
    await session.write_mode(2)
    with pytest.raises(protocol.LockSpeedError):
        await session.write_mode(0)
    assert lock.plain == ["0f4e040100000002"]


@pytest.mark.parametrize("scenario", ["write_bad", "write_silent"])
async def test_unconfirmed_write_is_uncertain_and_not_retried(key, scenario):
    lock = FakeLock(key, scenario)
    session = await started(lock, key)
    with pytest.raises(protocol.WriteUncertainError):
        await session.write_mode(1)
    assert sum(p.startswith("0f4e") for p in lock.plain) == 1


async def test_wrong_key_times_out_on_read(key):
    lock = FakeLock(key)
    session = await started(lock, os.urandom(16))
    with pytest.raises(protocol.LockSpeedError) as err:
        await session.read_mode()
    assert not isinstance(err.value, protocol.WriteUncertainError)


async def test_auth_rejected(key):
    lock = FakeLock(key, "auth")
    session = await started(lock, key)
    with pytest.raises(protocol.LockSpeedError, match="authorization"):
        await session.read_mode()


def test_parse_settings():
    settings = protocol.parse_settings(bytes.fromhex("8a000200c0"))
    assert (settings.flags, settings.speed, settings.sound, settings.raw) == (0x8A, 2, False, "8a000200c0")
    assert protocol.parse_settings(bytes.fromhex("ca000000c0")).sound is True
    with pytest.raises(protocol.LockSpeedError):
        protocol.parse_settings(bytes.fromhex("ca0000"))


@pytest.mark.parametrize(("on", "command", "flags"), [(False, "0f4e0401004000ff", 0x8A), (True, "0f4e0401004040ff", 0xCA)])
async def test_sound_commands_match_capture(key, on, command, flags):
    lock = FakeLock(key)
    lock.flags = 0x8A if on else 0xCA
    lock.mode = 0x01
    session = await started(lock, key)
    assert await session.write_sound(on) == flags
    assert lock.plain == [command]
    assert lock.mode == 0x01, "sound write must not touch the speed"


async def test_speed_write_accepted_with_sound_off(key):
    """Regression: with sound off the lock answers 8a00, not ca00."""
    lock = FakeLock(key)
    lock.flags = 0x8A
    session = await started(lock, key)
    assert await session.write_mode(2) == 0x8A
    assert lock.flags == 0x8A, "speed write must not touch the sound"
    assert (await session.read_settings()).speed == 2


async def test_sound_not_applied_is_uncertain(key):
    lock = FakeLock(key, "flags_ignored")
    session = await started(lock, key)
    with pytest.raises(protocol.WriteUncertainError, match="flags ca"):
        await session.write_sound(False)
    assert sum(p.startswith("0f4e") for p in lock.plain) == 1
