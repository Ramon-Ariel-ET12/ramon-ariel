#!/usr/bin/env python3
"""Assert the Delivery-1 deployment contract on the resolved compose file.

The assignment puts a numeric envelope on the plant PC (4 CPU, 8 GB), keeps the plant
services on the external ``planta-lan`` network with the ``academia.planta: pc`` label,
and routes internet through the ``enlace`` proxy. Those rules are easy to break with a
one-line compose edit, so they are checked here instead of in prose.

    python3 scripts/check_compose_budget.py                 # runs docker compose config
    python3 scripts/check_compose_budget.py --file cfg.json # checks a saved config

Exit code 0 when every rule holds, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MAX_CPU = 4.0
MAX_MEMORY_BYTES = 8 * 1024**3
PLANT_NETWORK = "planta-lan"
CONTROL_NETWORK = "control"
# The cloud replica is deliberately outside the plant PC. Everything else is plant-side.
CLOUD_ONLY = {"nube-sync"}
EXPECTED_PROXY = {
    "HTTP_PROXY": "http://enlace:3128",
    "HTTPS_PROXY": "http://enlace:3128",
    "NO_PROXY": "broker,sim,localhost",
}
PROXY_SERVICE = "cerebro"


def _bytes(value) -> int:
    """Compose resolves memory to bytes, but accept the short forms too."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "0").strip().lower()
    match = re.fullmatch(r"([\d.]+)\s*(b|k|kb|m|mb|g|gb)?", text)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2) or "b"
    factor = {"b": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2,
              "g": 1024**3, "gb": 1024**3}[unit]
    return int(number * factor)


def load_config(path: Path | None) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    completed = subprocess.run(["docker", "compose", "config", "--format", "json"],
                               capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"docker compose config failed:\n{completed.stderr[-2000:]}")
    return json.loads(completed.stdout)


def check(config: dict) -> list[str]:
    errors: list[str] = []
    networks = config.get("networks") or {}
    for name in (PLANT_NETWORK, CONTROL_NETWORK):
        if name not in networks:
            errors.append(f"falta la red {name}")
        elif not networks[name].get("external"):
            errors.append(f"la red {name} no es external")

    total_cpu = 0.0
    total_memory = 0
    for name, service in sorted((config.get("services") or {}).items()):
        service_networks = set(service.get("networks") or {})
        labels = service.get("labels") or {}
        limits = (((service.get("deploy") or {}).get("resources") or {}).get("limits") or {})

        if name not in CLOUD_ONLY:
            if PLANT_NETWORK not in service_networks:
                errors.append(f"{name}: no está en {PLANT_NETWORK}")
            if labels.get("academia.planta") != "pc":
                errors.append(f"{name}: falta el label academia.planta: pc")

        if limits.get("cpus") in (None, ""):
            errors.append(f"{name}: sin límite de CPU")
        else:
            total_cpu += float(limits["cpus"])
        if limits.get("memory") in (None, ""):
            errors.append(f"{name}: sin límite de memoria")
        else:
            total_memory += _bytes(limits["memory"])

    if total_cpu > MAX_CPU:
        errors.append(f"CPU total {total_cpu:g} > {MAX_CPU:g}")
    if total_memory > MAX_MEMORY_BYTES:
        errors.append(f"memoria total {total_memory / 1024**3:.3f} GiB > 8 GiB")

    environment = ((config.get("services") or {}).get(PROXY_SERVICE) or {}).get("environment") or {}
    for key, expected in EXPECTED_PROXY.items():
        if str(environment.get(key)) != expected:
            errors.append(f"{PROXY_SERVICE}.{key}={environment.get(key)!r}, se esperaba {expected!r}")

    print(f"servicios: {', '.join(sorted(config.get('services') or {}))}")
    print(f"CPU total: {total_cpu:g} / {MAX_CPU:g}")
    print(f"memoria total: {total_memory / 1024**3:.3f} GiB / 8 GiB")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, help="JSON de 'docker compose config' (si no, corre compose)")
    args = parser.parse_args()

    errors = check(load_config(args.file))
    if errors:
        print("\nFALLAS:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("OK: red, label, proxies y presupuesto de recursos en regla")
    return 0


if __name__ == "__main__":
    sys.exit(main())
