"""MLX90614 thermal-sensor SIMULATOR (demo mode).

Pure Python, no hardware, no serial, no camera. All values are generated here.
The dashboard labels this as SIMULATED so nobody mistakes it for a live sensor.

Ambient drifts slowly; object temperature wobbles around a baseline with
small noise and an occasional gentle warm "event". Both are clamped to
[config.SIM_MIN_C, config.SIM_MAX_C].
"""
from __future__ import annotations

import math
import random
import threading
import time

from . import config


class ThermalSimulator:
    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._obj = 27.5
        self._event_until = 0.0
        self._event_boost = 0.0

    @staticmethod
    def _clamp(v: float) -> float:
        return max(config.SIM_MIN_C, min(config.SIM_MAX_C, v))

    def read(self) -> tuple[float, float]:
        """Return (object_C, ambient_C), both within the configured range."""
        with self._lock:
            now = time.monotonic()
            t = now - self._t0

            # ambient: slow drift around 27 C, +/-1.2 C, tiny noise
            amb = 27.0 + 1.2 * math.sin(t / 90.0) + self._rng.gauss(0, 0.05)

            # occasional warm event (a few seconds), like something warm in view
            if now > self._event_until and self._rng.random() < 0.01:
                self._event_until = now + self._rng.uniform(4, 9)
                self._event_boost = self._rng.uniform(2.0, 4.0)
            boost = self._event_boost if now < self._event_until else 0.0

            # object: smooth pull toward (ambient + 0.5 + boost) with noise
            target = amb + 0.5 + boost
            self._obj += (target - self._obj) * 0.25 + self._rng.gauss(0, 0.08)

            return round(self._clamp(self._obj), 1), round(self._clamp(amb), 1)
