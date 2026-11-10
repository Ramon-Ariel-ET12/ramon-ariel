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
from app.contract import NotaCierre, NotaRecorrida, RespuestaOperador
from app.domain.events import ESCALADO, note_events
from app.domain.history import HistoricalValidator
from app.domain.materials import Materials
from app.domain.models import Ambiguity, ExtractedRow, PartDraft, PlantSnapshot
from app.domain.orders import make_proposal, order_id, order_payload, propose_tasks
from app.domain.parser import parse_transcript
from app.domain.rules import Decision, PlantState
from app.domain.safety import detect_safety, emergency_text
from app.integrations.plant_api import PlantClient
from app.llm.local import LocalLLM
from app.persistence.repository import Repository
from app.processing.asr import Transcriber
from app.processing.replies import apply_corrections, is_correction, read_reply
from app.publisher import Publisher
from app.rag.context import build_event_context

log = logging.getLogger(__name__)


class NoteWorkflow:
    def __init__(self, settings: Settings, repo: Repository, plant: PlantClient, publisher: Publisher,
                 snapshot: PlantSnapshot, materials: Materials, transcriber: Transcriber,
                 llm: LocalLLM | None = None, search=None):
        self.settings = settings
        self.repo = repo
        self.plant = plant
        self.publisher = publisher
        self.snapshot = snapshot
        self.materials = materials
        self.transcriber = transcriber
        self.llm = llm
        self.search = search
        self.agent = NoteAgent(snapshot)
        self.history = HistoricalValidator(plant, snapshot)
        self.queue: asyncio.Queue[NotaRecorrida] = asyncio.Queue()
        self.waiters: dict[str, asyncio.Event] = {}
        self.replies: dict[str, dict] = {}
        self.structural_damage: set[str] = set()
        self.background: set[asyncio.Task] = set()
        self.alerted: dict[str, dict] = {}
        self.closed: set[str] = set()
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
        for task in list(self.background):
            task.cancel()
        if self.background:
            await asyncio.gather(*self.background, return_exceptions=True)

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

    async def on_reply(self, payload: dict) -> None:
        """Persist the operator answer and wake the dialog waiting for it."""
        message_id = payload.get("mensaje_id")
        if not message_id:
            return
        try:
            reply = RespuestaOperador.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("invalid operator reply on %s: %s", message_id, exc)
            return
        try:
            notes = await self.repo.note_ids_for_message(message_id)
            await self.repo.add_reply(reply.id, message_id, notes[0] if notes else None,
                                      reply.texto, reply.ts)
            # The attempt that asked for it keeps the answer, even when it arrived after
            # the timeout of the dialog that sent the question.
            await self.repo.set_attempt_reply(message_id, reply.texto)
        except Exception:  # noqa: BLE001
            log.warning("reply %s could not be stored", reply.id, exc_info=True)
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
                # A late partial transcript from a cancelled ASR must not alert for a
                # note the workflow already closed.
                self.closed.add(note.id)
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

        transcript = await self._within(note, "transcription", self._transcribe(note), deadline,
                                        fallback="")
        if transcript:
            await self.repo.set_transcript(note.id, transcript)
        elif note.audio_url:
            # The note had audio and it could not be downloaded or transcribed. Reporting
            # "sin novedad" here would tell the plant that everything is normal.
            await self._handle_unreadable(note)
            return
        started = time.monotonic()
        draft, _safety = self.agent.analyze(transcript, note.id, note.ts, note.fotos)
        await self._record_step("parse", (time.monotonic() - started) * 1000)

        if draft.safety:
            await self._handle_safety(note, draft, deadline)
            return
        if not draft.rows and not draft.ambiguities:
            await self._handle_empty(note, draft)
            return

        draft = await self._resolve_ambiguities(note, draft, deadline)
        await self._within(note, "photo download", self._download_photos(note, draft), deadline)
        await self._confirm_historical_range(note, draft, deadline)

        valued = draft.valued_rows()
        if valued:
            draft, confirmed = await self._review_loop(note, draft, deadline)
            status = "confirmed" if confirmed else "confirmed_with_differences"
        else:
            await self._inform_only(note, draft)
            status = "confirmed"
        await self._finalize(note, draft, status)

    async def _within(self, note: NotaRecorrida, label: str, coro, deadline: float, fallback=None):
        """Run one pipeline step under the note's remaining real-time budget.

        The deadline was only checked between steps, so a slow ASR or a hanging download
        could keep a note (and the single worker) past its budget forever. A timed-out
        transcription returns "", which the caller treats as unreadable and never as
        "sin novedad".
        """
        budget = deadline - time.monotonic()
        if budget <= 0:
            log.error("note %s: %s skipped, the %.0fs note budget is spent",
                      note.id, label, self.settings.note_timeout_s)
            if hasattr(coro, "close"):
                coro.close()
            return fallback
        try:
            return await asyncio.wait_for(coro, timeout=budget)
        except TimeoutError:
            log.error("note %s: %s exceeded the remaining %.0fs", note.id, label, budget)
            return fallback

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
            loop = asyncio.get_running_loop()
            alerted = self.alerted

            def on_partial(text: str) -> None:
                # Runs inside the ASR thread: hand the partial transcript back to the
                # loop so the safety alert does not wait for the whole audio.
                if not text.strip() or note.id in alerted:
                    return
                asyncio.run_coroutine_threadsafe(self._early_alert(note, text), loop)

            result = await asyncio.to_thread(self.transcriber.transcribe, target,
                                             on_partial=on_partial)
        except Exception:  # noqa: BLE001
            log.exception("note %s transcription failed", note.id)
            return ""
        log.info("note %s transcribed in %sms: %s", note.id, result.latency_ms, result.text[:160])
        await self._record_step("asr", result.latency_ms, model=result.model)
        return result.text

    async def _record_step(self, task: str, latency_ms: int, model: str = "deterministic",
                           cost_usd: float = 0.0) -> None:
        """One row per pipeline step: model, tokens, estimated cost and latency."""
        try:
            await self.repo.record_usage(model, task, 0, 0, int(latency_ms), cost_usd)
        except Exception:  # noqa: BLE001
            log.warning("usage for step %s could not be stored", task, exc_info=True)

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
        # Both budgets are enforced, not just documented: MAX_ATTEMPTS caps the dialog
        # and MAX_NOTE_STEPS caps the loop even when MAX_ATTEMPTS is raised.
        max_attempts = min(self.settings.max_attempts, self.settings.max_note_steps)
        tokens_spent = 0
        no_effect = 0
        while attempt < max_attempts and time.monotonic() < deadline:
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
                if tokens_spent >= self.settings.token_budget:
                    log.warning("note %s: token budget (%s) exhausted, LLM disabled for this note",
                                note.id, self.settings.token_budget)
                else:
                    actions, usage = await self.llm.interpret_reply(
                        reply.get("texto", ""), [row.model_dump() for row in draft.rows])
                    if usage:
                        tokens_spent += int(usage["input_tokens"]) + int(usage["output_tokens"])
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
                    # The correction restates the draft (the operator was reading a stale
                    # screen, or a previous attempt already applied it). Resend once so the
                    # operator can confirm, instead of dropping the dialog and keeping a
                    # part nobody confirmed.
                    no_effect += 1
                    log.info("note %s: correction restates the draft (%s), resending: %s",
                             note.id, no_effect, reply.get("texto"))
                    if no_effect >= 2:
                        log.warning("note %s: correction still has no effect, stopping: %s",
                                    note.id, reply.get("texto"))
                        break
                    attempt += 1
                    continue
                draft = updated
                no_effect = 0
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
            await self.repo.add_attempt(f"attempt-{mid}", note.id, mid, "question_equipment", [])
            reply = await self._wait_reply(mid, min(40.0, max(4.0, deadline - time.monotonic())))
            if not reply:
                continue
            await self.repo.set_attempt_reply(mid, reply.get("texto", ""))
            tag = read_reply(reply.get("texto", ""), self.snapshot, "question_equipment").tag
            if tag and tag in ambiguity.candidates:
                draft = self._apply_equipment_resolution(draft, ambiguity, tag)
        values = [item for item in draft.ambiguities if item.kind == "value"]
        for index, ambiguity in enumerate(values):
            mid = f"TAB-{note.id}-val{index}"
            question = "¿El diferencial fue uno coma ocho o dieciocho? Repetime el valor."
            options = ["uno coma ocho", "dieciocho"]
            if ambiguity.repaired_value is not None and ambiguity.raw_value is not None:
                options = [f"{ambiguity.repaired_value:g}", f"{ambiguity.raw_value:g}"]
            await self._send_tablet(mid, note, question, options=options, waits=True, kind="question_value")
            await self.repo.add_attempt(f"attempt-{mid}", note.id, mid, "question_value", [])
            reply = await self._wait_reply(mid, min(20.0, max(4.0, deadline - time.monotonic())))
            if reply:
                await self.repo.set_attempt_reply(mid, reply.get("texto", ""))
                # The operator's answer is the value that gets stored: asking and then
                # ignoring it would leave a wrong reading in the confirmed part.
                answer = read_reply(reply.get("texto", ""), self.snapshot, "question_value")
                self._apply_value_answer(draft, ambiguity, answer.value, answer.unit)
        draft.ambiguities = []
        return draft

    def _apply_value_answer(self, draft: PartDraft, ambiguity: Ambiguity, value: float | None,
                            unit: str | None) -> None:
        if value is None:
            return
        repaired = ambiguity.repaired_value
        for row in draft.rows:
            if row.variable != "presion_diferencial":
                continue
            if ambiguity.tag and row.tag != ambiguity.tag:
                continue
            if repaired is not None and row.value is not None and abs(row.value - repaired) > 1e-9:
                continue
            row.value = value
            if unit:
                row.unit = unit
            row.flags = [flag for flag in row.flags if flag != "value_repaired"]
            log.info("note %s: operator set %s %s to %s %s", draft.note_id, row.tag, row.variable,
                     value, unit or row.unit)
            return

    def _label(self, tag: str) -> str:
        equipment = self.snapshot.equipment.get(tag)
        if not equipment:
            return tag
        return equipment.names[0] if equipment.names else tag

    def _apply_equipment_resolution(self, draft: PartDraft, ambiguity: Ambiguity, tag: str) -> PartDraft:
        clause = re.sub(r"\b(la|el)\s+(bomba|filtro)\b", tag, ambiguity.clause, count=1, flags=re.IGNORECASE)
        if clause == ambiguity.clause:
            # The clause did not name the family; prefix the chosen TAG so the
            # clause can be parsed with the resolved equipment.
            clause = f"{tag} {clause}"
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
            await self._send_tablet(mid, note, text, options=["Sí, confirmo", "No"], waits=True,
                                    kind="question_value")
            await self.repo.add_attempt(f"attempt-{mid}", note.id, mid, "question_value", [])
            reply = await self._wait_reply(mid, min(20.0, max(4.0, deadline - time.monotonic())))
            if not reply:
                # No answer: the reading is kept but flagged, so the confirmation cannot
                # be claimed and the part is stored as confirmed-with-differences.
                row.flags.append("historical_unconfirmed")
                continue
            await self.repo.set_attempt_reply(mid, reply.get("texto", ""))
            self._apply_historical_answer(row, reply.get("texto", ""))

    def _apply_historical_answer(self, row, text: str) -> None:
        """Honour the operator: a new value replaces the reading, a plain "no" removes it."""
        answer = read_reply(text, self.snapshot, "question_value")
        if answer.value is not None:
            row.value = answer.value
            if answer.unit:
                row.unit = answer.unit
            row.flags.append("value_corrected")
            return
        if is_correction(text):
            row.value = None
            row.unit = None
            row.flags.append("denied_by_operator")

    # ---------------------------------------------------------------- outcomes

    async def _handle_safety(self, note: NotaRecorrida, draft: PartDraft, deadline: float) -> None:
        event = note_events(draft, self.snapshot, note.ts)[0]
        tag = draft.rows[0].tag if draft.rows else None
        if draft.safety == "S1" and draft.photos and tag:
            self.structural_damage.add(tag)
        early = self.alerted.get(note.id)
        if early is None:
            # The operator-facing notice goes first: it is the emergency action. The
            # durable event follows immediately; neither waits for photo downloads.
            self.alerted[note.id] = event
            mid = f"ALERTA-{note.id}"
            await self._send_tablet(mid, note, emergency_text(draft.safety or "S1", tag),
                                    rows=draft.rows, waits=False, kind="notice")
            await self.publisher.publish("sistema/eventos", event, sync=True)
            await self.repo.insert_event(event, {"rows": [row.model_dump() for row in draft.rows],
                                                 "photos": [row.photo for row in draft.rows if row.photo],
                                                 "note_photos": list(draft.photos),
                                                 "safety": draft.safety})
        else:
            # The alert was already published from a partial transcript. Keep its id
            # (idempotency) and refresh the stored context with the full note.
            event["id"] = early["id"]
            await self.repo.update_event_context(early["id"], {
                "rows": [row.model_dump() for row in draft.rows],
                "photos": [row.photo for row in draft.rows if row.photo],
                "note_photos": list(draft.photos), "safety": draft.safety})
        await self._within(note, "photo download", self._download_photos(note, draft), deadline)
        await self.repo.save_part(note.id, "confirmed", [row.model_dump() for row in draft.rows],
                                  draft.safety, 0)
        await self.repo.set_note_status(note.id, "confirmed")

    async def _early_alert(self, note: NotaRecorrida, partial: str) -> None:
        """Raise the safety alert from the first ASR segment that names a trigger.

        The alert and the tablet notice must leave the plant in under 30 real seconds. A
        long note can take that long to transcribe, so the safety detector runs on the
        partial text while the rest of the audio is still being processed.
        """
        if note.id in self.alerted or note.id in self.closed:
            return
        code, _evidence = detect_safety(partial)
        if not code:
            return
        draft = parse_transcript(partial, self.snapshot, note_id=note.id, ts=note.ts, photos=note.fotos)
        event = note_events(draft, self.snapshot, note.ts)[0]
        tag = draft.rows[0].tag if draft.rows else None
        self.alerted[note.id] = event
        log.warning("note %s raised safety alert %s from a partial transcript", note.id, code)
        await self._send_tablet(f"ALERTA-{note.id}", note, emergency_text(code, tag),
                                rows=draft.rows, waits=False, kind="notice")
        await self.publisher.publish("sistema/eventos", event, sync=True)
        await self.repo.insert_event(event, {"rows": [row.model_dump() for row in draft.rows],
                                             "photos": [row.photo for row in draft.rows if row.photo],
                                             "note_photos": list(draft.photos),
                                             "safety": code})
        log.warning("note %s raised safety alert %s for %s", note.id, draft.safety, tag)

    async def _handle_unreadable(self, note: NotaRecorrida) -> None:
        """Audio could not be downloaded or transcribed: never report "sin novedad"."""
        await self._send_tablet(f"TAB-{note.id}-retry", note,
                                "No pudimos procesar el audio de esta nota. No se registra como sin novedad; "
                                "reintentá la grabación y avisá al supervisor.", waits=False, kind="notice")
        await self.repo.save_part(note.id, "unreadable", [], None, 0)
        await self.repo.set_note_status(note.id, "failed")
        log.error("note %s could not be transcribed; stored as unreadable", note.id)

    async def _handle_empty(self, note: NotaRecorrida, draft: PartDraft) -> None:
        if note.id.startswith("VIVO-"):
            await self._send_tablet(f"TAB-{note.id}-ok", note,
                                    "Nota recibida. No hay datos para el parte.", waits=False, kind="notice")
        else:
            event = note_events(draft, self.snapshot, note.ts)[0]
            await self.publisher.publish("sistema/eventos", event, sync=True)
            await self.repo.insert_event(event, {"transcript": draft.transcript})
            await self._send_ack(note)
        await self.repo.save_part(note.id, "confirmed", [], None, 0)
        await self.repo.set_note_status(note.id, "confirmed")

    async def _finalize(self, note: NotaRecorrida, draft: PartDraft, status: str) -> None:
        await self.repo.save_part(note.id, status, [row.model_dump() for row in draft.rows],
                                  draft.safety, len(draft.rows))
        await self.repo.set_note_status(note.id, "confirmed")
        photos = [row.photo for row in draft.rows if row.photo]
        # The plant's own pump state disambiguates a bare "parada" (the reserve pump is
        # normally stopped). Same data, same decision.
        plant_state, _ok = await self._plant_state()
        for event in note_events(draft, self.snapshot, note.ts, plant_state.pumps):
            await self.publisher.publish("sistema/eventos", event, sync=True)
            rows = draft.rows_for(event["equipo"] or "")
            context = {
                "rows": [row.model_dump() for row in rows],
                "photos": photos,
                "note_photos": list(draft.photos),
                "transcript": draft.transcript,
                "status": status,
            }
            await self.repo.insert_event(event, context)
            if event["tipo"] == ESCALADO:
                await self.maybe_order(event, rows=rows, sensor_variable=None)
                # The evidence (recent sensor trend, order history) is fetched after the
                # event is published and stored, so a slow historian never delays the
                # note or the MQTT dispatch loop.
                self._spawn(self._enrich_event(event, rows, photos, context))
        await self._send_ack(note)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    async def _enrich_event(self, event: dict, rows: list[ExtractedRow], photos: list[str],
                            context: dict) -> None:
        if self.plant is None:
            return
        try:
            evidence = await build_event_context(event, rows, photos, self.plant, self.search, self.snapshot,
                                                 self.materials)
        except Exception:  # noqa: BLE001
            log.warning("event context for %s could not be built", event["id"], exc_info=True)
            return
        for key in ("sensor_trend", "order_history", "available_parts"):
            if evidence.get(key):
                context[key] = evidence[key]
        try:
            await self.repo.update_event_context(event["id"], context)
        except Exception:  # noqa: BLE001
            log.warning("event context for %s could not be stored", event["id"], exc_info=True)

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
        context: dict = {"sensor_variable": variable}
        await self.repo.insert_event(event, context)
        await self.maybe_order(event, rows=[], sensor_variable=variable)
        self._spawn(self._enrich_event(event, [], [], context))

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
