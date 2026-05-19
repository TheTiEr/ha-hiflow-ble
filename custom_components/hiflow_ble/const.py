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
CONF_DTU_SERIAL_NUMBER = "dtu_serial_number"
CONF_INVERTERS = "inverters"
CONF_PORTS = "ports"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TIMEOUT = "timeout"

DEFAULT_UPDATE_INTERVAL_SECONDS = 30
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
