"""Button entities for HiFlow BLE.

All buttons belong to the *Wechselrichter* (inverter) device.
The DTU restart button has been removed — there is no separate DTU device.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from inspect import signature

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hiflow_ble.hiflow import HiFlow

from .const import (
    CONF_INVERTERS,
    DOMAIN,
    HASS_HIFLOW,
)
from .entity import HiFlowEntity, HiFlowEntityDescription


@dataclass(frozen=True)
class HiFlowButtonEntityDescription(HiFlowEntityDescription, ButtonEntityDescription):
    """Describes a HiFlow button entity."""

    action: str = ""


BUTTONS: tuple[HiFlowButtonEntityDescription, ...] = (
    HiFlowButtonEntityDescription(
        key="turn_off_inverter_<inverter_serial>",
        translation_key="turn_off",
        icon="mdi:power-off",
        action="async_turn_off_inverter",
    ),
    HiFlowButtonEntityDescription(
        key="turn_on_inverter_<inverter_serial>",
        translation_key="turn_on",
        icon="mdi:power-on",
        action="async_turn_on_inverter",
    ),
    HiFlowButtonEntityDescription(
        key="reboot_inverter_<inverter_serial>",
        translation_key="restart",
        device_class=ButtonDeviceClass.RESTART,
        icon="mdi:restart",
        action="async_reboot_inverter",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HiFlow button entities."""
    stash = hass.data[DOMAIN][entry.entry_id]
    hiflow: HiFlow = stash[HASS_HIFLOW]
    inverters: list[str] = list(entry.data.get(CONF_INVERTERS, []))

    if not inverters:
        return

    buttons: list[HiFlowButtonEntity] = []
    for desc in BUTTONS:
        for inverter_sn in inverters:
            new_key = desc.key.replace("<inverter_serial>", inverter_sn)
            buttons.append(
                HiFlowButtonEntity(
                    entry,
                    dataclasses.replace(desc, key=new_key, serial_number=inverter_sn),
                    hiflow,
                )
            )
    async_add_entities(buttons)


class HiFlowButtonEntity(HiFlowEntity, ButtonEntity):
    """A button that invokes a HiFlow async method."""

    def __init__(
        self,
        entry: ConfigEntry,
        description: HiFlowButtonEntityDescription,
        hiflow: HiFlow,
    ) -> None:
        super().__init__(entry, description)
        self._hiflow = hiflow

    async def async_press(self) -> None:
        method = getattr(self._hiflow, self.entity_description.action, None)
        if not callable(method):
            raise NotImplementedError(
                f"HiFlow has no method {self.entity_description.action!r}"
            )
        params = signature(method).parameters
        if "inverter_serial" in params:
            await method(self.entity_description.serial_number)
        else:
            await method()
