"""Coordinators for the HiFlow BLE integration.

Each subclass implements ``_async_update_data`` against one HiFlow query.
The base class provides two robustness primitives that every subclass uses:

* :meth:`_ensure_connected` — reconnect if the BLE link dropped between polls.
  Called only by the *connection owner* (``HiFlowRealDataUpdateCoordinator``).
  Passive coordinators (config, app-info, heartbeat) skip their poll when
  ``is_connected`` is False and let the owner handle recovery.  This prevents
  concurrent ``establish_connection`` calls which corrupt habluetooth's
  ``_connect_in_progress`` refcount ("Removing a non-existing connecting …").
  The library's own ``_connect_lock`` serialises any remaining concurrency.

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
        # Track reachability so we log WARNING once per outage, not every poll.
        self._device_reachable: bool = True
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    def get_hiflow(self) -> HiFlow:
        return self._hiflow

    def _on_unreachable(self, reason: str) -> None:
        """Log at WARNING the first time the device goes offline; silent after."""
        if self._device_reachable:
            _LOGGER.warning(
                "HiFlow device %s unreachable — sensors will show unavailable (%s)",
                self._config_entry.data.get(CONF_ADDRESS, "?"),
                reason,
            )
            self._device_reachable = False

    def _on_reachable(self) -> None:
        """Log at WARNING when the device comes back after an outage."""
        if not self._device_reachable:
            _LOGGER.warning(
                "HiFlow device %s is back online",
                self._config_entry.data.get(CONF_ADDRESS, "?"),
            )
            self._device_reachable = True

    async def _ensure_connected(self) -> bool:
        """Reconnect if dropped; run CommCmd handshake on fresh connections.

        Returns False if the BLE link can't be established at all.  A handshake
        failure is logged but does *not* cause a False return — the coordinator
        will attempt data requests anyway; they'll return None (unavailable)
        if the device still refuses them.

        This method is called only by the *connection owner*
        (``HiFlowRealDataUpdateCoordinator``).  Passive coordinators check
        ``_hiflow.is_connected`` directly and skip their poll when the link is
        down, leaving reconnection entirely to the owner.  This prevents
        concurrent ``establish_connection`` calls to the same address which
        cause habluetooth to underflow its ``_connect_in_progress`` counter
        ("Removing a non-existing connecting …").

        The BLEDevice is refreshed only when a reconnect is actually needed —
        not on every poll — to avoid redundant writes to ``_hiflow.address``
        from multiple concurrent callers.
        """
        if self._hiflow.is_connected and self._hiflow._handshake_done:
            self._on_reachable()
            return True

        if not self._hiflow.is_connected:
            # Refresh the BLEDevice so bleak_retry_connector uses up-to-date
            # advertising data. Only done here (at reconnect time), not on
            # every poll, so parallel coordinator polls don't race on .address.
            fresh = bluetooth.async_ble_device_from_address(
                self.hass,
                self._config_entry.data[CONF_ADDRESS],
                connectable=True,
            )
            if fresh is not None:
                self._hiflow.address = fresh
            else:
                _LOGGER.debug(
                    "HiFlow: no connectable BLEDevice found for %s — "
                    "reconnect will use cached address (bleak_retry_connector "
                    "path unavailable until device re-advertises)",
                    self._config_entry.data.get(CONF_ADDRESS, "?"),
                )
            try:
                await self._hiflow._ensure_connected()  # serialised by _connect_lock
            except BleLinkError as err:
                _LOGGER.debug("HiFlow reconnect failed: %s", err)
                self._on_unreachable(str(err))
                return False
            except Exception as err:
                _LOGGER.debug("HiFlow reconnect raised unexpectedly: %s", err)
                self._on_unreachable(str(err))
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
                _LOGGER.warning(
                    "CommCmd handshake failed — attempting V0 re-pair to refresh encRand"
                )
                try:
                    new_key = await self._hiflow.async_extract_enc_rand()
                    await async_check_and_update_enc_rand(
                        self.hass, self._config_entry, self._hiflow, new_key.hex()
                    )
                    ok = await self._hiflow.async_do_comm_cmd_handshake()
                    if ok:
                        _LOGGER.warning("V0 re-pair succeeded — encRand refreshed")
                    else:
                        _LOGGER.warning(
                            "V0 re-pair done but second handshake still failed — "
                            "device may be truly offline"
                        )
                except Exception as err:
                    _LOGGER.warning("V0 re-pair after failed handshake: %s", err)
        self._on_reachable()
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
            self._on_unreachable("no response to RealDataNew request")
        else:
            self._on_reachable()
        return response


class HiFlowConfigUpdateCoordinator(HiFlowDataUpdateCoordinator):
    """Config poller (slower cadence).

    Passive coordinator — does not attempt reconnection.  If the link is
    down, it skips the poll and returns the last known data; the
    ``HiFlowRealDataUpdateCoordinator`` (the connection owner) handles
    reconnect.  This prevents concurrent ``_ensure_connected`` races.
    """

    async def _async_update_data(self):
        if not self._hiflow.is_connected or not self._hiflow._handshake_done:
            return None
        response = await self._call_with_repair(self._hiflow.async_get_config)
        if not response:
            _LOGGER.debug("HiFlow get_config returned nothing")
        return response


class HiFlowAppInfoUpdateCoordinator(HiFlowDataUpdateCoordinator):
    """App-info poller.

    Passive coordinator — see ``HiFlowConfigUpdateCoordinator`` for rationale.
    """

    async def _async_update_data(self):
        if not self._hiflow.is_connected or not self._hiflow._handshake_done:
            return None
        response = await self._call_with_repair(self._hiflow.async_app_information_data)
        if not response:
            _LOGGER.debug("HiFlow app_information_data returned nothing")
        return response


class HiFlowHeartbeatCoordinator(HiFlowDataUpdateCoordinator):
    """Lightweight heartbeat to prevent the inverter from dropping idle BLE links.

    The HiFlow Pro (and its ESPHome BLE proxy path) disconnects the BLE client
    after roughly 90 seconds of inactivity.  This coordinator fires every
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS (45 s by default) and sends a HBResDTO
    frame — cheap enough to keep the link warm without interfering with the data
    or config pollers.

    Crucially it does *not* trigger reconnects: if the link is already down the
    data coordinator (which runs more recovery logic) handles reconnection.  This
    avoids two coordinators racing to re-establish the same BLE connection.
    """

    async def _async_update_data(self):
        if not self._hiflow.is_connected or not self._hiflow._handshake_done:
            # Link is down or handshake pending — let the data coordinator
            # handle recovery; don't start a competing reconnect here.
            return None
        response = await self._hiflow.async_heartbeat()
        if not response:
            _LOGGER.debug("HiFlow heartbeat returned nothing — link may be dropping")
        return response
