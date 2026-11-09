from __future__ import annotations

import httpx
import respx
from planta_contrato import EstadoSistema

from app.domain.history import HistoricalValidator, outside_range, range_from_values
from app.domain.models import ExtractedRow
from app.heartbeat import heartbeat_payload
from app.integrations.sync import CloudSync


class FakeRepo:
    def __init__(self, items):
        self.items = items
        self.acked = []
        self.bumped = []

    async def pending_sync(self, limit=50):
        return self.items[:limit]

    async def ack_sync(self, ids):
        self.acked.extend(ids)

    async def bump_sync(self, ids):
        self.bumped.extend(ids)


@respx.mock
async def test_sync_acknowledges_on_success():
    respx.post("http://cloud:8300/items").mock(return_value=httpx.Response(200, json={"ok": True}))
    repo = FakeRepo([{"id": 1, "topic": "sistema/eventos", "payload": {"id": "e"}}])
    sync = CloudSync(repo, "http://cloud:8300", client_factory=lambda: httpx.AsyncClient(trust_env=False))
    assert await sync.once() == 1
    assert repo.acked == [1]
    assert repo.bumped == []


@respx.mock
async def test_sync_keeps_items_on_failure():
    respx.post("http://cloud:8300/items").mock(return_value=httpx.Response(503))
    repo = FakeRepo([{"id": 2, "topic": "sistema/eventos", "payload": {}}])
    sync = CloudSync(repo, "http://cloud:8300", client_factory=lambda: httpx.AsyncClient(trust_env=False))
    assert await sync.once() == 0
    assert repo.acked == []
    assert repo.bumped == [2]


async def test_heartbeat_payload_validates():
    payload = await heartbeat_payload("Test", False, 4)
    model = EstadoSistema.model_validate(payload)
    assert model.enlace_ok is False
    assert model.pendientes_sincronizar == 4


def test_historical_range_and_margin():
    bounds = range_from_values([float(value) for value in range(100)])
    assert bounds is not None
    assert outside_range(200, "kg/cm2", bounds)
    assert not outside_range(50, "kg/cm2", bounds)
    assert outside_range(2000, "psi", bounds)
    narrow = range_from_values([1.0, 2.0])
    assert narrow is None


class FakePlant:
    async def historian(self, tag, variable, desde=None, hasta=None):
        return [{"valor": float(value % 100)} for value in range(2000)]


async def test_historical_validator_flags_outliers(snapshot, ts):
    validator = HistoricalValidator(FakePlant(), snapshot)
    flagged = await validator.check([
        ExtractedRow(tag="B-101", variable="presion_descarga_local", value=200.0, unit="kg/cm2"),
        ExtractedRow(tag="B-101", variable="presion_descarga_local", value=50.0, unit="kg/cm2"),
        ExtractedRow(tag="B-101", variable="goteo_empaquetadura", value=120.0, unit="gotas/min"),
    ], ts)
    assert [row.value for row in flagged] == [200.0]
