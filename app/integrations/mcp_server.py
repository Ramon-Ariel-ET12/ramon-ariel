"""MCP server exposing read-only plant tools.

Run over stdio:  python -m app.integrations.mcp_server
It is started by hand (or by an MCP client) and is not mounted into the main app.
"""

from __future__ import annotations

import json
import logging

from app.config import get_settings
from app.domain.materials import load_materials
from app.domain.plant import load_snapshot_file
from app.integrations.plant_api import PlantClient
from app.rag.bm25 import HybridIndex
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

log = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # noqa: BLE001
    FastMCP = None  # type: ignore[assignment]


_tools: Tools | None = None
_fragments = None


def _search_index():
    global _fragments
    if _fragments is None:
        from pathlib import Path

        settings = get_settings()
        path = Path(settings.evaluation_dir) / "fragmentos.jsonl"
        _fragments = HybridIndex([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                                  if line.strip()])
    return _fragments


class _Bm25Search:
    async def search(self, query: str, k: int = 8):
        return _search_index().search(query, k)


def build_tools() -> Tools:
    global _tools
    if _tools is None:
        settings = get_settings()
        snapshot = load_snapshot_file(settings.plant_snapshot_path)
        _tools = Tools(PlantClient(settings.plant_url), load_materials(settings.materials_path), snapshot,
                       _Bm25Search())  # type: ignore[arg-type]
    return _tools


if FastMCP is not None:
    mcp = FastMCP("pia-3-readonly")

    @mcp.tool()
    async def inventario(almacen: str = "yacimiento") -> dict:
        """Inventario de repuestos con stock por almacén (solo lectura)."""
        result = await build_tools().inventario(InventoryQuery(almacen=almacen))
        return result.model_dump()

    @mcp.tool()
    async def stock(codigo: str, almacen: str = "yacimiento") -> dict:
        """Stock de un repuesto en un almacén (solo lectura)."""
        result = await build_tools().stock(StockQuery(codigo=codigo, almacen=almacen))
        return result.model_dump()

    @mcp.tool()
    async def lista_materiales(equipo: str) -> dict:
        """Lista de materiales de un equipo (solo lectura)."""
        result = await build_tools().lista_materiales(BomQuery(equipo=equipo))
        return result.model_dump()

    @mcp.tool()
    async def catalogo_tareas(equipo: str | None = None) -> dict:
        """Catálogo de tareas estándar y no estándar (solo lectura)."""
        result = await build_tools().catalogo_tareas(TaskCatalogQuery(equipo=equipo))
        return result.model_dump()

    @mcp.tool()
    async def historial_sensores(tag: str, variable: str, desde: str | None = None,
                                 hasta: str | None = None, limite: int = 200) -> dict:
        """Historial de un sensor del equipo (solo lectura)."""
        result = await build_tools().historial_sensores(
            SensorHistoryQuery(tag=tag, variable=variable, desde=desde, hasta=hasta, limite=limite))
        return result.model_dump()

    @mcp.tool()
    async def historial_ordenes(equipo: str | None = None, limite: int = 20) -> dict:
        """Historial de órdenes de trabajo (solo lectura)."""
        result = await build_tools().historial_ordenes(OrderHistoryQuery(equipo=equipo, limite=limite))
        return result.model_dump()

    @mcp.tool()
    async def equipos(equipo: str | None = None) -> dict:
        """Equipos, TAGs y nombres informales (solo lectura)."""
        result = await build_tools().equipos(EquipmentQuery(equipo=equipo))
        return result.model_dump()

    @mcp.tool()
    async def buscar_manuales(consulta: str, k: int = 8) -> dict:
        """Búsqueda en manuales con cita de sección (solo lectura)."""
        result = await build_tools().buscar_manuales(ManualSearchQuery(consulta=consulta, k=k))
        return result.model_dump()


def main() -> None:
    if FastMCP is None:
        raise SystemExit("mcp SDK is not installed")
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
