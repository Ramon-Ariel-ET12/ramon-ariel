"""Strict contracts for the read-only tools.  Every model forbids extra fields."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EquipmentQuery(StrictModel):
    equipo: str | None = Field(default=None, description="TAG o nombre informal")


class EquipmentInfo(StrictModel):
    tag: str
    tipo: str
    descripcion: str
    fabricante: str | None = None
    modelo: str | None = None
    nombres: list[str] = Field(default_factory=list)
    unidad_manometro: str | None = None


class EquipmentList(StrictModel):
    equipos: list[EquipmentInfo]


class SensorHistoryQuery(StrictModel):
    tag: str
    variable: str
    desde: str | None = None
    hasta: str | None = None
    limite: int = Field(default=500, ge=1, le=5000)


class SensorSample(StrictModel):
    ts: str
    valor: float | None


class SensorHistory(StrictModel):
    tag: str
    variable: str
    unidad: str = ""
    muestras: list[SensorSample]


class OrderHistoryQuery(StrictModel):
    equipo: str | None = None
    limite: int = Field(default=50, ge=1, le=500)


class WorkOrder(StrictModel):
    id: str
    fecha: str | None = None
    equipo: str
    tareas: list[str] = Field(default_factory=list)
    ejecutor: str = ""
    estado: str = ""
    descripcion: str = ""
    origen: str = ""


class OrderHistory(StrictModel):
    ordenes: list[WorkOrder]


class InventoryQuery(StrictModel):
    almacen: str = Field(default="yacimiento")


class InventoryItem(StrictModel):
    codigo: str
    nombre: str
    unidad: str = ""
    costo_usd: float
    stock: dict[str, float]


class Inventory(StrictModel):
    almacen: str
    repuestos: list[InventoryItem]


class StockQuery(StrictModel):
    codigo: str
    almacen: str = "yacimiento"


class StockItem(StrictModel):
    codigo: str
    almacen: str
    cantidad: float


class BomQuery(StrictModel):
    equipo: str


class BomItem(StrictModel):
    codigo: str
    nombre: str
    costo_usd: float


class BillOfMaterials(StrictModel):
    equipo: str
    repuestos: list[BomItem]


class TaskCatalogQuery(StrictModel):
    equipo: str | None = None


class TaskInfo(StrictModel):
    codigo: str
    nombre: str
    equipo: list[str] = Field(default_factory=list)
    detiene: bool
    horas: float
    ejecutor: str
    repuestos: list[dict] = Field(default_factory=list)
    estandar: bool


class TaskCatalog(StrictModel):
    tareas: list[TaskInfo]


class ManualSearchQuery(StrictModel):
    consulta: str = Field(min_length=3)
    k: int = Field(default=8, ge=1, le=20)


class ManualHit(StrictModel):
    cita: str
    documento: str
    titulo: str
    vigente: bool
    texto: str


class ManualResults(StrictModel):
    consulta: str
    resultados: list[ManualHit]
