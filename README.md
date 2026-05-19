# ha-hiflow-ble

Home Assistant custom integration for the Hoymiles **HiFlow Pro**
(HMS-WB-series) microinverter — fully local over Bluetooth Low Energy, no cloud.

This is the BLE-equivalent of
[`ha-hoymiles-wifi`](https://github.com/suaveolent/ha-hoymiles-wifi) and uses
the [`hiflow-ble`](https://github.com/TheTiEr/hiflow-ble) library underneath.

## Hardware

Designed for the Hoymiles HMS WB-series microinverters, which advertise
themselves as `RMI-XXXXXXXXXXXX` over BLE. If you have a compatible device,
please open an issue with the model number so we can track confirmed hardware.

## Setup

1. Install via HACS (custom repo) or copy `custom_components/hiflow_ble` into
   your Home Assistant config.
2. Restart Home Assistant.
3. The integration auto-discovers `RMI-*` BLE devices. Open
   **Settings → Devices & Services**, you should see the inverter listed.
4. Click **Add**. The S-Miles app **must be closed** during pairing — the
   inverter only accepts one BLE central at a time.
5. The integration pairs (V0 handshake), extracts the per-device session
   key, and creates sensors, a power-limit slider, reboot/on/off buttons,
   and a connectivity binary sensor.

## Bluetooth requirements

The Home Assistant host needs access to a Bluetooth Low Energy adapter that
sees the inverter — either a local USB/built-in adapter or an
[ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)
in range. The HA `bluetooth` integration must be enabled.

## What works

- Sensors: PV string voltage/current/power/energy (per port), inverter AC
  voltage/current/power/frequency/PF/temperature, DTU power and lifetime/today
  energy.
- Number: power limit (0–100 %).
- Buttons: restart DTU, turn on/off inverter, reboot inverter.
- Binary sensor: BLE connectivity.

## Known quirks

- If you've connected with the S-Miles app and now HA can't connect, kill the
  app or force-stop it — the inverter only advertises while no central is
  bonded.
- On the first pairing, you may need to wait a moment while the device sets up
  its BLE bond. If pairing fails, factory-reset the pairing on the device
  (S-Miles app: "remove device") and try again.
