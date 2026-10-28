"""Read the current speed mode and sound setting from a Lock Ultra with bleak, outside Home Assistant.

Read-only: this tool cannot change the setting. Requires `pip install bleak cryptography`.

Usage: python tools/read_lock_speed.py lock.json
where lock.json is {"address": "AA:BB:CC:DD:EE:FF", "key_id": "xx", "encryption_key": "<32 hex>"}.
Prints the speed byte and raw payload only; the key is never printed. Keep lock.json private.
"""
import asyncio
import importlib.util
import json
import pathlib
import sys

from bleak import BleakClient, BleakScanner

_PATH = pathlib.Path(__file__).parents[1] / "custom_components" / "switchbot_lock_speed" / "protocol.py"
_spec = importlib.util.spec_from_file_location("protocol", _PATH)
protocol = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = protocol  # dataclasses look the module up while decorating
_spec.loader.exec_module(protocol)

NAMES = {0: "max (Max Mode, assumed)", 1: "standard (Standard, confirmed)", 2: "low (Low, assumed)"}


async def main(path: str) -> None:
    cfg = json.load(open(path, encoding="utf-8-sig"))
    print("Scanning for", cfg["address"], "...")
    device = await BleakScanner.find_device_by_address(cfg["address"], timeout=20)
    if device is None:
        print("Lock not found in scan")
        return
    async with BleakClient(device, timeout=20) as client:
        print("Connected")
        session = protocol.SpeedSession(client, int(cfg["key_id"], 16), bytes.fromhex(cfg["encryption_key"]))
        await session.start()
        s = await session.read_settings()
        print(
            f"Speed byte {s.speed:02x} -> {NAMES.get(s.speed, 'unknown')} | sound {'on' if s.sound else 'off'} "
            f"| raw {s.raw} | write_sent={session.write_sent}"
        )
    print("Disconnected")


asyncio.run(main(sys.argv[1]))
