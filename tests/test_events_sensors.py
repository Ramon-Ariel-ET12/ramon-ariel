from __future__ import annotations

from datetime import timedelta

from app.domain.events import ALERTA_SEGURIDAD, ESCALADO, SIN_NOVEDAD, event_id, note_events
from app.domain.parser import parse_transcript
from app.domain.safety import detect_safety, emergency_text
from app.domain.sensors import SensorDetector
from tests.conftest import FUGA, MARTES


def draft_of(text, snapshot, ts):
    return parse_transcript(text, snapshot, note_id="N", ts=ts)


def test_normal_pressure_is_sin_novedad(snapshot, ts):
    draft = draft_of("La uno está en ciento doce de descarga.", snapshot, ts)
    events = note_events(draft, snapshot, ts)
    assert [event["tipo"] for event in events] == [SIN_NOVEDAD]
    assert events[0]["equipo"] == "B-101"


def test_goteo_escalates(snapshot, ts):
    draft = draft_of("La dos pierde bastante por la empaquetadura.", snapshot, ts)
    events = note_events(draft, snapshot, ts)
    assert events[0]["tipo"] == ESCALADO
    assert events[0]["equipo"] == "B-102"


def test_pressure_out_of_limit_escalates(snapshot, ts):
    draft = draft_of("La uno está en ciento treinta kilos de descarga.", snapshot, ts)
    assert note_events(draft, snapshot, ts)[0]["tipo"] == ESCALADO


def test_differential_limits(snapshot, ts):
    high = draft_of("El filtro B me dio uno con ocho de diferencial.", snapshot, ts)
    assert note_events(high, snapshot, ts)[0]["tipo"] == ESCALADO
    low = draft_of("El filtro B me dio cero uno de diferencial.", snapshot, ts)
    assert note_events(low, snapshot, ts)[0]["tipo"] == ESCALADO
    normal = draft_of("El filtro B me dio cero nueve de diferencial.", snapshot, ts)
    assert note_events(normal, snapshot, ts)[0]["tipo"] == SIN_NOVEDAD


def test_reserve_stop_is_not_an_anomaly(snapshot, ts):
    draft = draft_of("La tres está parada, en reserva.", snapshot, ts)
    assert note_events(draft, snapshot, ts)[0]["tipo"] == SIN_NOVEDAD
    maintenance = draft_of("La tres está parada por mantenimiento.", snapshot, ts)
    assert note_events(maintenance, snapshot, ts)[0]["tipo"] == SIN_NOVEDAD


def test_tripped_pump_escalates(snapshot, ts):
    draft = draft_of("La dos está disparada, no arranca.", snapshot, ts)
    assert note_events(draft, snapshot, ts)[0]["tipo"] == ESCALADO


def test_one_event_per_equipment(snapshot, ts):
    draft = draft_of(MARTES[6], snapshot, ts)
    events = note_events(draft, snapshot, ts)
    assert {event["equipo"] for event in events} == {"B-101", "B-102", "F-201A"}
    assert all(event["tipo"] == SIN_NOVEDAD for event in events)


def test_event_ids_are_stable_and_unique(snapshot, ts):
    draft = draft_of(MARTES[6], snapshot, ts)
    first = note_events(draft, snapshot, ts)
    second = note_events(draft, snapshot, ts)
    assert [event["id"] for event in first] == [event["id"] for event in second]
    assert len({event["id"] for event in first}) == len(first)
    assert event_id("N", "B-101", ESCALADO) == event_id("N", "B-101", ESCALADO)


def test_safety_note_builds_an_alert(snapshot, ts):
    draft = draft_of(FUGA[0], snapshot, ts)
    assert draft.safety == "S1"
    events = note_events(draft, snapshot, ts)
    assert len(events) == 1
    assert events[0]["tipo"] == ALERTA_SEGURIDAD
    assert "N" in events[0]["nota_ids"]


def test_safety_detector_negations():
    assert detect_safety("pierde por la empaquetadura") == (None, None)
    assert detect_safety("sin pérdida, todo normal") == (None, None)
    assert detect_safety("no hay olor a gas") == (None, None)
    assert detect_safety("sale agua a presión para todos lados")[0] == "S1"
    assert detect_safety("hay olor a gas")[0] == "S2"
    assert detect_safety("sale humo del motor")[0] == "S3"
    assert detect_safety("mi compañero se golpeó y está sangrando")[0] == "S4"


def test_emergency_text_mentions_radio_and_supervisor():
    text = emergency_text("S1", "B-101")
    assert "radio" in text and "supervisor" in text and "emergencia" in text


def test_sensor_spike_does_not_escalate(snapshot):
    detector = SensorDetector(snapshot)
    base = detector.windows[("B-101", "presion_descarga")].limit.high
    assert base == 125
    t0 = __import__("datetime").datetime(2026, 11, 3, 8, 0)
    assert detector.feed("B-101", "presion_descarga", 112, t0, "buena") is None
    assert detector.feed("B-101", "presion_descarga", 130, t0 + timedelta(minutes=1), "buena") is None
    assert detector.feed("B-101", "presion_descarga", 112, t0 + timedelta(minutes=2), "buena") is None


def test_sustained_sensor_deviation_escalates_once(snapshot):
    detector = SensorDetector(snapshot)
    from datetime import datetime

    t0 = datetime(2026, 11, 3, 8, 0)
    events = []
    for minute in range(6):
        event = detector.feed("B-101", "presion_descarga", 130, t0 + timedelta(minutes=minute), "buena")
        if event:
            events.append(event)
    assert len(events) == 1
    assert events[0]["tipo"] == ESCALADO
    assert events[0]["origen"] == "sensor"


def test_sensor_without_quality_is_ignored(snapshot):
    detector = SensorDetector(snapshot)
    from datetime import datetime

    t0 = datetime(2026, 11, 3, 8, 0)
    assert detector.feed("B-101", "presion_descarga", None, t0, "sin_dato") is None
    assert detector.feed("B-101", "presion_descarga", 130, t0, "sin_dato") is None
