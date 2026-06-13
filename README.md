# ha-hiflow-ble

Home Assistant custom integration for **Hoymiles HiFlow Pro** (HMS-\*-WB series)
microinverters — fully local over Bluetooth Low Energy, no cloud dependency.

This is the BLE-equivalent of
[ha-hoymiles-wifi](https://github.com/suaveolent/ha-hoymiles-wifi) and uses the
[hiflow-ble](https://github.com/TheTiEr/hiflow-ble) Python library underneath.

---

## Confirmed hardware

| Model | BLE name prefix | Serial prefix | Rated power |
|---|---|---|---|
| HMS-800-2WB (HiFlow Pro 800) | `RMI-` | `0x1610` | 800 W |
| HMS-1600-4WB (HiFlow Pro 1600) | `RMI-` | `0x1164` | 1600 W |

Other HMS-WB models likely work. If yours does, open an issue with the model
name and inverter serial prefix (first 4 hex chars) so we can extend the table.

---

## Prerequisites

### Bluetooth

The HA host needs a Bluetooth Low Energy adapter that can reach the inverter:

- **Built-in or USB adapter** directly on the HA host, or
- **[ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)**
  (set `active: true`) placed within a few metres of the inverter.

The HA `bluetooth` integration must be enabled. Passive proxies are not
sufficient — the integration needs to write GATT characteristics.

### S-Miles app

Before pairing you need the **BLE PIN** you configured in the S-Miles app
(*Bluetooth connection PIN* in the app settings — not the account password).
If you never set one, the default is usually empty.

The S-Miles app **must be fully closed** during pairing and normal operation.
The inverter only accepts one BLE central at a time. On Android, force-stop
the app from the system settings to be sure.

---

## Installation

### HACS (recommended)

1. Add this repository as a **custom repository** in HACS
   (*HACS → Integrations → ⋮ → Custom repositories*,
   category: *Integration*).
2. Search for *HiFlow BLE* and install it.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/hiflow_ble` folder into your HA
   `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Setup

1. Open **Settings → Devices & Services → Add integration** and search for
   **HiFlow BLE**.
2. If the inverter was already discovered via Bluetooth, it appears in the
   list automatically. Otherwise pick the BLE address from the dropdown.
3. Enter your **BLE PIN** (the one from the S-Miles app). Leave empty if you
   never set one.
4. The integration pairs with the inverter (V0 handshake), extracts the
   per-device encryption key (`encRand`), and probes the inverter for its
   serial numbers and port layout.
5. Within a few seconds the device and all entities appear.

> **Tip:** If pairing fails, check that the S-Miles app is completely closed
> and try again. If it still fails, remove the device from the app
> (*device settings → disconnect / factory reset BLE*) and re-add it here.

---

## Entities

### Sensors

#### Per inverter (AC side)

| Entity | Unit | Notes |
|---|---|---|
| AC power | W | `sgs_data.active_power × 0.1` |
| AC reactive power | VAr | `sgs_data.reactive_power × 0.1` |
| AC current | A | `sgs_data.current × 0.01` |
| Grid voltage | V | `sgs_data.voltage × 0.1` |
| Grid frequency | Hz | `sgs_data.frequency × 0.01` |
| Inverter power factor | % | `sgs_data.power_factor × 0.1` |
| Inverter temperature | °C | `sgs_data.temperature × 0.1` |
| Inverter warning | — | Raw `sgs_data.warning_number` diagnostic |

#### Per PV port (DC side)

| Entity | Unit | Notes |
|---|---|---|
| Port N DC voltage | V | `pv_data.voltage × 0.1` |
| Port N DC current | A | `pv_data.current × 0.01` |
| Port N DC power | W | `pv_data.power × 0.1` |
| Port N total energy | Wh | Lifetime yield |
| Port N daily energy | Wh | Resets at midnight |
| Port N error code | — | Operational status code (0 = normal) |

#### Computed aggregates

| Entity | Unit | Notes |
|---|---|---|
| AC daily energy | Wh | Sum of all port daily energies |
| Total energy | Wh | Sum of all port lifetime energies |

### Numbers (sliders)

| Entity | Range | Notes |
|---|---|---|
| Power limit | 0–100 % | Always available; maps to `limit_power_mypower` (tenths of %) on the device |
| Power limit (W) | 0–*rated power* W | Shown only when rated power is known; converts Watt ↔ percent automatically |

Both sliders are **synchronised** — changing one updates the other on the next
poll. The device wire format is `A:{percent×10},B:0,C:0`.

### Buttons

| Entity | Action |
|---|---|
| Restart | Reboot the DTU (BLE link drops briefly) |
| Turn on | Start the inverter (re-enables output) |
| Turn off | Shut down the inverter output |

### Binary sensor

| Entity | Notes |
|---|---|
| BLE connectivity | `on` while the BLE GATT link is established |

---

## Options

Open *Settings → Devices & Services → HiFlow BLE → Configure* to adjust:

| Option | Default | Min | Notes |
|---|---|---|---|
| Polling interval | 30 s | 5 s | How often HA fetches RealData from the inverter |
| BLE request timeout | 15 s | 5 s | Per-request BLE timeout before marking the request failed |
| Inverter rated power | auto | — | Used for the Watt-based power limit slider. `0` disables the Watt slider. Auto-detected from the inverter serial number prefix; set manually if your model is not in the table yet |

The rated power is auto-detected from the first two bytes of the inverter serial
number (the `SERIAL_PREFIX_RATED_POWER` table in `const.py`). If your model is
not detected, set it manually and please open an issue with your serial prefix.

---

## Known quirks

**S-Miles app conflict**
The inverter only supports one BLE connection at a time. If the S-Miles app is
open (even in the background), Home Assistant cannot connect. Force-stop the app.

**BlueZ InProgress errors**
On Linux/BlueZ, a failed connect attempt can leave the HCI in a pending
`LE_Create_Connection` state for up to 30 seconds. The integration detects this
and automatically waits before retrying — you may see a 30-second pause in the
logs.

**encRand rotation**
The per-device encryption key (`encRand`) is normally stable across power cycles.
It can change after a factory reset or firmware update. If you see persistent
decryption errors in the log (`GCM tag mismatch`), delete and re-add the
integration to trigger a fresh pairing.

**Port error code at night**
`pv_data.error_code = 0x03000000` (decimal 50331648) is the normal status when
the inverter has no DC input — night-time, heavy cloud cover, or disconnected
panels. It is not a hardware fault.

**First poll delay**
The power-limit config coordinator polls every 5 minutes. The Watt/percent
sliders always show as available and retain their last known value between polls
(using `assumed_state`).

---

## Protocol notes

For contributors and curious readers.

### BLE GATT layout

- **Service:** `0000e0ff-3c17-d293-8e48-14fe2e4da212`
- **TX (write):** `0000ffe1-0000-1000-8000-00805f9b34fb`
- **RX (notify):** `0000ffe2-0000-1000-8000-00805f9b34fb`
- **MTU:** 512 bytes (negotiated at connect)

### Frame format

All frames share one header layout:

```
[0:2]   "HM" magic
[2:4]   cmd  (big-endian uint16)
[4:6]   tid  (big-endian uint16, monotonic)
[6:8]   CRC16-Modbus of the ciphertext
[8:10]  length = len(ciphertext) + 10
[10:N]  ciphertext
[N:N+16] AES-128-GCM auth tag  (V1 only)
```

### Encryption

**V0 — SN-keyed AES-128-CBC** (pairing only)

Used for the initial `APPInfoData` exchange to extract `encRand`.
Key and IV are derived from the 12-char serial tail of the BLE name and the
fixed salt `Hoymiles@#123456`, using triple-SHA-256.

**V1 — encRand-keyed AES-128-GCM** (all regular commands)

- Key: `triple-SHA-256(encRand)[:16]`
- Nonce: `triple-SHA-256(cmd_LE + tid_LE + encRand)[20:32]`
- AAD: `cmd_LE + tid_LE`

`encRand` is a 16-byte per-device secret, extracted during V0 pairing from
`APPInfoDataReqDTO → APPDtuInfoMO.enc_rand` (field 27). It is persisted in the
config entry and reused on every subsequent connect.

### CommCmd handshake

After every BLE (re-)connect, before the inverter will answer data requests, a
three-step application-layer handshake must complete:

1. `action=64` — login with `bleId` (a device-specific 18-digit decimal string
   derived by the same algorithm the S-Miles app uses)
   - sts=1: `bleId` is already whitelisted → proceed
   - sts=3: unknown `bleId` → step 2
2. `action=82` — submit BLE PIN to add `bleId` to the whitelist
   - sts=0: PIN correct, whitelisted
   - sts=1: wrong PIN
3. `action=104` — time-sync (`unix_ts,tz_offset_sec`)

The `bleId` is generated once per device and stored in the config entry so
subsequent reconnects skip the PIN step.

### Command codes

| Constant | Hex | Purpose |
|---|---|---|
| `CMD_APP_INFO_DATA_RES_DTO` | `0xA301` | V0 pairing — fetches `encRand` |
| `CMD_HB_RES_DTO` | `0xA302` | Heartbeat |
| `CMD_REAL_DATA_RES_DTO` | `0xA303` | Legacy RealData |
| `CMD_COMMAND_RES_DTO` | `0xA305` | Control commands (power limit, reboot, …) |
| `CMD_GET_CONFIG` | `0xA309` | Read config (power limit %, grid profile, …) |
| `CMD_SET_CONFIG` | `0xA310` | Write config (WiFi credentials, …) |
| `CMD_REAL_RES_DTO` | `0xA311` | RealDataNew (paged) |
| `CMD_NETWORK_INFO_RES` | `0xA314` | Network info |
| `CMD_APP_GET_HIST_POWER_RES` | `0xA315` | Historical power (paged) |
| `CMD_APP_GET_HIST_ED_RES` | `0xA316` | Historical daily energy |
| `CMD_COMM_CMD_RES_DTO` | `0xA318` | CommCmd handshake send |
| `CMD_COMM_CMD_STATUS_RES` | `0xA319` | CommCmd handshake poll |

### Serial number prefix → model

The first two bytes of the inverter serial (big-endian uint16) identify the
model:

| Prefix | Model | Type | Rated power |
|---|---|---|---|
| `0x1610` | HMS-800-2WB | 2×MPPT | 600/700/800 W |
| `0x1164` | HMS-1600-4WB | 4×MPPT | 1600/1800/2000 W |

---

## Contributing

Pull requests welcome. Please open an issue first for anything larger than a
bug fix so we can discuss the approach.

When reporting a bug, please include:

- HA version and integration version
- Inverter model and serial number prefix (first 4 hex chars)
- Relevant log lines (enable debug logging:
  `custom_components.hiflow_ble: debug` in your `configuration.yaml`)
- Whether the S-Miles app was closed

---

## License

MIT — see [LICENSE](LICENSE).
