from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.materials import load_materials
from app.domain.plant import load_snapshot_file

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=-3))


@pytest.fixture(scope="session")
def snapshot():
    return load_snapshot_file(ROOT / "datos" / "planta.yaml")


@pytest.fixture(scope="session")
def materials():
    return load_materials(ROOT / "datos" / "materiales.yaml")


@pytest.fixture
def ts():
    return datetime(2026, 11, 3, 8, 0, tzinfo=TZ)


MARTES = [
    'El de la izquierda me dio uno con cuatro de diferencial. La dos está en mil seiscientos veinte psi de descarga.',
    'A ver, la de la punta está en ciento catorce de descarga. El secundario me dio uno de diferencial.',
    'La de la punta está en ciento doce de descarga. El de la derecha me dio cero nueve de diferencial.',
    'La tres está parada, en reserva.',
    'Listo, la del medio está en mil seiscientos diez libras de descarga. El filtro A me dio uno coma tres de diferencial.',
    'El filtro B me dio cero nueve de diferencial. El pulmón está en cinco metros.',
    'La uno está en ciento doce kilogramos de descarga, el rodamiento me dio cincuenta y nueve grados con la pistola. '
    'También la dos está en mil seiscientos psi de descarga. El filtro A me dio uno coma tres de diferencial.',
    'Bueno, la dos está en mil quinientos noventa libras de descarga. El filtro A me dio uno tres de diferencial. '
    'La de la punta está en ciento doce kilos de descarga.',
]

FUGA = [
    '¡Atención! Se rompió algo en la descarga de la uno, sale agua a presión para todos lados, me alejé. '
    'Saqué foto desde lejos.',
    'La dos está en mil seiscientos diez libras de descarga. El pulmón está en cinco metros.',
    'Listo, la tres está parada, en reserva.',
    'La uno está en ciento catorce kilos de descarga, el rodamiento me dio sesenta y cuatro grados con la pistola.',
]
