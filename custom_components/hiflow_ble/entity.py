"""Entity base for the HiFlow BLE integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from hiflow_ble.hoymiles import get_inverter_model_name

from .const import DOMAIN
from .coordinator import HiFlowDataUpdateCoordinator


@dataclass(frozen=True)
class HiFlowEntityDescription(EntityDescription):
    """Base description with HiFlow-specific extras."""

    is_dtu_sensor: bool = False   # kept for API compatibility; no longer affects device routing
    serial_number: str | None = None
    port_number: int | None = None
    phase: str | None = None


class HiFlowEntity(Entity):
    """Common entity base — sets device-info, unique-id, translation placeholders.

    All entities are attached to the single *Wechselrichter* (inverter) device.
    There is no separate DTU device.
    """

    _attr_has_entity_name = True

    def __init__(
        self, config_entry: ConfigEntry, description: HiFlowEntityDescription
    ) -> None:
        super().__init__()
        self.entity_description = description
        self._config_entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{description.key}"

        if description.port_number is not None:
            self._attr_translation_placeholders = {
                "port_number": f"{description.port_number}"
            }
        if description.phase is not None:
            self._attr_translation_placeholders = {"phase": description.phase}

        serial = str(description.serial_number) if description.serial_number else None
        device_model = get_inverter_model_name(serial) if serial else "Unknown"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial or config_entry.entry_id)},
            translation_key="inverter",
            manufacturer="Hoymiles",
            serial_number=serial.upper() if serial else None,
            model=device_model,
        )


class HiFlowCoordinatorEntity(CoordinatorEntity, HiFlowEntity):
    """Coordinator-backed entity."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HiFlowEntityDescription,
        coordinator: HiFlowDataUpdateCoordinator,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        HiFlowEntity.__init__(self, config_entry, description)
