"""Utility helpers for the HiFlow BLE integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from hiflow_ble.hiflow import HiFlow
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
) -> dict[str, Any]:
    """Pair with the inverter, extract encRand, probe RealData.

    Returns a dict with: ``enc_rand`` (hex), ``dtu_serial_number``,
    ``inverters`` (list of hex SN strings), ``ports`` (list of dicts).

    Raises :class:`PairingFailed` if the V0 handshake doesn't yield encRand
    (usually because the S-Miles app is still bonded), or
    :class:`CannotConnect` if the BLE link itself fails.
    """
    if sn is None:
        sn = derive_sn_from_local_name(local_name)
    if sn is None:
        raise PairingFailed("cannot derive SN from BLE name and none provided")

    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    target = ble_device if ble_device is not None else address

    hiflow = HiFlow(target, sn=sn, timeout=DEFAULT_TIMEOUT_SECONDS)
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

        real_data = await hiflow.async_get_real_data_new()
        if real_data is None:
            raise CannotConnect("inverter returned no RealData after pairing")

        return {
            "enc_rand": hiflow.enc_rand.hex(),
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
