from __future__ import annotations

from app.domain.orders import order_id, order_payload, propose_tasks
from app.domain.parser import parse_transcript
from app.domain.rules import Decision, PlantState, build_proposal, evaluate


def state(**pumps):
    base = {"B-101": "marcha", "B-102": "marcha", "B-103": "parada"}
    base.update(pumps)
    return PlantState(pumps=base)


def test_filter_cartridges_approved_when_stock_and_cost_fit(materials, snapshot):
    proposal = build_proposal("F-201A", ["T-F-CAR"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert decision.approved, decision.reasons
    assert proposal.executor == "propio"
    assert proposal.parts == [{"codigo": "FC-CART-25", "cantidad": 48.0}]


def test_filter_b_without_stock_goes_pending(materials):
    proposal = build_proposal("F-201B", ["T-F-CAR"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert not decision.approved
    assert any("sin stock de FC-CART-10" in reason for reason in decision.reasons)
    assert decision.motive


def test_standard_pump_task_approved_when_reserve_available(materials):
    proposal = build_proposal("B-101", ["T-B-EMP"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert decision.approved, decision.reasons


def test_pump_stop_without_reserve_reduces_injection(materials):
    plant = state(**{"B-103": "mantenimiento"})
    proposal = build_proposal("B-101", ["T-B-EMP"], materials, plant)
    decision = evaluate(proposal, materials, plant)
    assert not decision.approved
    assert any("reduce la inyección" in reason for reason in decision.reasons)


def test_oil_top_up_is_approved(materials):
    proposal = build_proposal("B-101", ["T-B-ACE"], materials, state())
    assert evaluate(proposal, materials, state()).approved


def test_inspection_task_is_not_standard(materials):
    proposal = build_proposal("B-101", ["I-VIB"], materials, state())
    decision = evaluate(proposal, materials, state())
    assert not decision.approved
    assert any("no estándar" in reason for reason in decision.reasons)
    assert any("contratista" in reason for reason in decision.reasons)
    assert proposal.executor != "propio"


def test_cost_limit(materials):
    proposal = build_proposal("B-101", ["T-B-VAL"], materials, state())
    proposal.parts = [{"codigo": "TX-VAL-KIT", "cantidad": 2}]
    decision = evaluate(proposal, materials, state())
    assert any("costo de repuestos" in reason for reason in decision.reasons)


def test_structural_damage_forces_human_review(materials):
    proposal = build_proposal("B-101", ["T-B-EMP"], materials, state(), structural_damage=True)
    decision = evaluate(proposal, materials, state())
    assert not decision.approved
    assert any("daño estructural" in reason for reason in decision.reasons)


def test_task_proposal_from_rows(snapshot, ts):
    rows = parse_transcript("La dos pierde bastante por la empaquetadura.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-102", rows) == ["T-B-EMP"]
    differential = parse_transcript("El filtro A me dio uno coma tres de diferencial.", snapshot,
                                    note_id="N", ts=ts).rows
    assert propose_tasks("F-201A", differential) == ["T-F-CAR"]
    oil = parse_transcript("La uno tiene el visor de aceite bajo.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-101", oil) == ["T-B-ACE"]
    noise = parse_transcript("La uno hace un golpeteo metálico.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-101", noise) == ["I-VIB"]
    tripped = parse_transcript("La dos está disparada, no arranca.", snapshot, note_id="N", ts=ts).rows
    assert propose_tasks("B-102", tripped) == ["I-VAL"]


def test_order_id_is_deterministic(materials):
    assert order_id("F-201A", ["T-F-CAR"], "evt-1") == order_id("F-201A", ["T-F-CAR"], "evt-1")
    assert order_id("F-201A", ["T-F-CAR"], "evt-1") != order_id("F-201A", ["T-F-CAR"], "evt-2")


def test_order_payload_shape(materials, ts):
    proposal = build_proposal("F-201A", ["T-F-CAR"], materials, state())
    decision = Decision(approved=True)
    payload = order_payload("oid", ts, "Aprobada", proposal, decision, ["e1"])
    assert payload["estado"] == "Aprobada"
    assert payload["equipo"] == "F-201A"
    assert payload["detiene_equipo"] is False
    assert payload["reduce_inyeccion"] is False
    assert payload["motivo"] is None
    pending = order_payload("oid", ts, "PendienteAprobacion", proposal,
                            Decision(approved=False, reasons=["falta stock"]), ["e1"])
    assert pending["motivo"] == "falta stock"
