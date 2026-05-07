"""Config flow for BLE Heart Rate Monitor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback

from .const import (
    CONF_HRMAX,
    CONF_HRREST,
    DEFAULT_HRMAX,
    DEFAULT_HRREST,
    DOMAIN,
    HR_SERVICE_UUID,
)


class BleHeartRateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for BLE Heart Rate Monitor."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return BleHeartRateOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Initialize."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle device found via automatic BLE discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Confirm Bluetooth discovery."""
        if user_input is not None:
            assert self._discovery_info is not None
            name = self._discovery_info.name or self._discovery_info.address
            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                    CONF_NAME: name,
                },
            )

        self._set_confirm_only()
        name = (
            self._discovery_info.name
            if self._discovery_info
            else "Heart Rate Monitor"
        )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": name},
        )

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle user-initiated setup (manual selection)."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            info = self._discovered_devices[address]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            name = info.name or address
            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: address, CONF_NAME: name},
            )

        # Find all BLE HR monitors currently visible
        for info in async_discovered_service_info(self.hass, connectable=True):
            if HR_SERVICE_UUID in [str(u).lower() for u in info.service_uuids]:
                self._discovered_devices[info.address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{info.name or addr} ({addr})"
                            for addr, info in self._discovered_devices.items()
                        }
                    ),
                }
            ),
        )


class BleHeartRateOptionsFlow(OptionsFlow):
    """Options flow: HRmax / HRrest for HR-zone classification."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-step form for HRmax/HRrest."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HRMAX,
                        default=current.get(CONF_HRMAX, DEFAULT_HRMAX),
                    ): vol.All(vol.Coerce(int), vol.Range(min=100, max=220)),
                    vol.Required(
                        CONF_HRREST,
                        default=current.get(CONF_HRREST, DEFAULT_HRREST),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=100)),
                }
            ),
        )
