from __future__ import annotations

import pytest

from app.domain.parser import parse_transcript
from tests.conftest import FUGA, MARTES


def rows(draft):
    return [(row.tag, row.variable, row.value, row.unit) for row in draft.rows]


@pytest.mark.parametrize("text,expected", [
    (MARTES[0], [("F-201A", "presion_diferencial", 1.4, "kg/cm2"),
                 ("B-102", "presion_descarga_local", 1620.0, "psi")]),
    (MARTES[1], [("B-101", "presion_descarga_local", 114.0, "kg/cm2"),
                 ("F-201B", "presion_diferencial", 1.0, "kg/cm2")]),
    (MARTES[2], [("B-101", "presion_descarga_local", 112.0, "kg/cm2"),
                 ("F-201B", "presion_diferencial", 0.9, "kg/cm2")]),
    (MARTES[3], [("B-103", "estado", None, None)]),
    (MARTES[4], [("B-102", "presion_descarga_local", 1610.0, "psi"),
                 ("F-201A", "presion_diferencial", 1.3, "kg/cm2")]),
    (MARTES[5], [("F-201B", "presion_diferencial", 0.9, "kg/cm2"),
                 ("TK-301", "nivel", 5.0, "m")]),
    (MARTES[6], [("B-101", "presion_descarga_local", 112.0, "kg/cm2"),
                 ("B-101", "temperatura_rodamiento_ir", 59.0, "degC"),
                 ("B-102", "presion_descarga_local", 1600.0, "psi"),
                 ("F-201A", "presion_diferencial", 1.3, "kg/cm2")]),
    (MARTES[7], [("B-102", "presion_descarga_local", 1590.0, "psi"),
                 ("F-201A", "presion_diferencial", 1.3, "kg/cm2"),
                 ("B-101", "presion_descarga_local", 112.0, "kg/cm2")]),
    (FUGA[3], [("B-101", "presion_descarga_local", 114.0, "kg/cm2"),
               ("B-101", "temperatura_rodamiento_ir", 64.0, "degC")]),
])
def test_expected_rows(text, expected, snapshot, ts):
    draft = parse_transcript(text, snapshot, note_id="N", ts=ts)
    assert rows(draft) == expected


def test_preserves_note_timestamp(snapshot, ts):
    draft = parse_transcript(MARTES[0], snapshot, note_id="N", ts=ts)
    assert draft.ts == ts


def test_goteo_and_photo(snapshot, ts):
    draft = parse_transcript("La dos pierde bastante por la empaquetadura, le saqué foto.", snapshot,
                             note_id="N", ts=ts, photos=["/media/fotos/empaquetadura/01.jpg"])
    row = draft.rows[0]
    assert (row.tag, row.variable, row.observation) == (
        "B-102", "goteo_empaquetadura", "pérdida importante por empaquetadura")
    assert row.photo == "/media/fotos/empaquetadura/01.jpg"


def test_state_normal_and_abnormal(snapshot, ts):
    normal = parse_transcript("La tres está parada, en reserva.", snapshot, note_id="N", ts=ts)
    assert normal.rows[0].observation == "parada, en reserva"
    abnormal = parse_transcript("La dos está disparada, no arranca.", snapshot, note_id="N", ts=ts)
    assert abnormal.rows[0].observation == "disparada, no arranca"


def test_qualitative_rows_have_no_value(snapshot, ts):
    draft = parse_transcript("La uno hace un golpeteo metálico", snapshot, note_id="N", ts=ts)
    assert draft.rows[0].variable == "ruido"
    assert draft.rows[0].value is None


def test_rebalse(snapshot, ts):
    draft = parse_transcript("El pulmón está en cinco metros, está rebalsando a la pileta.", snapshot,
                             note_id="N", ts=ts)
    assert draft.rows[0].observation == "rebalse a pileta"
    assert draft.rows[0].value == 5.0


def test_equipment_ambiguity(snapshot, ts):
    draft = parse_transcript("La bomba está en ciento doce de descarga.", snapshot, note_id="N", ts=ts)
    assert draft.rows == []
    assert draft.ambiguities and draft.ambiguities[0].kind == "equipment"
    assert set(draft.ambiguities[0].candidates) == {"B-101", "B-102", "B-103"}


def test_value_ambiguity_is_repaired_and_flagged(snapshot, ts):
    draft = parse_transcript("El filtro B me dio dieciocho de diferencial.", snapshot, note_id="N", ts=ts)
    assert draft.rows[0].value == 1.8
    assert draft.ambiguities and draft.ambiguities[0].kind == "value"


def test_empty_transcript_has_no_rows(snapshot, ts):
    draft = parse_transcript("", snapshot, note_id="N", ts=ts)
    assert draft.rows == []
    assert draft.transcript == ""


ASR_MARTES = [
    "El de la izquierda me dio 1.4 de diferencial. La 2 está en 1620 PSI de descarga.",
    "A ver, la de la punta está en 114 de descarga. El secundario me dio uno de diferencial.",
    "La de la punta está en 112 de descarga, el de la derecha me dio 09 de diferencial.",
    "La 3 está parada, en reserva.",
    "Listo. La del medio está en 1610 libras de descarga. El filtro A me dio 1,3 de diferencial.",
    "El filtro B medio 09 de diferencial. El pulmón está en 5 metros.",
    "La 1 está en 112 kilogramos de descarga, el rodamiento medió 59 grados con la pistola. "
    "También la 2 está en 1600 psi de descarga. El filtro A medió 1,3 de diferencial.",
    "Bueno, la 2 está en 1590 libras de descarga, el filtro A me dio 1,3 de diferencial, "
    "la de la punta está en 112 kilos de descarga.",
]

ASR_EXPECTED = [
    [("F-201A", "presion_diferencial", 1.4, "kg/cm2"), ("B-102", "presion_descarga_local", 1620.0, "psi")],
    [("B-101", "presion_descarga_local", 114.0, "kg/cm2"), ("F-201B", "presion_diferencial", 1.0, "kg/cm2")],
    [("B-101", "presion_descarga_local", 112.0, "kg/cm2"), ("F-201B", "presion_diferencial", 0.9, "kg/cm2")],
    [("B-103", "estado", None, None)],
    [("B-102", "presion_descarga_local", 1610.0, "psi"), ("F-201A", "presion_diferencial", 1.3, "kg/cm2")],
    [("F-201B", "presion_diferencial", 0.9, "kg/cm2"), ("TK-301", "nivel", 5.0, "m")],
    [("B-101", "presion_descarga_local", 112.0, "kg/cm2"),
     ("B-101", "temperatura_rodamiento_ir", 59.0, "degC"),
     ("B-102", "presion_descarga_local", 1600.0, "psi"), ("F-201A", "presion_diferencial", 1.3, "kg/cm2")],
    [("B-102", "presion_descarga_local", 1590.0, "psi"), ("F-201A", "presion_diferencial", 1.3, "kg/cm2"),
     ("B-101", "presion_descarga_local", 112.0, "kg/cm2")],
]


@pytest.mark.parametrize("text,expected", list(zip(ASR_MARTES, ASR_EXPECTED, strict=False)))
def test_parser_survives_asr_digit_and_verb_artifacts(text, expected, snapshot, ts):
    draft = parse_transcript(text, snapshot, note_id="N", ts=ts)
    assert rows(draft) == expected
