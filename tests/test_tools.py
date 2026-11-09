from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.integrations.plant_api import PlantClient, PlantUnavailable
from app.tools.contracts import (
    BomQuery,
    InventoryQuery,
    SensorHistoryQuery,
    StockQuery,
)
from app.tools.queries import ToolError, Tools


class FakePlant:
    async def historian(self, tag, variable, desde=None, hasta=None):
        return [{"ts": "2026-11-03T08:00:00-03:00", "valor": 112.0},
                {"ts": "2026-11-03T08:01:00-03:00", "valor": 113.0}]

    async def order_history(self, equipo=None):
        return [{"id": "OT-1", "fecha": "2026-10-01", "equipo": "B-101", "tareas": ["T-B-EMP"],
                 "ejecutor": "propio", "estado": "Cerrada", "descripcion": "cambio empaq", "origen": "archivo"}]


def tools_with_fake(snapshot, materials):
    return Tools(FakePlant(), materials, snapshot)


async def test_sensor_history(snapshot, materials):
    result = await tools_with_fake(snapshot, materials).historial_sensores(
        SensorHistoryQuery(tag="B-101", variable="presion_descarga"))
    assert result.unidad == "kg/cm2"
    assert [sample.valor for sample in result.muestras] == [112.0, 113.0]


async def test_order_history(snapshot, materials):
    result = await tools_with_fake(snapshot, materials).historial_ordenes(
        __import__("app.tools.contracts", fromlist=["OrderHistoryQuery"]).OrderHistoryQuery(equipo="B-101"))
    assert result.ordenes[0].id == "OT-1"


async def test_inventory_stock_and_bom(snapshot, materials):
    toolbox = tools_with_fake(snapshot, materials)
    inventory = await toolbox.inventario(InventoryQuery())
    assert any(item.codigo == "TX-EMP-KIT" for item in inventory.repuestos)
    stock = await toolbox.stock(StockQuery(codigo="FC-CART-10"))
    assert stock.cantidad == 40
    bom = await toolbox.lista_materiales(BomQuery(equipo="F-201B"))
    assert {item.codigo for item in bom.repuestos} == {"FC-CART-10", "FC-JUNTA-TAPA", "INS-TRANS-P"}


async def test_unknown_part_is_a_tool_error(snapshot, materials):
    with pytest.raises(ToolError):
        await tools_with_fake(snapshot, materials).stock(StockQuery(codigo="NO-EXISTE"))


async def test_unknown_sensor_is_a_tool_error(snapshot, materials):
    with pytest.raises(ToolError):
        await tools_with_fake(snapshot, materials).historial_sensores(
            SensorHistoryQuery(tag="B-101", variable="variable_inventada"))


def test_strict_input_contracts():
    with pytest.raises(ValidationError):
        SensorHistoryQuery(tag="B-101", variable="presion_descarga", extra=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        StockQuery(codigo="X", almacen="yacimiento", comentario="no permitido")  # type: ignore[call-arg]


@respx.mock
async def test_plant_client_retries_transport_errors():
    route = respx.get("http://sim:8100/api/planta").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"equipos": []})])
    client = PlantClient("http://sim:8100", timeout=1)
    assert await client.definition() == {"equipos": []}
    assert route.call_count == 2


@respx.mock
async def test_plant_client_gives_up_after_retries():
    respx.get("http://sim:8100/api/planta").mock(side_effect=httpx.ReadTimeout("slow"))
    client = PlantClient("http://sim:8100", timeout=0.1)
    with pytest.raises(PlantUnavailable):
        await client.definition()


@respx.mock
async def test_link_state_is_direct():
    respx.get("http://enlace:8081/estado").mock(return_value=httpx.Response(200, json={"arriba": False}))
    client = PlantClient("http://sim:8100", link_control_url="http://enlace:8081")
    assert await client.link_state() is False
