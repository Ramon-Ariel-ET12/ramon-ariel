"""Historical range validation against the plant historian."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from app.domain.models import ExtractedRow, PlantSnapshot
from app.domain.units import to_kg
from app.integrations.plant_api import PlantClient

log = logging.getLogger(__name__)

SENSOR_MAP = {
    "presion_descarga_local": "presion_descarga",
    "presion_diferencial": "presion_diferencial",
    "temperatura_rodamiento_ir": "temperatura_aceite",
}
CACHE_SECONDS = 600.0
MARGIN = 0.05
MIN_HISTORY_SAMPLES = 1440   # one day at one sample per minute


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("empty")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def range_from_values(values: list[float]) -> tuple[float, float] | None:
    clean = [value for value in values if value is not None]
    if len(clean) < 20:
        return None
    # Observed operating range. A normal field reading is inside it; only a gross
    # outlier asks for confirmation.
    return min(clean), max(clean)


def outside_range(value: float, unit: str | None, bounds: tuple[float, float]) -> bool:
    low, high = bounds
    span = max(high - low, abs(high) * 0.02, 0.1)
    measured = to_kg(value, unit) if unit in ("psi", "bar", "kg/cm2") else value
    return measured < low - span * MARGIN or measured > high + span * MARGIN


class HistoricalValidator:
    def __init__(self, plant: PlantClient, snapshot: PlantSnapshot):
        self.plant = plant
        self.snapshot = snapshot
        self._cache: dict[tuple[str, str], tuple[float, tuple[float, float] | None]] = {}

    async def _bounds(self, tag: str, variable: str, reference: datetime):
        key = (tag, variable)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            samples = await self.plant.historian(tag, variable,
                                                 desde=(reference - timedelta(days=45)).isoformat(),
                                                 hasta=reference.isoformat())
        except Exception as exc:  # noqa: BLE001
            log.warning("historian unavailable for %s/%s: %s", tag, variable, exc)
            self._cache[key] = (now, None)
            return None
        values = [item.get("valor") for item in samples]
        # A range needs real history. In a scenario that starts from scratch, asking
        # "outside the historical range" from a handful of minutes would be noise.
        bounds = range_from_values(values) if len([v for v in values if v is not None]) >= MIN_HISTORY_SAMPLES else None
        self._cache[key] = (now, bounds)
        return bounds

    async def check(self, rows: list[ExtractedRow], reference: datetime) -> list[ExtractedRow]:
        flagged: list[ExtractedRow] = []
        for row in rows:
            if row.value is None:
                continue
            sensor = SENSOR_MAP.get(row.variable)
            if sensor is None:
                continue
            limit = self.snapshot.limit(row.tag, sensor)
            if limit is None:
                continue
            measured = to_kg(row.value, row.unit) if row.unit in ("psi", "bar", "kg/cm2") else row.value
            # A value inside the datasheet band is a normal operating reading even if it
            # is new in the observed history. Only an out-of-band value that is also new
            # asks the operator to confirm.
            in_band = ((limit.high is None or measured <= limit.high)
                       and (limit.low is None or measured >= limit.low))
            if in_band:
                continue
            bounds = await self._bounds(row.tag, sensor, reference)
            if bounds and outside_range(row.value, row.unit, bounds):
                flagged.append(row)
        return flagged
