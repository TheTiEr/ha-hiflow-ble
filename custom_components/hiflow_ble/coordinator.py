"""Coordinators for the HiFlow BLE integration.

Each subclass implements ``_async_update_data`` against one HiFlow query.
The base class provides two robustness primitives that every subclass uses:

* :meth:`_ensure_connected` — reconnect if the BLE link dropped between polls.
  The library already retries with backoff internally, but bailing out here
  prevents wasted work when the device is unreachable for the whole interval.

* :meth:`_call_with_repair` — wraps a HiFlow call so that an
  :class:`hiflow_ble.errors.EncRandStale` raised by the library triggers a
  fresh V0 pairing handshake, persists the new ``encRand`` to the config entry,
  and retries the original call exactly once.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from hiflow_ble.errors import BleLinkError, EncRandStale
from hiflow_ble.hiflow import HiFlow

from .const import CONF_ADDRESS, DOMAIN
from .util import async_check_and_update_enc_rand

_LOGGER = logging.getLogger(__name__)


class HiFlowDataUpdateCoordinator(DataUpdateCoordinator):
    """Base coordinator. Holds a *persistent* HiFlow client."""

    def __init__(
        self,
        hass: HomeAssistant,
        hiflow: HiFlow,
        config_entry: ConfigEntry,
        update_interval: timedelta,
    ) -> None:
        self._hiflow = hiflow
        self._config_entry = config_entry
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    def get_hiflow(self) -> HiFlow:
        return self._hiflow

    async def _ensure_connected(self) -> bool:
        """Reconnect if dropped; run CommCmd handshake on fresh connections.

        Returns False if the BLE link can't be established at all.  A handshake
        failure is logged but does *not* cause a False return — the coordinator
        will attempt data requests anyway; they'll return None (unavailable)
        if the device still refuses them.
        """
        was_connected = self._hiflow.is_connected
        if was_connected and self._hiflow._handshake_done:
            return True

        if not was_connected:
            # Refresh the BLEDevice so bleak_retry_connector uses up-to-date
            # advertising data. After a long uptime or overnight downtime the
            # cached BLEDevice object may be stale; a fresh lookup avoids
            # connection failures caused by outdated metadata.
            fresh = bluetooth.async_ble_device_from_address(
                self.hass,
                self._config_entry.data[CONF_ADDRESS],
                connectable=True,
            )
            if fresh is not None:
                self._hiflow.address = fresh
            try:
                await self._hiflow._ensure_connected()  # uses backoff internally
            except BleLinkError as err:
                _LOGGER.debug("HiFlow reconnect failed: %s", err)
                return False
            except Exception as err:
                _LOGGER.debug("HiFlow reconnect raised unexpectedly: %s", err)
                return False

        # Fresh (or handshake-less) connection — run the CommCmd handshake.
        # This covers: first setup, overnight device reboot, any BLE link drop.
        if not self._hiflow._handshake_done:
            ok = False
            try:
                ok = await self._hiflow.async_do_comm_cmd_handshake()
            except Exception as err:
                _LOGGER.warning("CommCmd handshake raised: %s", err)
            if not ok:
                # Handshake failure most likely means encRand is stale (device
                # rebooted and generated a new one). V0 re-pair refreshes it
                # transparently without user interaction.
                _LOGGER.debug(
                    "CommCmd handshake failed — attempting V0 re-pair to refresh encRand"
                )
                try:
                    new_key = await self._hiflow.async_extract_enc_rand()
                    await async_check_and_update_enc_rand(
                        self.hass, self._config_entry, self._hiflow, new_key.hex()
                    )
                    await self._hiflow.async_do_comm_cmd_handshake()
                except Exception as err:
                    _LOGGER.debug("V0 re-pair after failed handshake: %s", err)
                    # Device truly offline — data requests will return None.
        return True

    async def _call_with_repair(
        self,
        method: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Invoke ``method``; on stale-key, re-pair once and retry."""
        try:
            return await method(*args, **kwargs)
        except EncRandStale as err:
            _LOGGER.warning(
                "encRand appears stale (%s) — re-running V0 pairing handshake", err,
            )
            try:
                new_key = await self._hiflow.async_extract_enc_rand()
            except Exception as repair_err:
                _LOGGER.error("V0 re-pairing failed: %s", repair_err)
                return None
            await async_check_and_update_enc_rand(
                self.hass, self._config_entry, self._hiflow, new_key.hex(),
            )
            try:
                return await method(*args, **kwargs)
            except EncRandStale as second_err:
                # Two strikes — something else is wrong, surface as an empty
                # poll so the device shows up as unavailable.
                _LOGGER.error(
                    "Re-paired but next request still failed with stale encRand: %s",
                    second_err,
                )
                return None


class HiFlowRealDataUpdateCoordinator(HiFlowDataUpdateCoordinator):
    """RealDataNew poller."""

    async def _async_update_data(self):
        if not await self._ensure_connected():
            return None
        response = await self._call_with_repair(self._hiflow.async_get_real_data_new)
        if not response:
            _LOGGER.debug("HiFlow real_data_new returned nothing — inverter offline?")
        return response


class HiFlowConfigUpdateCoordinator(HiFlowDataUpdateCoordinator):
    """Config poller (slower cadence)."""

    async def _async_update_data(self):
        if not await self._ensure_connected():
            return None
        response = await self._call_with_repair(self._hiflow.async_get_config)
        if not response:
            _LOGGER.debug("HiFlow get_config returned nothing")
        return response


class HiFlowAppInfoUpdateCoordinator(HiFlowDataUpdateCoordinator):
    """App-info poller. Useful as a long-running heartbeat."""

    async def _async_update_data(self):
        if not await self._ensure_connected():
            return None
        response = await self._call_with_repair(self._hiflow.async_app_information_data)
        if not response:
            _LOGGER.debug("HiFlow app_information_data returned nothing")
        return response
