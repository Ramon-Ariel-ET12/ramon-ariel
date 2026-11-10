"""Sustained sensor anomaly detection.

A single sample outside a limit is not an event: the plant is noisy.  The detector
aggregates by simulated minute and requires a sustained window, with hysteresis so a
condition is announced once.  The active episode (start and event id) is persisted in
``sensor_state`` so a restart in the middle of a deviation reuses the same id instead
of announcing the same anomaly twice.
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
        self.event_id: str | None = None

    def add(self, ts: datetime, value: float | None) -> str | None:
        """Add a sample.

        Returns ``"start"`` when a normal condition turns sustained, ``"end"`` when a
        sustained condition clears and ``None`` otherwise.  The caller persists the
        episode on both transitions.
        """
        if value is None:
            self.samples.clear()
            return None
        self.samples.append((ts, value))
        cutoff = ts - timedelta(minutes=self.minutes)
        recent = [sample for sample in self.samples if sample[0] >= cutoff]
        if len(recent) < MIN_SAMPLES:
            return None
        outside = [self._outside(value) for _, value in recent]
        sustained = sum(outside) >= max(MIN_SAMPLES, int(len(outside) * 0.8))
        if sustained and not self.active:
            self.active = True
            self.since = recent[0][0]
            return "start"
        if not sustained and self.active:
            self.active = False
            self.since = None
            self.event_id = None
            return "end"
        return None

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

    def restore(self, episodes: list[dict]) -> None:
        """Seed active episodes read from ``sensor_state`` (survives a restart)."""
        for row in episodes:
            window = self.windows.get((row.get("tag"), row.get("variable")))
            if window is None or not row.get("active") or not row.get("event_id"):
                continue
            window.active = True
            window.since = row.get("since")
            window.event_id = row["event_id"]

    def episode(self, tag: str, variable: str) -> dict | None:
        """Current persisted episode of a sensor, or None when it is quiet."""
        window = self.windows.get((tag, variable))
        if window is None:
            return None
        return {
            "tag": tag,
            "variable": variable,
            "active": window.active,
            "since": window.since,
            "event_id": window.event_id,
        }

    def feed(self, tag: str, variable: str, value: float | None, ts: datetime,
             quality: str) -> tuple[dict | None, dict | None]:
        """Feed one sample.

        Returns ``(event, episode)``.  ``event`` is present only on the transition to a
        sustained deviation; ``episode`` is present only when the stored episode must be
        created or cleared.
        """
        if quality != "buena" or value is None:
            return None, None
        window = self.windows.get((tag, variable))
        if window is None:
            return None, None
        # A pump at rest has discharge pressure near suction (~1.5 kg/cm2). That is not
        # a low-pressure anomaly; "parada, en reserva" must stay quiet.
        if variable == "presion_descarga" and value <= 5:
            window.samples.clear()
            window.active = False
            window.since = None
            window.event_id = None
            return None, None
        transition = window.add(ts, value)
        if transition == "end":
            return None, self.episode(tag, variable)
        if transition != "start":
            return None, None
        # An episode restored from the database keeps its id: the anomaly is the same one.
        if window.event_id is None:
            window.event_id = str(uuid.uuid5(NAMESPACE, f"sensor:{tag}:{variable}:{window.since.isoformat()}"))
        direction = "alta" if window.limit.high is not None and value is not None and value >= window.limit.high else "baja"
        event = {
            "id": window.event_id,
            "ts": ts.isoformat(),
            "tipo": ESCALADO,
            "equipo": tag,
            "origen": "sensor",
            "parte_id": None,
            "nota_ids": [],
            "resumen": f"Desvío sostenido de {variable} en {tag}: alarma {direction} durante "
                       f"{WINDOW_MINUTES} minutos.",
        }
        return event, self.episode(tag, variable)


