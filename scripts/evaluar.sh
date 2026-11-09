#!/usr/bin/env bash
# Official correction for the first deliverable.
#   scripts/evaluar.sh [escenario ...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PLANTA_CONTRATO_DIR="${PLANTA_CONTRATO_DIR:-$ROOT/academia2026-tp/contrato}"
ALUMNO="${ALUMNO:-Ramón Ariel}"

if [ "$#" -gt 0 ]; then
    ESCENARIOS=("$@")
else
    ESCENARIOS=(martes-tranquilo fuga-sin-enlace)
fi

cd "$ROOT"
uv run --with httpx --with pyyaml python academia2026-tp/correccion/corregir.py \
    --repo "$ROOT" \
    --alumno "$ALUMNO" \
    --escenarios "${ESCENARIOS[@]}"
