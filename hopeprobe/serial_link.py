"""ESP32 serial communication layer (PySerial).

Runs a background reader thread so the Streamlit UI never blocks.
Only real data received from the ESP32 is ever stored. When the port is
closed or the ESP32 goes silent, readings are cleared / reported stale.

PROTOCOL (ASCII, one message per line, comma separated, '\\n' terminated)

  PC -> ESP32
    CMD,F|B|L|R|S      move forward/backward/left/right, S = stop
    PING               heartbeat, sent every 1 s (firmware stops motors
                       if no PC message arrives for 3 s)
    HELLO?             ask firmware to announce itself

  ESP32 -> PC
    HELLO,HOPEPROBE,<fw_version>
    TEMP,<object_C>,<ambient_C>      MLX90614 reading
    DIST,<cm>                        HC-SR04 reading (only if fitted)
    STATUS,MLX,<0|1>                 thermal sensor detected?
    STATUS,US,<0|1>                  ultrasonic sensor fitted?
    ACK,<F|B|L|R|S>                  command executed
    PONG
    ERR,<text>
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime

import serial
from serial.tools import list_ports

from . import config
from .thermal_sim import ThermalSimulator

CMD_NAMES = {"F": "FORWARD", "B": "BACKWARD", "L": "LEFT", "R": "RIGHT", "S": "STOP"}


def list_serial_ports() -> list[str]:
    try:
        return sorted(p.device for p in list_ports.comports())
    except Exception:
        return []


class SerialLink:
    def __init__(self) -> None:
        self._lock = threading.RLock()      # protects state
        self._wlock = threading.Lock()      # serialises writes
        self._ser: serial.Serial | None = None
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

        self.port = config.DEFAULT_PORT
        self.baud = config.DEFAULT_BAUD
        self.thermal_enabled = config.ENABLE_THERMAL
        self.ultra_enabled = config.ENABLE_ULTRASONIC
        self.thermal_sim = ThermalSimulator()   # demo mode: values generated in Python

        self.events: deque = deque(maxlen=400)
        self._last_sensor_log = 0.0
        self._last_obstacle_log = 0.0
        self._reset_data()
        self.log("INFO", "System startup - HOPEPROBE 3.0 dashboard started")

    # ------------------------------------------------------------------ state
    def _reset_data(self) -> None:
        self.last_rx: float | None = None          # monotonic
        self.last_rx_wall: datetime | None = None
        self.firmware: str | None = None
        self.mlx_ok: bool | None = None            # None = unknown
        self.us_ok: bool | None = None
        self.thermal: tuple[float, float, float] | None = None   # obj, amb, t
        self.distance: tuple[float, float] | None = None         # cm, t
        self.last_cmd: str | None = None
        self.last_ack: str | None = None           # last ACKed command letter
        self.cmd_pending = False

    def log(self, level: str, msg: str) -> None:
        with self._lock:
            self.events.append((datetime.now().strftime("%H:%M:%S"), level, msg))

    # ------------------------------------------------------------ connection
    def connect(self, port: str, baud: int) -> tuple[bool, str]:
        self.disconnect(quiet=True)
        self.port, self.baud = port, int(baud)
        try:
            ser = serial.Serial(port, int(baud), timeout=0.3, write_timeout=1.0)
        except (serial.SerialException, OSError, ValueError) as exc:
            msg = f"Cannot open {port}: {exc}"
            self.log("ERROR", msg)
            return False, msg
        stop = threading.Event()
        with self._lock:
            self._reset_data()
            self._ser, self._stop = ser, stop
        self._thread = threading.Thread(
            target=self._reader, args=(ser, stop), daemon=True, name="hp-serial")
        self._thread.start()
        self.log("INFO", f"Serial port {port} opened @ {baud} baud - waiting for ESP32 data")
        self._write(b"HELLO?\n")
        return True, f"Port {port} opened"

    def disconnect(self, quiet: bool = False) -> None:
        with self._lock:
            ser, stop = self._ser, self._stop
            self._ser = self._stop = None
        if ser is None:
            return
        try:                                  # best-effort safety stop
            with self._wlock:
                ser.write(b"CMD,S\n")
        except Exception:
            pass
        if stop:
            stop.set()
        try:
            ser.close()
        except Exception:
            pass
        with self._lock:
            self._reset_data()
        if not quiet:
            self.log("INFO", "ESP32 disconnected by operator (stop sent)")

    def _lost(self, ser: serial.Serial, exc: Exception) -> None:
        """Called by the reader thread when the port dies (cable pulled etc.)."""
        with self._lock:
            if self._ser is not ser:
                return
            self._ser = self._stop = None
            self._reset_data()
        try:
            ser.close()
        except Exception:
            pass
        self.log("ERROR", f"ESP32 disconnected - communication failure: {exc}")

    # --------------------------------------------------------------- writing
    def _write(self, data: bytes) -> bool:
        with self._lock:
            ser = self._ser
        if ser is None:
            return False
        try:
            with self._wlock:
                ser.write(data)
            return True
        except (serial.SerialException, OSError) as exc:
            self._lost(ser, exc)
            return False

    def send_command(self, cmd: str) -> tuple[bool, str]:
        """Send a movement command. Never pretends success when offline."""
        cmd = cmd.upper()
        name = CMD_NAMES.get(cmd)
        if name is None:
            return False, f"Unknown command {cmd!r}"
        with self._lock:
            connected = self._ser is not None
        if not connected:
            self.log("WARN", f"Command {name} NOT sent - ESP32 disconnected")
            return False, f"{name} not sent: ESP32 disconnected"
        if not self._write(f"CMD,{cmd}\n".encode()):
            self.log("ERROR", f"Command {name} failed to send")
            return False, f"{name} failed: serial write error"
        with self._lock:
            self.last_cmd = cmd
            self.cmd_pending = True
        self.log("CMD", f"Command sent: {name} (awaiting ACK)")
        return True, f"{name} sent, awaiting ACK"

    # --------------------------------------------------------------- reading
    def _reader(self, ser: serial.Serial, stop: threading.Event) -> None:
        last_ping = 0.0
        while not stop.is_set():
            try:
                now = time.monotonic()
                if now - last_ping >= 1.0:
                    last_ping = now
                    with self._wlock:
                        ser.write(b"PING\n")
                raw = ser.readline()
                if raw:
                    self._handle(raw.decode("ascii", errors="replace").strip())
            except (serial.SerialException, OSError) as exc:
                if not stop.is_set():
                    self._lost(ser, exc)
                return
            except Exception as exc:                      # never kill the thread
                self.log("ERROR", f"Reader error: {exc}")

    def _handle(self, line: str) -> None:
        if not line:
            return
        parts = [p.strip() for p in line.split(",")]
        tag = parts[0].upper()
        now = time.monotonic()
        with self._lock:
            self.last_rx, self.last_rx_wall = now, datetime.now()
        try:
            if tag == "HELLO" and len(parts) >= 3:
                with self._lock:
                    self.firmware = parts[2]
                self.log("INFO", f"ESP32 connected - firmware {parts[2]}")
            elif tag == "TEMP" and len(parts) >= 3:
                if config.SIMULATE_THERMAL:
                    return                    # thermal handled in Python; ignore ESP32 values
                obj, amb = float(parts[1]), float(parts[2])
                if math.isnan(obj) or math.isnan(amb):
                    return
                with self._lock:
                    self.thermal = (obj, amb, now)
                    due = now - self._last_sensor_log >= config.SENSOR_LOG_EVERY_S
                    if due:
                        self._last_sensor_log = now
                if due:
                    self.log("SENSOR", f"MLX90614 object {obj:.1f} C, ambient {amb:.1f} C")
            elif tag == "DIST" and len(parts) >= 2:
                if not self.ultra_enabled:
                    return
                cm = float(parts[1])
                with self._lock:
                    self.distance = (cm, now)
                if cm < config.OBSTACLE_CM and now - self._last_obstacle_log > 3.0:
                    self._last_obstacle_log = now
                    self.log("WARN", f"OBSTACLE WARNING: {cm:.0f} cm ahead")
            elif tag == "STATUS" and len(parts) >= 3:
                ok = parts[2] == "1"
                with self._lock:
                    if parts[1].upper() == "MLX":
                        changed = self.mlx_ok != ok
                        self.mlx_ok = ok
                        label = "Thermal sensor (MLX90614)"
                    elif parts[1].upper() == "US":
                        changed = self.us_ok != ok
                        self.us_ok = ok
                        label = "Ultrasonic sensor (HC-SR04)"
                    else:
                        return
                if changed:
                    self.log("INFO" if ok else "WARN",
                             f"{label} {'detected' if ok else 'not detected'}")
            elif tag == "ACK" and len(parts) >= 2:
                c = parts[1].upper()
                with self._lock:
                    self.last_ack = c
                    self.cmd_pending = False
                self.log("CMD", f"ESP32 acknowledged: {CMD_NAMES.get(c, c)}")
            elif tag == "ERR":
                self.log("ERROR", "ESP32 reported: " + ",".join(parts[1:]))
            elif tag == "PONG":
                pass
            else:
                self.log("WARN", f"Unrecognised message: {line[:60]}")
        except ValueError:
            self.log("WARN", f"Malformed message ignored: {line[:60]}")

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        """Thread-safe copy of everything the UI needs."""
        with self._lock:
            now = time.monotonic()
            to = config.DATA_TIMEOUT_S
            connected = self._ser is not None
            alive = connected and self.last_rx is not None and now - self.last_rx <= to
            th = self.thermal if (self.thermal and now - self.thermal[2] <= to) else None
            simulated = config.SIMULATE_THERMAL and self.thermal_enabled
            if simulated:
                o, a = self.thermal_sim.read()
                th = (o, a, now)
                if now - self._last_sensor_log >= config.SENSOR_LOG_EVERY_S:
                    self._last_sensor_log = now
                    self.events.append((datetime.now().strftime("%H:%M:%S"), "SENSOR",
                                        f"[SIMULATED] MLX90614 object {o:.1f} C, ambient {a:.1f} C"))
            di = self.distance if (self.distance and now - self.distance[1] <= to) else None
            return {
                "connected": connected,
                "alive": alive,
                "port": self.port,
                "baud": self.baud,
                "firmware": self.firmware,
                "last_rx_wall": self.last_rx_wall,
                "mlx_ok": self.mlx_ok,
                "us_ok": self.us_ok,
                "thermal": (th[0], th[1]) if th else None,
                "distance": di[0] if di else None,
                "last_cmd": self.last_cmd,
                "last_ack": self.last_ack,
                "cmd_pending": self.cmd_pending,
                "thermal_enabled": self.thermal_enabled,
                "thermal_simulated": simulated,
                "ultra_enabled": self.ultra_enabled,
                "events": list(self.events)[-120:][::-1],
            }
