"""Central settings. Edit here, or override with environment variables.

Optional modules are switched with the ENABLE_* flags (also toggleable in the
dashboard sidebar at run time).
"""
import os

# --- Serial (ESP32 DevKit V1) ---------------------------------------------
DEFAULT_PORT = os.environ.get("HOPEPROBE_PORT", "/dev/ttyUSB0")
DEFAULT_BAUD = 115200
BAUD_CHOICES = [9600, 57600, 115200, 230400]

# --- Optional modules --------------------------------------------------------
ENABLE_THERMAL = True        # MLX90614
ENABLE_ULTRASONIC = False    # HC-SR04 (not installed yet -> disabled by default)
ENABLE_CAMERA = True         # ESP32-CAM

# Example: http://192.168.4.1:81/stream  (leave empty until the camera is ready)
CAMERA_URL = os.environ.get("HOPEPROBE_CAM_URL", "")

# --- Behaviour ---------------------------------------------------------------
DATA_TIMEOUT_S = 3.0         # no data for this long -> NO DATA / stale
OBSTACLE_CM = 20.0           # obstacle warning below this distance
HEAT_MIN_C = 30.0            # "possible heat signature" band (object temp)
HEAT_MAX_C = 42.0
SENSOR_LOG_EVERY_S = 10.0    # throttle sensor readings in the event log
REFRESH_S = 1                # dashboard refresh interval
