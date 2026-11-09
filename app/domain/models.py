"""Internal domain models.

The wire contract lives in ``planta_contrato``; these models add the information the
plant contract cannot carry (photos per row, note timestamps, attempt tracking).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Equipment(StrictModel):
    tag: str
    kind: str = ""
    description: str = ""
    manufacturer: str | None = None
    model: str | None = None
    names: list[str] = Field(default_factory=list)
    gauge_unit: str | None = None


class SensorLimit(StrictModel):
    tag: str
    variable: str
    unit: str = ""
    high: float | None = None
    low: float | None = None
    trip: float | None = None


class PlantSnapshot(StrictModel):
    equipment: dict[str, Equipment] = Field(default_factory=dict)
    limits: dict[str, SensorLimit] = Field(default_factory=dict)
    local_readings: dict[str, list[str]] = Field(default_factory=dict)

    def limit(self, tag: str, variable: str) -> SensorLimit | None:
        return self.limits.get(f"{tag}|{variable}")

    def gauge_unit(self, tag: str) -> str | None:
        equipment = self.equipment.get(tag)
        return equipment.gauge_unit if equipment else None

    def pumps(self) -> list[str]:
        return [tag for tag, equipment in self.equipment.items() if equipment.kind == "bomba"]

    def filters(self) -> list[str]:
        return [tag for tag, equipment in self.equipment.items() if equipment.kind == "filtro"]


class ExtractedRow(StrictModel):
    tag: str
    variable: str
    value: float | None = None
    unit: str | None = None
    observation: str | None = None
    photo: str | None = None
    flags: list[str] = Field(default_factory=list)

    @property
    def has_value(self) -> bool:
        return self.value is not None

    def to_contract(self) -> dict:
        return {
            "tag": self.tag,
            "variable": self.variable,
            "valor": self.value,
            "unidad": self.unit,
            "observacion": self.observation,
        }


class Ambiguity(StrictModel):
    kind: Literal["equipment", "value"]
    tag: str | None = None
    candidates: list[str] = Field(default_factory=list)
    raw_value: float | None = None
    repaired_value: float | None = None
    clause: str = ""


class PartDraft(StrictModel):
    note_id: str
    ts: datetime
    transcript: str = ""
    rows: list[ExtractedRow] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    safety: str | None = None
    photos: list[str] = Field(default_factory=list)

    def valued_rows(self) -> list[ExtractedRow]:
        return [row for row in self.rows if row.has_value]

    def rows_for(self, tag: str) -> list[ExtractedRow]:
        return [row for row in self.rows if row.tag == tag]


class NoteContext(StrictModel):
    note_id: str
    ts: datetime
    operator: str = ""
    audio_url: str | None = None
    photos: list[str] = Field(default_factory=list)
    walk_id: str = ""
    live: bool = False


class ReplyContext(StrictModel):
    message_id: str
    note_id: str
    kind: Literal["question_equipment", "question_value", "draft", "notice"]
    draft: PartDraft | None = None
    target_tag: str | None = None
