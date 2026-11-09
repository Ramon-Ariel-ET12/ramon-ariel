"""Compare the parts built by the system with the plant truth (development mode).

    docker compose exec cerebro python -m evaluacion.evaluar_parte

Outside the correction mode, ``GET /api/verdad`` is open.  The official correction
closes it, so this evaluator is a development tool, not a substitute for corregir.py.
"""

from __future__ import annotations

import json

from app.config import get_settings
from app.domain.plant import load_snapshot_file
from app.integrations.plant_api import PlantClient
from app.persistence.db import Database
from app.persistence.repository import Repository

PRESSURE = {"kg/cm2", "psi", "bar"}


def close(shown, expected, unit, expected_unit) -> bool:
    if shown is None or expected is None:
        return shown == expected
    if unit in PRESSURE and expected_unit in PRESSURE:
        from app.domain.units import to_kg

        shown, expected = to_kg(float(shown), unit), to_kg(float(expected), expected_unit)
    elif unit and expected_unit and unit != expected_unit:
        return False
    return abs(float(shown) - float(expected)) <= max(0.6, abs(float(expected)) * 0.02)


async def main() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    await db.connect()
    repo = Repository(db)
    plant = PlantClient(settings.plant_url)
    try:
        truth = await plant.get_json("/api/verdad")
        snapshot = load_snapshot_file(settings.plant_snapshot_path)
        notes = [item for item in truth if item.get("tipo") != "vivo" and item.get("items") is not None]
        checked = 0
        rows_ok = 0
        rows_total = 0
        questions_ok = 0
        ambiguous = 0
        for note in notes:
            part = await repo.get_part(note["nota_id"])
            if not part:
                continue
            checked += 1
            rows = json.loads(part["rows"]) if isinstance(part["rows"], str) else part["rows"]
            expected = note["items"]
            used: set[int] = set()
            for item in expected:
                if item.get("valor") is None:
                    continue
                rows_total += 1
                match = None
                for index, row in enumerate(rows):
                    if index in used or row["tag"] != item["tag"]:
                        continue
                    if close(row.get("value"), item.get("valor"), row.get("unit"), item.get("unidad")):
                        match = index
                        break
                if match is not None:
                    used.add(match)
                    rows_ok += 1
            if note.get("ambiguedades"):
                ambiguous += 1
                dialogs = await db.fetch(
                    "SELECT count(*) AS n FROM tablet_messages WHERE note_id = %s", (note["nota_id"],))
                if dialogs and dialogs[0]["n"] > 1:
                    questions_ok += 1
        print(f"Notas evaluadas: {checked} de {len(notes)}")
        print(f"Aciertos por campo con valor: {rows_ok}/{rows_total} "
              f"({100 * rows_ok / rows_total:.1f}%)" if rows_total else "sin filas comparables")
        print(f"Notas ambiguas con pregunta: {questions_ok}/{ambiguous}" if ambiguous else "sin ambigüedades")
        print(f"Definición de planta: {len(snapshot.equipment)} equipos")
    finally:
        await db.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
