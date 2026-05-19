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

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from hiflow_ble.errors import BleLinkError, EncRandStale
from hiflow_ble.hiflow import HiFlow

from .const import DOMAIN
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
        """Reconnect if dropped; returns False if the link can't be brought up."""
        if self._hiflow.is_connected:
            return True
        try:
            await self._hiflow._ensure_connected()  # uses backoff internally
            return True
        except BleLinkError as err:
            _LOGGER.debug("HiFlow reconnect failed: %s", err)
            return False
        except Exception as err:
            _LOGGER.debug("HiFlow reconnect raised unexpectedly: %s", err)
            return False

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
