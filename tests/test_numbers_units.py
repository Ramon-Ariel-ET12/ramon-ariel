from __future__ import annotations

import pytest

from app.domain.numbers import parse_first_number, parse_numbers, tokenize
from app.domain.units import detect_unit, normalize_unit, to_kg


@pytest.mark.parametrize("text,expected", [
    ("ciento doce", 112.0),
    ("mil seiscientos veinte", 1620.0),
    ("mil quinientos noventa", 1590.0),
    ("cien", 100.0),
    ("cincuenta y nueve", 59.0),
    ("ochenta y cinco", 85.0),
    ("veintitrés", 23.0),
    ("uno con cuatro", 1.4),
    ("uno coma tres", 1.3),
    ("cero nueve", 0.9),
    ("uno tres", 1.3),
    ("uno y medio", 1.5),
    ("1.620", 1620.0),
    ("1,4", 1.4),
    ("112,5", 112.5),
])
def test_spanish_numbers(text, expected):
    assert parse_first_number(text) == pytest.approx(expected)


def test_does_not_merge_two_different_numbers():
    mentions = parse_numbers(tokenize("ciento doce y luego quinientos"))
    assert [m.value for m in mentions] == [112.0, 500.0]


def test_unit_aliases():
    assert normalize_unit("kilos") == "kg/cm2"
    assert normalize_unit("kilogramos") == "kg/cm2"
    assert normalize_unit("libras") == "psi"
    assert normalize_unit("bares") == "bar"
    assert normalize_unit("grados") == "degC"


def test_detect_unit_two_tokens():
    unit, index = detect_unit(tokenize("ciento veinte gotas por minuto"))
    assert (unit, index) == ("gotas/min", 2)


def test_pressure_conversion():
    assert to_kg(14.2233, "psi") == pytest.approx(1.0, abs=1e-4)
    assert to_kg(1.0, "bar") == pytest.approx(1.01972, abs=1e-4)
    assert to_kg(112, "kg/cm2") == 112


def test_asr_leading_zero_and_measure_verb():
    assert parse_first_number("09 de diferencial") == pytest.approx(0.9)
    assert parse_first_number("el rodamiento medió 59 grados") == pytest.approx(59.0)
    assert parse_first_number("el filtro B medio 09 de diferencial") == pytest.approx(0.9)
    assert parse_first_number("1949") == 1949.0
