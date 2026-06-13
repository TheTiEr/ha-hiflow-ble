"""Sensor entities for the HiFlow BLE integration.

Mirrors the dataclass-based description pattern used by ``ha-hoymiles-wifi``.
Scoped to single-phase inverters (no TGS, no built-in meter, no battery).

All entities belong to the single *Wechselrichter* (inverter) device.
Two computed entities aggregate per-port values:

* ``ac_daily_energy``      — sum of Port N daily energy  (= AC Tagesertrag)
* ``inverter_total_energy``— sum of Port N total energy  (= Gesamtertrag)
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DTU_SERIAL_NUMBER,
    CONF_INVERTERS,
    CONF_PORTS,
    DOMAIN,
    HASS_APP_INFO_COORDINATOR,
    HASS_DATA_COORDINATOR,
)
from .coordinator import HiFlowDataUpdateCoordinator
from .entity import HiFlowCoordinatorEntity, HiFlowEntityDescription


@dataclass(frozen=True)
class HiFlowSensorEntityDescription(HiFlowEntityDescription, SensorEntityDescription):
    """Sensor description with HiFlow-specific fields."""

    conversion_factor: float | None = None
    reset_at_midnight: bool = False
    assume_state: bool = False
    force_keep_maximum_within_day: bool = False


@dataclass(frozen=True)
class HiFlowSumSensorEntityDescription(HiFlowSensorEntityDescription):
    """Sensor that sums multiple data paths.

    ``sum_paths`` is a tuple of ``(path, conversion_factor)`` pairs.
    The sensor value is the sum of all resolved path values, each multiplied
    by the corresponding factor (use ``None`` for no scaling).
    """

    sum_paths: tuple[tuple[str, float | None], ...] = ()


# ---------------------------------------------------------------------------
# Static sensor descriptions (per-inverter and per-port)
# Computed / aggregate sensors are built dynamically in async_setup_entry.
# ---------------------------------------------------------------------------

HIFLOW_SENSORS: tuple[HiFlowSensorEntityDescription, ...] = (
    # ----- Per-inverter AC side (SGS = single grid string) -----
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].active_power",
        translation_key="ac_active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].reactive_power",
        translation_key="ac_reactive_power",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].voltage",
        translation_key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].current",
        translation_key="ac_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].frequency",
        translation_key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].power_factor",
        translation_key="inverter_power_factor",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].temperature",
        translation_key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HiFlowSensorEntityDescription(
        key="sgs_data[<inverter_count>].warning_number",
        translation_key="inverter_warning_number",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ----- Per-PV-port DC side -----
    HiFlowSensorEntityDescription(
        key="pv_data[<pv_count>].voltage",
        translation_key="port_dc_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HiFlowSensorEntityDescription(
        key="pv_data[<pv_count>].current",
        translation_key="port_dc_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.01,
    ),
    HiFlowSensorEntityDescription(
        key="pv_data[<pv_count>].power",
        translation_key="port_dc_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        conversion_factor=0.1,
    ),
    HiFlowSensorEntityDescription(
        key="pv_data[<pv_count>].energy_total",
        translation_key="port_dc_total_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HiFlowSensorEntityDescription(
        key="pv_data[<pv_count>].energy_daily",
        translation_key="port_dc_daily_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        reset_at_midnight=True,
    ),
    HiFlowSensorEntityDescription(
        key="pv_data[<pv_count>].error_code",
        translation_key="port_error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:check-circle-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Wire up sensors for a single HiFlow Pro config entry."""
    stash = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: HiFlowDataUpdateCoordinator = stash[HASS_DATA_COORDINATOR]

    dtu_sn: str = config_entry.data[CONF_DTU_SERIAL_NUMBER]
    inverters: list[str] = list(config_entry.data.get(CONF_INVERTERS, []))
    ports: list[dict] = list(config_entry.data.get(CONF_PORTS, []))

    # All entities live on the inverter device — use first inverter SN, fall back to DTU SN.
    inverter_sn: str = inverters[0] if inverters else dtu_sn

    entities: list[SensorEntity] = []
    for desc in HIFLOW_SENSORS:
        if "<inverter_count>" in desc.key:
            for idx, inv_sn in enumerate(inverters):
                new_key = desc.key.replace("<inverter_count>", str(idx))
                entities.append(
                    HiFlowDataSensorEntity(
                        config_entry,
                        dataclasses.replace(desc, key=new_key, serial_number=inv_sn),
                        coordinator,
                    )
                )
        elif "<pv_count>" in desc.key:
            for idx, port in enumerate(ports):
                new_key = desc.key.replace("<pv_count>", str(idx))
                updated = dataclasses.replace(
                    desc,
                    key=new_key,
                    serial_number=inverter_sn,
                    port_number=port["port_number"],
                )
                if updated.translation_key == "port_error_code":
                    cls = HiFlowErrorCodeSensorEntity
                elif updated.state_class == SensorStateClass.TOTAL_INCREASING:
                    cls = HiFlowEnergySensorEntity
                else:
                    cls = HiFlowDataSensorEntity
                entities.append(cls(config_entry, updated, coordinator))

    # -----------------------------------------------------------------------
    # Computed aggregate sensors
    # -----------------------------------------------------------------------
    if ports:
        # AC Tagesertrag = Σ pv_data[n].energy_daily
        daily_paths: tuple[tuple[str, float | None], ...] = tuple(
            (f"pv_data[{idx}].energy_daily", None) for idx in range(len(ports))
        )
        entities.append(
            HiFlowSumSensorEntity(
                config_entry,
                HiFlowSumSensorEntityDescription(
                    key="ac_daily_energy_sum",
                    translation_key="ac_daily_energy",
                    native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                    device_class=SensorDeviceClass.ENERGY,
                    state_class=SensorStateClass.TOTAL_INCREASING,
                    reset_at_midnight=True,
                    serial_number=inverter_sn,
                    sum_paths=daily_paths,
                ),
                coordinator,
            )
        )

        # Gesamtertrag = Σ pv_data[n].energy_total
        total_paths: tuple[tuple[str, float | None], ...] = tuple(
            (f"pv_data[{idx}].energy_total", None) for idx in range(len(ports))
        )
        entities.append(
            HiFlowSumSensorEntity(
                config_entry,
                HiFlowSumSensorEntityDescription(
                    key="inverter_total_energy",
                    translation_key="inverter_total_energy",
                    native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                    device_class=SensorDeviceClass.ENERGY,
                    state_class=SensorStateClass.TOTAL_INCREASING,
                    serial_number=inverter_sn,
                    sum_paths=total_paths,
                ),
                coordinator,
            )
        )

    app_info_coordinator: HiFlowDataUpdateCoordinator = stash[HASS_APP_INFO_COORDINATOR]
    for idx, port in enumerate(ports):
        entities.append(
            HiFlowHwPartNumberSensorEntity(
                config_entry,
                HiFlowSensorEntityDescription(
                    key=f"pv_hw_part_number_{idx}",
                    translation_key="pv_hw_part_number",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    serial_number=inverter_sn,
                    port_number=port["port_number"],
                ),
                app_info_coordinator,
                pv_index=idx,
            )
        )

    async_add_entities(entities)


# ---------- helpers ----------

def _resolve_path(obj, path: str):
    """Walk ``obj`` along ``path`` (e.g. ``sgs_data[0].active_power``)."""
    tokens = re.findall(r"\w+|\[\d+\]", path)
    for token in tokens:
        if obj is None:
            return None
        if token.startswith("["):
            try:
                obj = obj[int(token[1:-1])]
            except (IndexError, TypeError):
                return None
        else:
            obj = getattr(obj, token, None)
    return obj


# ---------- entity classes ----------

class HiFlowDataSensorEntity(HiFlowCoordinatorEntity, RestoreSensor):
    """Default sensor: pulls a numeric value from coordinator.data and scales it."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HiFlowSensorEntityDescription,
        coordinator: HiFlowDataUpdateCoordinator,
    ) -> None:
        super().__init__(config_entry, description, coordinator)
        self._attribute_name = description.key
        self._conversion_factor = description.conversion_factor
        self._native_value = None
        self._assumed_state = False
        self._last_known_value = None
        self._last_successful_update: datetime | None = None
        self._last_update_state: datetime | None = None
        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        if self._native_value == 0.0:
            if self.entity_description.assume_state:
                return self._last_known_value
            if (
                self._last_successful_update is not None
                and datetime.now() - self._last_successful_update <= timedelta(minutes=3)
            ):
                self._assumed_state = True
                return self._last_known_value
        else:
            self._last_successful_update = datetime.now()
            self._last_known_value = self._native_value
        self._assumed_state = False
        return self._native_value

    @property
    def assumed_state(self):
        return self._assumed_state

    def update_state_value(self) -> None:
        if (
            self.coordinator is None
            or not hasattr(self.coordinator, "data")
            or self.coordinator.data is None
        ):
            self._native_value = 0.0
            return
        new_value = _resolve_path(self.coordinator.data, self._attribute_name)
        if new_value is not None and self._conversion_factor is not None:
            new_value *= self._conversion_factor
        if (
            self.entity_description.force_keep_maximum_within_day
            and self._last_update_state is not None
            and self._last_update_state.date() == datetime.now().date()
            and new_value is not None
            and self._native_value is not None
        ):
            new_value = max(new_value, self._native_value)
        self._last_update_state = datetime.now()
        self._native_value = new_value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_sensor_data()
        if state:
            self._last_known_value = state.native_value


class HiFlowEnergySensorEntity(HiFlowDataSensorEntity, RestoreSensor):
    """Energy sensor: avoids resetting total_increasing on transient 0 values."""

    def __init__(self, config_entry, description, coordinator) -> None:
        super().__init__(config_entry, description, coordinator)
        self._last_known_value = None  # don't pre-seed for long-term stats

    def schedule_midnight_reset(self, reset_sensor_value: bool = True) -> None:
        now = datetime.now()
        midnight = datetime.combine(now.date(), time(0, 0))
        midnight = midnight + timedelta(days=1) if now > midnight else midnight
        time_until = (midnight - datetime.now()).total_seconds()
        if reset_sensor_value:
            self._last_known_value = 0
        self.hass.loop.call_later(time_until, self.schedule_midnight_reset)

    @property
    def native_value(self):
        super_value = super().native_value
        if super_value == 0.0:
            self._assumed_state = True
            return self._last_known_value
        self._last_known_value = super_value
        self._assumed_state = False
        return super_value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_sensor_data()
        if state:
            self._last_known_value = state.native_value
        if self.entity_description.reset_at_midnight:
            self.schedule_midnight_reset(reset_sensor_value=False)


class HiFlowSumSensorEntity(HiFlowEnergySensorEntity):
    """Energy sensor that sums values from multiple data paths.

    Overrides ``update_state_value`` — the ``key`` field in the description is
    used only for the unique-id, not as a data path.
    """

    # Class-level default so update_state_value() is safe when called by
    # super().__init__() before self._sum_paths is assigned.
    _sum_paths: tuple[tuple[str, float | None], ...] = ()

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HiFlowSumSensorEntityDescription,
        coordinator: HiFlowDataUpdateCoordinator,
    ) -> None:
        # Assign before super().__init__() because HiFlowDataSensorEntity.__init__
        # calls self.update_state_value(), which reads self._sum_paths.
        self._sum_paths = description.sum_paths
        super().__init__(config_entry, description, coordinator)

    def update_state_value(self) -> None:
        data = getattr(self.coordinator, "data", None)
        if data is None:
            self._native_value = 0.0
            self._last_update_state = datetime.now()
            return
        total = 0.0
        all_none = True
        for path, factor in self._sum_paths:
            val = _resolve_path(data, path)
            if val is not None:
                all_none = False
                total += val * factor if factor is not None else val
        self._native_value = None if all_none else total
        self._last_update_state = datetime.now()


class HiFlowHwPartNumberSensorEntity(HiFlowCoordinatorEntity, SensorEntity):
    """Diagnostic sensor exposing the PV hardware part number from AppInfo.

    This value helps build a community lookup table that maps pv_hw_part_number
    → rated power in Watt. If your inverter is not auto-detected, please report
    your value at https://github.com/TheTiEr/ha-hiflow-ble/issues.
    """

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: HiFlowSensorEntityDescription,
        coordinator: HiFlowDataUpdateCoordinator,
        pv_index: int,
    ) -> None:
        super().__init__(config_entry, description, coordinator)
        self._pv_index = pv_index

    @property
    def native_value(self):
        data = getattr(self.coordinator, "data", None)
        if data is None or not data.pv_info:
            return None
        try:
            value = data.pv_info[self._pv_index].pv_hw_part_number
            return value if value else None
        except IndexError:
            return None


class HiFlowErrorCodeSensorEntity(HiFlowDataSensorEntity):
    """Diagnostic sensor for PvMO.error_code.

    Exposes the raw integer code as ``native_value`` (for automations) and
    adds ``extra_state_attributes`` with a human-readable status string and
    the hex representation so users can quickly see whether a port is healthy.

    The ``error_code`` bitmask comes from the inverter firmware; individual bit
    meanings are device-specific and fetched server-side by the S-Miles app.
    The only portable interpretation is: 0 = normal, non-zero = fault/status.
    """

    @property
    def icon(self) -> str:
        code = self._native_value
        if code is None or code == 0:
            return "mdi:check-circle-outline"
        return "mdi:alert-circle-outline"

    @property
    def extra_state_attributes(self) -> dict:
        code = self._native_value
        if code is None:
            return {"status": "unavailable", "hex_code": None}
        code_int = int(code)
        if code_int == 0:
            status = "normal"
        else:
            # Decode known bitmask structure from WarnData:
            # bits 0-8 (code & 0x1FF): alarm type ID
            # (code & 0xD000) >> 14: severity (1 = critical)
            alarm_id = code_int & 0x1FF
            severity_bits = (code_int & 0xD000) >> 14
            severity = "critical" if severity_bits == 1 else "fault"
            status = f"{severity} (alarm {alarm_id})"
        return {
            "status": status,
            "hex_code": f"0x{code_int:04X}",
        }
