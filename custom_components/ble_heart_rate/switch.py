"""Switch entity for BLE Heart Rate Monitor — controls BLE connection."""
from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import CONF_ADDRESS, CONF_NAME, EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import BleHeartRateCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up switch entity."""
    coordinator: BleHeartRateCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data[CONF_NAME]
    async_add_entities([BleHeartRateSwitch(coordinator, address, name)])


class BleHeartRateSwitch(SwitchEntity):
    """Switch to enable/disable BLE connection to the HR monitor."""

    _attr_has_entity_name = True
    _attr_translation_key = "connect"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(
        self,
        coordinator: BleHeartRateCoordinator,
        address: str,
        name: str,
    ) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{address}_connect"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
        )

    @property
    def is_on(self) -> bool:
        """Return true if connection is enabled."""
        return self._coordinator.enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable BLE connection."""
        self._coordinator.enabled = True
        self.async_write_ha_state()
        # Trigger immediate connection attempt
        self.hass.async_create_task(self._coordinator._connect())

    async def async_turn_off(self, **kwargs) -> None:
        """Disable BLE connection and disconnect."""
        self._coordinator.enabled = False
        await self._coordinator.async_disconnect()
        self.async_write_ha_state()
