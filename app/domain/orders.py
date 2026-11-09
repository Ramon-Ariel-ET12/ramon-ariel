"""Order proposals derived from escalated events."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.domain.materials import Materials
from app.domain.models import ExtractedRow
from app.domain.rules import Decision, PlantState, Proposal, build_proposal, evaluate

NAMESPACE = uuid.UUID("f7b2c0d4-1e6a-4b8c-9d3f-5a7e2b1c9d40")

FILTER_CARTRIDGE_TASK = "T-F-CAR"
INSPECTION_TASK = "I-VIB"
VALVE_TASK = "I-VAL"


def propose_tasks(equipment: str, rows: list[ExtractedRow], sensor_variable: str | None = None) -> list[str]:
    """Deterministic evidence -> task mapping. Never lets text choose the task."""
    variables = {row.variable: row for row in rows}
    if equipment.startswith("F-") or sensor_variable == "presion_diferencial":
        return [FILTER_CARTRIDGE_TASK]
    if "goteo_empaquetadura" in variables:
        return ["T-B-EMP"]
    if "nivel_aceite_visor" in variables:
        return ["T-B-ACE"]
    if "estado_correas" in variables:
        return ["T-B-COR"]
    state = variables.get("estado")
    if state and "dispar" in (state.observation or ""):
        return [VALVE_TASK]
    if sensor_variable == "presion_succion":
        return [INSPECTION_TASK]
    if variables or sensor_variable:
        return [INSPECTION_TASK]
    return []


def order_id(equipment: str, tasks: list[str], first_event_id: str) -> str:
    key = f"order:{equipment}:{','.join(sorted(tasks))}:{first_event_id}"
    return str(uuid.uuid5(NAMESPACE, key))


def make_proposal(equipment: str, tasks: list[str], materials: Materials, state: PlantState,
                  *, structural_damage: bool = False, forced_pending: bool = False) -> tuple[Proposal, Decision]:
    proposal = build_proposal(equipment, tasks, materials, state, structural_damage=structural_damage)
    return proposal, evaluate(proposal, materials, state, forced_pending=forced_pending or structural_damage)


def order_payload(order_id_value: str, ts: datetime, state_name: str, proposal: Proposal,
                  decision: Decision, event_ids: list[str], *, tasks: list[str] | None = None) -> dict:
    return {
        "id": order_id_value,
        "ts": ts.isoformat(),
        "estado": state_name,
        "equipo": proposal.equipment,
        "evento_ids": event_ids,
        "tareas": tasks or proposal.tasks or ["NO-ESTANDAR"],
        "detiene_equipo": proposal.stops_equipment,
        "reduce_inyeccion": proposal.reduces_injection,
        "ejecutor": proposal.executor,
        "repuestos": proposal.parts,
        "motivo": decision.motive if state_name == "PendienteAprobacion" else None,
        "habilita": None,
        "monto_habilita_usd": None,
    }
