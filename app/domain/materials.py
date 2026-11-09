"""Maintenance data provided by the course: spare parts, bills of materials and tasks."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SparePart(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str
    name: str
    unit: str = ""
    cost_usd: float = 0.0
    stock: dict[str, float] = Field(default_factory=dict)


class Task(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str
    name: str
    equipment: list[str] = Field(default_factory=list)
    stops: bool = False
    hours: float = 0.0
    executor: str = "propio"
    parts: list[dict] = Field(default_factory=list)
    standard: bool = True


class Materials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: dict[str, SparePart] = Field(default_factory=dict)
    bom: dict[str, list[str]] = Field(default_factory=dict)
    standard: dict[str, dict[str, Task]] = Field(default_factory=dict)
    nonstandard: dict[str, Task] = Field(default_factory=dict)

    def task(self, code: str, equipment: str) -> Task | None:
        return self.standard.get(equipment, {}).get(code) or self.nonstandard.get(code)

    def is_standard(self, code: str, equipment: str) -> bool:
        return code in self.standard.get(equipment, {})

    def part_cost(self, code: str, quantity: float) -> float:
        part = self.parts.get(code)
        return part.cost_usd * quantity if part else 0.0

    def in_stock(self, code: str, quantity: float, warehouse: str = "yacimiento") -> bool:
        part = self.parts.get(code)
        return bool(part) and part.stock.get(warehouse, 0) >= quantity


def load_materials(path: Path | str) -> Materials:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    parts = {
        item["codigo"]: SparePart(
            code=item["codigo"],
            name=item["nombre"],
            unit=item.get("unidad", ""),
            cost_usd=float(item.get("costo_usd", 0)),
            stock={k: float(v) for k, v in (item.get("stock") or {}).items()},
        )
        for item in data.get("repuestos", [])
    }
    standard: dict[str, dict[str, Task]] = {}
    for item in data.get("tareas_estandar", []):
        task = Task(
            code=item["codigo"],
            name=item["nombre"],
            equipment=list(item.get("equipos", [])),
            stops=bool(item.get("detiene", False)),
            hours=float(item.get("horas", 0)),
            executor=item.get("ejecutor", "propio"),
            parts=list(item.get("repuestos", [])),
            standard=True,
        )
        for equipment in task.equipment:
            standard.setdefault(equipment, {})[task.code] = task
    nonstandard: dict[str, Task] = {}
    for item in data.get("tareas_no_estandar", []):
        nonstandard[item["codigo"]] = Task(
            code=item["codigo"],
            name=item["nombre"],
            stops=bool(item.get("detiene", False)),
            hours=float(item.get("horas", 0)),
            executor=item.get("ejecutor", "propio"),
            parts=list(item.get("repuestos", [])),
            standard=False,
        )
    return Materials(parts=parts, bom={k: list(v) for k, v in (data.get("lista_materiales") or {}).items()},
                     standard=standard, nonstandard=nonstandard)


def standard_codes_for(materials: Materials, equipment: str) -> set[str]:
    return set(materials.standard.get(equipment, {}))
