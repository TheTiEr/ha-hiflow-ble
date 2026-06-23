"""Number entities (power-limit slider) for HiFlow BLE.

The power-limit entity belongs to the *Wechselrichter* (inverter) device.

EEPROM wear protection
----------------------
The HiFlow Pro stores the power-limit in on-device flash.  Flash cells have a
finite write-cycle budget (~10 k–100 k writes depending on the chip).  Two
mechanisms protect against premature wear:

1. **Debounce** — ``DEBOUNCE_SECONDS`` after the last slider move we write once
   instead of writing on every intermediate position.  A UI drag that produces
   40 intermediate values turns into a single device write.

2. **Deduplication** — we compare the requested value against the last confirmed
   value read from the device (``coordinator.data.limit_power_mypower``).  If
   they are equal we skip the write entirely.  This avoids a write on every HA
   restart, integration reload, or accidental double-tap.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Callable

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_RATED_POWER_W,
    DEFAULT_RATED_POWER_W,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
)
from .coordinator import HiFlowDataUpdateCoordinator
from .entity import HiFlowCoordinatorEntity, HiFlowEntityDescription
from .util import detect_rated_power_w

_LOGGER = logging.getLogger(__name__)

# Wait this long after the last slider move before writing to the device.
# Absorbs rapid UI drags without triggering multiple EEPROM writes.
_DEBOUNCE_SECONDS = 2.0


def _confirmed_device_percent(coordinator: HiFlowDataUpdateCoordinator) -> int | None:
    """Return the last confirmed device power limit as an integer percent, or None."""
    data = getattr(coordinator, "data", None)
    if data is None:
        return None
    raw = getattr(data, "limit_power_mypower", None)
    if raw is None:
        return None
    return round(raw * 0.1)


@dataclass(frozen=True)
class HiFlowNumberEntityDescription(HiFlowEntityDescription, NumberEntityDescription):
    """Describes a HiFlow number entity."""

    conversion_factor: float | None = None


NUMBERS: tuple[HiFlowNumberEntityDescription, ...] = (
    HiFlowNumberEntityDescription(
        key="limit_power_mypower",
        translation_key="limit_power_mypower",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        conversion_factor=0.1,
    ),
)

WATT_NUMBER = HiFlowNumberEntityDescription(
    key="limit_power_mypower_watt",
    translation_key="limit_power_mypower_watt",
    native_unit_of_measurement=UnitOfPower.WATT,
    native_min_value=0,
    native_max_value=100,  # overridden per-entry with the rated power
    native_step=1,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HiFlow number entities."""
    stash = hass.data[DOMAIN][entry.entry_id]
    coordinator: HiFlowDataUpdateCoordinator = stash[HASS_CONFIG_COORDINATOR]

    dtu_sn: str = entry.data[CONF_DTU_SERIAL_NUMBER]
    inverters: list[str] = list(entry.data.get(CONF_INVERTERS, []))
    inverter_sn: str = inverters[0] if inverters else dtu_sn

    entities: list[NumberEntity] = [
        HiFlowPowerLimitNumber(
            entry,
            dataclasses.replace(desc, serial_number=inverter_sn),
            coordinator,
        )
        for desc in NUMBERS
    ]

    rated_power_w: int = entry.options.get(
        CONF_RATED_POWER_W,
        entry.data.get(CONF_RATED_POWER_W, DEFAULT_RATED_POWER_W),
    )
    if rated_power_w == DEFAULT_RATED_POWER_W:
        rated_power_w = detect_rated_power_w(entry)
    if rated_power_w > 0:
        entities.append(
            HiFlowPowerLimitWattNumber(
                entry,
                dataclasses.replace(
                    WATT_NUMBER,
                    serial_number=inverter_sn,
                    native_max_value=float(rated_power_w),
                ),
                coordinator,
                rated_power_w,
            )
        )

    async_add_entities(entities)


class HiFlowPowerLimitNumber(HiFlowCoordinatorEntity, NumberEntity):
    """Power-limit slider (percent) — maps to HiFlow.async_set_power_limit.

    Writes are debounced and deduplicated to protect the device's flash memory
    from excessive wear (see module docstring).
    """

    def __init__(
        self,
        entry: ConfigEntry,
        description: HiFlowNumberEntityDescription,
        coordinator: HiFlowDataUpdateCoordinator,
    ) -> None:
        super().__init__(entry, description, coordinator)
        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._native_value: float | None = None
        self._assumed_state = False
        self._debounce_unsub: Callable | None = None
        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        return self._native_value

    @property
    def assumed_state(self) -> bool:
        return self._assumed_state

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_debounce()

    async def async_set_native_value(self, value: float) -> None:
        if value < 0 or value > 100:
            _LOGGER.error("Power limit %s out of range [0, 100]", value)
            return

        # Update UI immediately so the slider feels responsive.
        self._assumed_state = True
        self._native_value = value
        self.async_write_ha_state()

        # (Re-)schedule the actual device write.
        percent = int(value)
        self._cancel_debounce()

        @callback
        def _fire(_now) -> None:
            self.hass.async_create_task(self._write_to_device(percent))

        self._debounce_unsub = async_call_later(self.hass, _DEBOUNCE_SECONDS, _fire)

    async def _write_to_device(self, percent: int) -> None:
        """Write ``percent`` to the inverter, skipping if the device already matches."""
        self._debounce_unsub = None

        confirmed = _confirmed_device_percent(self.coordinator)
        if confirmed is not None and confirmed == percent:
            _LOGGER.debug(
                "Power limit already %d %% on device — skipping write", percent
            )
            self._assumed_state = False
            self.async_write_ha_state()
            return

        _LOGGER.debug("Writing power limit %d %% to device", percent)
        hiflow = self.coordinator.get_hiflow()
        await hiflow.async_set_power_limit(percent)
        await self.coordinator.async_request_refresh()

    def _cancel_debounce(self) -> None:
        if self._debounce_unsub is not None:
            self._debounce_unsub()
            self._debounce_unsub = None

    def update_state_value(self) -> None:
        data = getattr(self.coordinator, "data", None)
        if data is None:
            return
        raw = getattr(data, self._attribute_name, None)
        if raw is None:
            return
        self._assumed_state = False
        self._native_value = (
            raw * self._conversion_factor if self._conversion_factor else raw
        )


class HiFlowPowerLimitWattNumber(HiFlowCoordinatorEntity, NumberEntity):
    """Power-limit slider in Watt.

    Converts Watt ↔ percent when reading from / writing to the device.
    The device stores the limit as tenths of percent (``limit_power_mypower``).

    Writes are debounced and deduplicated to protect the device's flash memory
    from excessive wear (see module docstring).
    """

    def __init__(
        self,
        entry: ConfigEntry,
        description: HiFlowNumberEntityDescription,
        coordinator: HiFlowDataUpdateCoordinator,
        rated_power_w: int,
    ) -> None:
        super().__init__(entry, description, coordinator)
        self._rated_power_w = rated_power_w
        self._native_value: float | None = None
        self._assumed_state = False
        self._debounce_unsub: Callable | None = None
        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        return self._native_value

    @property
    def assumed_state(self) -> bool:
        return self._assumed_state

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_debounce()

    async def async_set_native_value(self, value: float) -> None:
        percent = round(value / self._rated_power_w * 100)
        percent = max(0, min(100, percent))

        # Update UI immediately so the slider feels responsive.
        self._assumed_state = True
        self._native_value = value
        self.async_write_ha_state()

        # (Re-)schedule the actual device write.
        self._cancel_debounce()

        @callback
        def _fire(_now) -> None:
            self.hass.async_create_task(self._write_to_device(percent))

        self._debounce_unsub = async_call_later(self.hass, _DEBOUNCE_SECONDS, _fire)

    async def _write_to_device(self, percent: int) -> None:
        """Write ``percent`` to the inverter, skipping if the device already matches."""
        self._debounce_unsub = None

        confirmed = _confirmed_device_percent(self.coordinator)
        if confirmed is not None and confirmed == percent:
            _LOGGER.debug(
                "Power limit already %d %% on device — skipping write", percent
            )
            self._assumed_state = False
            self.async_write_ha_state()
            return

        _LOGGER.debug("Writing power limit %d %% to device", percent)
        hiflow = self.coordinator.get_hiflow()
        await hiflow.async_set_power_limit(percent)
        await self.coordinator.async_request_refresh()

    def _cancel_debounce(self) -> None:
        if self._debounce_unsub is not None:
            self._debounce_unsub()
            self._debounce_unsub = None

    def update_state_value(self) -> None:
        data = getattr(self.coordinator, "data", None)
        if data is None:
            return
        # limit_power_mypower is stored in tenths of percent (e.g. 750 = 75.0 %)
        raw = getattr(data, "limit_power_mypower", None)
        if raw is None:
            return
        self._assumed_state = False
        percent = raw * 0.1
        self._native_value = float(round(percent / 100.0 * self._rated_power_w))
