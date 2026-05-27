"""Config flow for the HiFlow BLE integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_ADDRESS,
    CONF_BLE_ID,
    CONF_BLE_PIN,
    CONF_DTU_SERIAL_NUMBER,
    CONF_ENC_RAND,
    CONF_INVERTERS,
    CONF_NAME_LOCAL,
    CONF_PORTS,
    CONF_SN,
    CONF_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
)
from .error import CannotConnect, PairingFailed
from .util import async_pair_and_probe, derive_sn_from_local_name

_LOGGER = logging.getLogger(__name__)


class HiFlowBLEConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discovery + manual + pair flow for a single HiFlow Pro."""

    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._address: str | None = None
        self._local_name: str | None = None
        self._sn: str | None = None
        self._pin: str = ""

    # ----- Bluetooth-triggered discovery -----

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth-discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self._address = discovery_info.address
        self._local_name = discovery_info.name
        self._sn = derive_sn_from_local_name(discovery_info.name)
        if not self._sn:
            return self.async_abort(reason="unsupported_device")

        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_pair()

    # ----- Manual user-initiated entry -----

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual fallback when no discovery is available."""
        errors: dict[str, str] = {}

        current_addresses = self._async_current_ids()
        seen: list[tuple[str, str]] = []
        for info in async_discovered_service_info(self.hass):
            if info.address in current_addresses:
                continue
            if not derive_sn_from_local_name(info.name):
                continue
            seen.append((info.address, info.name))

        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            for addr, name in seen:
                if addr == self._address:
                    self._local_name = name
                    break
            self._sn = derive_sn_from_local_name(self._local_name)
            await self.async_set_unique_id(self._address)
            self._abort_if_unique_id_configured()
            return await self.async_step_pair()

        if not seen:
            return self.async_show_form(step_id="user", errors={"base": "no_devices"})

        options = {addr: name for addr, name in seen}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
            errors=errors,
        )

    # ----- V0 pairing + RealData probe -----

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for BLE PIN, then run pairing + probe."""
        assert self._address is not None
        assert self._sn is not None

        if user_input is None:
            # Show the form with a PIN field — required to whitelist our bleId.
            return self.async_show_form(
                step_id="pair",
                data_schema=vol.Schema(
                    {vol.Required(CONF_BLE_PIN): str}
                ),
                description_placeholders={
                    "name": self._local_name or self._address,
                    "address": self._address,
                },
            )

        self._pin = user_input.get(CONF_BLE_PIN, "")

        errors: dict[str, str] = {}
        try:
            probed = await async_pair_and_probe(
                self.hass,
                self._address,
                sn=self._sn,
                local_name=self._local_name,
                pin=self._pin,
            )
        except PairingFailed as err:
            _LOGGER.warning("Pairing failed for %s: %s", self._address, err)
            errors["base"] = "pairing_failed"
        except CannotConnect as err:
            _LOGGER.warning("Cannot connect to %s: %s", self._address, err)
            errors["base"] = "cannot_connect"
        else:
            return self.async_create_entry(
                title=self._local_name or self._address,
                data={
                    CONF_ADDRESS: self._address,
                    CONF_NAME_LOCAL: self._local_name,
                    CONF_SN: self._sn,
                    CONF_ENC_RAND: probed["enc_rand"],
                    CONF_BLE_ID: probed["ble_id"],
                    CONF_BLE_PIN: self._pin,
                    CONF_DTU_SERIAL_NUMBER: probed["dtu_serial_number"],
                    CONF_INVERTERS: probed["inverters"],
                    CONF_PORTS: probed["ports"],
                    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL_SECONDS,
                    CONF_TIMEOUT: DEFAULT_TIMEOUT_SECONDS,
                },
            )

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema(
                {vol.Required(CONF_BLE_PIN): str}
            ),
            description_placeholders={
                "name": self._local_name or self._address,
                "address": self._address,
            },
            errors=errors,
        )
