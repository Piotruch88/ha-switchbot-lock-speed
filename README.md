# SwitchBot Lock Speed for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

Adds a **Motor speed** select (Max Mode / Standard / Low) and a **Sound** switch to a **SwitchBot Lock Ultra**, controlled locally over Bluetooth. No cloud, no SwitchBot Hub.

The official SwitchBot integration locks and unlocks the door but does not expose the motor speed or sound settings. This integration adds only those settings and leaves everything else to the official integration.

> **Unofficial project.** It is not affiliated with or endorsed by SwitchBot / Wonderlabs. It writes settings to your lock using commands captured from the official app. Use at your own risk.

[Polski opis niżej](#polski)

## Status

| | |
|---|---|
| Lock model | SwitchBot **Lock Ultra** only. Other SwitchBot locks are not offered in setup and may not have this setting. |
| Tested | One Lock Ultra, Home Assistant 2026.10 (local adapter), test suite on Home Assistant 2026.2 |
| `Standard` (0x01) | Confirmed on the lock and in the SwitchBot app |
| `Max Mode` (0x00), `Low` (0x02) | Inferred from app captures. Please open an issue if the app shows a different mode |
| Sound on/off | Captured from the app (flag `0x40` of the settings register) |

## Requirements

- Home Assistant with a working **Bluetooth** integration that can *connect* to the lock: a local adapter or an [ESPHome Bluetooth proxy](https://esphome.io/projects/?type=bluetooth) near the door.
- The lock's **key ID** and **encryption key**. If the lock is already set up in the official **SwitchBot Bluetooth** integration with its encryption key, they are reused automatically.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/Piotruch88/ha-switchbot-lock-speed`, category **Integration**.
2. Install **SwitchBot Lock Speed** and restart Home Assistant.

### Manual

Copy `custom_components/switchbot_lock_speed` to `/config/custom_components/` and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → SwitchBot Lock Speed**

- Pick your Lock Ultra from the list (taken from the official SwitchBot integration), or choose **Manual** and enter the address, key ID and encryption key.
- A test read is done before the entry is saved. If it fails, the dialog shows the stage and the reason (`lookup`, `connect`, `session init`, `command`).

## Usage

The entity `select.<lock>_motor_speed` has the options `max`, `standard` and `low`:

```yaml
action: select.select_option
target:
  entity_id: select.front_door_motor_speed
data:
  option: low
```

The switch `switch.<lock>_sound` turns the lock's sounds on and off:

```yaml
action: switch.turn_off
target:
  entity_id: switch.front_door_sound
```

- Both entities come from one read of the lock's settings register, at startup and after every change. The lock is **not polled** periodically, to save battery. To refresh after changing a setting in the SwitchBot app, use `homeassistant.update_entity` on either entity.
- Attributes: `raw_setting` (raw 5-byte read), `last_read`, `last_error`.

Example: set the speed before unlocking. Run the steps one after the other, because the lock accepts one Bluetooth connection at a time:

```yaml
alias: Quiet unlock
mode: single
sequence:
  - action: select.select_option
    continue_on_error: true
    target:
      entity_id: select.front_door_motor_speed
    data:
      option: low
  - delay: "00:00:03"
  - action: lock.unlock
    target:
      entity_id: lock.front_door
```

## Safety behaviour

- A speed or sound command is sent **once** per change and is **never retried**. Only connecting is retried, and nothing has been sent at that point.
- `Speed/Sound command was sent but not confirmed`: the command may have reached the lock. Check the SwitchBot app before trying again.
- `Speed/Sound not changed`: nothing was written.
- The integration sends no lock, unlock, calibration, key or firmware commands.

## Troubleshooting

| Message | Meaning / fix |
|---|---|
| `connect: lock busy or unreachable … No backend with an available connection slot` | The lock's single connection is in use by the SwitchBot app on a phone nearby or by the official integration. The integration retries for about 45 s. Close the app. |
| `… no scanner is currently scanning` | Your Bluetooth adapter stopped scanning. Reload the Bluetooth integration or restart Home Assistant, and consider a [recommended adapter](https://www.home-assistant.io/integrations/bluetooth/#known-working-high-performance-adapters) on a USB 2.0 port, or an ESPHome proxy. |
| `session init: … UnknownObject … StartNotify` | Stale BlueZ GATT cache. It is handled automatically (cache cleared, one reconnect). |

Debug log: **Settings → Devices & services → SwitchBot Lock Speed → ⋮ → Enable debug logging**.

## How it works

The session is the same as for other encrypted SwitchBot devices (see [pySwitchbot](https://github.com/sblibs/pySwitchbot)): request an IV (`57 000000 0f2103 <key_id>`), then AES-128-CTR commands on characteristic `cba20002-…`, with replies on `cba20003-…`.

Speed and sound live in one settings register, `0401`:

| Purpose | Plaintext command | Reply |
|---|---|---|
| Read settings | `0f4f0401` | `<flags> 00 <speed> 00 c0` |
| Write settings | `0f4e0401 00 <mask> <value> <speed>` | `<flags> 00` |
| Set speed | `0f4e0401 00 00 00 <speed>` | `<flags> 00` |
| Sound on / off | `0f4e0401 00 40 40 ff` / `0f4e0401 00 40 00 ff` | `ca 00` / `8a 00` |

`<flags>` bit `0x40` is the sound (`0xca` = on, `0x8a` = off). A write changes only the flag bits in `<mask>`, and speed `ff` leaves the speed unchanged. The other flag bits are not decoded yet.

`tools/read_lock_speed.py` reads the mode from a PC with `bleak`. It is read-only and useful for checking a lock outside Home Assistant.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

The tests run against a simulated lock with a random key. CI runs them together with `hassfest` and HACS validation.

## Credits & license

Session framing follows [pySwitchbot](https://github.com/sblibs/pySwitchbot) (MIT). This project is MIT-licensed, see [LICENSE](LICENSE). SwitchBot is a trademark of its owner and is used here only to describe compatibility.

---

## Polski

Integracja dodaje do zamka **SwitchBot Lock Ultra** encję **Prędkość silnika** (Max Mode / Standard / Low) i przełącznik **Dźwięk**, sterowane lokalnie przez Bluetooth. Jest nieoficjalna i niezwiązana z firmą SwitchBot. Używasz na własne ryzyko.

**Wymagania:**
- Bluetooth w Home Assistant, który może połączyć się z zamkiem (adapter lub proxy ESPHome).
- Klucz zamka (key ID i klucz szyfrowania). Jeśli zamek jest w oficjalnej integracji SwitchBot z kluczem, zostanie użyty automatycznie.

**Instalacja:**
1. HACS → Custom repositories → ten adres repozytorium, kategoria Integration.
2. Zainstaluj, zrestartuj HA.
3. Ustawienia → Urządzenia i usługi → Dodaj integrację → SwitchBot Lock Speed.

**Ważne:**
- Komenda zmiany prędkości lub dźwięku jest wysyłana raz i nigdy nie jest ponawiana. Ponawiane jest tylko łączenie, zanim cokolwiek zostanie wysłane.
- Zamek przyjmuje jedno połączenie naraz. Aplikacja SwitchBot otwarta na telefonie w pobliżu może blokować HA.
- Ustawienia są odczytywane przy starcie i po każdej zmianie. Zmiany z aplikacji odświeżysz akcją `homeassistant.update_entity`.
- `Standard` jest potwierdzony. `Max` i `Low` wywnioskowano z nagrań aplikacji. Jeśli aplikacja pokazuje inny tryb, zgłoś issue.
