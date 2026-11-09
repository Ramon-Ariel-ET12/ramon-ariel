from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.integration
async def test_mcp_lists_and_calls_inventory():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.integrations.mcp_server"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT), "PLANT_URL": "http://127.0.0.1:9"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "inventario" in names
            assert "historial_sensores" in names
            result = await session.call_tool("inventario", {"almacen": "yacimiento"})
            text = result.content[0].text if result.content else "{}"
            payload = json.loads(text)
            assert any(item["codigo"] == "TX-EMP-KIT" for item in payload["repuestos"])
