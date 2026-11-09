"""Deterministic transcript -> part rows.

The plant's notes are formulaic field speech.  A rule based parser is used for the
critical path because it is fast, offline and reproducible; an optional local model
can propose rows for unusual phrasing and its output is validated before use.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.equipment import EquipmentIndex, preprocess
from app.domain.models import Ambiguity, ExtractedRow, PartDraft, PlantSnapshot
from app.domain.numbers import parse_numbers, tokenize
from app.domain.safety import detect_safety
from app.domain.units import detect_unit, to_kg

BOUNDARY_TOKENS = {".", ";", ",", "!", "?", "¡", "¿", "tambien", "ademas", "despues", "mientras", "pero", "porque"}
TENS_WORDS = {
    "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa",
}
UNIT_WORDS = {"uno", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"}

NORMAL_STATES = {"parada, en reserva", "parada por mantenimiento"}
QUANTITATIVE = {"presion_descarga_local", "presion_diferencial", "temperatura_rodamiento_ir",
                "goteo_empaquetadura", "nivel"}
IMPLAUSIBLE_DIFFERENTIAL = 3.0


def split_clauses(tokens: list[str]) -> list[list[str]]:
    clauses: list[list[str]] = []
    current: list[str] = []
    for index, token in enumerate(tokens):
        if token in BOUNDARY_TOKENS or (token == "y" and not _is_number_connector(tokens, index)):
            if current:
                clauses.append(current)
            current = []
            continue
        current.append(token)
    if current:
        clauses.append(current)
    return clauses


def _is_number_connector(tokens: list[str], index: int) -> bool:
    nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
    if nxt == "medio":
        return True
    prev = tokens[index - 1] if index > 0 else ""
    return prev in TENS_WORDS and nxt in UNIT_WORDS


def detect_variable(text: str) -> str | None:
    if "diferencial" in text:
        return "presion_diferencial"
    if "descarga" in text:
        return "presion_descarga_local"
    if "rodamiento" in text and any(word in text for word in ("grado", "pistola", "temperatura")):
        return "temperatura_rodamiento_ir"
    if any(word in text for word in ("gotea", "goteando", "pierde", "chorrea", "perdida")) and any(
        word in text for word in ("empaquetadura", "prensaestopas", "sello")
    ):
        return "goteo_empaquetadura"
    if "correa" in text:
        return "estado_correas"
    if "aceite" in text or "visor" in text:
        return "nivel_aceite_visor"
    if any(word in text for word in ("ruido", "golpeteo", "golpea", "piedras", "chillan", "chirrido", "zumbido")):
        return "ruido"
    if any(
        word in text
        for word in ("parada", "parado", "reserva", "mantenimiento", "disparada", "disparo", "no arranca", "detenida")
    ):
        return "estado"
    if any(word in text for word in ("pulmon", "tanque", "nivel", "rebals")):
        return "nivel"
    # ASR often keeps the unit but drops the variable word ("la dos en 1600 psi").
    if any(word in text.split() for word in ("psi", "ps", "libras", "kilos", "kilogramos", "bar", "bares")):
        return "presion_descarga_local"
    return None


def _infer_unit(variable: str, explicit: str | None, tag: str | None, snapshot: PlantSnapshot) -> str | None:
    if variable == "presion_descarga_local":
        return explicit or snapshot.gauge_unit(tag or "") or "kg/cm2"
    if variable == "presion_diferencial":
        return explicit or "kg/cm2"
    if variable == "temperatura_rodamiento_ir":
        return "degC"
    if variable == "goteo_empaquetadura":
        return "gotas/min"
    if variable == "nivel":
        return "m"
    return explicit


def _observation(variable: str, text: str, value: float | None, unit: str | None, tag: str | None,
                 snapshot: PlantSnapshot) -> str | None:
    if variable == "goteo_empaquetadura":
        if "bastante" in text or "chorrea" in text:
            return "pérdida importante por empaquetadura"
        return "goteo por empaquetadura"
    if variable == "estado_correas":
        if "floj" in text:
            return "correas flojas"
        if "gastad" in text:
            return "correas gastadas"
        return "correas en mal estado"
    if variable == "ruido":
        if "golpeteo" in text or "golpea" in text:
            return "golpeteo metálico"
        if "piedras" in text:
            return "ruido a piedras"
        if "rodamiento" in text:
            return "ruido de rodamiento"
        return "ruido anormal"
    if variable == "estado":
        if "reserva" in text:
            return "parada, en reserva"
        if "mantenimiento" in text:
            return "parada por mantenimiento"
        if "dispar" in text or "no arranca" in text:
            return "disparada, no arranca"
        return "parada"
    if variable == "nivel_aceite_visor":
        return "nivel de aceite bajo"
    if variable == "nivel":
        return "rebalse a pileta" if "rebals" in text else None
    if value is None or tag is None:
        return None
    sensor = "presion_descarga" if variable == "presion_descarga_local" else variable
    limit = snapshot.limit(tag, sensor)
    if limit is None:
        if variable == "temperatura_rodamiento_ir" and value > 75:
            return "rodamiento caliente"
        return None
    measured = to_kg(value, unit) if variable.startswith("presion") else value
    if limit.high is not None and measured >= limit.high:
        return "diferencial alto" if variable == "presion_diferencial" else "presión de descarga alta"
    if limit.low is not None and measured <= limit.low:
        return "diferencial bajo" if variable == "presion_diferencial" else "presión de descarga baja"
    if variable == "temperatura_rodamiento_ir" and value > 75:
        return "rodamiento caliente"
    return None


def _merge_row(rows: list[ExtractedRow], new_row: ExtractedRow, index: dict[tuple[str, str], int]) -> int:
    key = (new_row.tag, new_row.variable)
    if key not in index:
        rows.append(new_row)
        index[key] = len(rows) - 1
        return index[key]
    current = rows[index[key]]
    if current.value is None and new_row.value is not None:
        current.value = new_row.value
        current.unit = new_row.unit
    if new_row.variable == "estado":
        combined = f"{current.observation or ''} {new_row.observation or ''}".lower()
        if "reserva" in combined:
            current.observation = "parada, en reserva"
        elif "mantenimiento" in combined:
            current.observation = "parada por mantenimiento"
        elif "dispar" in combined or "no arranca" in combined:
            current.observation = "disparada, no arranca"
        else:
            current.observation = "parada"
    elif new_row.observation and new_row.observation not in (current.observation or ""):
        current.observation = ", ".join(part for part in (current.observation, new_row.observation) if part)
    if new_row.photo and not current.photo:
        current.photo = new_row.photo
    for flag in new_row.flags:
        if flag not in current.flags:
            current.flags.append(flag)
    return index[key]


def _split_tag_like(tokens: list[str], snapshot: PlantSnapshot) -> list[str]:
    """Split ASR tokens such as "b109" into "b" + "109" when they are not real tags."""
    import re

    known = {tag.lower().replace("-", "") for tag in snapshot.equipment}
    output: list[str] = []
    for token in tokens:
        match = re.fullmatch(r"([bf])(\d{3})([a-z]?)", token)
        if match and token not in known:
            output.extend([match.group(1), match.group(2) + match.group(3)])
        else:
            output.append(token)
    return output


def _secondary_rows(clause: list[str], mentions, tag: str, masked: list[str],
                    numbers, snapshot: PlantSnapshot) -> list[ExtractedRow]:
    """A clause can carry two variables when ASR drops punctuation.

    Example: "la 1 en 112 de descarga el rodamiento medio 59 con la pistola".
    """
    text = " ".join(clause)
    rows: list[ExtractedRow] = []
    if "rodamiento" in masked and any(word in masked for word in ("pistola", "grado", "grados")):
        rodamiento = masked.index("rodamiento")
        after = [number for number in numbers if number.start >= rodamiento]
        value = after[0].value if after else None
        rows.append(ExtractedRow(tag=tag, variable="temperatura_rodamiento_ir", value=value,
                                 unit="degC" if value is not None else None,
                                 observation="rodamiento caliente" if value is not None and value > 75 else None))
    if "correa" in masked and "estado_correas" not in {row.variable for row in rows}:
        observation = "correas flojas" if "floj" in text else "correas en mal estado"
        rows.append(ExtractedRow(tag=tag, variable="estado_correas", observation=observation))
    if any(word in masked for word in ("aceite", "visor")):
        rows.append(ExtractedRow(tag=tag, variable="nivel_aceite_visor", observation="nivel de aceite bajo"))
    if any(word in masked for word in ("gotea", "goteando", "pierde", "chorrea")):
        observation = ("pérdida importante por empaquetadura" if "bastante" in text or "chorrea" in text
                       else "goteo por empaquetadura")
        rows.append(ExtractedRow(tag=tag, variable="goteo_empaquetadura", observation=observation))
    if any(word in masked for word in ("golpeteo", "golpea", "piedras", "ruido")):
        rows.append(ExtractedRow(tag=tag, variable="ruido", observation="ruido anormal"))
    return rows


def parse_transcript(
    transcript: str,
    snapshot: PlantSnapshot,
    *,
    note_id: str = "",
    ts: datetime | None = None,
    photos: list[str] | None = None,
) -> PartDraft:
    """Parse a note transcript into one row per equipment and variable."""
    photos = list(photos or [])
    draft = PartDraft(note_id=note_id, ts=ts or datetime.now().astimezone(), transcript=transcript, photos=photos)
    index = EquipmentIndex(snapshot)
    tokens = _split_tag_like(tokenize(preprocess(transcript)), snapshot)
    if not tokens:
        return draft

    safety_code, _evidence = detect_safety(transcript)
    if safety_code:
        mentions = index.find_mentions(tokens)
        tag = mentions[0].tag if mentions else "PLANTA"
        draft.safety = safety_code
        draft.rows = [
            ExtractedRow(
                tag=tag,
                variable="condicion_insegura",
                value=None,
                unit=None,
                observation=transcript.strip(),
                photo=photos[0] if photos else None,
            )
        ]
        return draft

    rows: list[ExtractedRow] = []
    row_index: dict[tuple[str, str], int] = {}
    current_tag: str | None = None
    photo_cursor = 0
    last_row: int | None = None

    for clause in split_clauses(tokens):
        if not clause:
            continue
        clause_text = " ".join(clause)
        mentions = index.find_mentions(clause)
        ambiguous = index.ambiguous_equipment(clause_text) if not mentions else None
        tag = mentions[0].tag if mentions else None
        if tag:
            current_tag = tag

        variable = detect_variable(clause_text)
        wants_photo = "foto" in clause_text

        if variable is None:
            if wants_photo and photo_cursor < len(photos) and last_row is not None:
                if not rows[last_row].photo:
                    rows[last_row].photo = photos[photo_cursor]
                photo_cursor += 1
            continue

        effective_tag = tag or current_tag
        if ambiguous and not mentions:
            effective_tag = None
            current_tag = None

        masked = index.mask(clause, mentions) if mentions else clause
        numbers = parse_numbers(masked) if variable in QUANTITATIVE else []
        value = numbers[0].value if numbers else None
        explicit_decimal = numbers[0].explicit_decimal if numbers else False
        explicit_unit, _ = detect_unit(clause)
        unit = _infer_unit(variable, explicit_unit, effective_tag, snapshot)

        flags: list[str] = []
        if variable == "presion_diferencial" and value is not None:
            if (value > IMPLAUSIBLE_DIFFERENTIAL) or (value >= 10 and not explicit_decimal):
                repaired = round(value / 10.0, 4)
                if value >= 100:
                    # ASR merged "B me dio cero nueve" into "B-109": the last two
                    # digits are the spoken decimal. This is not a field ambiguity.
                    alternative = round((value % 100) / 10.0, 4)
                    if 0.05 <= alternative <= IMPLAUSIBLE_DIFFERENTIAL:
                        value = alternative
                        flags.append("value_repaired")
                        repaired = None
                if repaired is not None:
                    if 0.05 <= repaired <= IMPLAUSIBLE_DIFFERENTIAL:
                        draft.ambiguities.append(
                            Ambiguity(
                                kind="value",
                                tag=effective_tag,
                                raw_value=value,
                                repaired_value=repaired,
                                clause=clause_text,
                            )
                        )
                        value = repaired
                        flags.append("value_repaired")

        if effective_tag is None:
            if ambiguous and not any(a.kind == "equipment" for a in draft.ambiguities):
                draft.ambiguities.append(
                    Ambiguity(kind="equipment", candidates=ambiguous, clause=clause_text)
                )
            continue

        if effective_tag.startswith("F-") and variable == "presion_descarga_local":
            variable = "presion_diferencial"
            unit = explicit_unit or "kg/cm2"
        observation = _observation(variable, clause_text, value, unit, effective_tag, snapshot)
        row = ExtractedRow(
            tag=effective_tag,
            variable=variable,
            value=value,
            unit=unit if value is not None else None,
            observation=observation,
            flags=flags,
        )
        if wants_photo and photo_cursor < len(photos):
            row.photo = photos[photo_cursor]
            photo_cursor += 1
        last_row = _merge_row(rows, row, row_index)
        for secondary in _secondary_rows(clause, mentions, effective_tag, masked, numbers, snapshot):
            if secondary.variable != variable:
                _merge_row(rows, secondary, row_index)

    # Photos that the note carries but the transcript does not mention belong to the last row.
    for leftover in photos[photo_cursor:]:
        if last_row is not None and rows[last_row].photo is None:
            rows[last_row].photo = leftover
        elif last_row is not None:
            draft.photos.append(leftover)

    draft.rows = rows
    return draft


def is_normal_observation(variable: str, observation: str | None) -> bool:
    if variable != "estado":
        return False
    normal = " ".join((observation or "").lower().split())
    return normal in NORMAL_STATES
