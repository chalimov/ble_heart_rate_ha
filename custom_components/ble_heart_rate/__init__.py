"""BLE Heart Rate Monitor integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HRMAX,
    CONF_HRREST,
    DEFAULT_HRMAX,
    DEFAULT_HRREST,
    DOMAIN,
)
from .coordinator import BleHeartRateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BLE Heart Rate Monitor from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data[CONF_NAME]
    hrmax: int = entry.options.get(CONF_HRMAX, DEFAULT_HRMAX)
    hrrest: int = entry.options.get(CONF_HRREST, DEFAULT_HRREST)

    coordinator = BleHeartRateCoordinator(hass, address, name, hrmax, hrrest)

    # Register BLE callback — fires when the device advertises
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.handle_bluetooth_event,
            BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    # Apply options-flow changes (HRmax/HRrest) without reload
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update — push new HRmax/HRrest into the coordinator."""
    coordinator: BleHeartRateCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.update_zone_params(
        entry.options.get(CONF_HRMAX, DEFAULT_HRMAX),
        entry.options.get(CONF_HRREST, DEFAULT_HRREST),
    )


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
