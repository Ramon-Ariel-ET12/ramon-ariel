"""LangChain tool wrappers over the same read-only functions."""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from app.tools.contracts import (
    BomQuery,
    EquipmentQuery,
    InventoryQuery,
    ManualSearchQuery,
    OrderHistoryQuery,
    SensorHistoryQuery,
    StockQuery,
    TaskCatalogQuery,
)
from app.tools.queries import Tools


def build_langchain_tools(tools: Tools) -> list[StructuredTool]:
    return [
        StructuredTool.from_function(
            coroutine=tools.equipos, name="equipos",
            description="Equipos de la planta con TAG y nombres informales.", args_schema=EquipmentQuery,
        ),
        StructuredTool.from_function(
            coroutine=tools.historial_sensores, name="historial_sensores",
            description="Historial de sensores de un equipo en las últimas horas o días.",
            args_schema=SensorHistoryQuery,
        ),
        StructuredTool.from_function(
            coroutine=tools.historial_ordenes, name="historial_ordenes",
            description="Historial de órdenes de trabajo por equipo.", args_schema=OrderHistoryQuery,
        ),
        StructuredTool.from_function(
            coroutine=tools.inventario, name="inventario",
            description="Inventario de repuestos con stock por almacén.", args_schema=InventoryQuery,
        ),
        StructuredTool.from_function(
            coroutine=tools.stock, name="stock",
            description="Stock de un repuesto en un almacén.", args_schema=StockQuery,
        ),
        StructuredTool.from_function(
            coroutine=tools.lista_materiales, name="lista_materiales",
            description="Lista de materiales de un equipo.", args_schema=BomQuery,
        ),
        StructuredTool.from_function(
            coroutine=tools.catalogo_tareas, name="catalogo_tareas",
            description="Catálogo de tareas estándar y no estándar de mantenimiento.",
            args_schema=TaskCatalogQuery,
        ),
        StructuredTool.from_function(
            coroutine=tools.buscar_manuales, name="buscar_manuales",
            description="Búsqueda en manuales con cita de sección y vigencia.", args_schema=ManualSearchQuery,
        ),
    ]
