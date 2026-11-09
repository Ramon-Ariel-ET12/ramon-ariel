"""Approval rules, in code.

These five rules are the only way an order can be approved without a planner.  They
mirror the rubric exactly and are evaluated against the plant state at decision time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.materials import Materials

MAX_PART_COST_USD = 2500.0
WAREHOUSE = "yacimiento"


class PlantState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pumps: dict[str, str] = Field(default_factory=dict)
    link_up: bool = True
    power: bool = True


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equipment: str
    tasks: list[str] = Field(default_factory=list)
    parts: list[dict] = Field(default_factory=list)
    executor: str = "propio"
    stops_equipment: bool = False
    reduces_injection: bool = False
    structural_damage: bool = False
    reasons: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    reasons: list[str] = Field(default_factory=list)

    @property
    def state(self) -> str:
        return "Aprobada" if self.approved else "PendienteAprobacion"

    @property
    def motive(self) -> str | None:
        return None if self.approved else "; ".join(self.reasons)


def build_proposal(equipment: str, task_codes: list[str], materials: Materials,
                   state: PlantState, *, structural_damage: bool = False) -> Proposal:
    parts: dict[str, float] = {}
    executor = "propio"
    stops = False
    for code in task_codes:
        task = materials.task(code, equipment)
        if task is None:
            continue
        stops = stops or task.stops
        if task.executor != "propio":
            executor = task.executor
        for part in task.parts:
            parts[part["codigo"]] = parts.get(part["codigo"], 0.0) + float(part.get("cantidad", 0))
    reduces = stops and equipment.startswith("B-") and state.pumps.get(equipment) == "marcha" and not any(
        other != equipment and status == "parada" for other, status in state.pumps.items()
    )
    return Proposal(
        equipment=equipment,
        tasks=list(task_codes),
        parts=[{"codigo": code, "cantidad": quantity} for code, quantity in parts.items()],
        executor=executor,
        stops_equipment=stops,
        reduces_injection=reduces,
        structural_damage=structural_damage,
    )


def evaluate(proposal: Proposal, materials: Materials, state: PlantState, *,
             forced_pending: bool = False) -> Decision:
    reasons: list[str] = []
    if not proposal.tasks:
        reasons.append("no hay tarea estándar aplicable")
    else:
        for code in proposal.tasks:
            task = materials.task(code, proposal.equipment)
            if task is None:
                reasons.append(f"tarea desconocida: {code}")
                continue
            if not materials.is_standard(code, proposal.equipment):
                reasons.append(f"tarea no estándar para {proposal.equipment}: {code}")
            if task.executor != "propio":
                reasons.append(f"la tarea {code} la hace {task.executor}")

    stops = any((materials.task(code, proposal.equipment) or _EMPTY).stops for code in proposal.tasks)
    if stops and proposal.equipment.startswith("B-") and state.pumps.get(proposal.equipment) == "marcha":
        if not any(other != proposal.equipment and status == "parada" for other, status in state.pumps.items()):
            reasons.append("reduce la inyección: no hay bomba de reserva disponible")

    bom = set(materials.bom.get(proposal.equipment, []))
    for part in proposal.parts:
        code = part["codigo"]
        quantity = float(part["cantidad"])
        if code not in bom or code not in materials.parts:
            reasons.append(f"repuesto {code} fuera de la lista de materiales de {proposal.equipment}")
        elif not materials.in_stock(code, quantity, WAREHOUSE):
            reasons.append(f"sin stock de {code} en el almacén del yacimiento")

    total = sum(materials.part_cost(part["codigo"], float(part["cantidad"])) for part in proposal.parts)
    if total >= MAX_PART_COST_USD:
        reasons.append(f"costo de repuestos USD {total:.0f} mayor o igual al límite de USD {MAX_PART_COST_USD:.0f}")

    if proposal.executor != "propio":
        reasons.append(f"requiere contratista ({proposal.executor})")
    if proposal.structural_damage:
        reasons.append("las fotos muestran daño estructural: revisión humana obligatoria")
    if forced_pending:
        reasons.append("revisión humana obligatoria en este escenario")

    return Decision(approved=not reasons, reasons=reasons)


class _Empty:
    stops = False


_EMPTY = _Empty()
