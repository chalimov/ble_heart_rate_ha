# BLE Heart Rate Monitor for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-0.2.0-blue)

A Home Assistant custom integration that connects standard Bluetooth Low Energy (BLE) heart rate monitors directly to Home Assistant — no external app or bridge required. Uses the built-in [Home Assistant Bluetooth stack](https://www.home-assistant.io/integrations/bluetooth/) (local adapter or Bluetooth Proxy) for communication.

Ships with **clinically-grounded HRV metrics**: RMSSD with Malik-rule artifact rejection, Elite-HRV-style 0–100 score, and DFA α1 with automatic training-zone classification for runners.

## Features

- **Automatic device discovery** via BLE advertising of the standard Heart Rate Service (`0x180D`).
- **Live heart rate** in bpm, parsed per the Bluetooth HRS 1.0 spec (HR8 / HR16, optional energy-expended, multiple RR sub-fields per notification).
- **Resting HRV** via RMSSD (ms) over a 5-minute sliding window, with artifact rejection.
- **HRV Score** — 0–100 log-normalized scale following the Elite HRV convention.
- **Exercise HRV** via DFA α1 (short-term fractal scaling exponent) over a 2-minute beat window.
- **Automatic training-zone detection** (recovery / aerobic / threshold / anaerobic) derived from DFA α1.
- **Sensor contact** state, **battery level**, and raw **RR intervals** exposed for power users.
- **Connect switch** — toggle the BLE connection on demand (e.g., to free the device for a phone app). State persists across restarts.
- **Auto-reconnect** on disconnect, with exponential backoff and advertisement-driven wakeup.

## Supported Devices

Any BLE heart rate monitor that advertises the standard Heart Rate Service (`0x180D`) should work. Tested and branded for:

Coospo · Polar · Garmin · Wahoo · Magene · Scosche · Moofit · iGPSPORT · XOSS · Bryton

> **Note on DFA α1 accuracy**: DFA α1 is sensitive to missed beats and motion-induced RR errors. **Chest straps** (Polar H10, Coospo H9Z, Wahoo Tickr, etc.) produce reliable α1 during exercise. **Optical wrist sensors** (Apple Watch, Fenix wrist, etc.) are *not* recommended for DFA α1 — they miss beats under motion and the metric becomes noisy. RMSSD at rest works fine on both.

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** → **Custom repositories**.
3. Add `https://github.com/chalimov/ble_heart_rate_ha` as an **Integration**.
4. Search for **BLE Heart Rate Monitor** and install it.
5. Restart Home Assistant.

### Manual

1. Copy the `custom_components/ble_heart_rate` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Setup

After installation, your heart rate monitor should be discovered automatically if it is advertising. You can also add it manually:

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **BLE Heart Rate Monitor**.
3. Select your device from the list.

Make sure Bluetooth is enabled and your device is in advertising mode (chest strap worn, or sensor activated).

## Sensors

| Sensor | Unit | Default | Description |
|---|---|---|---|
| Heart Rate | bpm | Enabled | Current heart rate. RR intervals, sensor contact, and energy expended exposed as attributes. |
| RR Interval | ms | Disabled | Most recent inter-beat interval (float, displayed as integer). |
| HRV (RMSSD) | ms | Enabled | Root-Mean-Square of Successive Differences, 5-min window, Malik-rule artifact rejection. The standard resting HRV metric. |
| HRV Score | — | Enabled | 0–100 log-normalized score derived from RMSSD (Elite HRV convention). |
| HRV DFA α1 | — | **Disabled** | Short-term fractal scaling exponent over 2-min beat window. Exercise metric. |
| Training Zone | enum | **Disabled** | Derived from DFA α1: `recovery` / `aerobic` / `threshold` / `anaerobic`. |
| Sensor Contact | — | Disabled | Whether the sensor detects skin contact (if device supports it). |
| Battery Level | % | Enabled | Device battery percentage (if device supports it). |

### Why `hrv_dfa_alpha1` and `training_zone` are disabled by default

These are **exercise metrics**, calibrated for active running/cycling. During normal 24/7 household monitoring they produce noisy, low-signal output. Enable them from the entity registry when you're actively using the strap for training.

## Understanding the HRV metrics

This integration exposes **three complementary HRV views**, each appropriate for a different context.

### HRV (RMSSD) — the resting autonomic-state metric

RMSSD is the most widely validated time-domain HRV metric (ECS/NASPE Task Force 1996). It reflects **parasympathetic/vagal tone** — higher values = better recovery state.

- **Window**: 5-minute sliding (Task Force short-term standard).
- **Gating**: requires ≥60 s of accumulated data and ≥20 valid NN pairs before reporting a value.
- **Artifact rejection** (Malik rule):
  - Physiological bounds 300–2000 ms (30–200 bpm).
  - Any RR differing by >20 % from the previous valid RR is flagged as ectopic.
  - Successive differences crossing an artifact are excluded from RMSSD (NN-only).
- **Best use**: morning, supine, after waking, before caffeine. Day-over-day trend is the signal, not absolute value.

### HRV Score — easier-to-read 0–100

RMSSD is log-normally distributed, so a 45 → 50 change means much more than 80 → 85. The score fixes that:

> **HRV Score = (ln(RMSSD) / 6.5) × 100**, clamped to 0–100.

| RMSSD | Score |
|------:|------:|
| 10 ms | 35 |
| 25 ms | 50 |
| 50 ms | 60 |
| 100 ms | 71 |
| 665 ms | 100 |

Typical healthy adult morning readings fall in the **50–75** band. A drop of >5 points vs your personal 7-day average is an early fatigue/stress signal.

### HRV DFA α1 — the exercise intensity metric

Short-term detrended fluctuation analysis scaling exponent (box sizes n=4..16 beats). Unlike RMSSD, α1 captures the **correlation structure** of successive RR intervals rather than their variance. It decreases monotonically with exercise intensity and is validated (Rogers & Gronwald 2020–2023) as a non-invasive proxy for ventilatory / lactate thresholds.

| α1 range | Zone | Physiological meaning |
|---|---|---|
| ≥ 1.0 | **recovery** | Rest or very low intensity; highly correlated RR structure. |
| 0.75 – 1.0 | **aerobic** | Easy, below aerobic threshold (VT1). |
| 0.5 – 0.75 | **threshold** | Between VT1 and anaerobic threshold (VT2). |
| < 0.5 | **anaerobic** | Above VT2; uncorrelated RR. |

Requires ≥64 valid beats; uses up to the most recent 240 valid NN intervals (~2 min at 120 bpm).

### Rest vs running — which metric to use when

| Context | Useful metric | Why |
|---|---|---|
| Morning wake-up HRV tracking | **HRV / HRV Score** | RMSSD at rest is the gold-standard recovery indicator. |
| Steady-state running / cycling | **DFA α1 / Training Zone** | RMSSD collapses to 2–10 ms during exercise and loses resolution. α1 remains informative. |
| During exercise | **Heart Rate** (obviously), **Training Zone** | Use zone transitions for effort guidance. |
| Post-exercise recovery window | **HRV (trending back to baseline)** | Nightly RMSSD return to resting levels indicates recovery. |

## Automations — example patterns

**Resting HRV only (filter out exercise readings):**

```yaml
template:
  - sensor:
      - name: "Resting HRV"
        unit_of_measurement: "ms"
        state: >
          {% if states('sensor.heart_rate_monitor_heart_rate') | int(0) < 90
             and states('sensor.heart_rate_monitor_hrv') not in ['unavailable','unknown','None'] %}
            {{ states('sensor.heart_rate_monitor_hrv') }}
          {% endif %}
```

**Fatigue alert on morning HRV drop:**

```yaml
alias: "HRV morning fatigue alert"
trigger:
  - platform: time
    at: "07:30:00"
condition:
  - condition: template
    value_template: >
      {{ states('sensor.heart_rate_monitor_hrv_score') | float(0)
         < (state_attr('sensor.hrv_7day_avg','state') | float(0)) - 5 }}
action:
  - service: notify.mobile_app
    data:
      message: "HRV score down — consider an easy day."
```

**Training-zone announcements during a run:**

```yaml
alias: "Zone change notification"
trigger:
  - platform: state
    entity_id: sensor.heart_rate_monitor_training_zone
action:
  - service: notify.mobile_app
    data:
      message: "Now in {{ trigger.to_state.state }} zone"
```

## Connect Switch

The integration provides a **Connect** switch entity that controls the BLE connection. Turning it off disconnects from the heart rate monitor and frees the Bluetooth slot, which is useful if you want to temporarily use the device with a phone app. The switch state persists across Home Assistant restarts and survives integration reloads.

## Technical Notes

- **BLE parsing**: full Heart Rate Service 1.0 spec — 8-bit and 16-bit HR, optional energy-expended, up to 9 RR sub-fields per notification. RR is decoded in float ms from its native 1/1024-s units.
- **Artifact rejection**: Malik (1996) criterion — physiological bounds + 20 % successive-change threshold. Rejected RR intervals are kept in history but excluded from HRV computation as NN-pair gaps.
- **RMSSD formula**: `√(Σ(NNᵢ₊₁ − NNᵢ)² / M)` over M valid NN pairs in the 5-min window.
- **DFA α1 implementation**: cumulative mean-centred integration → non-overlapping boxes n∈{4..16} → linear per-box detrending → log-log regression of F(n) vs n. Numpy-vectorized.
- **No external dependencies** beyond `bleak-retry-connector` (already a HA core dep) and `numpy` (transitive through HA core).
- **Reconnect strategy**: 60-s periodic retry, advertisement-triggered fast reconnect via the HA Bluetooth stack.

## Requirements

- Home Assistant 2024.1 or newer.
- Bluetooth support (local adapter or [Bluetooth Proxy](https://www.home-assistant.io/integrations/bluetooth/)).
- A BLE heart rate monitor advertising service `0x180D`.
- For DFA α1: a chest strap (optical wrist HR is not accurate enough).

## Troubleshooting

**HRV sensor shows "unavailable" immediately after connecting.**
Expected — requires ≥60 s of data and ≥20 valid NN pairs. Wear the strap for 1–2 minutes before checking.

**RMSSD is unrealistically high (>150 ms).**
Check sensor contact. Poor contact causes missed beats that, even with artifact rejection, can leak through as paired long-short RR patterns. Wet the strap electrodes if it's a chest strap.

**DFA α1 is erratic during a run.**
Likely a sensor issue (optical wrist HR, or poor chest-strap contact). DFA α1 is the most motion-sensitive metric in this integration.

**Training Zone stays on "recovery" during a run.**
α1 only drops with sustained intensity. Short sprints may not show; a steady 10-min tempo effort should drop to "aerobic" or below.

## Changelog

See [releases](https://github.com/chalimov/ble_heart_rate_ha/releases).

### 0.2.0
- **Medical-grade HRV correctness**: Malik-rule artifact rejection, NN-only RMSSD, float RR throughout, window + min-pair gating (≥60 s, ≥20 NN pairs).
- **New sensors**: `hrv_score` (0–100 log-normalized), `hrv_dfa_alpha1` (short-term fractal exponent), `training_zone` (enum).
- **Exercise-ready**: DFA α1 with Rogers-Gronwald threshold mapping for real-time training-intensity detection.

## License

MIT
