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

DEFAULT_UPDATE_INTERVAL_SECONDS = 30
DEFAULT_RATED_POWER_W = 0  # 0 = not configured, Watt entity is disabled
RATED_POWER_OPTIONS = [400, 600, 800, 1000, 1200, 1500, 1600, 2000]
MIN_UPDATE_INTERVAL_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 15
MIN_TIMEOUT_SECONDS = 5
DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS = 60 * 5
DEFAULT_APP_INFO_UPDATE_INTERVAL_SECONDS = 60 * 60 * 2

# hass.data slot keys
HASS_DATA_COORDINATOR = "data_coordinator"
HASS_CONFIG_COORDINATOR = "config_coordinator"
HASS_APP_INFO_COORDINATOR = "app_info_coordinator"
HASS_HIFLOW = "hiflow"
