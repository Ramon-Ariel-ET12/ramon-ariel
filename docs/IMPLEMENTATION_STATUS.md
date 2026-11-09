# Estado de implementación · Entrega 1

Auditoría contra el Enunciado y el Anexo de la Entrega 1. Un requisito se marca
`DONE` solo si tiene código y una prueba o corrida que lo respalde. Los estados
`PENDING` se actualizan con los resultados reales al final de la corrida.

Leyenda: **DONE** implementado y verificado · **PARTIAL** implementado con validación
incompleta · **PENDING** no ejecutado aún · **BLOCKED** depende de un recurso externo.

## Resultado de la evaluación oficial

**91,3 / 100 · APRUEBA**, sin faltas eliminatorias, en `martes-tranquilo` y
`fuga-sin-enlace`. Detalle completo en [`RESULTADOS.md`](RESULTADOS.md); corrida en
`var/corrida6/` del workspace y en `academia2026-tp/correccion/corridas/`.

## Infraestructura e integración

| ID | Requisito | Estado | Evidencia / archivo | Falta |
|---|---|---|---|---|
| I1 | Repo público con README, docker-compose.yml y tests/ en la raíz | DONE | `README.md`, `docker-compose.yml`, `tests/` | publicar el repo |
| I2 | `docker compose up` levanta el sistema al lado de la planta | DONE | `docker-compose.yml`, `Dockerfile`; stack real con cerebro + db + nube-sync; latido válido en `sistema/estado` | — |
| I3 | Servicios de planta solo en `planta-lan`, label `academia.planta: pc` | DONE | `docker-compose.yml` | verificación en runtime |
| I4 | Límite conjunto 4 CPU / 8 GB | DONE | `cerebro` 3 CPU/6 GB + `db` 1 CPU/1.5 GB | — |
| I5 | Proxy `enlace:3128` y `NO_PROXY=broker,sim,localhost` | DONE | `docker-compose.yml` | — |
| I6 | `planta_contrato` instalado con pip, sin copiar modelos | DONE | `Dockerfile` (contexto `contrato` o git documentado), `app/contract.py` | la fuente git documentada no está publicada (ver bloqueos) |
| I7 | Latido `sistema/estado` cada 30 s con `sistema`, `enlace_ok`, `pendientes_sincronizar` | DONE | `app/main.py`, `app/heartbeat.py`, `tests/test_sync_history.py` | — |
| I8 | PostgreSQL 16 + pgvector en el compose | DONE | `pgvector/pgvector:pg16`, `app/persistence/schema.sql` | — |
| I9 | Configuración por entorno, sin credenciales en el repo | DONE | `app/config.py`, `.env.example` | — |

## A. Parte por voz

| ID | Requisito | Estado | Evidencia | Falta |
|---|---|---|---|---|
| A1 | Escucha `planta/recorridas` y baja audio y fotos de `sim:8100` | DONE | `app/main.py`, `app/processing/workflow.py`, `app/integrations/plant_api.py` | — |
| A2 | Transcripción local, sin nube | DONE | `app/processing/asr.py`; WER 0,251, latencia 1,86 s media; extracción 8/8 sobre las hipótesis ASR (`tests/test_parser.py`) | — |
| A3 | Structured output validado a `FilaParte` | DONE | `app/domain/parser.py`, `app/publisher.py`, `tests/test_contract_validation.py` | — |
| A4 | Una fila por equipo y variable, aunque la nota los mezcle | DONE | `tests/test_parser.py` (8 notas de martes + fuga) | — |
| A5 | Hora igual al `ts` de la nota | DONE | `PartDraft.ts`, `notes.ts`; `tests/test_parser.py` | `FilaParte` no tiene `hora`: se persiste y se usa el `ts` del evento |
| A6 | Fotos asociadas a la fila | DONE | `photo` en `ExtractedRow`, `tests/test_parser.py` | — |
| A7 | Nombres informales resueltos contra `/api/planta` | DONE | `app/domain/equipment.py`, `tests/test_parser.py` | — |
| A8 | Ambigüedad de equipo → pregunta | DONE | `app/processing/workflow.py`, `tests/test_workflow_pure.py` | — |
| A9 | Unidades: kilos, psi, bar, manómetro por equipo | DONE | `app/domain/units.py`, `tests/test_numbers_units.py`, `tests/test_parser.py` | — |
| A10 | Diferencial "dieciocho" → preguntar | DONE | `app/domain/parser.py`, `tests/test_parser.py` | — |
| A11 | Rango histórico desde el historian (45 días) | DONE | `app/domain/history.py`, `tests/test_sync_history.py` | — |
| A12 | Valor fuera de rango → confirmación | DONE | `app/processing/workflow.py` (`_confirm_historical_range`) | — |
| A13 | Tablet: borrador con `pantalla.filas` y opciones | DONE | `app/processing/workflow.py`, `docs/SPEC_PARTE.md` | — |
| A14 | Entiende respuestas de campo y reenvía el borrador corregido | DONE | `app/processing/replies.py`, `tests/test_replies.py` | — |
| A15 | Borrador → Confirmado, con acuse | DONE | `app/processing/workflow.py` | — |
| A16 | Notas `VIVO-…` sin parte esperado | DONE | `workflow._handle_empty`, `enqueue` detecta `VIVO-` | — |
| A17 | Condiciones de corte, presupuesto de pasos/tokens y timeout global | DONE | `Settings.note_timeout_s/max_attempts/token_budget`, `docs/SPEC_PARTE.md` | — |
| A18 | Mini spec del flujo | DONE | `docs/SPEC_PARTE.md` | — |
| A19 | Primera evaluación contra `/api/verdad` | DONE | `evaluacion/evaluar_parte.py`; medición oficial de campos y preguntas en A2–A4b | — |

## B. Detección en planta

| ID | Requisito | Estado | Evidencia | Falta |
|---|---|---|---|---|
| B1 | Cada parte confirmado y cada desvío genera `EventoSistema` | DONE | `app/domain/events.py`, `app/domain/sensors.py` | — |
| B2 | Idempotente, `origen` parte/sensor y `nota_ids` | DONE | `uuid5` deterministas, `tests/test_events_sensors.py` | — |
| B3 | Límites de `planta.yaml`/`/api/planta`, no del manual Rev. C | DONE | `app/domain/events.py` usa `PlantSnapshot.limits` | — |
| B4 | Misma entrada → misma decisión | DONE | sin LLM; `tests/test_events_sensors.py` | — |
| B5 | `SinNovedad` o `Escalado` con contexto | DONE | `note_events` + `events.context`, `app/rag/context.py` | — |
| B6 | Anomalía sostenida, no pico aislado | DONE | `SensorWindow`, `tests/test_events_sensors.py` | — |
| B7 | "parada, en reserva" no es anomalía | DONE | `tests/test_events_sensors.py` | — |
| B8 | Alerta S1–S4 local, sin nube | DONE | `app/domain/safety.py`, `tests/test_events_sensors.py` | — |
| B9 | Aviso en tablet con radio y supervisor, `espera_respuesta: false` | DONE | `emergency_text`, `workflow._handle_safety` | — |
| B10 | `AlertaSeguridad` en menos de 30 s reales | DONE | B2 = 100 % en la corrida oficial; aviso y alerta dentro de la ventana | — |
| B11 | Sin falsas alarmas | DONE | negaciones y patrones, `tests/test_events_sensors.py` | — |

## C. Herramientas y MCP

| ID | Requisito | Estado | Evidencia | Falta |
|---|---|---|---|---|
| C1 | Tools de solo lectura con Pydantic `extra="forbid"` | DONE | `app/tools/contracts.py`, `app/tools/queries.py` | — |
| C2 | Equipos, historial de sensores, historial de órdenes | DONE | `tests/test_tools.py` | — |
| C3 | Inventario, stock, lista de materiales, catálogo de tareas | DONE | `tests/test_tools.py` | — |
| C4 | Búsqueda en manuales | DONE | `app/tools/queries.py`, `app/rag/search.py` | — |
| C5 | Al menos una tool por MCP | DONE | `app/integrations/mcp_server.py`, `tests/test_mcp.py` | — |
| C6 | Timeouts, reintentos y errores tipados | DONE | `PlantClient` (3 intentos), `tests/test_tools.py` | — |
| C7 | Tests automatizados de cada tool | DONE | `tests/test_tools.py` | — |
| C8 | Tools de LangChain | DONE | `app/tools/langchain_tools.py` | — |

## D. Órdenes, reglas y determinismo

| ID | Requisito | Estado | Evidencia | Falta |
|---|---|---|---|---|
| D1 | Reglas de aprobación en código contra el estado de planta | DONE | `app/domain/rules.py`, `tests/test_rules_orders.py` | no ejercitado por `martes-tranquilo`/`fuga-sin-enlace` (sin fallas de equipo) |
| D2 | Orden adecuada a la falla (tarea que resuelve o inspecciona) | DONE | `app/domain/orders.py`, `tests/test_rules_orders.py` | ídem; correr `tormenta-perfecta` o `sin-luz` |
| D3 | Motivo explícito en pendientes y daño estructural | DONE | `evaluate`, `structural_damage`, tests | — |
| D4 | Idempotencia y no duplicar órdenes abiertas | DONE | `order_id`, `repo.open_order`, E3 = 100 % | — |

## D. RAG, contexto y memoria

| ID | Requisito | Estado | Evidencia | Falta |
|---|---|---|---|---|
| R1 | Índice en pgvector con equipo, fabricante, documento, sección, cita y vigencia | DONE | `app/rag/indexer.py`, `app/persistence/schema.sql` | — |
| R2 | Rev. C vencida con otros límites | DONE | `current=false` + penalización, `tests/test_rag.py` | — |
| R3 | Secciones de TX-250/500, FC-24/96, PIA-1/2 no aplican | DONE | `metadata_weight`, `tests/test_rag.py` | — |
| R4 | Códigos de fabricante traducidos a F01–F10 (MBP-4 §6) | DONE | `app/rag/codes.py`, `tests/test_rag.py` | — |
| R5 | recall@k con `evaluacion/retrieval.json` (71) | DONE | `evaluacion/retrieval_eval.py`: hit@5 0,873 / recall@5 0,718 | reproducir en la corrida final |
| R6 | Comparación con BM25 (hit@5 0,85 / recall@5 0,66) | DONE | BM25 medido 0,859/0,674; híbrido 0,873/0,718 | — |
| R7 | Reportar Rev. C antes que D | DONE | BM25 6/71 (distractor@5), híbrido 0/71 | — |
| R8 | Citas de sección en cada conclusión | DONE | `ManualHit.cita`, `context.py` | — |
| R9 | Límites y stock fuera del RAG | DONE | API/SQL/datos; RAG solo documental | — |
| R10 | Context builder diseñado | DONE | `app/rag/context.py` | — |
| R11 | Estado de la conversación persistido en Postgres | DONE | `notes/parts/attempts/tablet_messages/replies` | — |
| R12 | Política de memoria escrita | DONE | `docs/MEMORIA.md` | — |

## E. Persistencia, offline y robustez

| ID | Requisito | Estado | Evidencia | Falta |
|---|---|---|---|---|
| E1 | Estado del parte persistido y reanudable | DONE | `app/persistence/*`, `workflow.start` | — |
| E2 | Idempotencia de notas, eventos, órdenes y tablet | DONE | claves únicas, ids deterministas | — |
| E3 | Cola de sincronización y reintentos | DONE | `app/integrations/sync.py`, `tests/test_sync_history.py` | — |
| E4 | Operación local sin enlace | DONE | MQTT/ASR/parser/reglas locales | — |
| E5 | Pendientes visibles en el latido | DONE | `pending_count`, `heartbeat_payload` | — |
| E6 | Sobrevive al corte de luz sin duplicar | PARTIAL | re-publicación de órdenes abiertas, `workflow/_resume_orders`, `tests/test_rules_orders.py` | no ejercitado por los dos escenarios; correr `sin-luz` |
| E7 | Registro de decisiones, tokens, costo y latencia | DONE | `decisions`, `usage_log`, logs | — |

## F. Pruebas y evaluación

| ID | Requisito | Estado | Evidencia | Falta |
|---|---|---|---|---|
| F1 | Suite de tests automatizada | DONE | `tests/` (98 passed, 1 skipped) | ampliar si aparece un caso real |
| F2 | `docker compose up` real | DONE | stack `cerebro` + `db` + `nube-sync` sobre `planta-lan`; latido válido | — |
| F3 | Evaluación oficial `martes-tranquilo` + `fuga-sin-enlace` | DONE | `var/corrida6/informe.md`: **91,3 / 100 · APRUEBA** | — |
| F4 | Sin `sin_alerta_de_seguridad` / `sistema_mudo` | DONE | alerta S1 en `fuga-sin-enlace`; 0 mensajes inválidos; sin eliminatorias | — |
| F5 | README e INFORME | DONE | `README.md`, `INFORME.md`, `docs/RESULTADOS.md` con métricas medidas | — |

## Bloqueos y supuestos

1. **Fuente de `planta_contrato`**: el mecanismo documentado
   (`git+https://github.com/NovitSoftware/academia2026-planta#subdirectory=contrato`)
   devuelve *Repository not found* y no está en PyPI. La instalación acepta
   `PLANTA_CONTRATO_DIR` como contexto de build apuntando al repo de la planta
   provisto. No se copiaron ni reimplementaron los modelos.
2. **Lista cerrada de modelos**: no fue provista. Se eligen modelos locales que entran
   en 4 CPU/8 GB y se documentan en `INFORME.md`; los identificadores son
   configurables por entorno.
3. **Canal de decisiones humanas**: el contrato no lo define; la central de aprobación
   y certificación (G2/G3) queda para la Entrega 2. En esta entrega la orden solo
   publica `Borrador → Aprobada|PendienteAprobacion`.
4. **`materiales.yaml` no se sirve por API**: se incluye la copia de datos provista
   por la cátedra en `datos/materiales.yaml`.
