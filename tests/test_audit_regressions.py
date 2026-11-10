"""Regression tests for the defects found in the Delivery 1 audit."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.config import Settings
from app.domain.parser import parse_transcript
from app.processing.workflow import NoteWorkflow
from app.rag.bm25 import metadata_weight
from app.tools.contracts import InventoryQuery
from app.tools.queries import Tools
from tests.conftest import TZ


class FakePlant:
    """Plant HTTP client double: the state clock and a historian with samples."""

    def __init__(self) -> None:
        self.historian_calls: list[tuple[str, str]] = []

    async def state(self) -> dict:
        return {"ts": "2026-11-03T08:00:00-03:00", "bombas": [], "enlace_arriba": True,
                "hay_energia": True}

    async def historian(self, tag: str, variable: str, desde=None, hasta=None) -> list[dict]:
        self.historian_calls.append((tag, variable))
        return [{"ts": "2026-11-03T07:00:00-03:00", "valor": 100.0 + index} for index in range(5)]


class FakeRepo:
    def __init__(self) -> None:
        self.events: list[tuple[dict, dict | None]] = []
        self.updated: dict[str, dict] = {}
        self.parts: list[dict] = []
        self.replies: list[dict] = []
        self.attempts: list[dict] = []
        self.usage: list[dict] = []

    async def set_note_status(self, *args):
        return None

    async def save_part(self, note_id, status, rows, safety, attempts):
        self.parts.append({"note_id": note_id, "status": status, "rows": rows, "safety": safety})

    async def insert_event(self, event, context=None):
        self.events.append((event, context))
        return True

    async def update_event_context(self, event_id, context):
        self.updated[event_id] = context

    async def add_tablet_message(self, message_id, note_id, ts, kind, payload):
        return True

    async def note_ids_for_message(self, message_id):
        return ["N1"]

    async def add_reply(self, reply_id, message_id, note_id, text, ts):
        self.replies.append({"id": reply_id, "message_id": message_id, "note_id": note_id,
                             "text": text, "ts": ts})

    async def add_attempt(self, attempt_id, note_id, message_id, kind, rows):
        self.attempts.append({"id": attempt_id, "kind": kind, "message_id": message_id})

    async def set_attempt_reply(self, message_id, reply):
        return None

    async def record_usage(self, model, task, input_tokens, output_tokens, latency_ms, cost_usd=0.0):
        self.usage.append({"model": model, "task": task, "latency_ms": latency_ms})

    async def open_order(self, equipment, tasks):
        return None

    async def upsert_order(self, *args):
        return None

    async def record_decision(self, *args):
        return None


class NoopPublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def publish(self, topic, payload, sync=True):
        self.messages.append((topic, payload))
        return True


def make_workflow(snapshot, materials, plant=None) -> tuple[NoteWorkflow, FakeRepo, NoopPublisher]:
    repo, publisher = FakeRepo(), NoopPublisher()
    workflow = NoteWorkflow(Settings(), repo=repo, plant=plant, publisher=publisher,  # type: ignore[arg-type]
                            snapshot=snapshot, materials=materials, transcriber=None)
    return workflow, repo, publisher


async def test_operator_reply_is_persisted(snapshot, materials):
    workflow, repo, _ = make_workflow(snapshot, materials)
    await workflow.on_reply({
        "id": "RESP-1", "ts": datetime(2026, 11, 3, 8, 0, tzinfo=TZ).isoformat(),
        "mensaje_id": "TAB-N1-0", "operador": "x", "texto": "Sí, confirmo.", "audio_url": None,
    })
    assert repo.replies and repo.replies[0]["message_id"] == "TAB-N1-0"
    assert repo.replies[0]["note_id"] == "N1"
    assert repo.replies[0]["text"] == "Sí, confirmo."


async def test_invalid_operator_reply_is_not_stored(snapshot, materials):
    workflow, repo, _ = make_workflow(snapshot, materials)
    await workflow.on_reply({"mensaje_id": "TAB-N1-0", "texto": "sin contrato"})
    assert repo.replies == []


async def test_escalated_event_carries_photos_and_sensor_trend(snapshot, materials):
    plant = FakePlant()
    workflow, repo, _ = make_workflow(snapshot, materials, plant=plant)
    draft = parse_transcript("La tres sigue goteando por la empaquetadura, le saqué foto.",
                            snapshot, note_id="N1", ts=datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                            photos=["/media/fotos/empaquetadura/01.jpg"])
    workflow.structural_damage = set()
    await workflow._finalize(__import__("app.contract", fromlist=["NotaRecorrida"]).NotaRecorrida(
        id="N1", ts=datetime(2026, 11, 3, 8, 0, tzinfo=TZ), operador="x", audio_url=None,
        fotos=["/media/fotos/empaquetadura/01.jpg"], recorrida_id="R"), draft, "confirmed")
    await __import__("asyncio").gather(*workflow.background)
    escalated = [event for event, _context in repo.events if event["tipo"] == "Escalado"]
    assert escalated, "the goteo must escalate"
    stored = repo.updated[escalated[-1]["id"]]
    assert stored["sensor_trend"], "the escalated event must carry the recent sensor trend"
    assert "presion_descarga" in stored["sensor_trend"]
    assert stored["rows"] and stored["rows"][0]["variable"] == "goteo_empaquetadura"


async def test_tool_calls_are_audited_with_arguments(snapshot, materials):
    calls: list[tuple] = []

    async def audit(name, arguments, ok, error, latency_ms):
        calls.append((name, arguments, ok, latency_ms))

    tools = Tools(plant=FakePlant(), materials=materials, snapshot=snapshot,  # type: ignore[arg-type]
                  search=None, audit=audit)
    result = await tools.inventario(InventoryQuery(almacen="yacimiento"))
    assert result.repuestos
    assert calls and calls[0][0] == "inventario" and calls[0][1] == {"almacen": "yacimiento"}
    assert calls[0][2] is True and calls[0][3] >= 0


async def test_failed_tool_is_audited_and_raises(snapshot, materials):
    calls: list[tuple] = []

    async def audit(name, arguments, ok, error, latency_ms):
        calls.append((name, ok, error))

    tools = Tools(plant=FakePlant(), materials=materials, snapshot=snapshot,  # type: ignore[arg-type]
                  search=None, audit=audit)
    try:
        await tools.stock(__import__("app.tools.contracts", fromlist=["StockQuery"]).StockQuery(
            codigo="NO-EXISTE"))
    except Exception as exc:  # noqa: BLE001
        assert "NO-EXISTE" in str(exc)
    else:  # pragma: no cover - the call must fail
        raise AssertionError("the tool must reject an unknown part")
    assert calls and calls[0][1] is False and calls[0][2]


def test_manufacturer_metadata_prefers_the_named_maker():
    chunk = {"title": "Límites", "section_key": "limites", "doc": "TX350-D",
             "current": True, "equipment": ["B-101"], "manufacturer": "Trimax Industrial S.A."}
    other = {**chunk, "doc": "FC48-3", "manufacturer": "Filtrapat S.R.L."}
    named = metadata_weight(chunk, "límite de descarga según Trimax", set())
    foreign = metadata_weight(other, "límite de descarga según Trimax", set())
    assert named > foreign


def test_draft_does_not_duplicate_photos(snapshot):
    photos = ["/media/fotos/manometro_diferencial/01.jpg"]
    draft = parse_transcript("La uno está en ciento doce kilos de descarga.",
                             snapshot, note_id="N1", ts=datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                             photos=photos)
    assert draft.photos == photos, "the note photo list must not be duplicated"
    assert draft.rows[-1].photo == photos[0]

# Exact texts the official simulator dictates for the four unsafe conditions
# (planta/sim/planta_sim/operador.py, ``nota_seguridad``).
SAFETY_TEXTS = {
    "S1": "¡Atención! Se rompió algo en la descarga de la uno, sale agua a presión para todos lados, "
          "me alejé. Saqué foto desde lejos.",
    "S2": "Hay olor a gas fuerte del lado del portón, viene del lado del separador.",
    "S3": "Sale humo del motor de la dos, hay olor a quemado.",
    "S4": "Mi compañero se golpeó la mano con la llave en el skid de filtros, está sangrando bastante.",
}


@pytest.mark.parametrize("codigo", sorted(SAFETY_TEXTS))
def test_each_official_unsafe_condition_is_detected(codigo):
    from app.domain.safety import detect_safety

    detected, evidence = detect_safety(SAFETY_TEXTS[codigo])
    assert detected == codigo, f"{codigo} not detected (got {detected!r})"
    assert evidence


def test_ordinary_notes_do_not_raise_the_safety_alert(snapshot):
    from app.domain.safety import detect_safety

    for texto in (
        "La empaquetadura gotea, no hay olor a gas.",
        "La uno está en ciento doce kilos de descarga.",
        "La tres sigue goteando por la empaquetadura, le saqué foto.",
        "El pulmón está en cinco metros.",
        "La dos está parada, en reserva.",
        "Hace un ruido a piedras en el extremo hidráulico.",
    ):
        assert detect_safety(texto)[0] is None, texto


# What the local ASR actually returned during the end-to-end audit: "a gas" glued into
# "agas", a stray comma inside "agua, presión", "Mi" heard as "Ni".
ASR_SAFETY_VARIANTS = {
    "S1": "Atención, se rompió algo en la descarga de la de la punta, sale agua, presión para todos lados, "
          "me alejé, saqué foto desde lejos.",
    "S2": "Hay olor agas fuerte del lado del pontón, viene del lado del separador.",
    "S3": "Sale humo del motor de la dos, hay olor a quemado.",
    "S4": "Ni compañero se golpeó la mano con la llave en el skid de filtros, está sangrando bastante.",
}


@pytest.mark.parametrize("codigo", sorted(ASR_SAFETY_VARIANTS))
def test_safety_survives_the_real_transcription(codigo):
    from app.domain.safety import detect_safety

    assert detect_safety(ASR_SAFETY_VARIANTS[codigo])[0] == codigo


def test_a_packaging_leak_is_not_a_pressurised_water_projection():
    from app.domain.safety import detect_safety

    assert detect_safety("La tres sigue goteando por la empaquetadura, sale agua por la empaquetadura.")[0] is None


def test_filter_name_survives_the_common_asr_misspelling(snapshot):
    """The official run transcribed "filtro" as "filto"; the reading must not be lost."""
    from datetime import datetime

    from app.domain.parser import parse_transcript

    draft = parse_transcript(
        "La dos está en 1600 psi de descarga, el fitro a medio 1,3 de diferencial.",
        snapshot, note_id="N1", ts=datetime(2026, 11, 3, 8, 0, tzinfo=TZ))
    rows = {(row.tag, row.variable): row.value for row in draft.rows}
    assert rows.get(("F-201A", "presion_diferencial")) == 1.3
    assert rows.get(("B-102", "presion_descarga_local")) == 1600


def test_bare_parada_is_quiet_when_the_plant_says_the_pump_is_stopped(snapshot):
    """ASR turned "parada, en reserva" into "parada"; the reserve pump is stopped."""
    from datetime import datetime

    from app.domain.events import ESCALADO, SIN_NOVEDAD, note_events
    from app.domain.parser import parse_transcript

    ts = datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    draft = parse_transcript("B-103 está parada.", snapshot, note_id="N1", ts=ts)
    assert [row.observation for row in draft.rows] == ["parada"]
    pumps = {"B-101": "marcha", "B-102": "marcha", "B-103": "parada"}
    assert note_events(draft, snapshot, ts, pumps)[0]["tipo"] == SIN_NOVEDAD
    running = {"B-101": "marcha", "B-102": "marcha", "B-103": "marcha"}
    assert note_events(draft, snapshot, ts, running)[0]["tipo"] == ESCALADO
    # Without plant state the observation stands on its own (conservative).
    assert note_events(draft, snapshot, ts)[0]["tipo"] == ESCALADO
