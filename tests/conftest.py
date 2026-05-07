"""Stub homeassistant + bleak modules so coordinator.py can be imported
without a real HA install. The tests only exercise pure helpers, so we
don't need any of the stubbed surface to actually work — just be importable.
"""
from __future__ import annotations

import sys
import types


class _Placeholder:
    """Permissive stand-in: callable, attribute-access returns more of itself,
    and subscriptable so `Foo[Generic]` annotations and Generic base classes
    work without real HA types."""
    def __init__(self, *a, **kw): ...
    def __call__(self, *a, **kw): return self
    def __getattr__(self, _): return _Placeholder()
    def __class_getitem__(cls, _): return cls


def _stub_pkg(name: str, **attrs) -> types.ModuleType:
    """Register `name` as a package so submodule imports don't ModuleNotFound."""
    mod = types.ModuleType(name)
    mod.__path__ = []  # type: ignore[attr-defined]
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_stub_pkg("homeassistant")
_stub_pkg("homeassistant.core",
          HomeAssistant=_Placeholder, callback=lambda f: f)
_stub_pkg("homeassistant.components")
_stub_pkg("homeassistant.components.bluetooth",
          BluetoothServiceInfoBleak=_Placeholder,
          BluetoothChange=_Placeholder,
          BluetoothScanningMode=_Placeholder(),
          async_ble_device_from_address=_Placeholder(),
          async_register_callback=_Placeholder(),
          async_discovered_service_info=_Placeholder())
_stub_pkg("homeassistant.components.bluetooth.match",
          BluetoothCallbackMatcher=_Placeholder)
_stub_pkg("homeassistant.helpers")
_stub_pkg("homeassistant.helpers.update_coordinator",
          DataUpdateCoordinator=_Placeholder)
_stub_pkg("homeassistant.config_entries",
          ConfigEntry=_Placeholder, ConfigFlow=_Placeholder,
          ConfigFlowResult=dict, OptionsFlow=_Placeholder)
_stub_pkg("homeassistant.const",
          CONF_ADDRESS="address", CONF_NAME="name",
          Platform=types.SimpleNamespace(
              BINARY_SENSOR="binary_sensor",
              SENSOR="sensor",
              SWITCH="switch"),
          PERCENTAGE="%", EntityCategory=_Placeholder())
_stub_pkg("bleak", BleakClient=_Placeholder, BleakError=Exception)
_stub_pkg("bleak_retry_connector", establish_connection=_Placeholder())
