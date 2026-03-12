"""Coordinator for BLE Heart Rate Monitor integration."""
from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from typing import Any

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import HR_MEASUREMENT_CHAR, BATTERY_LEVEL_CHAR

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = timedelta(seconds=60)
HRV_WINDOW_SECONDS = 300  # 5-minute sliding window for RMSSD
HRV_MIN_INTERVALS = 10  # minimum RR intervals needed for a meaningful RMSSD


@dataclass
class HeartRateData:
    """Data from heart rate monitor."""

    heart_rate: int | None = None
    rr_intervals: list[int] | None = None  # milliseconds (current notification)
    sensor_contact: bool | None = None  # None = feature not supported
    energy_expended: int | None = None  # kJ
    battery_level: int | None = None
    hrv_rmssd: float | None = None  # RMSSD in ms
    connected: bool = False


def compute_rmssd(rr_values: list[int]) -> float | None:
    """Compute RMSSD (Root Mean Square of Successive Differences) in ms.

    Requires at least HRV_MIN_INTERVALS RR intervals.
    """
    if len(rr_values) < HRV_MIN_INTERVALS:
        return None
    diffs_sq = [
        (rr_values[i + 1] - rr_values[i]) ** 2
        for i in range(len(rr_values) - 1)
    ]
    return round(math.sqrt(sum(diffs_sq) / len(diffs_sq)), 1)


def parse_hr_measurement(data: bytes | bytearray) -> dict[str, Any]:
    """Parse BLE Heart Rate Measurement characteristic (0x2A37).

    Format per Bluetooth HRS spec:
      Byte 0: Flags
        Bit 0: HR format (0=UINT8, 1=UINT16)
        Bits 1-2: Sensor contact (0b1x = supported, bit 0 = detected)
        Bit 3: Energy expended present
        Bit 4: RR-Interval present
      Byte 1+: HR value, optional energy, optional RR intervals
    """
    if not data:
        return {}

    flags = data[0]
    hr_16bit = bool(flags & 0x01)
    contact_bits = (flags >> 1) & 0x03
    energy_present = bool(flags & 0x08)
    rr_present = bool(flags & 0x10)

    offset = 1

    # Heart rate value
    if hr_16bit:
        heart_rate = int.from_bytes(data[offset : offset + 2], "little")
        offset += 2
    else:
        heart_rate = data[offset]
        offset += 1

    # Sensor contact: bits 1-2 → 0b10=supported/no contact, 0b11=supported/contact
    sensor_contact = None
    if contact_bits >= 2:
        sensor_contact = bool(contact_bits & 0x01)

    # Energy expended (UINT16 LE, kJ)
    energy_expended = None
    if energy_present and offset + 1 < len(data):
        energy_expended = int.from_bytes(data[offset : offset + 2], "little")
        offset += 2

    # RR intervals (UINT16 LE each, units of 1/1024 seconds)
    rr_intervals = None
    if rr_present:
        rr_intervals = []
        while offset + 1 < len(data):
            rr_raw = int.from_bytes(data[offset : offset + 2], "little")
            rr_ms = round(rr_raw * 1000 / 1024)
            rr_intervals.append(rr_ms)
            offset += 2

    return {
        "heart_rate": heart_rate,
        "rr_intervals": rr_intervals or None,
        "sensor_contact": sensor_contact,
        "energy_expended": energy_expended,
    }


class BleHeartRateCoordinator(DataUpdateCoordinator[HeartRateData]):
    """Coordinator for BLE Heart Rate Monitor."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"BLE HR {name}",
            update_interval=RECONNECT_INTERVAL,
        )
        self.address = address
        self.device_name = name
        self.data = HeartRateData()
        self._client: BleakClient | None = None
        self._connecting = False
        self.enabled = True  # controlled by the Connect switch
        # Sliding window of (timestamp, rr_ms) for HRV calculation
        self._rr_history: deque[tuple[float, int]] = deque()

    async def _async_update_data(self) -> HeartRateData:
        """Periodic reconnection attempt if disconnected."""
        if self.enabled and not self._client and not self._connecting:
            await self._connect()
        return self.data

    @callback
    def handle_bluetooth_event(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Handle BLE advertisement — trigger connection if not connected."""
        if self.enabled and not self._client and not self._connecting:
            self.hass.async_create_task(self._connect())

    async def _connect(self) -> None:
        """Connect to device and subscribe to HR notifications."""
        if self._connecting:
            return
        self._connecting = True
        try:
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if not device:
                _LOGGER.debug("Device %s not available", self.address)
                return

            _LOGGER.debug("Connecting to %s (%s)", self.device_name, self.address)
            client = await establish_connection(
                BleakClient,
                device,
                self.address,
                disconnected_callback=self._on_disconnect,
                max_attempts=2,
            )
            self._client = client

            # Subscribe to HR measurement notifications
            await client.start_notify(
                HR_MEASUREMENT_CHAR, self._on_hr_notification
            )
            _LOGGER.info(
                "Connected to %s (%s), receiving HR data",
                self.device_name,
                self.address,
            )

            # Try to read battery level (optional service, may not exist)
            try:
                battery_data = await client.read_gatt_char(BATTERY_LEVEL_CHAR)
                self.data.battery_level = battery_data[0]
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Battery service not available on %s", self.address)

            self.data.connected = True
            self.async_set_updated_data(self.data)

        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Failed to connect to %s: %s", self.address, err
            )
        finally:
            self._connecting = False

    @callback
    def _on_hr_notification(self, sender: Any, data: bytearray) -> None:
        """Handle heart rate measurement notification from device."""
        parsed = parse_hr_measurement(data)
        if not parsed:
            return
        self.data.heart_rate = parsed["heart_rate"]
        self.data.rr_intervals = parsed["rr_intervals"]
        self.data.sensor_contact = parsed["sensor_contact"]
        self.data.energy_expended = parsed["energy_expended"]
        self.data.connected = True

        # Accumulate RR intervals for HRV and compute RMSSD
        if parsed["rr_intervals"]:
            now = monotonic()
            for rr in parsed["rr_intervals"]:
                self._rr_history.append((now, rr))
            # Trim to sliding window
            cutoff = now - HRV_WINDOW_SECONDS
            while self._rr_history and self._rr_history[0][0] < cutoff:
                self._rr_history.popleft()
            rr_values = [rr for _, rr in self._rr_history]
            self.data.hrv_rmssd = compute_rmssd(rr_values)

        self.async_set_updated_data(self.data)

    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle BLE disconnect."""
        _LOGGER.info("Disconnected from %s (%s)", self.device_name, self.address)
        self._client = None
        self._rr_history.clear()
        self.data.connected = False
        self.data.heart_rate = None
        self.data.rr_intervals = None
        self.data.sensor_contact = None
        self.data.hrv_rmssd = None
        self.hass.loop.call_soon_threadsafe(self.async_set_updated_data, self.data)

    async def async_disconnect(self) -> None:
        """Disconnect from device (called on unload)."""
        if self._client:
            try:
                await self._client.disconnect()
            except BleakError:
                pass
            self._client = None
