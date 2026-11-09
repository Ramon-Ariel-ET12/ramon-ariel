"""Understanding what the operator says back on the tablet.

The simulator speaks like a field operator: confirmations are short, corrections name
the equipment and the right value ("No, la uno estaba en ciento quince kilos").  A
deterministic reader covers that vocabulary; the optional local model is only consulted
when the rules find nothing actionable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.equipment import EquipmentIndex, preprocess
from app.domain.models import ExtractedRow, PartDraft, PlantSnapshot
from app.domain.numbers import normalize_text, parse_numbers, tokenize
from app.domain.units import detect_unit

CONFIRMATIONS = ("confirmo", "correcto", "perfecto", "esta bien", "asi es", "de acuerdo", "dale")
QUESTION_WORDS = ("que bomba", "que filtro", "cual", "cual de")


@dataclass
class ReplyReading:
    kind: str  # confirmation | correction | answer | unknown
    tag: str | None = None
    value: float | None = None
    unit: str | None = None
    text: str = ""
    actions: list[dict] = field(default_factory=list)


def is_confirmation(text: str) -> bool:
    normal = normalize_text(text)
    if normal.startswith("no") or "ninguna" in normal:
        return False
    return any(word in normal for word in CONFIRMATIONS)


def is_correction(text: str) -> bool:
    normal = normalize_text(text)
    return normal.startswith("no") or "falto" in normal or "no lo dije" in normal


def _sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|,\s*(?=no\s+en)", text) if part.strip()]
    return [part for part in parts if not normalize_text(part).startswith(("no en", "no de"))]


def read_reply(text: str, snapshot: PlantSnapshot, kind: str) -> ReplyReading:
    index = EquipmentIndex(snapshot)
    reading = ReplyReading(kind="unknown", text=text)
    normal = normalize_text(text)

    if kind == "draft":
        if is_correction(text):
            reading.kind = "correction"
            reading.actions = _correction_actions(text, index)
            return reading
        if is_confirmation(text):
            reading.kind = "confirmation"
            return reading
        if "no te entendi" in normal or "repet" in normal:
            reading.kind = "unknown"
            return reading
        reading.kind = "correction" if any(c in normal for c in ("falto", "estaba en", " no en ")) else "unknown"
        if reading.kind == "correction":
            reading.actions = _correction_actions(text, index)
        return reading

    if kind in ("question_equipment", "question_value"):
        tokens = tokenize(preprocess(text))
        mentions = index.find_mentions(tokens)
        if mentions:
            reading.kind = "answer"
            reading.tag = mentions[0].tag
        numbers = parse_numbers(tokens)
        if numbers:
            reading.kind = "answer"
            reading.value = numbers[0].value
            reading.unit, _ = detect_unit(tokens)
        if reading.kind == "unknown" and "no te entendi" not in normal:
            reading.kind = "answer"
        return reading

    return reading


def _correction_actions(text: str, index: EquipmentIndex) -> list[dict]:
    actions: list[dict] = []
    for sentence in _sentences(text):
        tokens = tokenize(preprocess(sentence))
        mentions = index.find_mentions(tokens)
        masked = index.mask(tokens, mentions) if mentions else tokens
        numbers = parse_numbers(masked)
        unit, _ = detect_unit(tokens)
        normal = normalize_text(sentence)

        if "no lo dije" in normal and mentions:
            actions.append({"action": "remove", "tag": mentions[0].tag})
            continue
        if "falto" in normal and mentions:
            actions.append({
                "action": "add",
                "tag": mentions[0].tag,
                "value": numbers[0].value if numbers else None,
                "unit": unit,
            })
            continue
        if "era de" in normal and len(mentions) >= 2:
            actions.append({
                "action": "move",
                "from": mentions[-1].tag,
                "to": mentions[0].tag,
                "value": numbers[0].value if numbers else None,
            })
            continue
        if " es en " in normal and unit and mentions:
            actions.append({"action": "unit", "tag": mentions[0].tag, "unit": unit})
            continue
        if mentions and (numbers or "estaba en" in normal):
            actions.append({
                "action": "set",
                "tag": mentions[0].tag,
                "value": numbers[0].value if numbers else None,
                "wrong": numbers[1].value if len(numbers) > 1 else None,
                "unit": unit,
            })
            continue
        if numbers and len(mentions) == 0:
            actions.append({"action": "set_unknown", "value": numbers[0].value, "unit": unit})
    return actions


def _infer_variable(tag: str, unit: str | None, snapshot: PlantSnapshot) -> str:
    is_filter = tag.startswith("F-")
    if is_filter:
        return "presion_diferencial" if unit in (None, "kg/cm2", "psi", "bar") else "observacion"
    if unit == "gotas/min":
        return "goteo_empaquetadura"
    if unit == "degC":
        return "temperatura_rodamiento_ir"
    if unit in ("kg/cm2", "psi", "bar"):
        return "presion_descarga_local"
    return "observacion"


def apply_corrections(draft: PartDraft, actions: list[dict], snapshot: PlantSnapshot) -> PartDraft:
    rows = [row.model_copy(deep=True) for row in draft.rows]
    for action in actions:
        kind = action.get("action")
        tag = action.get("tag")
        if kind == "remove" and tag:
            rows = [row for row in rows if row.tag != tag]
        elif kind == "add" and tag:
            variable = _infer_variable(tag, action.get("unit"), snapshot)
            rows.append(ExtractedRow(tag=tag, variable=variable, value=action.get("value"),
                                     unit=action.get("unit") if action.get("value") is not None else None,
                                     observation="corregido por el operador"))
        elif kind == "move" and action.get("to"):
            target_tag = action["to"]
            value = action.get("value")
            for row in rows:
                if row.tag == action.get("from") and row.value is not None and value is not None and abs(row.value - value) <= max(0.6, abs(value) * 0.02):
                    row.tag = target_tag
                    break
            rows = _dedupe(rows)
        elif kind == "unit" and tag:
            for row in rows:
                if row.tag == tag and row.value is not None:
                    row.unit = action.get("unit")
        elif kind == "set" and tag:
            value = action.get("value")
            unit = action.get("unit")
            wrong = action.get("wrong")
            candidates = [row for row in rows if row.tag == tag and row.value is not None]
            if wrong is not None and candidates:
                candidates.sort(key=lambda row: abs(float(row.value or 0) - float(wrong)))
            if not candidates:
                variable = _infer_variable(tag, unit, snapshot)
                rows.append(ExtractedRow(tag=tag, variable=variable, value=value,
                                         unit=unit if value is not None else None,
                                         observation="corregido por el operador"))
            else:
                row = candidates[0]
                if value is not None:
                    row.value = value
                if unit is not None:
                    row.unit = unit
        elif kind == "set_unknown":
            for row in rows:
                if row.value is not None and action.get("value") is not None and abs(row.value - action["value"]) <= 1.0:
                    if action.get("unit"):
                        row.unit = action["unit"]
                    break
    draft.rows = _dedupe(rows)
    return draft


def _dedupe(rows: list[ExtractedRow]) -> list[ExtractedRow]:
    seen: dict[tuple[str, str], ExtractedRow] = {}
    for row in rows:
        seen[(row.tag, row.variable)] = row
    return list(seen.values())
