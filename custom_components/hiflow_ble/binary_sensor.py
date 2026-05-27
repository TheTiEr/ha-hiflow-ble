"""Binary sensors for the HiFlow BLE integration.

The BLE-connectivity sensor belongs to the *Wechselrichter* (inverter) device.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hiflow_ble.hoymiles import NetworkState

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    DOMAIN,
    HASS_DATA_COORDINATOR,
)
from .coordinator import HiFlowDataUpdateCoordinator
from .entity import HiFlowCoordinatorEntity, HiFlowEntityDescription


@dataclass(frozen=True)
class HiFlowBinarySensorEntityDescription(
    HiFlowEntityDescription, BinarySensorEntityDescription
):
    """Describes a HiFlow binary sensor."""


BINARY_SENSORS: tuple[HiFlowBinarySensorEntityDescription, ...] = (
    HiFlowBinarySensorEntityDescription(
        key="ble_link",
        translation_key="ble_link",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HiFlow binary sensors."""
    stash = hass.data[DOMAIN][entry.entry_id]
    coordinator: HiFlowDataUpdateCoordinator = stash[HASS_DATA_COORDINATOR]

    dtu_sn: str = entry.data[CONF_DTU_SERIAL_NUMBER]
    inverters: list[str] = list(entry.data.get(CONF_INVERTERS, []))
    # All entities live on the inverter device.
    inverter_sn: str = inverters[0] if inverters else dtu_sn

    entities = []
    for desc in BINARY_SENSORS:
        entities.append(
            HiFlowConnectivityBinarySensor(
                entry,
                dataclasses.replace(desc, serial_number=inverter_sn),
                coordinator,
            )
        )
    async_add_entities(entities)


class HiFlowConnectivityBinarySensor(HiFlowCoordinatorEntity, BinarySensorEntity):
    """Reports whether the BLE link is up."""

    def __init__(
        self,
        entry: ConfigEntry,
        description: HiFlowBinarySensorEntityDescription,
        coordinator: HiFlowDataUpdateCoordinator,
    ) -> None:
        super().__init__(entry, description, coordinator)
        self._hiflow = coordinator.get_hiflow()
        self._is_on: bool | None = None
        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    def update_state_value(self) -> None:
        state = self._hiflow.get_state()
        if state == NetworkState.Online:
            self._is_on = True
        elif state == NetworkState.Offline:
            self._is_on = False
        else:
            self._is_on = None
