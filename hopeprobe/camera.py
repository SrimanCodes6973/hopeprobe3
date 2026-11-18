"""ESP32-CAM monitor (kept completely separate from the serial link).

The video itself is shown by the browser (MJPEG <img>), so no OpenCV is
needed. This module only checks whether the camera's stream port accepts a
TCP connection, so the dashboard can show CONNECTED / DISCONNECTED.

The probe opens and immediately closes a TCP socket WITHOUT sending an HTTP
request, so it does not use up the camera's single stream slot.
"""
from __future__ import annotations

import socket
import threading
import time
from urllib.parse import urlparse

from . import config


class CameraMonitor:
    def __init__(self, log) -> None:
        self._log = log
        self._lock = threading.Lock()
        self.url = config.CAMERA_URL
        self.enabled = config.ENABLE_CAMERA
        self._status = "NOT CONFIGURED"
        self._fail_count = 0
        threading.Thread(target=self._loop, daemon=True, name="hp-camera").start()

    def configure(self, url: str, enabled: bool) -> None:
        with self._lock:
            if url.strip() != self.url or enabled != self.enabled:
                self._fail_count = 0

            self.url, self.enabled = url.strip(), enabled

    @property
    def status(self) -> str:
        with self._lock:
            if not self.enabled:
                return "DISABLED"
            return self._status

    @staticmethod
    def _probe(url: str) -> bool:
        p = urlparse(url)
        if not p.hostname:
            return False
        port = p.port or (443 if p.scheme == "https" else 80)

        try:
            with socket.create_connection((p.hostname, port), timeout=1.5):
                return True
        except OSError:
            return False

    def _loop(self) -> None:
        FAIL_THRESHOLD = 3

        while True:
            with self._lock:
                url, enabled = self.url, self.enabled

            if not enabled:
                new = "DISABLED"
                self._fail_count = 0

            elif not url:
                new = "NOT CONFIGURED"
                self._fail_count = 0

            else:
                success = self._probe(url)

                if success:
                    self._fail_count = 0
                    new = "CONNECTED"

                else:
                    self._fail_count += 1

                    if self._fail_count >= FAIL_THRESHOLD:
                        new = "DISCONNECTED"
                    else:
                        # Keep the previous status during temporary failures.
                        new = self._status

            with self._lock:
                old, self._status = self._status, new

            if new != old and new in ("CONNECTED", "DISCONNECTED") and old != "NOT CONFIGURED":
                self._log("INFO" if new == "CONNECTED" else "WARN", f"Camera {new.lower()}")
            elif new == "CONNECTED" and old == "NOT CONFIGURED":
                self._log("INFO", "Camera connected")

            time.sleep(4)
