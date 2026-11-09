from __future__ import annotations

import pytest

from app.config import Settings
from app.contract import NotaRecorrida
from app.domain.materials import load_materials
from app.domain.plant import load_snapshot_file
from app.processing.workflow import NoteWorkflow
from tests.conftest import TZ


class FakeRepo:
    def __init__(self):
        self.tablet: list[str] = []
        self.parts: list[dict] = []
        self.events: list[dict] = []

    async def get_part(self, note_id):
        return None

    async def set_note_status(self, *args):
        return None

    async def set_transcript(self, *args):
        return None

    async def add_tablet_message(self, message_id, note_id, ts, kind, payload):
        self.tablet.append(message_id)
        return True

    async def add_attempt(self, *args):
        return None

    async def set_attempt_reply(self, *args):
        return None

    async def save_part(self, note_id, status, rows, safety, attempts):
        self.parts.append({"note_id": note_id, "status": status, "rows": rows})

    async def insert_event(self, event, context=None):
        self.events.append(event)
        return True


class FakePublisher:
    def __init__(self):
        self.messages: list[tuple[str, dict]] = []

    async def publish(self, topic, payload, sync=True):
        self.messages.append((topic, payload))
        return True


def make_workflow(text: str, snapshot, materials) -> tuple[NoteWorkflow, FakeRepo, FakePublisher]:
    repo, publisher = FakeRepo(), FakePublisher()
    workflow = NoteWorkflow(Settings(), repo=repo, plant=None, publisher=publisher,  # type: ignore[arg-type]
                            snapshot=snapshot, materials=materials, transcriber=None)

    async def transcribe(note):
        return text

    async def wait_reply(message_id, timeout):
        return {"texto": "La tres." if "-eq" in message_id else "Sí, confirmo."}

    async def no_history(rows, reference):
        return []

    workflow._transcribe = transcribe  # type: ignore[assignment]
    workflow._wait_reply = wait_reply  # type: ignore[assignment]
    workflow.history.check = no_history  # type: ignore[assignment]
    return workflow, repo, publisher


async def test_ambiguous_observation_asks_and_gets_a_draft(snapshot, materials):
    workflow, repo, _ = make_workflow("La bomba está parada en reserva.", snapshot, materials)
    note = NotaRecorrida(id="N1", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                         operador="x", audio_url=None, fotos=[], recorrida_id="R")
    await workflow._process(note)
    assert "TAB-N1-eq0" in repo.tablet
    assert "TAB-N1-info" in repo.tablet
    assert repo.parts and repo.parts[0]["status"] == "confirmed"


async def test_asr_merged_differential_first_draft_is_correct(snapshot, materials):
    workflow, repo, publisher = make_workflow("El filtro B-109 de diferencial. El pulmón está en 5 metros.",
                                              snapshot, materials)
    note = NotaRecorrida(id="N2", ts=__import__("datetime").datetime(2026, 11, 3, 8, 0, tzinfo=TZ),
                         operador="x", audio_url=None, fotos=[], recorrida_id="R")
    await workflow._process(note)
    draft = next(payload for topic, payload in publisher.messages
                 if topic == "sistema/tablet" and payload["id"] == "TAB-N2-0")
    rows = {(row["tag"], row["variable"]): row["valor"] for row in draft["pantalla"]["filas"]}
    assert rows[("F-201B", "presion_diferencial")] == 0.9
    assert "TAB-N2-hist0" not in repo.tablet
