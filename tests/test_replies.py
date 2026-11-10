from __future__ import annotations

from app.domain.parser import parse_transcript
from app.processing.replies import apply_corrections, is_confirmation, is_correction, read_reply


def test_confirmation_variants():
    for text in ["Sí, confirmo.", "Está bien, confirmo.", "Correcto, dale.", "Sí, así es. Confirmo.",
                 "Perfecto, confirmo."]:
        assert is_confirmation(text), text


def test_correction_is_not_a_confirmation():
    text = "No. Te faltó la dos, que estaba en ciento veinte gotas por minuto. Corregilo y te confirmo."
    assert is_correction(text)
    assert not is_confirmation(text)


def test_corrected_value(snapshot):
    reading = read_reply("No. La uno estaba en ciento quince kilos, no en ciento doce. Arreglá eso.",
                         snapshot, "draft")
    assert reading.kind == "correction"
    action = reading.actions[0]
    assert (action["action"], action["tag"], action["value"], action["unit"]) == (
        "set", "B-101", 115.0, "kg/cm2")


def test_corrected_pressure_in_psi(snapshot):
    reading = read_reply("No. La dos estaba en mil seiscientos cuarenta libras, no en mil seiscientos veinte.",
                         snapshot, "draft")
    assert reading.actions[0]["value"] == 1640.0
    assert reading.actions[0]["unit"] == "psi"


def test_missing_hidden_value(snapshot, ts):
    draft = parse_transcript("La dos pierde bastante por la empaquetadura, le saqué foto.", snapshot,
                             note_id="N", ts=ts)
    reading = read_reply("No. Te faltó la dos, que estaba en ciento veinte gotas por minuto. Arreglá eso.",
                         snapshot, "draft")
    updated = apply_corrections(draft, reading.actions, snapshot)
    goteo = next(row for row in updated.rows if row.variable == "goteo_empaquetadura")
    assert (goteo.value, goteo.unit) == (120.0, "gotas/min")


def test_unit_correction(snapshot, ts):
    draft = parse_transcript("El filtro B me dio cero nueve de diferencial.", snapshot, note_id="N", ts=ts)
    draft.rows[0].unit = "bar"
    reading = read_reply("No. Lo del filtro B es en kilos, no en bar. Arreglá eso.", snapshot, "draft")
    updated = apply_corrections(draft, reading.actions, snapshot)
    assert updated.rows[0].unit == "kg/cm2"


def test_remove_row(snapshot, ts):
    draft = parse_transcript("El pulmón está en cinco metros.", snapshot, note_id="N", ts=ts)
    reading = read_reply("No. Lo del pulmón no lo dije. Arreglá eso.", snapshot, "draft")
    updated = apply_corrections(draft, reading.actions, snapshot)
    assert updated.rows == []


def test_equipment_answer(snapshot):
    reading = read_reply("Era la dos.", snapshot, "question_equipment")
    assert reading.kind == "answer"
    assert reading.tag == "B-102"


def test_value_question_answer_is_read(snapshot):
    reading = read_reply("El filtro B está en kilos.", snapshot, "question_value")
    assert reading.tag == "F-201B"


def test_correction_reaches_a_null_reading_instead_of_another_variable(snapshot, ts):
    """NOTA-00014: the ASR dropped the discharge value; the correction must fill it and
    leave the bearing temperature alone."""
    draft = parse_transcript("La del medio está en 1610P SI de descarga. El rodamiento me dio 51 grados con la pistola.",
                             snapshot, note_id="N", ts=ts)
    assert draft.rows[0].value is None
    reading = read_reply(
        "No. La dos estaba en mil seiscientos diez psi, no en cincuenta y uno. "
        "Te faltó la dos, que estaba en cincuenta y uno grados. Arreglá eso.", snapshot, "draft")
    updated = apply_corrections(draft, reading.actions, snapshot)
    by_variable = {row.variable: row for row in updated.rows}
    assert (by_variable["presion_descarga_local"].value, by_variable["presion_descarga_local"].unit) == (
        1610.0, "psi")
    assert (by_variable["temperatura_rodamiento_ir"].value,
            by_variable["temperatura_rodamiento_ir"].unit) == (51.0, "degC")


def test_correction_fixes_a_wrong_discharge_reading(snapshot, ts):
    """NOTA-00083: the operator corrects 580 psi to 1580 psi and adds the bearing."""
    draft = parse_transcript("La dos está en 580 psi de descarga.", snapshot, note_id="N", ts=ts)
    reading = read_reply(
        "No. La dos estaba en mil quinientos ochenta psi, no en quinientos ochenta. "
        "Te faltó la dos, que estaba en cincuenta y tres grados. Corregilo y te confirmo.",
        snapshot, "draft")
    updated = apply_corrections(draft, reading.actions, snapshot)
    by_variable = {row.variable: row for row in updated.rows}
    assert (by_variable["presion_descarga_local"].value, by_variable["presion_descarga_local"].unit) == (
        1580.0, "psi")
    assert by_variable["temperatura_rodamiento_ir"].value == 53.0


def test_add_does_not_duplicate_a_variable_that_is_already_there(snapshot, ts):
    draft = parse_transcript("La uno está en 112 kilos de descarga. El rodamiento me dio 51 grados con la pistola.",
                             snapshot, note_id="N", ts=ts)
    reading = read_reply("Te faltó la uno, que estaba en cincuenta y uno grados.", snapshot, "draft")
    updated = apply_corrections(draft, reading.actions, snapshot)
    temps = [row for row in updated.rows if row.variable == "temperatura_rodamiento_ir"]
    assert len(temps) == 1 and temps[0].value == 51.0
