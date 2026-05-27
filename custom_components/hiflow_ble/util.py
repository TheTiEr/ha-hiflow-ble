"""Utility helpers for the HiFlow BLE integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from hiflow_ble.hiflow import HiFlow, generate_ble_id
from hiflow_ble.hoymiles import generate_inverter_serial_number

from .const import CONF_ENC_RAND, DEFAULT_TIMEOUT_SECONDS
from .error import CannotConnect, PairingFailed

_LOGGER = logging.getLogger(__name__)


def derive_sn_from_local_name(local_name: str | None) -> str | None:
    """Extract the 12-char serial tail from a 'RMI-XXXXXXXXXXXX' BLE name."""
    if not local_name:
        return None
    for prefix in ("RMI-", "MI-", "MSA-", "RMSA-"):
        if local_name.startswith(prefix):
            return local_name.split("-", 1)[1][-12:].upper()
    return None


async def async_pair_and_probe(
    hass: HomeAssistant,
    address: str,
    sn: str | None = None,
    local_name: str | None = None,
    pin: str = "",
) -> dict[str, Any]:
    """Pair with the inverter, extract encRand, run CommCmd handshake, probe RealData.

    Returns a dict with: ``enc_rand`` (hex), ``ble_id``, ``dtu_serial_number``,
    ``inverters`` (list of hex SN strings), ``ports`` (list of dicts).

    ``pin``: the user's custom BLE PIN (set via the S-Miles app).  Required on
    first pair when the generated bleId is not yet in the device's whitelist.

    Raises :class:`PairingFailed` if the V0 handshake doesn't yield encRand
    or the CommCmd handshake fails, or :class:`CannotConnect` on BLE failure.
    """
    if sn is None:
        sn = derive_sn_from_local_name(local_name)
    if sn is None:
        raise PairingFailed("cannot derive SN from BLE name and none provided")

    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    target = ble_device if ble_device is not None else address

    # Generate a stable bleId for this device — persisted in the config entry
    # so the same ID is reused on every reconnect (avoids repeated PIN prompts).
    ble_id = generate_ble_id()

    hiflow = HiFlow(target, sn=sn, timeout=DEFAULT_TIMEOUT_SECONDS, ble_id=ble_id, pin=pin)
    try:
        try:
            await hiflow.connect()
        except Exception as err:
            _LOGGER.debug("connect() failed: %s", err)
            raise CannotConnect(str(err)) from err

        try:
            await hiflow.async_extract_enc_rand()
        except Exception as err:
            _LOGGER.debug("V0 pairing failed: %s", err)
            raise PairingFailed(str(err)) from err

        # CommCmd handshake: login (action=64) + optional PIN (action=82) + time-sync (action=104).
        # The device won't answer V1 RealData requests until this succeeds.
        ok = await hiflow.async_do_comm_cmd_handshake(ble_id=ble_id, pin=pin)
        if not ok:
            raise PairingFailed(
                "CommCmd handshake failed — check the BLE PIN and make sure the "
                "S-Miles app is not connected."
            )

        real_data = await hiflow.async_get_real_data_new()
        if real_data is None:
            raise CannotConnect("inverter returned no RealData after pairing")

        return {
            "enc_rand": hiflow.enc_rand.hex(),
            "ble_id": ble_id,
            "dtu_serial_number": real_data.device_serial_number,
            "inverters": [
                generate_inverter_serial_number(s.serial_number)
                for s in real_data.sgs_data
            ],
            "ports": [
                {
                    "inverter_serial_number": generate_inverter_serial_number(
                        p.serial_number
                    ),
                    "port_number": p.port_number,
                }
                for p in real_data.pv_data
            ],
        }
    finally:
        await hiflow.disconnect()


async def async_check_and_update_enc_rand(
    hass: HomeAssistant, config_entry: ConfigEntry, hiflow: HiFlow, enc_rand: str
) -> None:
    """Persist a refreshed encRand back to the config entry if it changed."""
    old = config_entry.data.get(CONF_ENC_RAND)
    if old == enc_rand:
        return
    _LOGGER.debug("Updating enc_rand %s → %s", old, enc_rand)
    hiflow.enc_rand = bytes.fromhex(enc_rand)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_ENC_RAND: enc_rand}
    )
