from __future__ import annotations

from app.config import Settings
from app.domain.parser import parse_transcript
from app.processing.workflow import NoteWorkflow


def workflow(snapshot, materials):
    return NoteWorkflow(Settings(), repo=None, plant=None, publisher=None, snapshot=snapshot,  # type: ignore[arg-type]
                        materials=materials, transcriber=None)


def test_equipment_resolution_rebuilds_the_row(snapshot, materials, ts):
    draft = parse_transcript("La bomba está en ciento doce de descarga.", snapshot, note_id="N", ts=ts)
    ambiguity = draft.ambiguities[0]
    resolved = workflow(snapshot, materials)._apply_equipment_resolution(draft, ambiguity, "B-102")
    assert [(row.tag, row.variable, row.value, row.unit) for row in resolved.rows] == [
        ("B-102", "presion_descarga_local", 112.0, "psi")]


def test_equipment_label_uses_plant_alias(snapshot, materials):
    wf = workflow(snapshot, materials)
    assert wf._label("B-101") == "la uno"
    assert wf._label("F-201B") == "el filtro B"
