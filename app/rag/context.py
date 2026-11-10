"""Evidence context for an escalated event.

The full maintenance analysis belongs to the second deliverable; this builder is the
contract for it: source rows, photos, sensor trend, cited manual sections, historical
orders and available parts, with no LLM in the loop.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.materials import Materials
from app.domain.models import ExtractedRow, PlantSnapshot
from app.integrations.plant_api import PlantClient
from app.rag.search import ManualSearch


def _query_for(equipment: str, rows: list[ExtractedRow], snapshot: PlantSnapshot) -> str:
    description = snapshot.equipment.get(equipment)
    parts = [description.description if description else equipment]
    for row in rows:
        parts.append(row.variable.replace("_", " "))
        if row.observation:
            parts.append(row.observation)
    parts.append("falla causa probable accion recomendada")
    return " ".join(parts)


async def sensor_trend(plant: PlantClient, snapshot: PlantSnapshot, equipment: str | None,
                       hours: int = 6) -> dict:
    """Recent trend per sensor of one equipment (last hours), for the escalated event."""
    if not equipment:
        return {}
    try:
        state = await plant.state()
        now = datetime.fromisoformat(state["ts"])
    except Exception:  # noqa: BLE001
        now = datetime.now().astimezone()
    trend: dict[str, dict] = {}
    for key in snapshot.limits:
        tag, variable = key.split("|", 1)
        if tag != equipment:
            continue
        try:
            samples = await plant.historian(tag, variable, desde=(now - timedelta(hours=hours)).isoformat(),
                                            hasta=now.isoformat())
        except Exception:  # noqa: BLE001
            continue
        values = [item["valor"] for item in samples if item.get("valor") is not None]
        if not values:
            continue
        limit = snapshot.limit(tag, variable)
        trend[variable] = {
            "n": len(values),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "last": round(values[-1], 2),
            "unit": limit.unit if limit else "",
        }
    return trend


async def build_event_context(event: dict, rows: list[ExtractedRow], photos: list[str],
                              plant: PlantClient, search: ManualSearch | None, snapshot: PlantSnapshot,
                              materials: Materials | None) -> dict:
    equipment = event.get("equipo")
    context: dict = {"event": event, "rows": [row.model_dump() for row in rows], "photos": photos}
    if not equipment:
        return context
    context["sensor_trend"] = await sensor_trend(plant, snapshot, equipment)
    if search is not None:
        try:
            context["sections"] = await search.search(_query_for(equipment, rows, snapshot), 6)
        except Exception:  # noqa: BLE001
            context["sections"] = []
    try:
        history = await plant.order_history(equipment)
        context["order_history"] = history[-5:]
    except Exception:  # noqa: BLE001
        context["order_history"] = []
    if materials is not None:
        context["available_parts"] = [
            {"codigo": code, "stock": materials.parts[code].stock.get("yacimiento", 0),
             "costo_usd": materials.parts[code].cost_usd}
            for code in materials.bom.get(equipment, []) if code in materials.parts
        ]
    return context
