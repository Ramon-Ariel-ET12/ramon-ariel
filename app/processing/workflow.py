"""The voice-note workflow: transcript -> draft -> operator review -> confirmed part."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from app.agent import NoteAgent
from app.config import Settings
from app.contract import NotaCierre, NotaRecorrida
from app.domain.events import ESCALADO, note_events
from app.domain.history import HistoricalValidator
from app.domain.materials import Materials
from app.domain.models import Ambiguity, ExtractedRow, PartDraft, PlantSnapshot
from app.domain.orders import make_proposal, order_id, order_payload, propose_tasks
from app.domain.parser import parse_transcript
from app.domain.rules import Decision, PlantState
from app.domain.safety import emergency_text
from app.integrations.plant_api import PlantClient
from app.llm.local import LocalLLM
from app.persistence.repository import Repository
from app.processing.asr import Transcriber
from app.processing.replies import apply_corrections, read_reply
from app.publisher import Publisher

log = logging.getLogger(__name__)


class NoteWorkflow:
    def __init__(self, settings: Settings, repo: Repository, plant: PlantClient, publisher: Publisher,
                 snapshot: PlantSnapshot, materials: Materials, transcriber: Transcriber,
                 llm: LocalLLM | None = None):
        self.settings = settings
        self.repo = repo
        self.plant = plant
        self.publisher = publisher
        self.snapshot = snapshot
        self.materials = materials
        self.transcriber = transcriber
        self.llm = llm
        self.agent = NoteAgent(snapshot)
        self.history = HistoricalValidator(plant, snapshot)
        self.queue: asyncio.Queue[NotaRecorrida] = asyncio.Queue()
        self.waiters: dict[str, asyncio.Event] = {}
        self.replies: dict[str, dict] = {}
        self.structural_damage: set[str] = set()
        self._task: asyncio.Task | None = None

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        await self.repo.reset_stuck_notes()
        self._task = asyncio.create_task(self._worker(), name="note-worker")
        for row in await self.repo.pending_notes():
            await self._queue_row(row)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, payload: dict) -> None:
        note = NotaRecorrida.model_validate(payload)
        created = await self.repo.create_note(
            note.id, note.ts, note.operador, note.recorrida_id, note.audio_url, list(note.fotos),
            note.id.startswith("VIVO-"),
        )
        if not created:
            log.info("duplicate note %s ignored", note.id)
            return
        await self.queue.put(note)

    async def _queue_row(self, row: dict) -> None:
        payload = {
            "id": row["id"], "ts": row["ts"].isoformat(), "operador": row["operator"],
            "audio_url": row["audio_url"], "fotos": row["photos"] or [], "recorrida_id": row["walk_id"],
        }
        await self.queue.put(NotaRecorrida.model_validate(payload))

    def on_reply(self, payload: dict) -> None:
        message_id = payload.get("mensaje_id")
        if not message_id:
            return
        self.replies[message_id] = payload
        waiter = self.waiters.get(message_id)
        if waiter:
            waiter.set()

    async def _worker(self) -> None:
        while True:
            note = await self.queue.get()
            try:
                await self._process(note)
            except Exception:  # noqa: BLE001
                log.exception("note %s failed", note.id)
                await self.repo.set_note_status(note.id, "failed")
            finally:
                self.queue.task_done()

    # ---------------------------------------------------------------- processing

    async def _process(self, note: NotaRecorrida) -> None:
        existing = await self.repo.get_part(note.id)
        if existing and existing["status"] in ("confirmed", "confirmed_with_differences"):
            await self.repo.set_note_status(note.id, "done")
            return
        deadline = time.monotonic() + self.settings.note_timeout_s
        await self.repo.set_note_status(note.id, "processing")
        # Keep the plant's event clock slow while the local ASR works, and give the
        # operator immediate feedback. It is a notice, not a question or a draft.
        if not note.id.startswith("VIVO-"):
            await self._send_tablet(f"TAB-{note.id}-processing", note,
                                    "Nota recibida. Procesando el parte...", waits=False, kind="notice")

        transcript = await self._transcribe(note)
        if transcript:
            await self.repo.set_transcript(note.id, transcript)
        draft, _safety = self.agent.analyze(transcript, note.id, note.ts, note.fotos)

        if draft.safety:
            await self._handle_safety(note, draft, deadline)
            return
        if not draft.rows and not draft.ambiguities:
            await self._handle_empty(note, draft)
            return

        draft = await self._resolve_ambiguities(note, draft, deadline)
        await self._download_photos(note, draft)
        await self._confirm_historical_range(note, draft, deadline)

        valued = draft.valued_rows()
        if valued:
            draft, confirmed = await self._review_loop(note, draft, deadline)
            status = "confirmed" if confirmed else "confirmed_with_differences"
        else:
            await self._inform_only(note, draft)
            status = "confirmed"
        await self._finalize(note, draft, status)

    async def _transcribe(self, note: NotaRecorrida) -> str:
        if not note.audio_url:
            return ""
        try:
            audio = await self.plant.download(note.audio_url)
        except Exception as exc:  # noqa: BLE001
            log.error("note %s audio download failed: %s", note.id, exc)
            return ""
        suffix = Path(note.audio_url).suffix or ".wav"
        import tempfile

        target = Path(tempfile.gettempdir()) / "pia-audio" / f"{note.id}{suffix}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(audio)
        except OSError:
            log.exception("note %s audio could not be stored", note.id)
            return ""
        try:
            result = await asyncio.to_thread(self.transcriber.transcribe, target)
        except Exception:  # noqa: BLE001
            log.exception("note %s transcription failed", note.id)
            return ""
        log.info("note %s transcribed in %sms: %s", note.id, result.latency_ms, result.text[:160])
        return result.text

    async def _download_photos(self, note: NotaRecorrida, draft: PartDraft) -> None:
        mapping: dict[str, str] = {}
        for index, url in enumerate(note.fotos):
            try:
                data = await self.plant.download(url)
                target = (self.settings.media_dir / "photos" / note.id
                          / f"{index + 1:02d}{Path(url).suffix or '.jpg'}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                mapping[url] = str(target)
            except Exception as exc:  # noqa: BLE001
                log.warning("photo %s could not be archived: %s", url, exc)
                continue
        for row in draft.rows:
            if row.photo and row.photo in mapping:
                row.photo = mapping[row.photo]

    # ---------------------------------------------------------------- tablet

    async def _send_tablet(self, message_id: str, note: NotaRecorrida, text: str, *,
                           rows: list[ExtractedRow] | None = None, options: list[str] | None = None,
                           waits: bool = True, kind: str = "draft") -> None:
        pantalla = None
        if options is not None:
            pantalla = {"titulo": "Pregunta", "filas": [], "opciones": options}
        elif rows is not None:
            pantalla = {"titulo": "Parte de recorrida - borrador", "filas": [row.to_contract() for row in rows]}
        payload = {
            "id": message_id,
            "ts": datetime.now(UTC).isoformat(),
            "nota_ids": [note.id],
            "texto": text,
            "pantalla": pantalla,
            "espera_respuesta": waits,
            "audio_url": None,
        }
        await self.repo.add_tablet_message(message_id, note.id, note.ts, kind, payload)
        await self.publisher.publish("sistema/tablet", payload, sync=False)

    async def _wait_reply(self, message_id: str, timeout: float) -> dict | None:
        if message_id in self.replies:
            return self.replies.pop(message_id)
        event = self.waiters.setdefault(message_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return None
        finally:
            self.waiters.pop(message_id, None)
        return self.replies.pop(message_id, None)

    async def _send_draft(self, message_id: str, note: NotaRecorrida, draft: PartDraft,
                          attempt: int) -> None:
        count = len(draft.valued_rows())
        text = f"Borrador del parte de recorrida: {count} lectura(s). Revisá y confirmá."
        await self._send_tablet(message_id, note, text, rows=draft.rows, waits=True, kind="draft")
        await self.repo.add_attempt(f"attempt-{message_id}", note.id, message_id, "draft",
                                    [row.model_dump() for row in draft.rows])

    async def _inform_only(self, note: NotaRecorrida, draft: PartDraft) -> None:
        mid = f"TAB-{note.id}-info"
        text = "Parte de recorrida sin lecturas numéricas. Observaciones registradas."
        await self._send_tablet(mid, note, text, rows=draft.rows, waits=True, kind="draft")
        await self._wait_reply(mid, 20)
        await self._send_ack(note)

    async def _review_loop(self, note: NotaRecorrida, draft: PartDraft,
                           deadline: float) -> tuple[PartDraft, bool]:
        attempt = 0
        confirmed = False
        while attempt < self.settings.max_attempts and time.monotonic() < deadline:
            mid = f"TAB-{note.id}-{attempt}"
            await self._send_draft(mid, note, draft, attempt)
            remaining = deadline - time.monotonic()
            reply = await self._wait_reply(mid, min(40.0, max(4.0, remaining)))
            if not reply:
                log.warning("note %s: no reply to draft %s", note.id, mid)
                break
            reading = read_reply(reply.get("texto", ""), self.snapshot, "draft")
            await self.repo.set_attempt_reply(mid, reply.get("texto", ""))
            if reading.kind == "unknown" and self.llm is not None and self.llm.enabled:
                actions, usage = await self.llm.interpret_reply(
                    reply.get("texto", ""), [row.model_dump() for row in draft.rows])
                if usage:
                    await self.repo.record_usage(usage["model"], usage["task"], usage["input_tokens"],
                                                 usage["output_tokens"], usage["latency_ms"],
                                                 usage.get("cost_usd", 0.0))
                if actions:
                    reading = type(reading)(kind="correction", actions=actions)
            if reading.kind == "confirmation":
                confirmed = True
                break
            if reading.kind == "correction" and reading.actions:
                updated = apply_corrections(draft.model_copy(deep=True), reading.actions, self.snapshot)
                if updated.rows == draft.rows:
                    log.warning("note %s: correction had no effect: %s", note.id, reply.get("texto"))
                    break
                draft = updated
                attempt += 1
                continue
            log.warning("note %s: unreadable reply: %s", note.id, reply.get("texto"))
            attempt += 1
        return draft, confirmed

    async def _send_ack(self, note: NotaRecorrida) -> None:
        await self._send_tablet(f"TAB-{note.id}-ok", note, "Parte guardado.", waits=False, kind="notice")

    # ---------------------------------------------------------------- ambiguity

    async def _resolve_ambiguities(self, note: NotaRecorrida, draft: PartDraft,
                                   deadline: float) -> PartDraft:
        equipment = [item for item in draft.ambiguities if item.kind == "equipment"]
        for index, ambiguity in enumerate(equipment):
            options = [f"{self._label(tag)} ({tag})" for tag in ambiguity.candidates]
            mid = f"TAB-{note.id}-eq{index}"
            await self._send_tablet(mid, note, "¿De qué equipo se trata?", options=options,
                                    waits=True, kind="question_equipment")
            reply = await self._wait_reply(mid, min(40.0, max(4.0, deadline - time.monotonic())))
            if not reply:
                continue
            tag = read_reply(reply.get("texto", ""), self.snapshot, "question_equipment").tag
            if tag and tag in ambiguity.candidates:
                draft = self._apply_equipment_resolution(draft, ambiguity, tag)
        values = [item for item in draft.ambiguities if item.kind == "value"]
        for index, _ in enumerate(values):
            mid = f"TAB-{note.id}-val{index}"
            question = "¿El diferencial fue uno coma ocho o dieciocho? Repetime el valor."
            await self._send_tablet(mid, note, question, waits=True, kind="question_value")
            await self._wait_reply(mid, min(20.0, max(4.0, deadline - time.monotonic())))
        draft.ambiguities = []
        return draft

    def _label(self, tag: str) -> str:
        equipment = self.snapshot.equipment.get(tag)
        if not equipment:
            return tag
        return equipment.names[0] if equipment.names else tag

    def _apply_equipment_resolution(self, draft: PartDraft, ambiguity: Ambiguity, tag: str) -> PartDraft:
        clause = re.sub(r"\b(la|el)\s+(bomba|filtro)\b", tag, ambiguity.clause, count=1, flags=re.IGNORECASE)
        sub = parse_transcript(clause, self.snapshot, note_id=draft.note_id, ts=draft.ts, photos=[])
        by_key = {(row.tag, row.variable): row for row in draft.rows}
        for row in sub.rows:
            by_key.setdefault((row.tag, row.variable), row)
        draft.rows = list(by_key.values())
        return draft

    async def _confirm_historical_range(self, note: NotaRecorrida, draft: PartDraft,
                                        deadline: float) -> None:
        flagged = await self.history.check(draft.rows, note.ts)
        for index, row in enumerate(flagged):
            mid = f"TAB-{note.id}-hist{index}"
            text = (f"{row.tag} {row.variable} = {row.value} {row.unit or ''} está fuera del rango histórico. "
                    "¿Confirmás la lectura?")
            await self._send_tablet(mid, note, text, waits=True, kind="question_value")
            await self._wait_reply(mid, min(20.0, max(4.0, deadline - time.monotonic())))

    # ---------------------------------------------------------------- outcomes

    async def _handle_safety(self, note: NotaRecorrida, draft: PartDraft, deadline: float) -> None:
        event = note_events(draft, self.snapshot, note.ts)[0]
        tag = draft.rows[0].tag if draft.rows else None
        if draft.safety == "S1" and draft.photos and tag:
            self.structural_damage.add(tag)
        # The operator-facing notice goes first: it is the emergency action. The
        # durable event follows immediately; neither waits for photo downloads.
        mid = f"ALERTA-{note.id}"
        await self._send_tablet(mid, note, emergency_text(draft.safety or "S1", tag),
                                rows=draft.rows, waits=False, kind="notice")
        await self.publisher.publish("sistema/eventos", event, sync=True)
        await self.repo.insert_event(event, {"rows": [row.model_dump() for row in draft.rows],
                                             "photos": draft.photos, "safety": draft.safety})
        await self._download_photos(note, draft)
        await self.repo.save_part(note.id, "confirmed", [row.model_dump() for row in draft.rows],
                                  draft.safety, 0)
        await self.repo.set_note_status(note.id, "confirmed")
        log.warning("note %s raised safety alert %s for %s", note.id, draft.safety, tag)

    async def _handle_empty(self, note: NotaRecorrida, draft: PartDraft) -> None:
        if note.id.startswith("VIVO-"):
            await self._send_tablet(f"TAB-{note.id}-ok", note,
                                    "Nota recibida. No hay datos para el parte.", waits=False, kind="notice")
        else:
            event = note_events(draft, self.snapshot, note.ts)[0]
            await self.publisher.publish("sistema/eventos", event, sync=True)
            await self.repo.insert_event(event, {"transcript": draft.transcript})
        await self.repo.save_part(note.id, "confirmed", [], None, 0)
        await self.repo.set_note_status(note.id, "confirmed")
        await self._send_ack(note)

    async def _finalize(self, note: NotaRecorrida, draft: PartDraft, status: str) -> None:
        await self.repo.save_part(note.id, status, [row.model_dump() for row in draft.rows],
                                  draft.safety, len(draft.rows))
        await self.repo.set_note_status(note.id, "confirmed")
        context = {
            "rows": [row.model_dump() for row in draft.rows],
            "photos": draft.photos,
            "transcript": draft.transcript,
            "status": status,
        }
        for event in note_events(draft, self.snapshot, note.ts):
            await self.publisher.publish("sistema/eventos", event, sync=True)
            await self.repo.insert_event(event, context)
            if event["tipo"] == ESCALADO:
                await self.maybe_order(event, rows=draft.rows_for(event["equipo"] or ""),
                                       sensor_variable=None)
        await self._send_ack(note)

    # ---------------------------------------------------------------- orders

    async def _plant_state(self) -> tuple[PlantState, bool]:
        try:
            state = await self.plant.state()
            pumps = {item["tag"]: item["estado"] for item in state.get("bombas", [])}
            return PlantState(pumps=pumps, link_up=bool(state.get("enlace_arriba", True)),
                              power=bool(state.get("hay_energia", True))), True
        except Exception as exc:  # noqa: BLE001
            log.error("plant state unavailable: %s", exc)
            return PlantState(pumps={}), False

    async def maybe_order(self, event: dict, *, rows: list[ExtractedRow],
                          sensor_variable: str | None) -> None:
        equipment = event.get("equipo")
        if not equipment or equipment.startswith(("TK-", "FT-")):
            return
        tasks = propose_tasks(equipment, rows, sensor_variable)
        if not tasks:
            return
        existing = await self.repo.open_order(equipment, tasks)
        if existing:
            log.info("order already open for %s %s: %s", equipment, tasks, existing["id"])
            return
        state, ok = await self._plant_state()
        proposal, decision = make_proposal(
            equipment, tasks, self.materials, state,
            structural_damage=equipment in self.structural_damage, forced_pending=not ok,
        )
        oid = order_id(equipment, tasks, event["id"])
        now = datetime.now(UTC)
        draft_state = Decision(approved=False)
        borrador = order_payload(oid, now, "Borrador", proposal, draft_state, [event["id"]])
        final = order_payload(oid, now, decision.state, proposal, decision, [event["id"]])
        await self.publisher.publish("sistema/ordenes", borrador, sync=True)
        await self.repo.upsert_order(oid, equipment, tasks, "Borrador", borrador)
        log.info("order %s for %s %s -> %s (%s)", oid, equipment, tasks, decision.state,
                 "; ".join(decision.reasons) or "reglas cumplidas")
        await self.publisher.publish("sistema/ordenes", final, sync=True)
        await self.repo.upsert_order(oid, equipment, tasks, decision.state, final)
        await self.repo.record_decision(oid, decision.state, decision.reasons, state.model_dump())

    async def handle_sensor_event(self, event: dict, variable: str | None) -> None:
        await self.publisher.publish("sistema/eventos", event, sync=True)
        await self.repo.insert_event(event, {"sensor_variable": variable})
        await self.maybe_order(event, rows=[], sensor_variable=variable)

    async def handle_closure(self, payload: dict) -> None:
        try:
            closure = NotaCierre.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log.error("invalid closure: %s", exc)
            return
        row = await self.repo.orders_by_id(closure.orden_id)
        if not row:
            log.warning("closure for unknown order %s", closure.orden_id)
            return
        payload_order = dict(row["payload"])
        payload_order["ts"] = datetime.now(UTC).isoformat()
        payload_order["estado"] = "Ejecutada"
        payload_order["motivo"] = None
        await self.publisher.publish("sistema/ordenes", payload_order, sync=True)
        await self.repo.upsert_order(closure.orden_id, row["equipment"], row["tasks"], "Ejecutada", payload_order)
        log.info("order %s executed by %s", closure.orden_id, closure.tecnico)
