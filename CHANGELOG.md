# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.3.0] - 2026-11-13

### Added
- BLE PIN is now editable in the options flow (gear icon) — previously only
  settable during initial pairing, so changing the PIN in the S-Miles app
  required deleting and re-adding the integration.
- Auto-detect rated power from the BLE name prefix (`NAME_PREFIX_RATED_POWER`),
  checked before the inverter-serial prefix: `4161` → HMS-1000-2WB (1000 W, #16),
  `1650` → HiFlow 800 (800 W, #11). Fixes the HMS-1000-2WB being mis-detected
  as an 800 W model (it shares inverter-serial prefix `0x1610` with it).
- Manual entry step (MAC + serial/BLE-name) for devices whose BLE proxy strips
  the advertised local name, reachable from "Enter address manually…" and
  automatically when nothing is auto-discovered. (#13)

### Fixed
- Update listener now reloads the config entry only when the user actually
  saved new options, not on every `entry.data` write. Previously, every V0
  re-pair (which persists a fresh `encRand`) triggered a full teardown/setup
  of all 43 entities; this compounded into reload storms (~12 in 10 minutes)
  when the inverter woke up in the morning. (#25, closes #19)
- Coordinator now bails via the existing unreachable-handling path when no
  connectable `BLEDevice` is visible, instead of silently falling back to a
  plain `BleakClient.connect()` with no retry/backoff that re-hammered
  ESPHome BLE proxies on every poll while the device stayed invisible. (#22,
  closes #27)
- Home Assistant's configured timezone (DST-aware) is now sent to the
  inverter during the CommCmd time-sync handshake, instead of a hard-coded
  `OFFSET = 3600` (CET). The fixed offset made the inverter's clock an hour
  off during CEST, which caused daily false S-Miles "offline" alarms at
  08:00. (#24, addresses #18 — pairs with hiflow-ble#4 for the remaining
  `request.offset` path)
- Config-flow crash (`KeyError: 'address'`) when a BLE advertisement carries
  no local name. (#13)
- `KeyError` on an empty `user_input` dict in the config flow, and devices
  silently hidden from the picker when only a passive-only BLE scanner (no
  `bluetooth_proxy: active: true`) is in range — now shows a `not_connectable`
  error instead. (#14)
- Serial prefix `0x1620` (HMS-1600/2000-4WB) resolved as `"Unknown"` and
  logged a warning per entity — fixed in hiflow-ble#5, which this integration
  picks up automatically. (closes #20, #28)
- Turn on / turn off / restart buttons had no effect on some units — fixed in
  hiflow-ble#6, which this integration picks up automatically. (closes #23)

## [0.2.0] - 2026-07-26

### Added
- Watt-based power limit slider with serial-prefix rated-power auto-detection.
- Debounce and dedup power-limit writes to protect inverter flash.

### Fixed
- Prevent BLE connection cycling and concurrent reconnect races (#9, #7).
- Single connection owner: only the data coordinator drives reconnects.
- Power limit sliders always available regardless of coordinator state.
- Prevent BLE idle-disconnect cycling and `bleak_retry_connector` warning.

### Docs
- Overhauled README with complete entity list, protocol details, quirks.
- Confirmed HF-800-WB hardware and corrected `error_code 0x03000000` note.

## [0.1.0] - 2026-06-13

### Added
- First public release: local BLE control of Hoymiles HiFlow Pro
  micro-inverters in Home Assistant, no cloud/Wi-Fi bridge required.
- Auto-discovery of `RMI-*` devices via Bluetooth with guided BLE-PIN pairing.
- Real-time sensors: AC power, voltage, current, frequency, power factor,
  temperature, daily & total energy per PV port.
- Power limit control (percent slider always available; Watt slider once
  rated power is set in options).
- `pv_hw_part_number` diagnostic sensor per PV port.
- Restart / turn on / turn off buttons, BLE connectivity binary sensor.
- Non-blocking startup, stale-`encRand` auto-repair, configurable polling
  interval and timeout. German and English translations.

[0.3.0]: https://github.com/TheTiEr/ha-hiflow-ble/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/TheTiEr/ha-hiflow-ble/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/TheTiEr/ha-hiflow-ble/releases/tag/v0.1.0
