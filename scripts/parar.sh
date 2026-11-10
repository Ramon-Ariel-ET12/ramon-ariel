#!/usr/bin/env bash
# Stops everything this project starts, so no container keeps running.
#
#   ./scripts/parar.sh              # stops and removes the containers; keeps the data
#   ./scripts/parar.sh --volumes    # also deletes the assistant DB and media (irreversible)
#   ./scripts/parar.sh --estado     # only shows what is running
#
# What it stops:
#   - the development stack        (project pia-asistente)
#   - the plant used for testing   (project planta, from academia2026-tp)
#   - a leftover corrector stack   (project alumno-academianovit2026), if a run was cut
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PLANT="$ROOT/academia2026-tp"

VOLUMES=0
ESTADO=0
for arg in "$@"; do
    case "$arg" in
        --volumes) VOLUMES=1 ;;
        --estado) ESTADO=1 ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "opción desconocida: $arg" >&2; exit 2 ;;
    esac
done

mostrar() {
    echo "== contenedores del proyecto"
    docker ps --format '{{.Names}}\t{{.Status}}' \
        | grep -E '^(pia-asistente|planta-|alumno-)' || echo "   (ninguno)"
}

if [ "$ESTADO" -eq 1 ]; then
    mostrar
    exit 0
fi

bajar() {  # bajar <proyecto> <archivo>
    local proyecto="$1" archivo="$2"
    [ -f "$archivo" ] || return 0
    if [ "$VOLUMES" -eq 1 ]; then
        docker compose -p "$proyecto" -f "$archivo" down --volumes --remove-orphans >/dev/null 2>&1 || true
    else
        docker compose -p "$proyecto" -f "$archivo" down --remove-orphans >/dev/null 2>&1 || true
    fi
}

bajar pia-asistente "$ROOT/docker-compose.yml"
bajar alumno-academianovit2026 "$ROOT/docker-compose.yml"
bajar planta "$PLANT/docker-compose.yml"

echo "listo"
mostrar
if [ "$VOLUMES" -eq 1 ]; then
    echo "   (se borraron los volúmenes: base del asistente y media)"
else
    echo "   (los datos se conservan; usá --volumes para borrarlos)"
fi
