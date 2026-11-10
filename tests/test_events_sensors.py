from __future__ import annotations

from datetime import timedelta

import pytest

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
    assert detect_safety("sin humo ni fuego") == (None, None)
    assert detect_safety("huele a gasoil") == (None, None)
    assert detect_safety("sale agua a presión para todos lados")[0] == "S1"
    assert detect_safety("hay olor a gas")[0] == "S2"
    assert detect_safety("sale humo del motor")[0] == "S3"
    assert detect_safety("mi compañero se golpeó y está sangrando")[0] == "S4"


@pytest.mark.parametrize("text,expected", [
    ("Se rompió el niple de descarga de la uno", "S1"),
    ("Se rompió la brida de descarga, sale agua", "S1"),
    ("Se cortó la línea de descarga", "S1"),
    ("Reventó el niple", "S1"),
    ("Huele a gas en la bomba dos", "S2"),
    ("Siento que hay olor a gas", "S2"),
    ("Se prendió fuego el motor", "S3"),
    ("Se lastimó el operador", "S4"),
    ("El operador se cayó y está inconsciente", "S4"),
    ("El compañero no responde", "S4"),
])
def test_safety_variants_the_asr_can_produce(text, expected):
    assert detect_safety(text)[0] == expected


def test_emergency_text_mentions_radio_and_supervisor():
    text = emergency_text("S1", "B-101")
    assert "radio" in text and "supervisor" in text and "emergencia" in text


def test_sensor_spike_does_not_escalate(snapshot):
    detector = SensorDetector(snapshot)
    base = detector.windows[("B-101", "presion_descarga")].limit.high
    assert base == 125
    t0 = __import__("datetime").datetime(2026, 11, 3, 8, 0)
    assert detector.feed("B-101", "presion_descarga", 112, t0, "buena")[0] is None
    assert detector.feed("B-101", "presion_descarga", 130, t0 + timedelta(minutes=1), "buena")[0] is None
    assert detector.feed("B-101", "presion_descarga", 112, t0 + timedelta(minutes=2), "buena")[0] is None


def test_sustained_sensor_deviation_escalates_once(snapshot):
    detector = SensorDetector(snapshot)
    from datetime import datetime

    t0 = datetime(2026, 11, 3, 8, 0)
    events = []
    for minute in range(6):
        event, _episode = detector.feed("B-101", "presion_descarga", 130, t0 + timedelta(minutes=minute), "buena")
        if event:
            events.append(event)
    assert len(events) == 1
    assert events[0]["tipo"] == ESCALADO
    assert events[0]["origen"] == "sensor"


def test_sensor_without_quality_is_ignored(snapshot):
    detector = SensorDetector(snapshot)
    from datetime import datetime

    t0 = datetime(2026, 11, 3, 8, 0)
    assert detector.feed("B-101", "presion_descarga", None, t0, "sin_dato")[0] is None
    assert detector.feed("B-101", "presion_descarga", 130, t0, "sin_dato")[0] is None


def test_restored_episode_reuses_the_same_event_id(snapshot):
    """A restart in the middle of a deviation must not announce a second event."""
    from datetime import datetime

    t0 = datetime(2026, 11, 3, 8, 0)
    first = SensorDetector(snapshot)
    event, episode = None, None
    for minute in range(3):
        event, episode = first.feed("B-101", "presion_descarga", 130, t0 + timedelta(minutes=minute), "buena")
    assert event is not None and episode is not None and episode["active"] is True

    # New process: only the persisted episode survives.
    second = SensorDetector(snapshot)
    second.restore([{"tag": "B-101", "variable": "presion_descarga", "active": True,
                     "since": episode["since"], "event_id": episode["event_id"]}])
    again = None
    for minute in range(3, 8):
        candidate, _ = second.feed("B-101", "presion_descarga", 130, t0 + timedelta(minutes=minute), "buena")
        again = again or candidate
    # The episode was already announced: a restart neither repeats it nor invents a new id.
    assert again is None
    assert second.episode("B-101", "presion_descarga")["event_id"] == event["id"]


def test_episode_is_cleared_when_the_deviation_ends(snapshot):
    from datetime import datetime

    t0 = datetime(2026, 11, 3, 8, 0)
    detector = SensorDetector(snapshot)
    for minute in range(3):
        detector.feed("B-101", "presion_descarga", 130, t0 + timedelta(minutes=minute), "buena")
    transition = None
    for minute in range(3, 7):
        _event, candidate = detector.feed("B-101", "presion_descarga", 112, t0 + timedelta(minutes=minute), "buena")
        transition = transition or candidate
    assert transition is not None and transition["active"] is False
