"""HiFlow BLE Home Assistant integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from hiflow_ble.hiflow import HiFlow

from .const import (
    CONF_ADDRESS,
    CONF_BLE_ID,
    CONF_BLE_PIN,
    CONF_ENC_RAND,
    CONF_SN,
    CONF_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
    HASS_DATA_COORDINATOR,
    HASS_HIFLOW,
)
from .coordinator import (
    HiFlowConfigUpdateCoordinator,
    HiFlowRealDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HiFlow BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    address: str = entry.data[CONF_ADDRESS]
    enc_rand_hex: str = entry.data[CONF_ENC_RAND]
    sn: str = entry.data[CONF_SN]
    ble_id: str = entry.data.get(CONF_BLE_ID, "")
    pin: str = entry.data.get(CONF_BLE_PIN, "")
    # Options (set via gear icon) take priority over legacy data values.
    timeout = entry.options.get(
        CONF_TIMEOUT, entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT_SECONDS)
    )
    update_interval = timedelta(
        seconds=entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS),
        )
    )

    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    target = ble_device if ble_device is not None else address

    hiflow = HiFlow(
        target,
        enc_rand=bytes.fromhex(enc_rand_hex),
        sn=sn,
        timeout=timeout,
        ble_id=ble_id,
        pin=pin,
    )

    data_coordinator = HiFlowRealDataUpdateCoordinator(
        hass, hiflow, entry, update_interval
    )
    config_coordinator = HiFlowConfigUpdateCoordinator(
        hass, hiflow, entry, timedelta(seconds=DEFAULT_CONFIG_UPDATE_INTERVAL_SECONDS)
    )
    hass.data[DOMAIN][entry.entry_id] = {
        HASS_HIFLOW: hiflow,
        HASS_DATA_COORDINATOR: data_coordinator,
        HASS_CONFIG_COORDINATOR: config_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Do NOT block setup on a BLE connect attempt — the inverter may be
    # unreachable at HA startup (proxy too far away, overnight power-off, …).
    # The coordinator will connect and run the CommCmd handshake on its first
    # scheduled poll; entities show as unavailable in the meantime.
    entry.async_create_background_task(
        hass,
        data_coordinator.async_refresh(),
        name="hiflow_ble_initial_refresh",
    )

    # Reload the entry when the user saves new options (e.g. changed interval).
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))

    return True


async def _async_reload_on_options_change(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the config entry so new options (e.g. polling interval) take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down the entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        stash = hass.data[DOMAIN].pop(entry.entry_id, None)
        if stash and (hiflow := stash.get(HASS_HIFLOW)):
            try:
                await hiflow.disconnect()
            except Exception as err:
                _LOGGER.debug("disconnect() on unload failed: %s", err)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry
) -> bool:
    """Allow removing the device entry from the UI."""
    return True
