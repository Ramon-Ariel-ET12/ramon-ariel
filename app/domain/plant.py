"""Build a PlantSnapshot from the plant API payload or from the bundled definition."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.domain.models import Equipment, PlantSnapshot, SensorLimit


def snapshot_from_definition(data: dict) -> PlantSnapshot:
    equipment: dict[str, Equipment] = {}
    for item in data.get("equipos", []):
        gauge = (item.get("manometro_local") or {}).get("unidad")
        equipment[item["tag"]] = Equipment(
            tag=item["tag"],
            kind=item.get("tipo", ""),
            description=item.get("descripcion", ""),
            manufacturer=item.get("fabricante"),
            model=item.get("modelo"),
            names=list(item.get("nombres") or []),
            gauge_unit=gauge,
        )
    limits: dict[str, SensorLimit] = {}
    for item in data.get("sensores", []):
        limit = SensorLimit(
            tag=item["tag"],
            variable=item["variable"],
            unit=item.get("unidad", ""),
            high=item.get("alarma_alta"),
            low=item.get("alarma_baja"),
            trip=item.get("disparo"),
        )
        limits[f"{limit.tag}|{limit.variable}"] = limit
    return PlantSnapshot(equipment=equipment, limits=limits,
                         local_readings={k: list(v) for k, v in (data.get("lecturas_locales") or {}).items()})


def load_snapshot_file(path: Path | str) -> PlantSnapshot:
    return snapshot_from_definition(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
