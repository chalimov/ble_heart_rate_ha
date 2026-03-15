"""BLE Heart Rate Monitor integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import BleHeartRateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BLE Heart Rate Monitor from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data[CONF_NAME]

    coordinator = BleHeartRateCoordinator(hass, address, name)

    # Register BLE callback — fires when the device advertises
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.handle_bluetooth_event,
            BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        coordinator: BleHeartRateCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await coordinator.async_disconnect()
    return unload_ok
