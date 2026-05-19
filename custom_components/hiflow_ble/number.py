"""Number entities (power-limit slider) for HiFlow BLE."""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    DOMAIN,
    HASS_CONFIG_COORDINATOR,
)
from .coordinator import HiFlowDataUpdateCoordinator
from .entity import HiFlowCoordinatorEntity, HiFlowEntityDescription

_LOGGER = logging.getLogger(__name__)


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
        is_dtu_sensor=True,
    ),
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

    entities = []
    for desc in NUMBERS:
        if desc.is_dtu_sensor:
            updated = dataclasses.replace(desc, serial_number=dtu_sn)
            entities.append(HiFlowPowerLimitNumber(entry, updated, coordinator))
    async_add_entities(entities)


class HiFlowPowerLimitNumber(HiFlowCoordinatorEntity, NumberEntity):
    """Power-limit slider — maps to HiFlow.async_set_power_limit."""

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
        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        return self._native_value

    @property
    def assumed_state(self) -> bool:
        return self._assumed_state

    async def async_set_native_value(self, value: float) -> None:
        if value < 0 or value > 100:
            _LOGGER.error("Power limit %s out of range [0, 100]", value)
            return
        hiflow = self.coordinator.get_hiflow()
        await hiflow.async_set_power_limit(int(value))
        await self.coordinator.async_request_refresh()
        self._assumed_state = True
        self._native_value = value

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
