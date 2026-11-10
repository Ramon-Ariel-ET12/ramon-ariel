"""Human-like end-to-end probe for the plant assistant.

Drives the *official* simulator the way a person does: it asks the plant to record a
voice note with a given text (the simulator synthesises the audio and publishes a real
``NotaRecorrida``), then watches the real MQTT bus and the assistant console, exactly
like an operator standing in front of the tablet.

Nothing is mocked: audio download, local ASR, parsing, tablet messages and the virtual
operator's answers are the production path.

    uv run python scripts/e2e_probe.py --texto "La uno está en ciento doce kilos de descarga." \
        --items '[{"tag":"B-101","variable":"presion_descarga_local","valor":112,"unidad":"kg/cm2"}]'

    uv run python scripts/e2e_probe.py --solo-escuchar --segundos 60

``--reiniciar`` leaves a clean bench first: it empties the assistant tables and moves the
plant to ``martes-tranquilo`` at ×1. Without it, re-emitting a note reuses the simulator's
note id (NOTA-00001, NOTA-00002, …), the assistant correctly deduplicates it and nothing
is shown on the tablet — the probe now says so instead of looking like a silent failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any

import httpx

PLANT = "http://localhost:8100"
APP = "http://localhost:8200"
BROKER = ("localhost", 1883)
TABLES = ("notes, parts, attempts, tablet_messages, replies, events, orders, decisions, "
          "sensor_state, sync_queue, usage_log")


def _docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True)


def reset_bench() -> None:
    """Clean state for one probe: empty assistant tables and a known scenario."""
    postgres = ["exec", "-T", "db", "psql", "-U", "pia", "-d", "pia", "-c",
                f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE;"]
    cleaned = _docker(*postgres)
    print("estado del asistente vaciado" if cleaned.returncode == 0
          else f"aviso: no se pudo vaciar la base ({cleaned.stderr.strip()[:120]})")
    httpx.post(f"{PLANT}/api/control/escenario/martes-tranquilo", timeout=20).raise_for_status()
    httpx.post(f"{PLANT}/api/control/velocidad", json={"velocidad": 1}, timeout=20).raise_for_status()
    httpx.post(f"{PLANT}/api/control/auto-lento", json={"activo": False}, timeout=20).raise_for_status()
    estado = httpx.get(f"{PLANT}/api/estado", timeout=10).json()
    if estado.get("pausado"):
        httpx.post(f"{PLANT}/api/control/pausa", timeout=10)
    print(f"planta en {estado.get('escenario')} ×{estado.get('velocidad')}")


def app_note_ids() -> set[str]:
    try:
        return {nota["id"] for nota in httpx.get(f"{APP}/api/state", timeout=10).json()["notes"]}
    except Exception:  # noqa: BLE001
        return set()


def _print_truncated(value: Any, limit: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "…"


def emit_note(texto: str, items: list[dict], fotos: list[str], seguridad: str | None) -> dict:
    body = {"accion": "nota", "params": {"texto": texto, "items": items, "fotos": fotos,
                                         "seguridad": seguridad}}
    response = httpx.post(f"{PLANT}/api/control/accion", json=body, timeout=20)
    response.raise_for_status()
    return response.json()


def app_state() -> dict:
    return httpx.get(f"{APP}/api/state", timeout=10).json()


def watch(segundos: float) -> None:
    import paho.mqtt.client as mqtt

    seen: list[tuple[float, str, dict]] = []
    started = time.time()

    def on_connect(client, _u, _f, _rc, _p=None):
        client.subscribe("sistema/#", qos=1)
        client.subscribe("planta/recorridas", qos=1)

    def on_message(_c, _u, message):
        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError:
            payload = {"raw": message.payload[:120].decode("utf-8", "replace")}
        seen.append((time.time() - started, message.topic, payload))
        if message.topic == "sistema/tablet":
            pantalla = payload.get("pantalla") or {}
            filas = pantalla.get("filas") or []
            print(f"[{time.time() - started:6.1f}s] TABLET {payload.get('id')} "
                  f"espera={payload.get('espera_respuesta')} filas={len(filas)} "
                  f"opciones={pantalla.get('opciones') or []}")
            print(f"          texto: {payload.get('texto')}")
            for fila in filas:
                print(f"          fila: {_print_truncated(fila, 200)}")
        elif message.topic == "sistema/eventos":
            print(f"[{time.time() - started:6.1f}s] EVENTO {payload.get('tipo')} "
                  f"equipo={payload.get('equipo')} origen={payload.get('origen')} "
                  f"nota_ids={payload.get('nota_ids')}")
            print(f"          {payload.get('resumen')}")
        elif message.topic == "sistema/ordenes":
            print(f"[{time.time() - started:6.1f}s] ORDEN {payload.get('estado')} "
                  f"equipo={payload.get('equipo')} tareas={payload.get('tareas')} "
                  f"motivo={payload.get('motivo')}")
        elif message.topic == "sistema/estado":
            print(f"[{time.time() - started:6.1f}s] LATIDO enlace_ok={payload.get('enlace_ok')} "
                  f"pendientes={payload.get('pendientes_sincronizar')}")
        elif message.topic == "planta/recorridas":
            print(f"[{time.time() - started:6.1f}s] NOTA {payload.get('id')} ts={payload.get('ts')} "
                  f"fotos={len(payload.get('fotos') or [])}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"e2e-probe-{int(started)}")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(*BROKER, keepalive=30)
    client.loop_start()
    try:
        time.sleep(segundos)
    finally:
        client.loop_stop()
        client.disconnect()
    print(f"\n== mensajes observados: {len(seen)}")
    print(f"== asuntos: {sorted({topic for _, topic, _ in seen})}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--texto", help="texto que dicta el operador (nota de voz real)")
    parser.add_argument("--items", default="[]", help="parte esperado (verdad de campo) en JSON")
    parser.add_argument("--fotos", nargs="*", default=[], help="rutas de foto de la planta")
    parser.add_argument("--seguridad", default=None, help="S1..S4 si la nota es insegura")
    parser.add_argument("--segundos", type=float, default=45, help="cuánto escuchar después de emitir")
    parser.add_argument("--reiniciar", action="store_true",
                        help="vaciar el estado del asistente y dejar la planta en martes-tranquilo ×1")
    parser.add_argument("--solo-escuchar", action="store_true")
    args = parser.parse_args()

    if args.reiniciar:
        reset_bench()

    if not args.solo_escuchar:
        if not args.texto:
            parser.error("--texto es obligatorio salvo con --solo-escuchar")
        items = json.loads(args.items)
        antes = app_note_ids()
        print(f"nota: {args.texto}")
        print(f"verdad: {json.dumps(items, ensure_ascii=False)}")
        emitido = emit_note(args.texto, items, args.fotos, args.seguridad)
        print(json.dumps(emitido, ensure_ascii=False))
        print()
        nuevo = emitido.get("id")
        if nuevo and nuevo in antes:
            print(f"ERROR: la nota {nuevo} ya existía en el asistente y se descarta por idempotencia.\n"
                  "       volvé a correr con --reiniciar (o vaciá la base) para observar el flujo.")
            return 3
    watch(args.segundos)
    try:
        state = app_state()
        print("\n== estado del asistente")
        print(json.dumps({key: state[key] for key in ("pending_sync", "rag_chunks", "usage")},
                         ensure_ascii=False))
        print("notas:", [(n["id"], n["status"]) for n in state["notes"][:4]])
        print("eventos:", [(e["type"], e["equipment"]) for e in state["events"][:6]])
        print("órdenes:", [(o["state"], o["equipment"], o["tasks"]) for o in state["orders"][:6]])
    except Exception as exc:  # noqa: BLE001
        print(f"(sin estado del asistente: {exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
