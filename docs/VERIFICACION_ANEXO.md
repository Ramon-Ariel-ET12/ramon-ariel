# Verificación del Anexo — Entrega 1

Cada fila corresponde a un requisito del **Anexo de entregas** (Entrega 1). La columna
*Evidencia* apunta al código, al comando o al artefacto que lo demuestra; la columna
*Estado* usa **MET**, **PARCIAL** o **NO**.

Método: lectura del anexo, inspección del árbol en `HEAD`, `docker compose config`,
`docker inspect` de la pila en ejecución, consultas a PostgreSQL y a la API de la planta,
`pytest`, `ruff`, `corrector.py` y `evaluacion/retrieval_eval.py`.

## Repo y ejecución

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 1 | Repo público `nombre-apellido` con `README.md`, `docker-compose.yml` y `tests/` en la raíz | **NO** | `git remote -v` vacío: no hay repo público. Los tres archivos existen. Es el único bloqueante de la entrega. |
| 2 | `docker compose up` levanta el sistema al lado de la planta | MET | `docker compose config` (redes externas `planta-lan` y `planta-control`); `docker compose up -d` levanta `cerebro`, `db`, `panel` y `nube-sync` y el sistema queda `ready`. |
| 3 | Servicios de planta solo en `planta-lan` y con `academia.planta: pc` | PARCIAL | Los tres servicios de planta (`cerebro`, `db`, `panel`) llevan el label. `cerebro` y `db` están **solo** en `planta-lan`; `panel` es el ingreso dual-homed (`planta-lan` + `planta-control`) porque `planta-lan` es `internal` y Docker no publica puertos de un contenedor que solo está ahí. Único servicio fuera de la PC de planta: `nube-sync` (sin label, en `planta-control`). `scripts/check_compose_budget.py` lo verifica sobre el compose resuelto. |
| 4 | Suma de límites ≤ 4 CPU y 8 GB | MET | `deploy.resources.limits`: cerebro 3 CPU/6 GiB + db 0,5/1 GiB + panel 0,25/128 MiB = **3,75 CPU / 7,1 GiB**; con `nube-sync` 4,0 CPU / 7,4 GiB. |
| 5 | `HTTP(S)_PROXY=http://enlace:3128`, `NO_PROXY=broker,sim,localhost` | MET | Los tres servicios de planta llevan los tres valores exactos (`docker compose config`). El cliente HTTP de la planta usa `trust_env=False`, así que el proxy no intercepta `sim`/`broker`. |
| 6 | `planta_contrato` instalado con pip, sin copia de modelos | MET | `Dockerfile`: `uv pip install` del paquete (contexto `contrato` o `git+https://github.com/NovitSoftware/academia2026-tp#subdirectory=contrato`, público y verificado). En el contenedor: `site-packages/planta_contrato/__init__.py`, versión 0.2.0. No hay modelos del contrato en `app/`. |
| 7 | Latido `sistema/estado` cada 30 s con `sistema`, `enlace_ok`, `pendientes_sincronizar` | MET | `app/heartbeat.py` publica los tres campos; `heartbeat_seconds=30`. Medido en la corrida: 28 latidos/0 huecos y 24/0. |
| 8 | PostgreSQL 16 con pgvector en el compose | MET | `pgvector/pgvector:pg16`; en ejecución: PostgreSQL 16.15 y `vector` 0.8.7. |

## A. Parte por voz

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 9 | Escucha `planta/recorridas` y baja audio y fotos de `http://sim:8100{audio_url}` | MET | `main.py` suscribe el tópico; `PlantClient.download` resuelve rutas relativas contra `PLANT_URL`. |
| 10 | Transcripción con un modelo local de la lista cerrada | PARCIAL | `faster-whisper small`, int8, CPU, `local_files_only`, horneado en la imagen: es local y funciona con el enlace caído. La lista cerrada no está publicada en el material, así que no se puede verificar la pertenencia. |
| 11 | Structured output validado a `FilaParte`: fila por equipo+variable, hora = ts de la nota, fotos en su fila | MET | Parser determinista → `ExtractedRow`; cada `MensajeTablet` se valida contra el contrato (incluye `FilaParte`). Eventos y mensajes usan `note.ts`, no el reloj de la máquina. Las fotos se asignan a la fila de la cláusula que las menciona. |
| 12 | Nombres informales contra `GET /api/planta`; si queda ambiguo, pregunta | MET | `EquipmentIndex` construye alias desde `equipos[].nombres` ("la dos", "el de la izquierda", "la de reserva"); "la bomba"/"el filtro" sin calificador → pregunta con opciones. |
| 13 | Unidades: kilos = kg/cm²; B-101 kg/cm², B-102 psi, B-103 bar; "dieciocho" vs "uno ocho" se pregunta | MET | `unidad_manometro` por equipo desde `/api/planta` (verificado: kg/cm2 / psi / bar); `kilos → kg/cm2`; el diferencial ambiguo se pregunta con opciones. |
| 14 | Rango histórico de 45 días; fuera de rango pide confirmación | MET | `HistoricalValidator` consulta `/api/historian/{tag}/{variable}` con `desde = ts − 45 días`; fuera del rango observado pregunta y aplica la respuesta (o la descarta si el operador niega). |
| 15 | Tablet: borrador en `pantalla.filas`, opciones al elegir, entiende respuestas habladas y reenvía el borrador; Borrador → Confirmado | MET | `_send_tablet` arma `pantalla.filas`/`opciones`; `read_reply` interpreta "No, la uno estaba en ciento quince kilos"; `parts.status` pasa a `confirmed`. En la corrida A2/A3 dan 69 % por límites del operador virtual, no del flujo. |
| 16 | Notas `VIVO-`: sin parte esperado y pueden no traer nada | MET | `tests/test_workflow_flow.py`: nota `VIVO-` vacía no genera evento ni borrador; nota `VIVO-` con lectura real genera el parte. |

## B. Detección en planta

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 17 | Evento por parte confirmado y por desvío de `planta/sensores/#`: id idempotente, origen, `nota_ids` | MET | `note_events` (uno por equipo, `uuid5` determinista, `origen: parte`, `nota_ids`); `SensorDetector` publica el evento del episodio sostenido con id persistido en `sensor_state`. |
| 18 | Límites de `planta.yaml`/`/api/planta`, no del manual; misma data → misma decisión | MET | `snapshot.limits` (alarma alta/baja/disparo) desde la API con fallback `datos/planta.yaml`; detección determinista, sin LLM ni nube. |
| 19 | SinNovedad o Escalado con contexto; sostenida sí, pico no; "parada, en reserva" no es anomalía | MET | `note_events` + `build_event_context` (filas, fotos, tendencia de 6 h, secciones citadas, historial de órdenes, repuestos); ventana de 5 min/3 muestras/80 % con histéresis; `NORMAL_STATES` incluye "parada, en reserva". |
| 20 | Alerta S1–S4 local, tablet con procedimiento y aviso por radio, `espera_respuesta: false`, < 30 s, sin falsas alarmas | MET | `app/domain/safety.py` (detector local sobre el texto, también parcial); `emergency_text` nombra el procedimiento y el aviso por radio; `waits=False`. Medido: **20,4 s** en la corrida oficial, 0 falsas alarmas. |

## Tools y MCP

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 21 | Tools de solo lectura con Pydantic estricto (`extra="forbid"`): equipos, sensores, órdenes, inventario/stock/BOM, tareas, manuales | MET | `app/tools/contracts.py` (`StrictModel`: `extra="forbid", strict=True`) para las seis familias; `queries.py` solo lee. |
| 22 | Al menos una expuesta por un servidor MCP | MET | `app/integrations/mcp_server.py` (FastMCP, 8 tools, stdio); `tests/test_mcp.py` levanta el servidor y llama una tool. |
| 23 | Manejo de errores, timeouts y reintentos en cada tool | MET | `audited()` aplica timeout duro (2–20 s según la tool) y un reintento a **las ocho**; el cliente de planta reintenta 3 veces con espera; los errores se tipan como `ToolError` y se auditan. Tests: `test_every_tool_has_a_timeout_and_one_retry`, `test_tool_that_recovers_on_retry_returns_the_value`. |
| 24 | Tests automatizados de cada tool en `tests/` | MET | `tests/test_tools.py` cubre las seis familias y los caminos de error; `tests/test_mcp.py` el servidor. |

## Control y evaluación

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 25 | Condiciones de corte, presupuesto de pasos y tokens, timeout global por nota | MET | `NOTE_TIMEOUT_S=180` (deadline por nota, aplicado con `asyncio.wait_for` a ASR y descargas), `MAX_ATTEMPTS=6`, `MAX_NOTE_STEPS=8`, `TOKEN_BUDGET=8000` (corta el LLM opcional). Todos configurables y aplicados en el bucle. |
| 26 | Mini spec del flujo del parte en el repo | MET | `docs/SPEC_PARTE.md`: máquina de estados, mensajes de tablet, correcciones, presupuesto y eventos posteriores. |
| 27 | Primera evaluación contra `/api/verdad`: aciertos por campo y preguntas solo en ambiguas | MET | `evaluacion/evaluar_parte.py` (usa `/api/verdad`, compara por TAG+valor+unidad y cuenta preguntas). Corrida registrada: 8/8 notas, 11/15 campos, 1/1 ambigua preguntada. La medición oficial es A2/A3/A4 del corrector. |

## RAG, contexto y memoria

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 28 | Indexa en pgvector con metadatos de equipo, fabricante, documento, sección, cita y vigente | MET | `rag_chunks` tiene las seis columnas; 681/701 fragmentos con equipo y fabricante (los 20 sin equipo son órdenes de planta sin TAG); cita = id del fragmento; `current` desde `vigente`. |
| 29 | Trampas: Rev. C vencida, secciones de otros modelos, códigos → F01–F10 (MBP-4 §6) | MET | Los fragmentos con `vigente=false` (108, Rev. C) **no se devuelven** (filtro en SQL y en el índice en memoria); el manual de otro modelo se penaliza ×0,55 salvo que la pregunta lo nombre (incluye títulos "otros modelos"); `expand_query` traduce códigos a F01–F10 en la consulta léxica, en los dos caminos. |
| 30 | recall@k con 71 preguntas, `corpus.evaluar.evaluar`, comparación con BM25 y Rev. C antes que D | MET | `evaluacion/retrieval.json` (71), `retrieval_eval.py` llama al evaluador del repo de la planta. Híbrido **hit@5 0,873 / recall@5 0,718 / MRR 0,678**; BM25 0,859/0,674/0,581; Rev. C antes que D: **0** contra 6. |
| 31 | Cada conclusión cita la sección del manual | MET | `build_event_context` guarda `sections` con la cita; `_enrich_event` la persiste en `events.context`; el panel la muestra ("fuentes: TX350-D §3.2"); la tool de manuales devuelve `cita`. |
| 32 | Justificación de qué va por RAG y qué por API/SQL (límites y stock no salen del RAG) | MET | `docs/MEMORIA.md` §"Qué se consulta por RAG y qué por API o SQL": tabla por clase de consulta y por qué. |
| 33 | Context builder diseñado | MET | `app/rag/context.py`: evento, filas, fotos, tendencia de sensores, secciones citadas, historial de órdenes y repuestos; el análisis completo queda para la Entrega 2. |
| 34 | Memoria: estado de conversación por nota en Postgres y política escrita | MET | `notes`, `parts`, `attempts`, `tablet_messages`, `replies` (todas en `schema.sql`, escritas desde el workflow); `docs/MEMORIA.md` con qué se guarda, cuánto y cuándo se borra. |

## Cómo se verifica

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 35 | `corregir.py --escenarios martes-tranquilo fuga-sin-enlace` mide A1–A4b, B1, B2, F1, F2 | MET | Corrida oficial: **91,3 / 100 · APRUEBA**; A1 100, A4a 100, A4b 100, B1 100, B2 100, E1–E3 100, F1 100, F2 100; A2/A3 69 %. |
| 36 | Eliminatorias: `sin_alerta_de_seguridad`, `sistema_mudo` | MET | `eliminatorias: {}` en `resultado.json`; alerta S1 publicada a los 20,4 s. |

## Resumen

- **MET: 33** · **PARCIAL: 2** (`panel` dual-homed, lista cerrada de modelos no
  publicada) · **NO: 1** (repo público). El conjunto etiquetado es `cerebro` + `db` +
  `panel`; el único servicio fuera de la PC de planta es `nube-sync`; el dual-homing del
  `panel` es la desviación documentada, con su motivo.
- El único bloqueante real es el **repo público** (requisito 1): no hay remoto y el commit
  está solo local. No depende del código.
- Los otros dos parciales están acotados y documentados: el `panel` es el ingreso sin
  estado que exige que `planta-lan` sea `internal`, y la lista cerrada es información que
  la cátedra no publicó.
