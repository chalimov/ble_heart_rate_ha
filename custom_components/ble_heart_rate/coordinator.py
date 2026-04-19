"""Coordinator for BLE Heart Rate Monitor integration."""
from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import Any

import numpy as np

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import HR_MEASUREMENT_CHAR, BATTERY_LEVEL_CHAR

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = timedelta(seconds=60)
CONNECT_TIMEOUT = 15  # seconds — HA recommends ≥10s for BLE
HRV_WINDOW_SECONDS = 300  # 5-minute sliding window (Task Force short-term standard)
HRV_MIN_WINDOW_SECONDS = 60  # require ≥1 min of data before reporting RMSSD
HRV_MIN_VALID_PAIRS = 20  # minimum valid successive-difference pairs
BATTERY_REFRESH_INTERVAL = 600  # re-read battery every 10 minutes

# Artifact rejection thresholds (Malik / Task Force 1996).
RR_MIN_MS = 300.0  # 200 bpm — anything faster is an artifact
RR_MAX_MS = 2000.0  # 30 bpm — anything slower is an artifact or missed beat
RR_MAX_REL_CHANGE = 0.20  # reject RR differing >20% from last valid RR

# DFA α1 parameters (Rogers & Gronwald short-term scaling exponent).
DFA_MIN_BEATS = 64  # min valid beats for a meaningful α1
DFA_MAX_BEATS = 240  # rolling window length; ≈2 min at 120 bpm
DFA_BOX_SIZES = tuple(range(4, 17))  # n ∈ {4..16} defines "short-term" α1
# Training-zone thresholds mapping α1 → intensity band.
# α1 ≥ 1.0: correlated, low-intensity/rest
# 0.75 ≤ α1 < 1.0: easy/aerobic (below VT1)
# 0.5 ≤ α1 < 0.75: threshold (between VT1 and VT2)
# α1 < 0.5: anaerobic (above VT2), trending toward uncorrelated/white noise
ZONE_AEROBIC_THRESHOLD = 0.75
ZONE_ANAEROBIC_THRESHOLD = 0.5
ZONE_RECOVERY_THRESHOLD = 1.0

# Minimum packet lengths for parsing validation
_MIN_LEN_HR8 = 2  # flags + 1-byte HR
_MIN_LEN_HR16 = 3  # flags + 2-byte HR


@dataclass
class HeartRateData:
    """Data from heart rate monitor."""

    heart_rate: int | None = None
    rr_intervals: list[float] | None = None  # milliseconds (current notification)
    sensor_contact: bool | None = None  # None = feature not supported
    energy_expended: int | None = None  # kJ
    battery_level: int | None = None
    hrv_rmssd: float | None = None  # RMSSD in ms
    hrv_score: int | None = None  # Elite-HRV-style 0–100 score
    hrv_dfa_alpha1: float | None = None  # short-term fractal scaling exponent
    training_zone: str | None = None  # recovery / aerobic / threshold / anaerobic
    connected: bool = False


def is_physiological_rr(rr_ms: float) -> bool:
    """True if RR interval is within physiological bounds (30–200 bpm)."""
    return RR_MIN_MS <= rr_ms <= RR_MAX_MS


def is_artifact(rr_ms: float, prev_valid: float | None) -> bool:
    """Malik rule: flag RR as artifact if out of range or >20% change from prior."""
    if not is_physiological_rr(rr_ms):
        return True
    if prev_valid is None:
        return False
    return abs(rr_ms - prev_valid) / prev_valid > RR_MAX_REL_CHANGE


def compute_rmssd(
    entries: list[tuple[float, float, bool]],
) -> float | None:
    """Compute RMSSD in ms from a history of (timestamp, rr_ms, is_valid) entries.

    Follows Task Force 1996: RMSSD = √(Σ(NNᵢ₊₁−NNᵢ)² / M) over M valid adjacent
    NN pairs. Successive differences are only included when both RR endpoints
    are flagged valid (non-ectopic). Requires ≥HRV_MIN_WINDOW_SECONDS of data
    and ≥HRV_MIN_VALID_PAIRS usable pairs.
    """
    if not entries:
        return None
    if entries[-1][0] - entries[0][0] < HRV_MIN_WINDOW_SECONDS:
        return None
    sq_sum = 0.0
    count = 0
    for i in range(len(entries) - 1):
        _, rr_a, valid_a = entries[i]
        _, rr_b, valid_b = entries[i + 1]
        if valid_a and valid_b:
            diff = rr_b - rr_a
            sq_sum += diff * diff
            count += 1
    if count < HRV_MIN_VALID_PAIRS:
        return None
    return round(math.sqrt(sq_sum / count), 1)


def compute_hrv_score(rmssd_ms: float | None) -> int | None:
    """Compute Elite-HRV-style 0–100 score from RMSSD in ms.

    Formula: (ln(RMSSD) / 6.5) × 100, clamped to [0, 100] and rounded to int.
    6.5 is the empirical upper bound of ln(RMSSD) from Elite HRV's reference
    dataset (~6M readings). Log-normalization flattens the skewed RMSSD
    distribution so equal score deltas correspond to equal autonomic-state
    deltas (30→40 RMSSD is a bigger change than 70→80).
    """
    if rmssd_ms is None or rmssd_ms <= 0:
        return None
    score = (math.log(rmssd_ms) / 6.5) * 100.0
    return int(round(max(0.0, min(100.0, score))))


def compute_dfa_alpha1(rr_ms: list[float]) -> float | None:
    """Short-term DFA scaling exponent α1 over RR intervals.

    Peng et al. 1994 DFA: integrate the mean-centred series, split into
    non-overlapping boxes of size n ∈ {4..16}, detrend each box with a
    linear least-squares fit, and compute F(n) = RMS of residuals across
    all boxes. α1 is the slope of log(F(n)) vs log(n).

    Physiology (Rogers & Gronwald): α1 drops monotonically with exercise
    intensity — ~1.0 at rest, ~0.75 at aerobic threshold (VT1), ~0.5 at
    anaerobic threshold (VT2). Returns None if the window is too short or
    the signal is flat (F(n)=0, undefined log).
    """
    n_beats = len(rr_ms)
    if n_beats < DFA_MIN_BEATS:
        return None
    rr = np.asarray(rr_ms[-DFA_MAX_BEATS:], dtype=np.float64)
    y = np.cumsum(rr - rr.mean())

    log_n: list[float] = []
    log_F: list[float] = []
    for n in DFA_BOX_SIZES:
        n_boxes = y.size // n
        if n_boxes < 1:
            continue
        boxes = y[: n_boxes * n].reshape(n_boxes, n).astype(np.float64)
        x = np.arange(n, dtype=np.float64)
        x_centered = x - x.mean()
        denom = float((x_centered ** 2).sum())
        if denom == 0.0:
            continue
        y_mean = boxes.mean(axis=1, keepdims=True)
        slopes = ((boxes - y_mean) * x_centered).sum(axis=1) / denom
        intercepts = y_mean.ravel() - slopes * x.mean()
        fitted = slopes[:, None] * x + intercepts[:, None]
        residuals = boxes - fitted
        F_n = float(np.sqrt(np.mean(residuals ** 2)))
        if F_n <= 0.0:
            continue  # flat signal at this scale — undefined log
        log_n.append(math.log(n))
        log_F.append(math.log(F_n))

    if len(log_n) < 3:
        return None
    slope, _ = np.polyfit(np.array(log_n), np.array(log_F), 1)
    return round(float(slope), 3)


def classify_training_zone(alpha1: float | None) -> str | None:
    """Map DFA α1 to a training-intensity zone per Rogers & Gronwald thresholds."""
    if alpha1 is None:
        return None
    if alpha1 >= ZONE_RECOVERY_THRESHOLD:
        return "recovery"
    if alpha1 >= ZONE_AEROBIC_THRESHOLD:
        return "aerobic"
    if alpha1 >= ZONE_ANAEROBIC_THRESHOLD:
        return "threshold"
    return "anaerobic"


def parse_hr_measurement(data: bytes | bytearray) -> dict[str, Any]:
    """Parse BLE Heart Rate Measurement characteristic (0x2A37).

    Format per Bluetooth HRS spec:
      Byte 0: Flags
        Bit 0: HR format (0=UINT8, 1=UINT16)
        Bits 1-2: Sensor contact (0b1x = supported, bit 0 = detected)
        Bit 3: Energy expended present
        Bit 4: RR-Interval present
      Byte 1+: HR value, optional energy, optional RR intervals

    Returns empty dict if data is missing or truncated.
    """
    if not data or len(data) < _MIN_LEN_HR8:
        return {}

    flags = data[0]
    hr_16bit = bool(flags & 0x01)
    contact_bits = (flags >> 1) & 0x03
    energy_present = bool(flags & 0x08)
    rr_present = bool(flags & 0x10)

    # Validate minimum length for the HR format
    min_len = _MIN_LEN_HR16 if hr_16bit else _MIN_LEN_HR8
    if len(data) < min_len:
        return {}

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

    # Energy expended (UINT16 LE, kJ) — need 2 full bytes
    energy_expended = None
    if energy_present and offset + 2 <= len(data):
        energy_expended = int.from_bytes(data[offset : offset + 2], "little")
        offset += 2

    # RR intervals (UINT16 LE each, units of 1/1024 seconds). Kept as float ms
    # to preserve sub-ms resolution for HRV — rounding each to int would add
    # ~±0.5 ms uncorrelated noise per interval, inflating RMSSD.
    rr_intervals = None
    if rr_present:
        rr_intervals = []
        while offset + 2 <= len(data):
            rr_raw = int.from_bytes(data[offset : offset + 2], "little")
            rr_ms = rr_raw * 1000.0 / 1024.0
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
        self._setup_complete = False  # set True after switch restore
        # Sliding window of (timestamp, rr_ms, is_valid) for HRV calculation.
        # is_valid reflects Malik-rule artifact rejection at ingestion time.
        self._rr_history: deque[tuple[float, float, bool]] = deque()
        self._last_valid_rr: float | None = None
        self._last_battery_read: float = 0.0

    async def _async_update_data(self) -> HeartRateData:
        """Periodic reconnection attempt if disconnected."""
        if (
            self._setup_complete
            and self.enabled
            and not self._client
            and not self._connecting
        ):
            await self._connect()
        return self.data

    @callback
    def handle_bluetooth_event(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Handle BLE advertisement — trigger connection if not connected."""
        if (
            self._setup_complete
            and self.enabled
            and not self._client
            and not self._connecting
        ):
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
                timeout=CONNECT_TIMEOUT,
            )

            # Check if disabled or already disconnected during await
            if not self.enabled or not client.is_connected:
                if client.is_connected:
                    await client.disconnect()
                return

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
                self._last_battery_read = monotonic()
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

        # Accumulate RR intervals for HRV and compute RMSSD.
        # Each RR is tagged valid/invalid via the Malik rule at ingestion so
        # that successive differences crossing an artifact are skipped later.
        now = monotonic()
        if parsed["rr_intervals"]:
            prev_valid = self._last_valid_rr
            for rr in parsed["rr_intervals"]:
                valid = not is_artifact(rr, prev_valid)
                self._rr_history.append((now, rr, valid))
                if valid:
                    prev_valid = rr
            self._last_valid_rr = prev_valid
            # Trim to sliding window
            cutoff = now - HRV_WINDOW_SECONDS
            while self._rr_history and self._rr_history[0][0] < cutoff:
                self._rr_history.popleft()
            self.data.hrv_rmssd = compute_rmssd(list(self._rr_history))
            self.data.hrv_score = compute_hrv_score(self.data.hrv_rmssd)
            # DFA α1 is beat-indexed, not time-indexed, and uses only valid NN
            valid_rrs = [rr for _, rr, v in self._rr_history if v]
            self.data.hrv_dfa_alpha1 = compute_dfa_alpha1(valid_rrs)
            self.data.training_zone = classify_training_zone(
                self.data.hrv_dfa_alpha1
            )

        # Periodically re-read battery level
        if (
            self._client
            and now - self._last_battery_read > BATTERY_REFRESH_INTERVAL
        ):
            self._last_battery_read = now
            self.hass.async_create_task(self._read_battery())

        self.async_set_updated_data(self.data)

    @callback
    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle BLE disconnect (called on event loop by bleak)."""
        _LOGGER.info("Disconnected from %s (%s)", self.device_name, self.address)
        self._client = None
        self._rr_history.clear()
        self._last_valid_rr = None
        self.data.connected = False
        self.data.heart_rate = None
        self.data.rr_intervals = None
        self.data.sensor_contact = None
        self.data.hrv_rmssd = None
        self.data.hrv_score = None
        self.data.hrv_dfa_alpha1 = None
        self.data.training_zone = None
        self.async_set_updated_data(self.data)

    async def async_disconnect(self) -> None:
        """Disconnect from device (called on unload or switch-off)."""
        client = self._client
        self._client = None  # prevent _on_disconnect from double-processing
        if client:
            try:
                await client.disconnect()
            except BleakError:
                pass
        # Always clear data — don't rely on disconnect callback firing
        self._rr_history.clear()
        self._last_valid_rr = None
        self.data = HeartRateData()
        self.async_set_updated_data(self.data)

    async def _read_battery(self) -> None:
        """Re-read battery level from the device."""
        client = self._client
        if not client or not client.is_connected:
            return
        try:
            battery_data = await client.read_gatt_char(BATTERY_LEVEL_CHAR)
            self.data.battery_level = battery_data[0]
            self.async_set_updated_data(self.data)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Battery re-read failed on %s", self.address)

    async def async_request_connect(self) -> None:
        """Public method to trigger a connection attempt."""
        if not self._client and not self._connecting:
            await self._connect()
