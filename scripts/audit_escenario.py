"""Independent verification of one saved correction scenario.

Reads the JSON the plant saves for a scenario (``/api/correccion``) and recomputes the
facts the delivery asks for from the raw MQTT register and the field truth. It is a
second opinion, not a copy of the official scoring code.

    uv run python scripts/audit_escenario.py <escenario>.json [--planta datos/planta.yaml]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

A_KG = {"kg/cm2": 1.0, "psi": 1 / 14.2233, "bar": 1 / 0.980665}
PRESSURE = set(A_KG)
NORMAL = {"parada, en reserva", "parada por mantenimiento"}
LIMITS = {"presion_descarga_local": "presion_descarga", "presion_diferencial": "presion_diferencial"}


def _kg(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    return value * A_KG[unit] if unit in A_KG else value


def _close(shown: float | None, unit: str | None, expected: float | None, expected_unit: str | None) -> bool:
    if shown is None or expected is None:
        return shown is expected
    if unit in PRESSURE and expected_unit in PRESSURE:
        shown, expected = _kg(shown, unit), _kg(expected, expected_unit)
    elif unit and expected_unit and unit != expected_unit:
        return False
    assert shown is not None and expected is not None
    return abs(shown - expected) <= max(0.6, abs(expected) * 0.02)


def _sim(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archivo", type=Path)
    parser.add_argument("--planta", type=Path, default=Path("datos/planta.yaml"))
    args = parser.parse_args()

    datos = json.loads(args.archivo.read_text(encoding="utf-8"))
    verdad = datos.get("verdad") or []
    notas = [v for v in verdad if "recorrida_id" in v and v.get("tipo") != "vivo"]
    dialogos = [v for v in verdad if v.get("tipo") == "dialogo"]
    registro = datos.get("registro") or []

    import yaml

    planta = yaml.safe_load(args.planta.read_text(encoding="utf-8"))
    limites = {f"{s['tag']}|{s['variable']}": s for s in planta.get("sensores", [])}

    tablet: dict[str, list[dict]] = defaultdict(list)
    eventos: dict[str, list[dict]] = defaultdict(list)
    alertas: list[dict] = []
    latidos: list[dict] = []
    invalidos: list[dict] = []
    ordenes: dict[str, list[dict]] = defaultdict(list)
    for item in registro:
        topico, payload = item["topico"], item["payload"]
        if not item.get("valido"):
            invalidos.append(item)
        if topico == "sistema/tablet":
            for nota in payload.get("nota_ids") or []:
                tablet[nota].append(item)
        elif topico == "sistema/eventos":
            for nota in payload.get("nota_ids") or []:
                eventos[nota].append(payload)
            if payload.get("tipo") == "AlertaSeguridad":
                alertas.append(item)
        elif topico == "sistema/estado":
            latidos.append(item)
        elif topico == "sistema/ordenes":
            ordenes[payload["id"]].append(item)

    print(f"== escenario: {datos.get('escenario')} · notas del operador: {len(notas)} · "
          f"mensajes publicados: {len(registro)} · inválidos: {len(invalidos)}")

    def mensajes(nota_id: str) -> list[dict]:
        vistos, salida = set(), []
        for item in tablet.get(nota_id, []):
            if item["payload"]["id"] not in vistos:
                vistos.add(item["payload"]["id"])
                salida.append(item)
        return salida

    def preguntas(nota_id: str) -> list[dict]:
        return [m for m in mensajes(nota_id)
                if m["payload"].get("espera_respuesta", True)
                and (not (m["payload"].get("pantalla") or {}).get("filas")
                     or (m["payload"].get("pantalla") or {}).get("opciones"))]

    borradores = [d for d in dialogos if d.get("filas_mostradas", 0) > 0]
    con_borrador = {n["nota_id"]: True for n in notas
                    if any((m["payload"].get("pantalla") or {}).get("filas") for m in mensajes(n["nota_id"]))}
    al_primero: set[str] = set()
    visto: set[str] = set()
    for dialogo in borradores:
        for nota_id in dialogo.get("nota_ids") or []:
            if nota_id in visto:
                continue
            visto.add(nota_id)
            if dialogo.get("confirmo"):
                al_primero.add(nota_id)
    ultimo: dict[str, bool] = {}
    for dialogo in dialogos:
        if dialogo.get("filas_mostradas", 0) > 0:
            for nota_id in dialogo.get("nota_ids") or []:
                ultimo[nota_id] = bool(dialogo.get("confirmo"))

    campos_ok = campos_total = 0
    incompletas: list[str] = []
    for nota in notas:
        nota_id = nota["nota_id"]
        con_filas = [m for m in mensajes(nota_id) if (m["payload"].get("pantalla") or {}).get("filas")]
        filas = (con_filas[-1]["payload"]["pantalla"]["filas"] if con_filas else [])
        usados: set[int] = set()
        for esperado in nota.get("items") or []:
            if esperado.get("valor") is None:
                continue
            campos_total += 1
            for indice, fila in enumerate(filas):
                if indice in usados or fila.get("tag") != esperado["tag"]:
                    continue
                if _close(fila.get("valor"), fila.get("unidad"), esperado.get("valor"), esperado.get("unidad")):
                    usados.add(indice)
                    campos_ok += 1
                    break
        faltan = sorted({i["tag"] for i in (nota.get("items") or []) if i.get("valor") is not None}
                        - {f.get("tag") for f in filas})
        if faltan:
            incompletas.append(f"  {nota_id}: {faltan} · {nota.get('texto')[:100]}")

    print(f"\nA1 notas con borrador con filas: {len(con_borrador)}/{len(notas)}")
    print(f"A2 confirmadas en el primer borrador: {len(al_primero)}/{len(notas)}")
    print(f"A3 confirmadas en el último borrador: {sum(1 for n in notas if ultimo.get(n['nota_id']))}/{len(notas)}")
    if campos_total:
        print(f"A3b aciertos por campo (TAG+valor+unidad): {campos_ok}/{campos_total} "
              f"= {100 * campos_ok / campos_total:.1f}%")
    ambiguas = [n for n in notas if n.get("ambiguedades")]
    claras = [n for n in notas if not n.get("ambiguedades") and not n.get("seguridad")]
    print(f"A4a ambiguas con pregunta: {sum(1 for n in ambiguas if preguntas(n['nota_id']))}/{len(ambiguas)}")
    print(f"A4b claras sin pregunta: {sum(1 for n in claras if not preguntas(n['nota_id']))}/{len(claras)}")
    if incompletas:
        print("  notas con equipos faltantes en el borrador final:")
        print("\n".join(incompletas))

    correctos = total = 0
    errores: list[str] = []
    for nota in notas:
        if nota.get("seguridad"):
            continue
        esperado_por_tag: dict[str, str] = {}
        for item in nota.get("items") or []:
            tag = item["tag"]
            observacion = _sim(item.get("observacion"))
            anomalo = bool(observacion) and observacion not in NORMAL
            limite = limites.get(f"{tag}|{LIMITS.get(item.get('variable'), '')}")
            if limite and item.get("valor") is not None and item.get("unidad") in A_KG:
                valor_kg = _kg(item["valor"], item["unidad"])
                if limite.get("alarma_alta") is not None and valor_kg >= limite["alarma_alta"]:
                    anomalo = True
                if limite.get("alarma_baja") is not None and valor_kg <= limite["alarma_baja"]:
                    anomalo = True
            esperado_por_tag[tag] = "Escalado" if anomalo else "SinNovedad"
        publicados = {e.get("equipo"): e["tipo"] for e in eventos.get(nota["nota_id"], [])}
        for tag, esperado in esperado_por_tag.items():
            total += 1
            obtenido = publicados.get(tag)
            if obtenido == esperado:
                correctos += 1
            else:
                errores.append(f"  {nota['nota_id']} {tag}: esperado {esperado}, publicado {obtenido}")
    print(f"\nB1 clasificación por equipo: {correctos}/{total}")
    if errores:
        print("\n".join(errores))

    print("\nB2 seguridad:")
    inseguras = [n for n in notas if n.get("seguridad")]
    for nota in inseguras:
        alerta = next((a for a in alertas if nota["nota_id"] in (a["payload"].get("nota_ids") or [])), None)
        msgs = sorted(mensajes(nota["nota_id"]), key=lambda m: m["ts_real"])
        lapso = (round((_when(alerta["ts_real"]) - _when(nota["ts_real"])).total_seconds(), 1)
                 if alerta else None)
        lapso_aviso = (round((_when(msgs[0]["ts_real"]) - _when(nota["ts_real"])).total_seconds(), 1)
                       if msgs else None)
        print(f"  {nota['nota_id']} {nota['seguridad']}: AlertaSeguridad={bool(alerta)} en {lapso}s reales · "
              f"aviso tablet={bool(msgs)} en {lapso_aviso}s · "
              f"espera_respuesta={(msgs[0]['payload'].get('espera_respuesta') if msgs else None)}")
    falsas = [a for a in alertas
              if not any(nota["nota_id"] in (a["payload"].get("nota_ids") or []) for nota in inseguras)]
    print(f"  alertas de seguridad falsas: {len(falsas)}")

    huecos = sum(1 for a, b in zip(latidos, latidos[1:], strict=False)
                 if (_when(b["ts_real"]) - _when(a["ts_real"])).total_seconds() > 60)
    print(f"\nF2 latidos: {len(latidos)} · huecos > 60 s: {huecos} · "
          f"F1 inválidos: {len(invalidos)}")
    if invalidos:
        for item in invalidos[:5]:
            print(f"  inválido {item['topico']}: {(item.get('error') or '')[:120]}")

    grupos_dup = 0
    for nota in notas:
        grupos: dict[tuple, set] = defaultdict(set)
        for evento in eventos.get(nota["nota_id"], []):
            grupos[(evento["tipo"], evento.get("equipo"))].add(evento["id"])
        grupos_dup += sum(1 for ids in grupos.values() if len(ids) > 1)
    print(f"E3 grupos de eventos con más de un id: {grupos_dup}")

    abiertas: dict[tuple, set] = defaultdict(set)
    final: dict[str, dict] = {}
    for oid, publicaciones in ordenes.items():
        final[oid] = publicaciones[-1]["payload"]
    for oid, payload in final.items():
        if payload["estado"] not in ("Rechazada", "Cerrada", "Certificada"):
            abiertas[(payload["equipo"], tuple(sorted(payload["tareas"])))].add(oid)
    print(f"órdenes: {len(final)} · abiertas duplicadas: {sum(1 for ids in abiertas.values() if len(ids) > 1)}")
    for _oid, payload in sorted(final.items(), key=lambda item: item[1]["equipo"]):
        print(f"  {payload['estado']:22} {payload['equipo']:7} {payload['tareas']} "
              f"reduce_inyeccion={payload.get('reduce_inyeccion')} motivo={payload.get('motivo')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
