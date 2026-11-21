# HOPEPROBE 3.0 — SEARCH, DETECT, RESCUE

Streamlit control dashboard for the HOPEPROBE disaster-response robot.
Real data only: if hardware is missing the dashboard says DISCONNECTED and shows `--`, never invented values.

```
app.py                      dashboard UI
hopeprobe/config.py         all settings + optional-module switches
hopeprobe/serial_link.py    ESP32 serial layer (background thread)
hopeprobe/camera.py         ESP32-CAM status check (separate from serial)
firmware/hopeprobe_esp32/   Arduino sketch for the ESP32 DevKit V1
tools/serial_test.py        stand-alone serial monitor for debugging
```

## 1. Install (Archcraft / Arch Linux)

```bash
sudo pacman -S --needed python python-pip
cd hopeprobe3
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Serial permission (Arch uses the `uucp` group), then **log out and back in**:

```bash
sudo usermod -aG uucp $USER
groups            # after re-login, "uucp" must be listed
```

## 2. Run

```bash
cd hopeprobe3
source .venv/bin/activate
streamlit run app.py
```

Open http://localhost:8501. The dashboard works with nothing plugged in
(everything shows DISCONNECTED). Use the sidebar to connect.

## 3. Connect the ESP32 (do this in stages)

**Stage 1 – UI only.** Run the dashboard, check the layout, event log and that
STOP/FORWARD buttons say "not sent: ESP32 disconnected".

**Stage 2 – Serial + thermal sensor.**
1. Arduino IDE → install *ESP32 by Espressif* in Boards Manager (no extra libraries needed; thermal data is simulated in the Python dashboard, demo mode).
2. Open `firmware/hopeprobe_esp32/hopeprobe_esp32.ino`, board "ESP32 Dev Module", upload.
   (Hold **BOOT** while "Connecting…" shows if upload fails.)
3. **Close the Arduino Serial Monitor** (it locks the port).
4. `ls /dev/ttyUSB*` (or `/dev/ttyACM*`) to find the port.
5. Dashboard sidebar → port, baud 115200 → CONNECT. Header should turn ESP32 CONNECTED / SYSTEM ONLINE and thermal values appear.

**Stage 3 – Camera.** The ESP32-CAM runs its own firmware (Arduino example
*CameraWebServer*, board "AI Thinker ESP32-CAM"). It is a separate device on
Wi-Fi, independent from the DevKit serial link. Put the MJPEG URL in the sidebar,
e.g. `http://192.168.4.1:81/stream`, or set `HOPEPROBE_CAM_URL` / `CAMERA_URL` in
`hopeprobe/config.py`. The laptop's browser must be able to reach that address
(join the camera's Wi-Fi or the same network). The ESP32-CAM serves one stream
client at a time, so don't open the stream in another tab.

**Stage 4 – Motors.** Wire the L298N (pins in the sketch header). Test with
wheels **off the ground** first. If a direction is reversed, swap that motor's wires.

**Stage 5 – Ultrasonic (when you get it).** Wire HC-SR04 (ECHO through a
5 V→3.3 V divider!), set `ENABLE_ULTRASONIC 1` in the sketch, re-upload, then
tick the Ultrasonic box in the sidebar (or `ENABLE_ULTRASONIC = True` in `config.py`).

## 4. Serial protocol

ASCII lines ending in `\n`, 115200 baud.

| PC → ESP32 | meaning |
|---|---|
| `CMD,F` `CMD,B` `CMD,L` `CMD,R` | forward / backward / left / right |
| `CMD,S` | stop |
| `PING` | heartbeat (every 1 s) – firmware stops motors after 3 s without any PC message |
| `HELLO?` | ask for `HELLO` + `STATUS` |

| ESP32 → PC | meaning |
|---|---|
| `HELLO,HOPEPROBE,1.0` | firmware announce |
| `DIST,<cm>` | HC-SR04 (only if fitted) |
| `STATUS,US,<0\|1>` | sensor detected? |
| `ACK,<cmd>` | command executed |
| `PONG`, `ERR,<text>` | heartbeat reply / error |

The robot status in the header changes **only after an `ACK`** from the ESP32.

## 5. Debugging

Quick test without the dashboard: `python tools/serial_test.py /dev/ttyUSB0`

| Problem | Fix |
|---|---|
| `No such file or directory: '/dev/ttyUSB0'` | Wrong port or cable is charge-only. Unplug/replug, run `ls /dev/ttyUSB* /dev/ttyACM*` and `dmesg \| tail`. Use the port shown. |
| `Permission denied` | Not in `uucp` group: `sudo usermod -aG uucp $USER`, then log out/in. Quick test only: `sudo chmod 666 /dev/ttyUSB0`. |
| `Device or resource busy` | Another program has the port: close Arduino Serial Monitor / `screen` / old dashboard. Find it with `fuser /dev/ttyUSB0`. |
| Port opens but ESP32 stays NO DATA | Wrong baud (must be 115200 in sketch and dashboard), firmware not uploaded, or press EN/RESET on the board. |
| Port never appears in `dmesg` | Bad USB cable/port; try another. Some ESP32 boards need a CP210x/CH340 driver – on Arch these are in the kernel (`lsmod \| grep -E "cp210x\|ch341"`). |
| ESP32 resets every time you connect | Normal (DTR toggles reset). Wait ~1 s for `HELLO`. |
| Upload fails "Connecting…" | Hold BOOT during upload. Disconnect anything on GPIO 0/2 and the L298N 5 V while flashing. |
| Thermal shows SENSOR FAULT | Check SDA=21, SCL=22, 3.3 V, GND; sensor needs I²C pull-ups (most breakouts have them). |
| Garbled characters in log | Baud mismatch. |
| Camera DISCONNECTED | Laptop not on the camera's network, wrong IP/port in URL, or camera not powered (needs a stable 5 V ≥ 500 mA). |
| Dashboard stops after cable pulled | It shouldn't: the log shows "ESP32 disconnected – communication failure". Click CONNECT again after re-plugging. |

## 6. Notes

- Optional modules: `ENABLE_*` in `hopeprobe/config.py` or sidebar checkboxes. Ultrasonic is **off by default**.
- The "possible heat signature" note (object temperature 30–42 °C) is only an indicator; MLX90614 readings depend on distance and surface. Tune `HEAT_MIN_C/HEAT_MAX_C` in config.
- The dashboard is a student/exhibition project, not a certified rescue device.
