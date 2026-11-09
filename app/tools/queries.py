"""Read-only tools over the plant API, the provided maintenance data and the manual index."""

from __future__ import annotations

import logging

from app.domain.materials import Materials
from app.domain.models import PlantSnapshot
from app.integrations.plant_api import PlantClient
from app.rag.search import ManualSearch
from app.tools.contracts import (
    BillOfMaterials,
    BomItem,
    BomQuery,
    EquipmentInfo,
    EquipmentList,
    EquipmentQuery,
    Inventory,
    InventoryItem,
    InventoryQuery,
    ManualHit,
    ManualResults,
    ManualSearchQuery,
    OrderHistory,
    OrderHistoryQuery,
    SensorHistory,
    SensorHistoryQuery,
    SensorSample,
    StockItem,
    StockQuery,
    TaskCatalog,
    TaskCatalogQuery,
    TaskInfo,
    WorkOrder,
)

log = logging.getLogger(__name__)


class ToolError(RuntimeError):
    pass


class Tools:
    """Every method is a read.  Writes only exist in the approval rule engine."""

    def __init__(self, plant: PlantClient, materials: Materials, snapshot: PlantSnapshot,
                 search: ManualSearch | None = None):
        self.plant = plant
        self.materials = materials
        self.snapshot = snapshot
        self.search = search

    async def equipos(self, query: EquipmentQuery) -> EquipmentList:
        items = []
        for tag, equipment in self.snapshot.equipment.items():
            if query.equipo and query.equipo.lower() not in (tag.lower(), " ".join(equipment.names).lower()):
                continue
            items.append(EquipmentInfo(tag=tag, tipo=equipment.kind, descripcion=equipment.description,
                                       fabricante=equipment.manufacturer, modelo=equipment.model,
                                       nombres=equipment.names, unidad_manometro=equipment.gauge_unit))
        return EquipmentList(equipos=items)

    async def historial_sensores(self, query: SensorHistoryQuery) -> SensorHistory:
        limit = self.snapshot.limit(query.tag, query.variable)
        if limit is None:
            raise ToolError(f"no existe el sensor {query.tag}/{query.variable}")
        try:
            samples = await self.plant.historian(query.tag, query.variable, query.desde, query.hasta)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"historiador no disponible: {exc}") from exc
        return SensorHistory(
            tag=query.tag, variable=query.variable, unidad=limit.unit,
            muestras=[SensorSample(ts=item["ts"], valor=item.get("valor")) for item in samples[-query.limite:]],
        )

    async def historial_ordenes(self, query: OrderHistoryQuery) -> OrderHistory:
        try:
            orders = await self.plant.order_history(query.equipo)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"historial de órdenes no disponible: {exc}") from exc
        items = []
        for order in orders[-query.limite:]:
            items.append(WorkOrder(
                id=str(order.get("id", "")), fecha=order.get("fecha"),
                equipo=order.get("equipo", ""), tareas=list(order.get("tareas") or []),
                ejecutor=order.get("ejecutor", ""), estado=order.get("estado", ""),
                descripcion=order.get("descripcion", ""), origen=order.get("origen", ""),
            ))
        return OrderHistory(ordenes=items)

    async def inventario(self, query: InventoryQuery) -> Inventory:
        return Inventory(
            almacen=query.almacen,
            repuestos=[
                InventoryItem(codigo=part.code, nombre=part.name, unidad=part.unit,
                              costo_usd=part.cost_usd, stock=part.stock)
                for part in self.materials.parts.values()
            ],
        )

    async def stock(self, query: StockQuery) -> StockItem:
        part = self.materials.parts.get(query.codigo)
        if part is None:
            raise ToolError(f"no existe el repuesto {query.codigo}")
        return StockItem(codigo=part.code, almacen=query.almacen,
                         cantidad=float(part.stock.get(query.almacen, 0)))

    async def lista_materiales(self, query: BomQuery) -> BillOfMaterials:
        if query.equipo not in self.materials.bom:
            raise ToolError(f"no hay lista de materiales para {query.equipo}")
        return BillOfMaterials(
            equipo=query.equipo,
            repuestos=[BomItem(codigo=code, nombre=self.materials.parts[code].name,
                               costo_usd=self.materials.parts[code].cost_usd)
                       for code in self.materials.bom[query.equipo] if code in self.materials.parts],
        )

    async def catalogo_tareas(self, query: TaskCatalogQuery) -> TaskCatalog:
        seen: dict[str, TaskInfo] = {}
        for equipment, tasks in self.materials.standard.items():
            if query.equipo and equipment != query.equipo:
                continue
            for task in tasks.values():
                seen[task.code] = TaskInfo(codigo=task.code, nombre=task.name, equipo=[equipment],
                                           detiene=task.stops, horas=task.hours, ejecutor=task.executor,
                                           repuestos=task.parts, estandar=True)
        for code, task in self.materials.nonstandard.items():
            seen[code] = TaskInfo(codigo=code, nombre=task.name, equipo=[], detiene=task.stops,
                                  horas=task.hours, ejecutor=task.executor, repuestos=task.parts,
                                  estandar=False)
        return TaskCatalog(tareas=list(seen.values()))

    async def buscar_manuales(self, query: ManualSearchQuery) -> ManualResults:
        if self.search is None:
            raise ToolError("el indice de manuales no esta configurado")
        hits = await self.search.search(query.consulta, query.k)
        return ManualResults(
            consulta=query.consulta,
            resultados=[ManualHit(cita=hit["citation"], documento=hit["doc"], titulo=hit["title"],
                                  vigente=bool(hit["current"]), texto=hit["text"]) for hit in hits],
        )
