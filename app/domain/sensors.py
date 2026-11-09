"""Sustained sensor anomaly detection.

A single sample outside a limit is not an event: the plant is noisy.  The detector
aggregates by simulated minute and requires a sustained window, with hysteresis so a
condition is announced once.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timedelta

from app.domain.events import ESCALADO
from app.domain.models import PlantSnapshot, SensorLimit

NAMESPACE = uuid.UUID("a3c1e5f2-8b4d-4e6a-9f70-1c2d3e4f5a6b")
WINDOW_MINUTES = 5
MIN_SAMPLES = 3


class SensorWindow:
    def __init__(self, limit: SensorLimit, minutes: int = WINDOW_MINUTES):
        self.limit = limit
        self.samples: deque[tuple[datetime, float]] = deque(maxlen=120)
        self.minutes = minutes
        self.active = False
        self.since: datetime | None = None

    def add(self, ts: datetime, value: float | None) -> bool:
        """Add a sample; return True only on a transition from normal to sustained."""
        if value is None:
            self.samples.clear()
            return False
        self.samples.append((ts, value))
        cutoff = ts - timedelta(minutes=self.minutes)
        recent = [sample for sample in self.samples if sample[0] >= cutoff]
        if len(recent) < MIN_SAMPLES:
            return False
        outside = [self._outside(value) for _, value in recent]
        sustained = sum(outside) >= max(MIN_SAMPLES, int(len(outside) * 0.8))
        if sustained and not self.active:
            self.active = True
            self.since = recent[0][0]
            return True
        if not sustained and self.active:
            self.active = False
            self.since = None
        return False

    def _outside(self, value: float) -> bool:
        if self.limit.high is not None and value >= self.limit.high:
            return True
        if self.limit.low is not None and value <= self.limit.low:
            return True
        return False


class SensorDetector:
    def __init__(self, snapshot: PlantSnapshot):
        self.snapshot = snapshot
        self.windows: dict[tuple[str, str], SensorWindow] = {}
        for key, limit in snapshot.limits.items():
            tag, variable = key.split("|", 1)
            if variable in ("presion_descarga", "presion_succion", "temperatura_aceite", "vibracion",
                            "presion_diferencial"):
                self.windows[(tag, variable)] = SensorWindow(limit)

    def feed(self, tag: str, variable: str, value: float | None, ts: datetime, quality: str) -> dict | None:
        if quality != "buena" or value is None:
            return None
        window = self.windows.get((tag, variable))
        if window is None:
            return None
        # A pump at rest has discharge pressure near suction (~1.5 kg/cm2). That is not
        # a low-pressure anomaly; "parada, en reserva" must stay quiet.
        if variable == "presion_descarga" and value <= 5:
            window.samples.clear()
            window.active = False
            window.since = None
            return None
        if not window.add(ts, value):
            return None
        direction = "alta" if window.limit.high is not None and value is not None and value >= window.limit.high else "baja"
        event_id = str(uuid.uuid5(NAMESPACE, f"sensor:{tag}:{variable}:{window.since.isoformat()}"))
        return {
            "id": event_id,
            "ts": ts.isoformat(),
            "tipo": ESCALADO,
            "equipo": tag,
            "origen": "sensor",
            "parte_id": None,
            "nota_ids": [],
            "resumen": f"Desvío sostenido de {variable} en {tag}: alarma {direction} durante "
                       f"{WINDOW_MINUTES} minutos.",
        }


