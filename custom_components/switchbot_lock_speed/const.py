"""Constants for SwitchBot Lock Speed."""

DOMAIN = "switchbot_lock_speed"

# Same keys as the official SwitchBot integration, so its lock entries can be reused.
CONF_KEY_ID = "key_id"
CONF_ENCRYPTION_KEY = "encryption_key"
SWITCHBOT_DOMAIN = "switchbot"
# Only this model is verified; other SwitchBot locks may not have the setting.
SWITCHBOT_LOCK_ULTRA = "lock_ultra"

SWITCHBOT_MANUFACTURER_ID = 0x0969

# Mode byte -> option key. 0x01 = Standard is confirmed on the lock. 0x00 = Max and
# 0x02 = Low are inferred (0x00 is the state before and after both recordings, Max is
# the default); the entity reads the real byte, so a wrong guess shows up as soon as
# the mode is changed in the SwitchBot app.
MODES: dict[int, str] = {0x00: "max", 0x01: "standard", 0x02: "low"}
MODE_VALUES: dict[str, int] = {name: value for value, name in MODES.items()}
