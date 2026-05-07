"""Constants for the BLE Heart Rate integration."""

DOMAIN = "ble_heart_rate"

# Standard BLE Heart Rate Service (0x180D)
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_CHAR = "00002a37-0000-1000-8000-00805f9b34fb"

# Standard BLE Battery Service (0x180F)
BATTERY_LEVEL_CHAR = "00002a19-0000-1000-8000-00805f9b34fb"

# User-configurable HR-zone parameters (Karvonen / heart-rate reserve method).
# %HRR = (HR − HRrest) / (HRmax − HRrest); zones map onto bands of %HRR.
CONF_HRMAX = "hrmax"
CONF_HRREST = "hrrest"
DEFAULT_HRMAX = 173
DEFAULT_HRREST = 55

# Karvonen HRR thresholds → 4-zone classification.
# %HRR equivalence to %VO2-reserve is the line-of-identity (Swain 1997, ACSM),
# so these are the physiologically meaningful boundaries:
#   <60% recovery / 60–75% aerobic / 75–90% threshold / ≥90% anaerobic
ZONE_RECOVERY_HRR = 0.60
ZONE_AEROBIC_HRR = 0.75
ZONE_THRESHOLD_HRR = 0.90
