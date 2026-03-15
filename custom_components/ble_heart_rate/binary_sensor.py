"""BLE Heart Rate Monitor binary sensor platform."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BleHeartRateCoordinator

_CONNECTION_STATUS = BinarySensorEntityDescription(
    key="connected",
    name="Connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BLE Heart Rate binary sensors."""
    coordinator: BleHeartRateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ConnectionStatusSensor(coordinator, entry)])


class ConnectionStatusSensor(
    CoordinatorEntity[BleHeartRateCoordinator], BinarySensorEntity
):
    """Binary sensor showing BLE connection status."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BleHeartRateCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        address = entry.data[CONF_ADDRESS]
        name = entry.data[CONF_NAME]
        self.entity_description = _CONNECTION_STATUS
        self._attr_unique_id = f"{address}_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
        )
        self._attr_is_on = coordinator.data.connected if coordinator.data else False

    @property
    def available(self) -> bool:
        """Always available — shows disconnected when device is off."""
        return True

    @callback
    def _handle_coordinator_update(self) -> None:
        is_on = self.coordinator.data.connected if self.coordinator.data else False
        if self._attr_is_on != is_on:
            self._attr_is_on = is_on
            self.async_write_ha_state()
