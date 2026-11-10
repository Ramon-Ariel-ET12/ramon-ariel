"""Deterministic event detection for confirmed parts and sensor deviations."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.domain.models import ExtractedRow, PartDraft, PlantSnapshot
from app.domain.units import to_kg

NAMESPACE = uuid.UUID("6f0d7f9e-6a8b-4b55-9c0e-2f4d8f0b3a11")

SIN_NOVEDAD = "SinNovedad"
ESCALADO = "Escalado"
ALERTA_SEGURIDAD = "AlertaSeguridad"

QUALITATIVE_ANOMALIES = {"goteo_empaquetadura", "estado_correas", "ruido", "nivel_aceite_visor"}
NORMAL_STATES = {"parada, en reserva", "parada por mantenimiento"}


def _normal(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def row_is_anomalous(row: ExtractedRow, snapshot: PlantSnapshot,
                     pump_states: dict[str, str] | None = None) -> bool:
    if row.variable in QUALITATIVE_ANOMALIES:
        return True
    if row.variable == "condicion_insegura":
        return True
    if row.variable == "estado":
        observation = _normal(row.observation)
        if observation in NORMAL_STATES:
            return False
        # A pump the operator reports as stopped is only an anomaly if the plant says it
        # is running. The reserve pump is normally stopped, and the ASR sometimes loses
        # the qualifier ("parada, en reserva" heard as "parada").
        if observation == "parada" and pump_states and _normal(pump_states.get(row.tag)) == "parada":
            return False
        return True
    if row.variable == "nivel":
        return "rebals" in _normal(row.observation)
    if row.variable == "temperatura_rodamiento_ir":
        return row.value is not None and row.value > 75
    if row.variable == "presion_diferencial" and row.value is not None:
        limit = snapshot.limit(row.tag, "presion_diferencial")
        measured = to_kg(row.value, row.unit)
        return _outside(measured, limit)
    if row.variable == "presion_descarga_local" and row.value is not None:
        limit = snapshot.limit(row.tag, "presion_descarga")
        measured = to_kg(row.value, row.unit)
        return _outside(measured, limit)
    return False


def _outside(value: float, limit) -> bool:
    if limit is None:
        return False
    if limit.high is not None and value >= limit.high:
        return True
    if limit.low is not None and value <= limit.low:
        return True
    return False


def tag_is_anomalous(rows: list[ExtractedRow], snapshot: PlantSnapshot,
                     pump_states: dict[str, str] | None = None) -> bool:
    return any(row_is_anomalous(row, snapshot, pump_states) for row in rows)


def event_id(note_id: str, tag: str | None, kind: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"part:{note_id}:{tag or 'PLANTA'}:{kind}"))


def note_events(draft: PartDraft, snapshot: PlantSnapshot, ts: datetime,
                pump_states: dict[str, str] | None = None) -> list[dict]:
    """Build one event per equipment in the part (or a plant level event when empty)."""
    if draft.safety:
        tag = draft.rows[0].tag if draft.rows else None
        return [{
            "id": event_id(draft.note_id, tag, ALERTA_SEGURIDAD),
            "ts": ts.isoformat(),
            "tipo": ALERTA_SEGURIDAD,
            "equipo": tag,
            "origen": "parte",
            "parte_id": draft.note_id,
            "nota_ids": [draft.note_id],
            "resumen": f"Condición insegura {draft.safety} informada por el operador.",
        }]

    if not draft.rows:
        return [{
            "id": event_id(draft.note_id, None, SIN_NOVEDAD),
            "ts": ts.isoformat(),
            "tipo": SIN_NOVEDAD,
            "equipo": None,
            "origen": "parte",
            "parte_id": draft.note_id,
            "nota_ids": [draft.note_id],
            "resumen": "Recorrida sin novedad: la nota no reporta lecturas ni observaciones.",
        }]

    by_tag: dict[str, list[ExtractedRow]] = {}
    for row in draft.rows:
        by_tag.setdefault(row.tag, []).append(row)

    events: list[dict] = []
    for tag, rows in by_tag.items():
        anomalous = tag_is_anomalous(rows, snapshot, pump_states)
        kind = ESCALADO if anomalous else SIN_NOVEDAD
        if anomalous:
            details = ", ".join(
                f"{row.variable}={row.value} {row.unit or ''}".strip() if row.value is not None
                else f"{row.variable}: {row.observation}"
                for row in rows
            )
            summary = f"Anomalía sostenida en {tag}: {details}."
        else:
            summary = f"{tag} dentro de los rangos de operación según el parte confirmado."
        events.append({
            "id": event_id(draft.note_id, tag, kind),
            "ts": ts.isoformat(),
            "tipo": kind,
            "equipo": tag,
            "origen": "parte",
            "parte_id": draft.note_id,
            "nota_ids": [draft.note_id],
            "resumen": summary,
        })
    return events
