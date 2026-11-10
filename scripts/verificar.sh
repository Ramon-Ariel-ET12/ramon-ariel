#!/usr/bin/env bash
# Full verification of Delivery 1, in the only order that works.
#
#   ./scripts/verificar.sh                 # everything, stack left running for inspection
#   ./scripts/verificar.sh --sin-corrector # skip the official run (reuse the last one)
#   ./scripts/verificar.sh --sin-e2e       # skip the operator probe
#   ./scripts/verificar.sh --cerrar        # stop and remove every container at the end
#
# Steps
#   1. stop the development stack  (the official run and the dev stack both publish
#      8200/8300; if the dev stack is up, the corrector's `up -d` fails with
#      "Bind for 0.0.0.0:8300 failed: port is already allocated")
#   2. official correction: martes-tranquilo + fuga-sin-enlace
#   3. independent re-scoring of the saved run
#   4. bring the development stack back up
#   5. unit + integration tests and lint
#   6. RAG evaluation
#   7. human-like end-to-end probe
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PLANT="academia2026-tp"
CORRIDA="$PLANT/correccion/corridas/academiaNovit2026"
SALIDA="${SALIDA:-$ROOT/var/audit/verificacion}"
mkdir -p "$SALIDA"

CORRECTOR=1
E2E=1
CERRAR=0
for arg in "$@"; do
    case "$arg" in
        --sin-corrector) CORRECTOR=0 ;;
        --sin-e2e) E2E=0 ;;
        --cerrar) CERRAR=1 ;;
        *) echo "opción desconocida: $arg" >&2; exit 2 ;;
    esac
done

paso() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fallos=0
resultado() {  # resultado <nombre> <código>
    if [ "$2" -eq 0 ]; then
        printf '   OK   %s\n' "$1"
    else
        printf '   FALLA %s (exit %s)\n' "$1" "$2"
        fallos=$((fallos + 1))
    fi
}

if [ ! -d "$PLANT/contrato/planta_contrato" ]; then
    echo "Falta el repo de la planta en $PLANT (git clone https://github.com/NovitSoftware/academia2026-tp)" >&2
    exit 2
fi

if [ "$CORRECTOR" -eq 1 ]; then
    paso "1/7 Deteniendo el stack de desarrollo (libera 8200 y 8300)"
    docker compose stop >/dev/null 2>&1 || true
    for puerto in 8200 8300; do
        if ss -ltn 2>/dev/null | grep -q ":$puerto "; then
            echo "   el puerto $puerto sigue ocupado: pará el proceso que lo usa" >&2
            exit 1
        fi
    done
    echo "   8200 y 8300 libres"

    paso "2/7 Corrección oficial (martes-tranquilo + fuga-sin-enlace)"
    rm -rf "$CORRIDA"
    uv run --with httpx --with pyyaml python "$PLANT/correccion/corregir.py" \
        --repo "$ROOT" --alumno "${ALUMNO:-Ramón Ariel}" \
        --escenarios martes-tranquilo fuga-sin-enlace 2>&1 | tee "$SALIDA/correccion.log"
    resultado "corrección oficial" "${PIPESTATUS[0]}"

    paso "3/7 Verificación independiente de la corrida guardada"
    for escenario in martes-tranquilo fuga-sin-enlace; do
        uv run python scripts/audit_escenario.py "$CORRIDA/$escenario.json" \
            2>&1 | tee "$SALIDA/audit-$escenario.txt"
        resultado "auditoría $escenario" "${PIPESTATUS[0]}"
    done
fi

paso "4/7 Levantando el stack de desarrollo"
docker compose up -d >/dev/null 2>&1
for _ in $(seq 1 40); do
    curl -sf http://localhost:8200/health >/dev/null 2>&1 && break
    sleep 2
done
curl -sf http://localhost:8200/health && echo || { echo "el asistente no respondió" >&2; fallos=$((fallos + 1)); }

paso "5/7 Pruebas y lint"
DB_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' pia-asistente-db-1 2>/dev/null)"
if [ -n "$DB_IP" ]; then
    TEST_DATABASE_URL="postgresql://${POSTGRES_USER:-pia}:${POSTGRES_PASSWORD:-pia-local-dev}@$DB_IP:5432/${POSTGRES_DB:-pia}" \
        uv run pytest -q 2>&1 | tail -3
    resultado "pytest (con Postgres real)" "${PIPESTATUS[0]}"
else
    uv run pytest -q 2>&1 | tail -3
    resultado "pytest (sin Postgres: 1 skip)" "${PIPESTATUS[0]}"
fi
uv run ruff check . 2>&1 | tail -2
resultado "ruff" "${PIPESTATUS[0]}"

paso "6/7 Evaluación del RAG (71 preguntas)"
uv run python evaluacion/retrieval_eval.py 2>&1 | tee "$SALIDA/retrieval.txt" | head -4
resultado "RAG" "${PIPESTATUS[0]}"

if [ "$E2E" -eq 1 ]; then
    paso "7/7 Punta a punta con el operador virtual"
    uv run python scripts/e2e_probe.py --reiniciar \
        --texto "La bomba está en ciento doce kilos de descarga." \
        --items '[{"tag":"B-101","variable":"presion_descarga_local","valor":112,"unidad":"kg/cm2"}]' \
        --segundos 70 2>&1 | tee "$SALIDA/e2e.txt" | grep -E "TABLET|EVENTO|texto:|fila:|opciones|== " | head -20
    resultado "end-to-end" "${PIPESTATUS[0]}"
fi

if [ "$CERRAR" -eq 1 ]; then
    paso "Cerrando contenedores"
    "$ROOT/scripts/parar.sh"
fi

paso "Resumen"
if [ "$fallos" -eq 0 ]; then
    echo "Todo pasó. Evidencia en $SALIDA"
else
    echo "$fallos paso(s) con falla. Evidencia en $SALIDA"
fi
exit $(( fallos > 0 ))
