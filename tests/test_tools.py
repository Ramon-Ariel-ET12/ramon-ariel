from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.integrations.plant_api import PlantClient, PlantUnavailable
from app.tools.contracts import (
    BomQuery,
    InventoryQuery,
    ManualSearchQuery,
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


def test_contracts_do_not_coerce_strings_into_numbers():
    """strict=True: a JSON string where an integer is expected is rejected."""
    with pytest.raises(ValidationError):
        SensorHistoryQuery(tag="B-101", variable="presion_descarga", limite="5")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ManualSearchQuery(consulta="limite", k="3")  # type: ignore[arg-type]


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


class FakeSearch:
    async def search(self, query, k=8):
        return [{"citation": "TX350-D §3.2", "doc": "TX350-D", "title": "Límites de operación",
                 "current": True, "text": "vibración 7,1 mm/s"}][:k]


async def test_equipment_tool_lists_plant_tags(snapshot, materials):
    from app.tools.contracts import EquipmentQuery

    result = await tools_with_fake(snapshot, materials).equipos(EquipmentQuery())
    tags = {item.tag for item in result.equipos}
    assert {"B-101", "B-102", "B-103", "F-201A", "F-201B"} <= tags


async def test_task_catalog_uses_typed_parts(snapshot, materials):
    from app.tools.contracts import TaskCatalogQuery

    result = await tools_with_fake(snapshot, materials).catalogo_tareas(TaskCatalogQuery())
    by_code = {task.codigo: task for task in result.tareas}
    change = by_code["T-B-EMP"]
    assert change.estandar is True
    assert change.repuestos[0].codigo == "TX-EMP-KIT"
    assert change.repuestos[0].cantidad == 1


async def test_manual_search_tool_returns_citations(snapshot, materials):
    from app.tools.contracts import ManualSearchQuery

    tools = Tools(FakePlant(), materials, snapshot, search=FakeSearch())
    result = await tools.buscar_manuales(ManualSearchQuery(consulta="limite de vibracion"))
    assert [hit.cita for hit in result.resultados] == ["TX350-D §3.2"]
    assert result.resultados[0].vigente is True


def test_warehouse_is_validated():
    from app.tools.contracts import InventoryQuery

    assert InventoryQuery(almacen="central").almacen == "central"
    with pytest.raises(ValidationError):
        InventoryQuery(almacen="deposito-inventado")


async def test_malformed_historian_payload_is_a_tool_error(snapshot, materials):
    class BrokenPlant:
        async def historian(self, tag, variable, desde=None, hasta=None):
            return [{"sin_hora": True}]

    tools = Tools(BrokenPlant(), materials, snapshot)  # type: ignore[arg-type]
    with pytest.raises(ToolError):
        await tools.historial_sensores(SensorHistoryQuery(tag="B-101", variable="presion_descarga"))
