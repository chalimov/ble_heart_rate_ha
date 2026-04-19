"""Sensor entities for BLE Heart Rate Monitor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME, PERCENTAGE, EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BleHeartRateCoordinator, HeartRateData

SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key="heart_rate",
        translation_key="heart_rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
    ),
    SensorEntityDescription(
        key="rr_interval",
        translation_key="rr_interval",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line-variant",
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="hrv",
        translation_key="hrv",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-flash",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="hrv_score",
        translation_key="hrv_score",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-plus",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="hrv_dfa_alpha1",
        translation_key="hrv_dfa_alpha1",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-sine-variant",
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="training_zone",
        translation_key="training_zone",
        device_class=SensorDeviceClass.ENUM,
        options=["recovery", "aerobic", "threshold", "anaerobic"],
        icon="mdi:speedometer",
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="sensor_contact",
        translation_key="sensor_contact",
        icon="mdi:connection",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="battery",
        translation_key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensor entities."""
    coordinator: BleHeartRateCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data[CONF_NAME]

    async_add_entities(
        BleHeartRateSensor(coordinator, desc, address, name)
        for desc in SENSOR_DESCRIPTIONS
    )


class BleHeartRateSensor(
    CoordinatorEntity[BleHeartRateCoordinator], SensorEntity
):
    """Sensor entity for BLE Heart Rate Monitor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BleHeartRateCoordinator,
        description: SensorEntityDescription,
        address: str,
        name: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
            manufacturer=_extract_manufacturer(name),
            model="Heart Rate Monitor",
        )

    @property
    def native_value(self) -> int | float | str | None:
        """Return sensor value."""
        data: HeartRateData = self.coordinator.data
        key = self.entity_description.key

        if key == "heart_rate":
            return data.heart_rate
        if key == "rr_interval":
            return data.rr_intervals[-1] if data.rr_intervals else None
        if key == "sensor_contact":
            if data.sensor_contact is True:
                return "Detected"
            if data.sensor_contact is False:
                return "Not Detected"
            return None
        if key == "hrv":
            return data.hrv_rmssd
        if key == "hrv_score":
            return data.hrv_score
        if key == "hrv_dfa_alpha1":
            return data.hrv_dfa_alpha1
        if key == "training_zone":
            return data.training_zone
        if key == "battery":
            return data.battery_level
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for the heart rate sensor."""
        if self.entity_description.key != "heart_rate":
            return None
        data: HeartRateData = self.coordinator.data
        attrs: dict[str, Any] = {}
        if data.rr_intervals:
            attrs["rr_intervals_ms"] = [round(r, 1) for r in data.rr_intervals]
        if data.sensor_contact is not None:
            attrs["sensor_contact"] = data.sensor_contact
        if data.energy_expended is not None:
            attrs["energy_expended_kj"] = data.energy_expended
        return attrs or None


def _extract_manufacturer(name: str) -> str | None:
    """Try to extract manufacturer from BLE device name."""
    known = {
        "coospo": "Coospo",
        "polar": "Polar",
        "garmin": "Garmin",
        "wahoo": "Wahoo",
        "magene": "Magene",
        "scosche": "Scosche",
        "moofit": "Moofit",
        "igpsport": "iGPSPORT",
        "xoss": "XOSS",
        "bryton": "Bryton",
    }
    name_lower = name.lower()
    for prefix, manufacturer in known.items():
        if prefix in name_lower:
            return manufacturer
    return None
