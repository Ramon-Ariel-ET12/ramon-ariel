"""Idempotent repositories for notes, parts, events, orders, sync and RAG."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.persistence.db import Database

TERMINAL_ORDER_STATES = {"Rechazada", "Cerrada", "Certificada"}
OPEN_ORDER_STATES = {"Borrador", "PendienteAprobacion", "Aprobada", "Ejecutada", "Observada"}


def _vector(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- notes and parts

    async def create_note(self, note_id: str, ts: datetime, operator: str, walk_id: str,
                          audio_url: str | None, photos: list[str], live: bool) -> bool:
        row = await self.db.fetchrow(
            """INSERT INTO notes (id, ts, operator, walk_id, audio_url, photos, live)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING
               RETURNING id""",
            (note_id, ts, operator, walk_id, audio_url, Jsonb(photos), live),
        )
        return row is not None

    async def get_note(self, note_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM notes WHERE id = %s", (note_id,))

    async def next_note_to_process(self) -> dict | None:
        return await self.db.fetchrow(
            "SELECT * FROM notes WHERE status = 'received' ORDER BY ts, received_at LIMIT 1"
        )

    async def reset_stuck_notes(self) -> None:
        await self.db.execute("UPDATE notes SET status = 'received' WHERE status = 'processing'")

    async def pending_notes(self) -> list[dict]:
        return await self.db.fetch(
            """SELECT n.* FROM notes n
               WHERE n.status = 'received'
                 AND NOT EXISTS (SELECT 1 FROM parts p WHERE p.note_id = n.id
                                 AND p.status IN ('confirmed', 'confirmed_with_differences'))
               ORDER BY n.ts, n.received_at"""
        )

    async def set_note_status(self, note_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE notes SET status = %s, updated_at = now() WHERE id = %s", (status, note_id)
        )

    async def set_transcript(self, note_id: str, transcript: str) -> None:
        await self.db.execute("UPDATE notes SET transcript = %s, updated_at = now() WHERE id = %s",
                              (transcript, note_id))

    async def save_part(self, note_id: str, status: str, rows: list[dict], safety: str | None,
                        attempts: int) -> None:
        await self.db.execute(
            """INSERT INTO parts (note_id, status, rows, safety, attempts)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (note_id) DO UPDATE SET status = EXCLUDED.status, rows = EXCLUDED.rows,
                 safety = EXCLUDED.safety, attempts = EXCLUDED.attempts, updated_at = now()""",
            (note_id, status, Jsonb(rows), safety, attempts),
        )

    async def get_part(self, note_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM parts WHERE note_id = %s", (note_id,))

    async def add_attempt(self, attempt_id: str, note_id: str, message_id: str | None, kind: str,
                          rows: list[dict]) -> None:
        await self.db.execute(
            """INSERT INTO attempts (id, note_id, message_id, kind, rows)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (attempt_id, note_id, message_id, kind, Jsonb(rows)),
        )

    async def set_attempt_reply(self, message_id: str, reply: str) -> None:
        await self.db.execute("UPDATE attempts SET reply = %s WHERE message_id = %s", (reply, message_id))

    # ---------------------------------------------------------------- tablet

    async def add_tablet_message(self, message_id: str, note_id: str, ts: datetime, kind: str,
                                 payload: dict) -> bool:
        row = await self.db.fetchrow(
            """INSERT INTO tablet_messages (id, note_id, ts, kind, payload)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
            (message_id, note_id, ts, kind, Jsonb(payload)),
        )
        return row is not None

    async def add_reply(self, reply_id: str, message_id: str, note_id: str, text: str,
                        ts: datetime | None) -> None:
        await self.db.execute(
            """INSERT INTO replies (id, message_id, note_id, text, ts)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (reply_id, message_id, note_id, text, ts),
        )

    async def note_ids_for_message(self, message_id: str) -> list[str]:
        row = await self.db.fetchrow("SELECT note_id FROM tablet_messages WHERE id = %s", (message_id,))
        return [row["note_id"]] if row and row["note_id"] else []

    # ---------------------------------------------------------------- events

    async def insert_event(self, event: dict, context: dict | None = None) -> bool:
        row = await self.db.fetchrow(
            """INSERT INTO events (id, ts, type, equipment, origin, part_id, note_ids, summary, context)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
            (
                event["id"], event["ts"], event["tipo"], event.get("equipo"), event["origen"],
                event.get("parte_id"), Jsonb(event.get("nota_ids", [])), event["resumen"],
                Jsonb(context) if context is not None else None,
            ),
        )
        return row is not None

    async def events_for_note(self, note_id: str) -> list[dict]:
        return await self.db.fetch("SELECT * FROM events WHERE note_ids @> %s::jsonb",
                                   (Jsonb([note_id]),))

    async def update_event_context(self, event_id: str, context: dict) -> None:
        await self.db.execute("UPDATE events SET context = %s WHERE id = %s", (Jsonb(context), event_id))

    # ---------------------------------------------------------------- orders

    async def upsert_order(self, order_id: str, equipment: str, tasks: list[str], state: str,
                           payload: dict) -> None:
        await self.db.execute(
            """INSERT INTO orders (id, equipment, tasks, state, payload)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state, payload = EXCLUDED.payload,
                 tasks = EXCLUDED.tasks, updated_at = now()""",
            (order_id, equipment, Jsonb(tasks), state, Jsonb(payload)),
        )

    async def open_order(self, equipment: str, tasks: list[str]) -> dict | None:
        wanted = set(tasks)
        for row in await self.db.fetch(
            "SELECT id, equipment, tasks, state FROM orders WHERE state = ANY(%s) AND equipment = %s",
            (list(OPEN_ORDER_STATES), equipment),
        ):
            if set(row["tasks"] or []) == wanted:
                return row
        return None

    async def open_orders(self) -> list[dict]:
        return await self.db.fetch(
            "SELECT id, equipment, tasks, state, payload FROM orders WHERE state = ANY(%s) ORDER BY created_at",
            (list(OPEN_ORDER_STATES),),
        )

    async def orders_by_id(self, order_id: str) -> dict | None:
        return await self.db.fetchrow("SELECT * FROM orders WHERE id = %s", (order_id,))

    async def record_decision(self, order_id: str, decision: str, reasons: list[str],
                              plant_state: dict) -> None:
        await self.db.execute(
            "INSERT INTO decisions (order_id, decision, reasons, plant_state) VALUES (%s, %s, %s, %s)",
            (order_id, decision, Jsonb(reasons), Jsonb(plant_state)),
        )

    # ---------------------------------------------------------------- sensors

    async def sensor_event_id(self, tag: str, variable: str) -> str | None:
        row = await self.db.fetchrow(
            "SELECT event_id FROM sensor_state WHERE tag = %s AND variable = %s AND active",
            (tag, variable),
        )
        return row["event_id"] if row else None

    async def sensor_episodes(self) -> list[dict]:
        return await self.db.fetch(
            "SELECT tag, variable, active, since, event_id FROM sensor_state WHERE active"
        )

    async def set_sensor_event(self, tag: str, variable: str, event_id: str | None, since: datetime | None) -> None:
        await self.db.execute(
            """INSERT INTO sensor_state (tag, variable, active, since, event_id)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (tag, variable) DO UPDATE SET active = EXCLUDED.active,
                 since = EXCLUDED.since, event_id = EXCLUDED.event_id, updated_at = now()""",
            (tag, variable, event_id is not None, since, event_id),
        )

    # ---------------------------------------------------------------- sync queue

    async def enqueue(self, topic: str, payload: dict) -> None:
        await self.db.execute("INSERT INTO sync_queue (topic, payload) VALUES (%s, %s)",
                              (topic, Jsonb(payload)))

    async def pending_sync(self, limit: int = 50) -> list[dict]:
        return await self.db.fetch(
            "SELECT id, topic, payload, attempts FROM sync_queue WHERE acked = false ORDER BY id LIMIT %s",
            (limit,),
        )

    async def pending_count(self) -> int:
        row = await self.db.fetchrow("SELECT count(*) AS n FROM sync_queue WHERE acked = false")
        return int(row["n"]) if row else 0

    async def ack_sync(self, ids: list[int]) -> None:
        if not ids:
            return
        await self.db.execute("UPDATE sync_queue SET acked = true WHERE id = ANY(%s)", (ids,))

    async def bump_sync(self, ids: list[int]) -> None:
        if not ids:
            return
        await self.db.execute("UPDATE sync_queue SET attempts = attempts + 1 WHERE id = ANY(%s)", (ids,))

    # ---------------------------------------------------------------- usage

    async def record_usage(self, model: str, task: str, input_tokens: int, output_tokens: int,
                           latency_ms: int, cost_usd: float = 0.0) -> None:
        await self.db.execute(
            """INSERT INTO usage_log (model, task, input_tokens, output_tokens, latency_ms, cost_usd)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (model, task, input_tokens, output_tokens, latency_ms, cost_usd),
        )

    async def usage_summary(self) -> dict:
        row = await self.db.fetchrow(
            """SELECT coalesce(sum(input_tokens),0) AS input, coalesce(sum(output_tokens),0) AS output,
                      coalesce(sum(latency_ms),0) AS latency, count(*) AS calls FROM usage_log"""
        )
        return row or {"input": 0, "output": 0, "latency": 0, "calls": 0}

    # ---------------------------------------------------------------- RAG

    async def rag_count(self) -> int:
        row = await self.db.fetchrow("SELECT count(*) AS n FROM rag_chunks")
        return int(row["n"]) if row else 0

    async def rag_upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        async with self.db.pool.connection() as conn:  # type: ignore[union-attr]
            async with conn.cursor() as cur:
                for chunk, embedding in zip(chunks, embeddings, strict=False):
                    await cur.execute(
                        """INSERT INTO rag_chunks
                             (id, doc, number, title, section_key, page, current, manufacturer, equipment,
                              citation, text, content_hash, embedding, tsv)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector,
                                   to_tsvector('spanish', %s))
                           ON CONFLICT (id) DO UPDATE SET
                             text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                             embedding = EXCLUDED.embedding, tsv = EXCLUDED.tsv,
                             current = EXCLUDED.current, equipment = EXCLUDED.equipment""",
                        (
                            chunk["id"], chunk["doc"], chunk.get("number", ""), chunk.get("title", ""),
                            chunk.get("section_key", ""), chunk.get("page"), chunk.get("current", True),
                            chunk.get("manufacturer", ""), Jsonb(chunk.get("equipment", [])),
                            chunk["citation"], chunk["text"], chunk["content_hash"], _vector(embedding),
                            chunk["text"],
                        ),
                    )

    async def rag_lexical(self, query: str, limit: int = 40) -> list[dict]:
        return await self.db.fetch(
            """SELECT id, citation, doc, title, section_key, current, manufacturer, equipment, text,
                      ts_rank_cd(tsv, websearch_to_tsquery('spanish', %s)) AS score
               FROM rag_chunks
               WHERE current IS NOT FALSE AND tsv @@ websearch_to_tsquery('spanish', %s)
               ORDER BY score DESC LIMIT %s""",
            (query, query, limit),
        )

    async def rag_vector(self, embedding: list[float], limit: int = 40) -> list[dict]:
        return await self.db.fetch(
            """SELECT id, citation, doc, title, section_key, current, manufacturer, equipment, text,
                      1 - (embedding <=> %s::vector) AS score
               FROM rag_chunks WHERE embedding IS NOT NULL AND current IS NOT FALSE
               ORDER BY embedding <=> %s::vector LIMIT %s""",
            (_vector(embedding), _vector(embedding), limit),
        )

    async def rag_all(self) -> list[dict]:
        return await self.db.fetch("SELECT id, citation, doc, title, section_key, current, text FROM rag_chunks")

    async def rag_refresh_metadata(self, chunks: list[dict]) -> None:
        """Update derived metadata in place, without recomputing embeddings."""
        if not chunks:
            return
        async with self.db.pool.connection() as conn:  # type: ignore[union-attr]
            async with conn.cursor() as cur:
                for chunk in chunks:
                    await cur.execute(
                        """UPDATE rag_chunks SET
                             equipment = %s::jsonb,
                             manufacturer = %s,
                             section_key = %s,
                             current = %s
                           WHERE id = %s""",
                        (Jsonb(chunk.get("equipment", [])),
                         chunk.get("manufacturer", ""),
                         chunk.get("section_key", ""),
                         chunk.get("current", True), chunk["id"]),
                    )

    # ---------------------------------------------------------------- console

    async def console_state(self) -> dict[str, Any]:
        notes = await self.db.fetch("SELECT id, ts, status, transcript FROM notes ORDER BY ts DESC LIMIT 10")
        events = await self.db.fetch("SELECT id, ts, type, equipment, origin, summary, context "
                                     "FROM events ORDER BY created_at DESC LIMIT 15")
        orders = await self.db.fetch("SELECT id, equipment, state, tasks, payload FROM orders ORDER BY updated_at DESC LIMIT 15")
        pending = await self.pending_count()
        usage = await self.usage_summary()
        chunks = await self.rag_count()
        return {"notes": notes, "events": events, "orders": orders, "pending_sync": pending,
                "usage": usage, "rag_chunks": chunks}

    @staticmethod
    def loads(value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value
