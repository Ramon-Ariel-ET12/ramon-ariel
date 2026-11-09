"""Application assembly: MQTT ingestion, note workflow, heartbeat, sync and UI."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import Settings, get_settings
from app.domain.materials import load_materials
from app.domain.plant import load_snapshot_file
from app.domain.sensors import SensorDetector
from app.heartbeat import heartbeat_payload
from app.integrations.mqtt import MqttTransport
from app.integrations.plant_api import PlantClient
from app.integrations.sync import CloudSync
from app.llm.local import LocalLLM
from app.logging_setup import configure_logging
from app.persistence.db import Database
from app.persistence.repository import Repository
from app.processing.asr import Transcriber
from app.processing.workflow import NoteWorkflow
from app.publisher import Publisher

log = logging.getLogger(__name__)


@dataclass
class Context:
    settings: Settings
    db: Database
    repo: Repository
    plant: PlantClient
    mqtt: MqttTransport
    publisher: Publisher
    materials: object
    snapshot: object
    transcriber: Transcriber
    workflow: NoteWorkflow
    detector: SensorDetector
    link_up: bool = True
    ready: bool = False
    tasks: list[asyncio.Task] = field(default_factory=list)
    digests: dict[tuple[str, str], datetime] = field(default_factory=dict)


ctx: Context | None = None


async def _load_snapshot(plant: PlantClient, settings: Settings):
    try:
        from app.domain.plant import snapshot_from_definition

        return snapshot_from_definition(await plant.definition())
    except Exception as exc:  # noqa: BLE001
        log.warning("using bundled plant definition: %s", exc)
        return load_snapshot_file(settings.plant_snapshot_path)


async def _resume_orders(ctx_: Context) -> None:
    for order in await ctx_.repo.open_orders():
        payload = dict(order["payload"])
        if payload.get("estado") == "Borrador":
            continue
        await ctx_.publisher.publish("sistema/ordenes", payload, sync=False)
        log.info("resumed order %s in state %s", order["id"], payload.get("estado"))


async def _heartbeat_loop(ctx_: Context) -> None:
    while True:
        try:
            link = await ctx_.plant.link_state()
            ctx_.link_up = link
            payload = await heartbeat_payload(ctx_.settings.system_name, link,
                                              await ctx_.repo.pending_count())
            await ctx_.publisher.publish("sistema/estado", payload, sync=False)
        except Exception:  # noqa: BLE001
            log.exception("heartbeat failed")
        await asyncio.sleep(ctx_.settings.heartbeat_seconds)


async def _link_loop(ctx_: Context) -> None:
    """Publish a degraded heartbeat as soon as the link is down, and while it stays down."""
    while True:
        try:
            link = await ctx_.plant.link_state()
            changed = link != ctx_.link_up
            ctx_.link_up = link
            if changed or not link:
                await _heartbeat_once(ctx_)
        except Exception:  # noqa: BLE001
            log.warning("link monitor failed", exc_info=True)
        await asyncio.sleep(2.0)


async def _sync_loop(ctx_: Context) -> None:
    sync = CloudSync(ctx_.repo, ctx_.settings.cloud_sync_url, ctx_.settings.sync_batch_size)
    while True:
        await asyncio.sleep(ctx_.settings.sync_poll_seconds)
        synced = await sync.once()
        if synced:
            log.info("synced %s items to cloud replica", synced)


async def _sensor_digest(ctx_: Context, payload: dict) -> None:
    if ctx_.link_up:
        return
    key = (payload.get("tag", ""), payload.get("variable", ""))
    stamp = datetime.fromisoformat(payload["ts"])
    last = ctx_.digests.get(key)
    if last and stamp - last < timedelta(minutes=15):
        return
    ctx_.digests[key] = stamp
    await ctx_.repo.enqueue("sensor/digest", payload)


async def _dispatch_loop(ctx_: Context) -> None:
    async for topic, payload in ctx_.mqtt.messages():
        try:
            if topic == "planta/recorridas":
                await ctx_.workflow.enqueue(payload)
            elif topic == "planta/respuestas":
                ctx_.workflow.on_reply(payload)
            elif topic.startswith("planta/sensores/"):
                tag = payload.get("tag")
                variable = payload.get("variable")
                if not tag or not variable:
                    continue
                stamp = datetime.fromisoformat(payload["ts"])
                event = ctx_.detector.feed(tag, variable, payload.get("valor"), stamp,
                                           payload.get("calidad", "buena"))
                if event:
                    await ctx_.workflow.handle_sensor_event(event, variable)
                await _sensor_digest(ctx_, payload)
            elif topic == "planta/cierres":
                await ctx_.workflow.handle_closure(payload)
            elif topic == "planta/energia":
                log.info("plant energy state: %s", payload.get("hay_energia"))
        except Exception:  # noqa: BLE001
            log.exception("failed to handle %s", topic)


async def _rag_loop(ctx_: Context) -> None:
    from app.rag.indexer import ensure_index

    for _ in range(3):
        try:
            count = await ensure_index(ctx_.repo, ctx_.plant, ctx_.settings)
            log.info("rag index ready with %s chunks", count)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("rag indexing failed: %s", exc)
            await asyncio.sleep(20)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ctx
    settings = get_settings()
    configure_logging(settings.log_level)
    db = Database(settings.database_url)
    await db.connect()
    repo = Repository(db)
    plant = PlantClient(settings.plant_url, link_control_url=settings.link_control_url)
    snapshot = await _load_snapshot(plant, settings)
    materials = load_materials(settings.materials_path)
    transcriber = Transcriber(settings.asr_model, threads=settings.asr_threads,
                              beam_size=settings.asr_beam_size)
    try:
        await asyncio.to_thread(transcriber.warmup)
    except Exception:  # noqa: BLE001
        log.exception("ASR warmup failed; notes will fail until the model is available")

    mqtt = MqttTransport(settings.mqtt_host, settings.mqtt_port)
    mqtt.start()
    if not await mqtt.wait_connected(30):
        log.error("mqtt not connected yet; continuing with reconnect")
    publisher = Publisher(mqtt, repo)
    llm = LocalLLM(settings.llm_model, enabled=settings.llm_enabled)
    workflow = NoteWorkflow(settings, repo, plant, publisher, snapshot, materials, transcriber, llm)
    detector = SensorDetector(snapshot)
    ctx = Context(settings, db, repo, plant, mqtt, publisher, materials, snapshot, transcriber,
                  workflow, detector)
    publisher.pending_hook = lambda: _heartbeat_once(ctx)
    await workflow.start()
    await _resume_orders(ctx)
    ctx.tasks = [
        asyncio.create_task(_dispatch_loop(ctx), name="mqtt-dispatch"),
        asyncio.create_task(_heartbeat_loop(ctx), name="heartbeat"),
        asyncio.create_task(_link_loop(ctx), name="link"),
        asyncio.create_task(_sync_loop(ctx), name="sync"),
    ]
    ctx.ready = True
    # The correction waits for this first heartbeat before releasing the plant clock.
    await _heartbeat_loop_once(ctx)
    ctx.tasks.append(asyncio.create_task(_rag_loop(ctx), name="rag"))
    app.state.ctx = ctx
    log.info("system ready as %s", settings.system_name)
    try:
        yield
    finally:
        for task in ctx.tasks:
            task.cancel()
        for task in ctx.tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await workflow.stop()
        mqtt.stop()
        await db.close()
        ctx = None


async def _heartbeat_once(ctx_: Context) -> None:
    ctx_.link_up = await ctx_.plant.link_state()
    payload = await heartbeat_payload(ctx_.settings.system_name, ctx_.link_up,
                                      await ctx_.repo.pending_count())
    await ctx_.publisher.publish("sistema/estado", payload, sync=False)


async def _heartbeat_loop_once(ctx_: Context) -> None:
    try:
        await _heartbeat_once(ctx_)
    except Exception:  # noqa: BLE001
        log.exception("initial heartbeat failed")


app = FastAPI(title="PIA-3 assistant", lifespan=lifespan)


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


@app.get("/health")
async def health():
    if ctx is None:
        return JSONResponse({"ready": False}, status_code=503)
    return {"ready": ctx.ready, "database": await ctx.db.health(), "link_up": ctx.link_up,
            "system": ctx.settings.system_name}


@app.get("/api/state")
async def state():
    if ctx is None:
        return JSONResponse({"ready": False}, status_code=503)
    return await ctx.repo.console_state()


@app.get("/", response_class=HTMLResponse)
async def index():
    if ctx is None:
        return HTMLResponse("<h1>PIA-3 assistant</h1><p>starting...</p>")
    data = await ctx.repo.console_state()
    rows = []
    for note in data["notes"]:
        rows.append(f"<tr><td>{_esc(note['id'])}</td><td>{_esc(note['ts'])}</td>"
                    f"<td>{_esc(note['status'])}</td><td>{_esc((note['transcript'] or '')[:120])}</td></tr>")
    events = [f"<li><b>{_esc(e['type'])}</b> {_esc(e['equipment'])} ({_esc(e['origin'])}) - {_esc(e['summary'])}</li>"
              for e in data["events"]]
    orders = [f"<li><b>{_esc(o['state'])}</b> {_esc(o['equipment'])} {_esc(o['tasks'])} "
              f"<small>{_esc((o['payload'] or {}).get('motivo') or '')}</small></li>" for o in data["orders"]]
    usage = data["usage"]
    body = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>PIA-3 · Central de mantenimiento</title>
<style>body{{font-family:system-ui;margin:2rem;color:#1b1b1b}}table{{border-collapse:collapse}}
td,th{{border-bottom:1px solid #ddd;padding:.35rem .6rem;text-align:left;vertical-align:top}}
.badge{{background:#0a7;color:#fff;padding:.1rem .5rem;border-radius:6px}}</style></head><body>
<h1>PIA-3 · Central de mantenimiento</h1>
<p><span class="badge">{_esc(ctx.settings.system_name)}</span>
enlace {'arriba' if ctx.link_up else 'caído'} · pendientes de sincronizar: {data['pending_sync']} ·
fragmentos RAG: {data['rag_chunks']}</p>
<p>LLM: {usage['calls']} llamadas · tokens entrada {usage['input']} · salida {usage['output']} · latencia {usage['latency']} ms</p>
<h2>Partes recientes</h2><table><tr><th>Nota</th><th>Hora</th><th>Estado</th><th>Transcripción</th></tr>{''.join(rows)}</table>
<h2>Eventos</h2><ul>{''.join(events)}</ul>
<h2>Órdenes</h2><ul>{''.join(orders)}</ul>
<p><a href="/api/state">JSON</a> · <a href="/health">salud</a></p></body></html>"""
    return HTMLResponse(body)


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.ui_port, log_config=None)


if __name__ == "__main__":
    main()
