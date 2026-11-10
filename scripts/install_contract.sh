#!/usr/bin/env bash
# Install the provided integration contract with pip. It is never copied into the repo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${1:-${PLANTA_CONTRATO_DIR:-$ROOT/academia2026-tp/contrato}}"

if [ -d "$SOURCE/planta_contrato" ]; then
    echo "Instalando planta_contrato desde $SOURCE"
    uv pip install "$SOURCE"
else
    echo "Instalando planta_contrato desde la fuente pública"
    uv pip install "git+https://github.com/NovitSoftware/academia2026-tp#subdirectory=contrato"
fi
