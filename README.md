# BLE Heart Rate Monitor for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-0.1.0-blue)

A Home Assistant custom integration that connects standard Bluetooth Low Energy (BLE) heart rate monitors directly to Home Assistant — no external app or bridge required. Uses the built-in [Home Assistant Bluetooth Proxy](https://www.home-assistant.io/integrations/bluetooth/) for communication.

## Features

- **Automatic device discovery** via Bluetooth advertising
- **Heart Rate** sensor (bpm) with RR intervals and energy expended as attributes
- **RR Interval** sensor (ms) for raw inter-beat interval data
- **HRV (RMSSD)** sensor (ms) — computed over a 5-minute sliding window
- **Sensor Contact** detection (if supported by device)
- **Battery Level** reporting (if supported by device)
- **Connect switch** — enable/disable the BLE connection on demand (e.g., to free the slot for a phone app)

## Supported Devices

Any BLE heart rate monitor that advertises the standard Heart Rate Service (`0x180D`) should work, including:

Coospo · Polar · Garmin · Wahoo · Magene · Scosche · Moofit · iGPSPORT · XOSS · Bryton

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **Custom repositories**
3. Add `https://github.com/chalimov/ble_heart_rate_ha` as an **Integration**
4. Search for **BLE Heart Rate Monitor** and install it
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/ble_heart_rate` folder into your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Setup

After installation, your heart rate monitor should be automatically discovered if it is advertising. You can also add it manually:

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **BLE Heart Rate Monitor**
3. Select your device from the list

Make sure Bluetooth is enabled and your device is in pairing/advertising mode.

## Sensors

| Sensor | Unit | Default | Description |
|---|---|---|---|
| Heart Rate | bpm | Enabled | Current heart rate with RR intervals as attributes |
| RR Interval | ms | Disabled | Latest raw inter-beat interval |
| HRV (RMSSD) | ms | Enabled | Heart rate variability (5-min window, requires ≥10 RR intervals) |
| Sensor Contact | — | Disabled | Whether the sensor detects skin contact |
| Battery Level | % | Enabled | Device battery percentage (if supported) |

## Connect Switch

The integration provides a **Connect** switch entity that controls the BLE connection. Turning it off disconnects from the heart rate monitor and frees the Bluetooth slot, which is useful if you want to temporarily use the device with a phone app. The switch state persists across Home Assistant restarts.

## Requirements

- Home Assistant with Bluetooth support (built-in adapter or [Bluetooth Proxy](https://www.home-assistant.io/integrations/bluetooth/))
- A BLE heart rate monitor

## License

MIT
