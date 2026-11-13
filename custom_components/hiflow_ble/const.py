"""Constants for the HiFlow BLE integration."""

DOMAIN = "hiflow_ble"
NAME = "HiFlow BLE"
CONFIG_VERSION = 1

ISSUE_URL = "https://github.com/TheTiEr/ha-hiflow-ble/issues"

# Config-entry keys
CONF_ADDRESS = "address"             # BLE MAC
CONF_NAME_LOCAL = "local_name"       # advertised name, e.g. RMI-XXX
CONF_SN = "sn"                       # 12-char device serial tail
CONF_ENC_RAND = "enc_rand"           # hex string
CONF_BLE_ID = "ble_id"              # bleId generated during first pairing (persisted)
CONF_BLE_PIN = "ble_pin"            # user's BLE PIN set in the S-Miles app
CONF_DTU_SERIAL_NUMBER = "dtu_serial_number"
CONF_INVERTERS = "inverters"
CONF_PORTS = "ports"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TIMEOUT = "timeout"
CONF_RATED_POWER_W = "rated_power_w"

# Sentinel used in the discovery dropdown to trigger manual MAC/serial entry.
MANUAL_ENTRY = "__manual__"

DEFAULT_UPDATE_INTERVAL_SECONDS = 30
DEFAULT_RATED_POWER_W = 0  # 0 = not configured, Watt entity is disabled
RATED_POWER_OPTIONS = [400, 600, 800, 1000, 1200, 1500, 1600, 2000]

# First 4 chars of the BLE-advertised serial (the RMI-XXXX… local name / CONF_SN)
# → rated power in Watt. This is checked *before* SERIAL_PREFIX_RATED_POWER
# because some models share an inverter-serial prefix but differ in rated power
# (e.g. the HMS-1000-2WB reports inverter-serial prefix 0x1610 like the 800 W
# model, so it can only be told apart by its RMI name prefix — see issue #16).
# Keys are uppercase. Extend as users report new models via GitHub issues.
NAME_PREFIX_RATED_POWER: dict[str, int] = {
    "1650": 800,   # HiFlow 800    (issue #11)
    "4161": 1000,  # HMS-1000-2WB  (issue #16)
}

# First 2 bytes of inverter serial number (big-endian uint16) → rated power in Watt.
# Used as a fallback when the BLE name prefix is unknown.
# Extend this table as users report new models via GitHub issues.
SERIAL_PREFIX_RATED_POWER: dict[int, int] = {
    0x1610: 800,   # HMS-800-2WB  (HiFlow Pro 800)
    0x1164: 1600,  # HMS-1600-4WB (HiFlow Pro 1600)
}
MIN_UPDATE_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 15
MIN_TIMEOUT_SECONDS = 5
DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS = 60 * 5
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 45  # shorter than the ~90 s inverter idle timeout

# hass.data slot keys
HASS_DATA_COORDINATOR = "data_coordinator"
HASS_CONFIG_COORDINATOR = "config_coordinator"
HASS_HEARTBEAT_COORDINATOR = "heartbeat_coordinator"
HASS_HIFLOW = "hiflow"
# Snapshot of entry.options taken at setup. The update listener compares
# against it so that writes to entry.data (the rotating encRand) do not
# trigger a reload — see _async_reload_on_options_change.
HASS_OPTIONS_SNAPSHOT = "options_snapshot"
