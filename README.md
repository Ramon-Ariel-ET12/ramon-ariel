# PIA-3 · Parte por voz, detección en planta y órdenes

Sistema para la planta de inyección de agua PIA-3 de la Academia Novit 2026, primera
entrega: **parte de recorrida por voz**, **detección determinista en planta**,
**alerta de seguridad local**, **herramientas de solo lectura + MCP** y **RAG con
pgvector medido contra BM25**.

El repositorio se levanta al lado de la planta simulada (repo `academia2026-tp`, que no
forma parte de esta entrega) con `docker compose up`.

## Arquitectura

```
planta-lan (interna, sin internet)                         planta-control (internet)
┌────────────────────────────────────────────────┐         ┌───────────────────────┐
│ broker MQTT        sim (API + historiador)      │         │ enlace :3128 (proxy)  │
│       │                  ▲                     │         └──────────┬────────────┘
│       ▼                  │ HTTP directo        │                    │
│  ┌──────────────────────────────────────────┐  │                    ▼
│  │ cerebro  (label academia.planta=pc)      │  │          ┌─────────────────────┐
│  │  MQTT · flujo del parte · eventos        │──┼─proxy───▶│ nube-sync (réplica) │
│  │  reglas · órdenes · RAG · tools · MCP    │  │          └─────────────────────┘
│  │  ASR local · parser · LLM local opcional │  │
│  │  UI :8200                               │  │
│  └──────────────────┬───────────────────────┘  │
│                     ▼                          │
│          db (PostgreSQL 16 + pgvector, pc)     │
└────────────────────────────────────────────────┘
```

### Qué corre en la planta y qué en la nube

- **Planta (`cerebro` + `db`, solo `planta-lan`, 4 CPU / 8 GB entre ambos)**:
  recepción MQTT, descarga de audio y fotos, transcripción local, detección de
  condición insegura, extracción del parte, diálogo con la tablet, eventos, reglas de
  aprobación, órdenes, herramientas locales, índice y búsqueda de manuales, memoria.
  Nada de esto necesita internet: el enlace puede estar caído y la planta sigue
  operando y alertando.
- **Nube (`nube-sync`, red `planta-control`)**: réplica/archivo de eventos, órdenes,
  partes y digests de sensores. Es lo que hace medible `pendientes_sincronizar`.
  Nunca participa de la detección ni de la alerta de seguridad.

Justificación: el hardware de planta (4 núcleos, 8 GB, sin GPU) alcanza para
`faster-whisper small` int8 y un modelo de lenguaje de 0,5 B opcional; la latencia de
la nube es incompatible con la alerta de 30 s.

## Requisitos

- Docker 24+ con Compose v2.
- El repo de la planta `academia2026-tp` al lado de este repo (para desarrollo y
  corrección). Crea las redes externas `planta-lan` y `planta-control`.
- `uv` para desarrollo local y tests.
- `planta_contrato` instalado con pip (ver abajo).

## Cómo levantarlo

### 1. Levantar la planta

```bash
cd academia2026-tp
docker compose up -d --build
```

### 2. Instalar el contrato de integración

El mecanismo documentado es:

```bash
pip install "git+https://github.com/NovitSoftware/academia2026-planta#subdirectory=contrato"
```

En este entorno ese repositorio no está publicado (devuelve *Repository not found*).
El build acepta el checkout local provisto como contexto, **sin copiar los modelos**:

```bash
export PLANTA_CONTRATO_DIR="$PWD/academia2026-tp/contrato"
```

### 3. Levantar el sistema

```bash
PLANTA_CONTRATO_DIR="$PWD/academia2026-tp/contrato" docker compose up -d --build
```

- Central de mantenimiento / estado: <http://localhost:8200>
- API de estado: <http://localhost:8200/api/state>
- Salud: <http://localhost:8200/health>

El compose usa `postgres` con pgvector, aplica el esquema al arrancar y deja el
latido en `sistema/estado` cada 30 s.

Para habilitar el LLM local opcional (no se hornea por defecto porque no está en el
camino evaluado):

```bash
docker compose build --build-arg DOWNLOAD_LLM=1 cerebro
LLM_ENABLED=true docker compose up -d cerebro
```

### 4. Desarrollo local (sin Docker)

```bash
uv sync
uv pip install ./academia2026-tp/contrato      # o: pip install -e ./academia2026-tp/contrato
cp .env.example .env                          # ajustar DATABASE_URL, PLANT_URL, MQTT_HOST
uv run python -m app.main
```

`uv sync` no instala el contrato (es un paquete externo provisto por la cátedra); por
eso el paso explícito. `uv.lock` fija el resto de las dependencias.

## Variables de entorno

| Variable | Default | Uso |
|---|---|---|
| `SISTEMA_NOMBRE` | `Academia Novit` | campo `sistema` del latido |
| `DATABASE_URL` | `postgresql://pia:pia-local-dev@localhost:5432/pia` | Postgres (en compose: `db`) |
| `PLANT_URL` | `http://localhost:8100` | API de la planta (en compose: `sim`) |
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` | broker (en compose: `broker`) |
| `LINK_CONTROL_URL` | `http://localhost:8081` | puerto de control del enlace |
| `CLOUD_SYNC_URL` | `http://localhost:8300` | réplica en nube (vía proxy) |
| `HTTP_PROXY` / `HTTPS_PROXY` | — | `http://enlace:3128` en planta |
| `NO_PROXY` | — | `broker,sim,localhost` |
| `ASR_MODEL` | `/models/faster-whisper-small` | modelo ASR local |
| `ASR_THREADS` / `ASR_BEAM_SIZE` | `4` / `5` | decodificación |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | embeddings RAG |
| `LLM_ENABLED` | `false` | habilita el LLM local opcional para respuestas libres |
| `LLM_MODEL` | `/models/qwen2.5-0.5b-instruct` | modelo local opcional |
| `NOTE_TIMEOUT_S` | `90` | timeout global por nota |
| `MAX_ATTEMPTS` | `6` | borradores por nota |
| `HEARTBEAT_SECONDS` | `30` | latido |
| `SYNC_BATCH_SIZE` | `50` | cola de nube |
| `MEDIA_DIR` | `/data/media` | audio y fotos |
| `LOG_LEVEL` | `INFO` | logging |

## Cómo funciona

### Parte por voz

`planta/recorridas` → descarga del WAV → **faster-whisper** local → detección de
seguridad S1–S4 en código → parser determinista de habla de campo → borrador en
`pantalla.filas` → respuesta del operador (`planta/respuestas`) → corrección o
confirmación → parte **Confirmado** → eventos.

- Una fila por equipo y variable, con la hora de la nota (no el reloj de la máquina).
- Nombres informales desde `GET /api/planta`; ambigüedad de equipo → pregunta con
  opciones; diferencial "dieciocho" → pregunta y valor reparado.
- Unidades: `kilos` = kg/cm²; manómetro local por equipo (kg/cm² en B-101, psi en
  B-102, bar en B-103), `grados`, `metros`, `gotas/min`.
- Rango histórico: `GET /api/historian/{tag}/{variable}` (45 días), percentiles
  robustos; un valor fuera de rango pide confirmación.
- Fotos descargadas y asociadas a la fila; el contrato `FilaParte` no tiene campo de
  hora ni de foto, así que se persisten en Postgres y se usan en la evidencia.
- `VIVO-…` no tiene parte esperado; se procesa igual y puede no reportar nada.
- Spec de trabajo: [`docs/SPEC_PARTE.md`](docs/SPEC_PARTE.md).

### Detección y alertas

- Un evento por equipo del parte (`SinNovedad` o `Escalado`) y por desvío sostenido de
  sensores. Ids `uuid5` estables; los mismos datos dan la misma decisión.
- Límites de `planta.yaml` / `GET /api/planta`; nunca del manual Rev. C.
- Sensor: agregación por minuto simulado, ventana de 5 min con al menos 3 muestras e
  histéresis; un pico aislado no escala. `parada, en reserva` no es anomalía.
- Seguridad: S1 agua a presión, S2 olor a gas, S3 humo/fuego, S4 persona lesionada.
  Detecta en código, sin nube, y publica `AlertaSeguridad` + aviso de tablet
  (`espera_respuesta: false`) con el aviso por radio al supervisor.

### Órdenes y reglas

La propuesta de tarea es determinista (evidencia → tarea). Se publica `Borrador` y
después `Aprobada` o `PendienteAprobacion` con motivo. Las cinco reglas se aplican en
código contra el estado de bombas al decidir: tarea estándar, inyección mantenida,
stock en el yacimiento, costo < USD 2.500, personal propio. Daño estructural en foto o
estado de planta desconocido → pendiente. No hay aprobación por texto de una nota,
historial o manual.

### Herramientas y MCP

Tools de solo lectura con Pydantic `extra="forbid"`, timeout y reintentos:
equipos, historial de sensores, historial de órdenes, inventario, stock, lista de
materiales, catálogo de tareas y búsqueda en manuales. También se exponen como tools
de LangChain y por **MCP**:

```bash
docker compose exec cerebro python -m app.integrations.mcp_server   # stdio
```

Tests: `tests/test_tools.py` y `tests/test_mcp.py`.

### RAG

- Ingesta de `/documentos/fragmentos.jsonl` (701 fragmentos) con metadata: documento,
  fabricante/emisor, equipos, sección, cita, página y vigencia.
- PostgreSQL + pgvector, HNSW; búsqueda híbrida BM25 español + vectorial con RRF y
  re-ranking por metadata (penaliza `vigente=false` y secciones de otros modelos).
- Evaluación: `uv run python evaluacion/retrieval_eval.py` (71 preguntas, recall@k,
  comparación con BM25 y conteo de Rev. C antes que D).
- Límites y stock **no** salen del RAG: vienen de la API y de los datos estructurados.
- Context builder para el análisis: `app/rag/context.py` (el análisis completo es de
  la Entrega 2).
- Códigos de fabricante traducidos a F01–F10 con la tabla del MBP-4 §6
  (`app/rag/codes.py`).

### Persistencia, offline y reinicio

- Postgres guarda notas, transcripciones, partes, intentos, mensajes de tablet,
  respuestas, eventos, órdenes, decisiones, ventanas de sensores, cola de nube y
  consumo de modelos.
- Idempotencia por `id` en notas, eventos, órdenes, tablet y respuestas.
- Cola de sincronización hacia `nube-sync` a través del proxy; `pendientes_sincronizar`
  es su profundidad y `enlace_ok` sale del puerto de control del enlace.
- Al reiniciar se reanudan notas pendientes y se re-publican las órdenes abiertas con
  el mismo id y estado, nunca como `Borrador`.
- Política de memoria y retención: [`docs/MEMORIA.md`](docs/MEMORIA.md).

## Pruebas

```bash
uv sync
uv pip install ./academia2026-tp/contrato
uv run pytest -q
```

Cobertura: números y unidades, parser de las notas reales, ambigüedad, correcciones,
contratos estrictos, eventos deterministas, pico vs sostenido, seguridad, reglas de
aprobación, órdenes, tools, MCP, RAG/BM25, cola de sincronización, latido, rango
histórico e idempotencia (integración con `TEST_DATABASE_URL`).

## Evaluación oficial

Con la planta levantada y el contrato disponible:

```bash
PLANTA_CONTRATO_DIR="$PWD/academia2026-tp/contrato" \
uv run --with httpx --with pyyaml python academia2026-tp/correccion/corregir.py \
  --repo . --alumno "Ramón Ariel" \
  --escenarios martes-tranquilo fuga-sin-enlace
```

El resultado queda en `academia2026-tp/correccion/corridas/academiaNovit2026/`
(`informe.md`, `resultado.json`). Se evalúan A1–A4b, B1, B2, F1, F2 y las eliminatorias
`sin_alerta_de_seguridad` y `sistema_mudo`.

## Resultados medidos

- **Evaluación oficial (`martes-tranquilo` + `fuga-sin-enlace`): 91,3 / 100 · APRUEBA,
  sin faltas eliminatorias.** A1 100 %, A2 69 %, A3 69 %, A4a 100 %, A4b 100 %,
  B1 100 %, B2 100 %, E1/E2/E3 100 %, F1/F2 100 %. Las notas no confirmadas son las que
  no tienen ninguna fila con valor (solo "parada, en reserva" o la condición insegura);
  el operador virtual no puede confirmarlas porque no hay valores que comparar.
  Detalle: [`docs/RESULTADOS.md`](docs/RESULTADOS.md).
- RAG: hit@5 0,873 / recall@5 0,718 contra BM25 0,859 / 0,674; Rev. C antes que D: 0
  contra 6/71 (`evaluacion/informe_retrieval.json`).
- ASR: 1,86 s de latencia media por nota y extracción exacta de las 8 notas de prueba
  de `martes-tranquilo`.
- Pruebas: 109 passed, 1 skipped.

## Limitaciones conocidas

- La fuente git documentada de `planta_contrato` no está publicada; el build usa el
  checkout provisto como contexto (`PLANTA_CONTRATO_DIR`). Sin ese contexto ni la
  fuente git, el build falla explícitamente: no se copian ni reimplementan modelos.
- La lista cerrada de modelos no fue provista; los modelos elegidos y sus versiones
  están en [`INFORME.md`](INFORME.md) y son configurables.
- La extracción del parte es determinista por diseño (hardware y reproducibilidad);
  el LLM local es opcional y solo interpreta respuestas libres. No decide reglas.
- La central de aprobación/certificación (G2/G3) corresponde a la Entrega 2: el
  contrato no tiene un canal de decisiones humanas.
- Las notas con solo observaciones (sin filas numéricas) no se pueden confirmar por
  comparación de valores; se muestran y se confirman al recibir la respuesta.
- El ASR y los embeddings requieren descargar modelos en el build; en runtime no hay
  internet en la planta. El LLM local opcional solo se hornea con
  `DOWNLOAD_LLM=1`.
- La confirmación por rango histórico se pide solo cuando el valor está fuera de la
  banda de la hoja de datos; un valor nuevo pero dentro de banda no se cuestiona.
