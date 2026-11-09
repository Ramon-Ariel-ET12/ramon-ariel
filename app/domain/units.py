"""Unit normalisation for the plant's local readings.

The rubric and the simulator convert pressures to kg/cm2 with these exact factors,
so we use the same ones for alarm and historical range checks.
"""

from __future__ import annotations

import re

from app.domain.numbers import normalize_text

# value_in_kg_per_cm2 = value * KG_FACTOR[unit]
KG_FACTOR = {"kg/cm2": 1.0, "psi": 1 / 14.2233, "bar": 1.01972}

UNIT_ALIASES = {
    "kilo": "kg/cm2", "kilos": "kg/cm2", "kilogramo": "kg/cm2", "kilogramos": "kg/cm2",
    "kg": "kg/cm2", "kg/cm2": "kg/cm2", "kg/cm²": "kg/cm2", "kilogramo fuerza": "kg/cm2",
    "psi": "psi", "ps": "psi", "ps y": "psi", "libra": "psi", "libras": "psi", "lb": "psi",
    "bar": "bar", "bares": "bar",
    "metro": "m", "metros": "m", "m": "m",
    "grado": "degC", "grados": "degC", "degc": "degC", "c": "degC", "°c": "degC",
    "gota": "gotas/min", "gotas": "gotas/min", "gotas por minuto": "gotas/min",
    "gotas/min": "gotas/min", "gotas minuto": "gotas/min",
}

PRESSURE_UNITS = {"kg/cm2", "psi", "bar"}


def normalize_unit(text: str | None) -> str | None:
    if not text:
        return None
    normal = normalize_text(text).strip()
    if normal in UNIT_ALIASES:
        return UNIT_ALIASES[normal]
    compact = re.sub(r"\s+", " ", normal)
    return UNIT_ALIASES.get(compact)


def detect_unit(tokens: list[str]) -> tuple[str | None, int | None]:
    """Find the first explicit unit in a token list and the index where it appears."""
    for index, token in enumerate(tokens):
        unit = normalize_unit(token)
        if unit:
            return unit, index
        # Two-token forms: "gotas por minuto".
        if index + 2 < len(tokens) and token == "gotas" and tokens[index + 1] == "por" and tokens[index + 2] == "minuto":
            return "gotas/min", index
        if index + 1 < len(tokens) and token in ("kg", "grados") and tokens[index + 1] in ("cm2", "c"):
            return normalize_unit(token), index
    return None, None


def to_kg(value: float, unit: str | None) -> float:
    factor = KG_FACTOR.get(unit or "kg/cm2")
    if factor is None:
        return value
    return value * factor


def canonical_pressure_unit(unit: str | None) -> str:
    unit = unit or "kg/cm2"
    return unit if unit in PRESSURE_UNITS else "kg/cm2"
