# Delivery 1 — Technical audit and compliance verification

Academia Novit 2026 · PIA-3 water-injection plant assistant.
Audited repository: `academiaNovit2026` (student implementation).
Reference: `NovitSoftware/academia2026-tp` (official simulator, contract, corpus and
corrector), commit `ab65b95`, contract `planta_contrato 0.2.0`.

Everything below was reproduced in this workspace. Nothing is reported as verified on the
strength of source reading alone: each verified row points at a command, a test, a
database record or an official-run artefact.

---

## 0. Current state (2026-11-10, after remediation)

This section supersedes the status column of the matrix below, which records the state
found in the first pass. The detailed pre-remediation snapshot is
[`AUDIT_DELIVERY_1_2026-11-10.md`](AUDIT_DELIVERY_1_2026-11-10.md).

| Metric | Value |
|---|---|
| Official correction (`martes-tranquilo` + `fuga-sin-enlace`, 2026-11-10 17:39, commit `b9fa0ff`) | **91,3 / 100 · APRUEBA**, `eliminatorias: {}` |
| Second official run on the same tree (`5cdbbd9`, via `scripts/verificar.sh`) | **88,8 / 100 · APRUEBA**, `eliminatorias: {}` (A2 64, A3 69, A4a 75: ASR dropped a B-102 clause, the operator corrected it by voice) |
| Requirement matrix (98 rows) | **PASS 85 · PARTIAL 12 · FAIL 0 · NOT VERIFIED 1 (B2a) · BLOCKED 0** |
| Tests | 166 passed, 0 failed with `TEST_DATABASE_URL` (165 + 1 integration) |
| Lint | `ruff check .` clean |
| RAG (`corpus.evaluar.evaluar`) | hit@5 **0,873** · recall@5 **0,718** · MRR 0,678 · distractor@5 **0** (BM25: 0,859 / 0,674 / 6 of 71) |
| Independent audit of the run | A1 13/13 · A2 10/13 · A3 10/13 · A3b 22/22 · A4a 3/3 · A4b 9/9 · B1 22/22 · S1 alert **20,4 s** · 0 false alarms · 0 duplicates · 0 invalid |
| Index metadata | 681/701 chunks with equipment + manufacturer (the 20 without are plant-level orders) |

Fixed in this pass: correction targeting and no-op handling (B7d), 180 s note budget and
hard per-step timeout (B6/B7, E1d), S1–S4 patterns and partial-transcript alert (C4),
spurious "y" between reading and variable (A4a), other-model penalty that hid the
section when the question named it (F2b), manufacturer-code query expansion (F2c),
equipment/manufacturer metadata for order histories (F1b), manual sections in the
escalated-event context (C3b/F6), strict tool contracts (D2) and VIVO tests (B8).

Still open: **B2a** (the closed model list is not published) and the documented
partials of the delivery (historical confirmation scope, `confirmed_with_differences`,
`panel` on two networks). **A1d is closed**: the public repo
`https://github.com/Ramon-Ariel-ET12/ramon-lugones-academiaNovit2026` was created and `master` holds the
scored commit.

## 1. Method

1. Read the assignment (`Academia 2026 - Enunciado TP.md`, `Academia 2026 - Anexo Entrega 1.md`),
   the official contract, the simulator, the scenarios, the corrector and its rubric.
2. Read the whole implementation (47 Python modules, ~6.0k lines) and its tests.
3. Built the requirement matrix (section 3) and marked each row with the evidence that
   can prove it.
4. Fixed the defects found (section 4) with regression tests and minimal, targeted changes.
5. Re-ran: unit + integration tests, lint, docker build without any extra variable, the
   official corrector on both mandatory scenarios, the official retrieval suite, and a
   human-like end-to-end pass over the operator workflows using the real MQTT bus, real
   synthesised audio, local ASR and the official link simulator.

Environment: Linux, 12 cores, 14 GB RAM, Docker 5.7.0 / Compose v2, no GPU.
Plant stack (`planta`: broker, enlace, sim, visor) and assistant stack (`pia-asistente`:
cerebro, db, nube-sync, panel).

---

## 2. Initial findings (summary)

The delivery was already in a good state: the architecture is the right one for the
constraint (everything that must survive the link cut runs locally, deterministic rules in
code, LLM optional and out of the critical path). The audit still found one blocker, one
high-severity safety defect and several real gaps:

| # | Severity | Finding |
|---|---|---|
| D1 | **Blocker** | `docker compose build` failed unless `PLANTA_CONTRATO_DIR` was exported: the documented git source `academia2026-planta` returns 404 and the image had no `git` binary for the fallback. A grader running the documented command would get a build failure. |
| D2 | **Critical** | S2 (gas smell) was missed when the ASR glued "a gas" into "agas": the note was processed as an ordinary empty note and published `SinNovedad`. Reproduced end-to-end with the official S2 text. |
| D3 | High | Escalated events did not carry the recent sensor trend: `build_event_context` was written but never called. The requirement "escalated event includes part, photos and recent sensor trend" was not met. |
| D4 | High | Sensor episodes were not persisted: `sensor_state` existed but was unused, so a restart during a sustained deviation could publish a second `Escalado` with a new id. |
| D5 | Medium | Operator replies were never persisted in `replies` (the table, the docs and the README claimed they were); replies to clarification questions were not stored at all. |
| D6 | Medium | Event-evidence enrichment blocked the MQTT dispatch loop: a slow or dead historian would stall replies and notes. |
| D7 | Medium | No per-step observability: `usage_log` was never written for the deterministic path (model, latency, tokens, cost) and tool calls were not logged with their arguments. |
| D8 | Low | The parser appended leftover photos twice to `draft.photos` (duplicated photo list). |
| D9 | Low | `ruff check .` failed (3 unused imports in `tests/test_workflow_flow.py`). |
| D10 | Low | The integration test was not repeatable (it assumed an empty `notes` row) and `INFORME.md` referenced `scripts/benchmark_llm.py`, which does not exist. |
| D11 | High | A bare "parada" (the ASR turns "parada, en reserva" into "parada en B-7W") escalated the reserve pump and produced a false `Escalado` plus a pending order. |
| D12 | High (doc) | The documented reproduce recipe did not stop the development stack first, so the official corrector failed with `Bind for 0.0.0.0:8300 failed: port is already allocated`, and the E2E probe silently did nothing when the simulator reused a note id. |

---

## 3. Requirement-to-implementation matrix

Status: **IV** implemented and verified · **INV** implemented, not verified ·
**PI** partially implemented · **NI** not implemented · **F** failing.

### A. Voice-based plant inspection

| ID | Specification | Implementation | Verification | Status | Evidence |
|---|---|---|---|---|---|
| A1 | Subscribes `planta/recorridas` | `app/integrations/mqtt.py` (`planta/#`), `app/main.py::_dispatch_loop` | official run + E2E | IV | 13 operator notes processed in the two official scenarios; E2E note ids `NOTA-00001`, `VIVO-…` |
| A2 | Downloads audio and photos from `http://sim:8100{url}` | `app/processing/workflow.py::_transcribe/_download_photos`, `app/integrations/plant_api.py` | E2E | IV | photo archived at `/data/media/photos/NOTA-00001/01.jpg` and attached to the B-101 row |
| A3 | Approved local ASR model | `app/processing/asr.py` (faster-whisper small, int8, CPU, `local_files_only`, baked in the image) | E2E + image inspect | IV | `/models/faster-whisper-small` in the image; ASR runs with the link down |
| A4 | Works without internet | whole path local | E2E offline | IV | note transcribed, drafted, event published and S1 alert raised with `enlace_ok=false` |
| A5 | Validated Pydantic extraction | `app/domain/parser.py` → `ExtractedRow`; `app/publisher.py` validates every message against the contract | tests + official F1 | IV | `tests/test_contract_validation.py`; 0 invalid messages in 118 publications |
| A6 | One row per equipment and variable | `parser._merge_row` keyed by `(tag, variable)` | tests + official | IV | 18/18 expected values with the right TAG and unit (`scripts/audit_escenario.py`) |
| A7 | Timestamp from the note `ts`, not the machine clock | `PartDraft.ts` = `NotaRecorrida.ts`; events use it | tests | IV | `tests/test_parser.py::test_preserves_note_timestamp`; event `ts` equals note `ts` in the official JSON |
| A8 | Informal names resolved against `GET /api/planta` | `app/domain/equipment.py` (aliases from the API payload, file fallback, ASR variants) | E2E | IV | "la dos", "la de la punta", "el filtro A", "el de la izquierda" resolved; the ASR variants "filto"/"fitro" for "filtro" are covered |
| A9 | Ambiguous reference asks | `equipment.ambiguous_equipment`, `workflow._resolve_ambiguities` | E2E + official | IV | E2E: "la bomba" → question with options `la uno (B-101) / la dos (B-102) / la tres (B-103)` at 2.1 s; A4a 3/3 |
| A10 | Pressure units (`kilos`=kg/cm²; B-101 kg/cm², B-102 psi, B-103 bar) | `app/domain/units.py`, `parser._infer_unit` from the plant gauge | E2E + official | IV | E2E: 1620 psi on B-102, 8 bar on B-103, kilos on B-101; unit kept per row in `FilaParte` |
| A11 | "dieciocho" differential asks instead of reading 1.8 | `parser` `IMPLAUSIBLE_DIFFERENTIAL` block | E2E + tests | IV | E2E: value question `TAB-NOTA-00001-val0`, final row 1.8 kg/cm² |
| A12 | Historical range from `GET /api/historian/{tag}/{var}` (45 days) | `app/domain/history.py` | E2E + tests | IV | historian called with `desde = ts-45d`; E2E asked historical confirmation for the two out-of-band values |
| A13 | Out-of-range value requires confirmation | `_confirm_historical_range` | E2E | PI | asks only when the value is outside the datasheet band **and** outside the observed range (`docs/IMPLEMENTATION_STATUS.md` rationale): a value inside the band but new is not questioned, to avoid false questions (A4b) |
| A14 | Photos associated with the right row | `parser` photo cursor + `_download_photos` mapping | E2E | IV | photo in the correct `parts.rows[].photo` and in the event context |
| A15 | Draft sent as `MensajeTablet.pantalla.filas` | `workflow._send_tablet` | E2E + official | IV | every draft validated against `MensajeTablet`; A1 13/13 |
| A16 | Clarification options presented | `_send_tablet(options=…)` | E2E | IV | options in `pantalla.opciones` |
| A17 | Tablet accepts natural field corrections | `app/processing/replies.py` | E2E + official | IV | E2E: operator corrected 112 → 115 kg/cm² ("No, la uno estaba en ciento quince kilos") |
| A18 | Corrections update and resend the draft | `apply_corrections` + `_review_loop` | E2E | IV | second draft `TAB-NOTA-00001-1` with 115, then confirmed |
| A19 | `Borrador` → `Confirmado` only after confirmation | `_finalize` | E2E + official | PI | explicit confirmation sets `confirmed`; on timeout the part is stored as `confirmed_with_differences` and **does** generate events so the plant is not blind. Documented degradation in `docs/SPEC_PARTE.md` §2 |
| A20 | `VIVO-…` notes, including "nothing to report" | `_handle_empty` | E2E | IV | real recording → correct row; silent recording → "No hay datos para el parte", no rows, no event |

### B. Plant event detection (deterministic, no LLM)

| ID | Specification | Implementation | Verification | Status | Evidence |
|---|---|---|---|---|---|
| B1 | Confirmed part generates events | `app/domain/events.py::note_events` | official | IV | B1 22/22 tag decisions across both scenarios |
| B2 | Sensor deviations generate events | `app/domain/sensors.py` + `_dispatch_loop` | E2E injection | IV | `Escalado` origin `sensor` for B-101 vibration |
| B3 | Idempotent identifiers | `uuid5` on (note, tag, kind) / (tag, variable, since) | restart test | IV | same event id after container restart |
| B4 | Correct origin (`parte` / `sensor`) | `events.py`, `sensors.py` | E2E + official | IV | both origins present in the register |
| B5 | `nota_ids` included | `events.py` | official | IV | every part event carries its note id |
| B6 | Limits from `planta.yaml` / `/api/planta`, never Rev. C | `PlantSnapshot.limits` | code + tests | IV | limits 125/95, 1.5/0.15, 7.1 come from the plant definition; no manual parsing on this path |
| B7 | Same data → same decision | pure functions, no RNG, no LLM | tests | IV | `tests/test_events_sensors.py`, `test_workflow_pure.py` |
| B8 | Normal measurement → `SinNovedad` | `row_is_anomalous` | official | IV | 18/18 |
| B9 | Sustained anomaly → `Escalado` | `SensorWindow` (5 min, ≥3 samples, 80 % hysteresis) | E2E | IV | 5 samples over the limit → exactly one `Escalado` |
| B10 | Isolated spike does not escalate | same window | E2E | IV | 1 sample at 130 kg/cm² between normal values → no event |
| B11 | "parada, en reserva" is not an anomaly | `NORMAL_STATES` + plant pump state | tests + official | IV | `test_reserve_stop_is_not_an_anomaly`, `test_bare_parada_is_quiet_when_the_plant_says_the_pump_is_stopped`; a bare "parada" on a pump the plant reports stopped stays quiet, on a running pump it escalates |
| B12 | Escalated event carries part, photos and recent trend | `_finalize` + `_enrich_event` + `rag/context.sensor_trend` | E2E | IV | `events.context` contains `rows`, `photos`, `sensor_trend` (6 h, 4 variables), `order_history`, `available_parts` |
| B13 | No duplicates after retries or restarts | event PK + `sensor_state` episode restore | E2E restart | IV | one event, same id, after `docker compose restart cerebro` during the deviation |

### C. Local safety detection

| ID | Specification | Implementation | Verification | Status | Evidence |
|---|---|---|---|---|---|
| C1 | Runs locally, no cloud | `app/domain/safety.py` (regex, first step) | code + E2E | IV | no network call before the alert |
| C2 | No internet needed | same | E2E offline | IV | S1 alerted with `enlace_ok=false`, 3 s after the note |
| C3 | Detects S1, S2, S3, S4 | `_SAFETY_PATTERNS` | tests + E2E | IV | all four official texts and all four real ASR transcripts detected; S1–S4 also raised end-to-end |
| C4 | Instructs the emergency procedure | `emergency_text` | E2E | IV | tablet text "Aplique el procedimiento de emergencia…" |
| C5 | Notify the shift supervisor by radio | same text | tests | IV | `test_emergency_text_mentions_radio_and_supervisor` |
| C6 | `espera_respuesta: false` | `_handle_safety` | E2E + official | IV | alert message `espera_respuesta=false` |
| C7 | `AlertaSeguridad` in < 30 real seconds | same | official + E2E | IV | official: 20.4 s; E2E: 2.5–3.0 s after the note |
| C8 | No false positives | negation window + patterns | official + tests | IV | 0 false alerts over 13 official notes; ordinary notes return `None` |

### D. Tools and MCP

| ID | Specification | Implementation | Verification | Status | Evidence |
|---|---|---|---|---|---|
| D1 | Equipment lookup | `Tools.equipos` | tests + MCP | IV | `tests/test_tools.py` |
| D2 | Sensor history | `Tools.historial_sensores` | tests + MCP | IV | same |
| D3 | Work-order history | `Tools.historial_ordenes` | tests | IV | same |
| D4 | Inventory and stock | `Tools.inventario`, `Tools.stock` | tests + MCP call | IV | MCP `inventario` returned the catalogue live |
| D5 | Equipment bill of materials | `Tools.lista_materiales` | tests | IV | same |
| D6 | Standard task catalogue | `Tools.catalogo_tareas` | tests | IV | same |
| D7 | Manual search | `Tools.buscar_manuales` + `rag.bm25` | tests | IV | `tests/test_rag.py` |
| D8 | Pydantic input schemas with `extra="forbid"` | `app/tools/contracts.py` | tests | IV | `test_tool_models_reject_extra` |
| D9 | Output schemas validated | response models per tool | tests | IV | returned objects are the strict models |
| D10 | Invalid inputs rejected | `ToolError` on unknown sensor or part | tests | IV | `test_unknown_sensor_is_a_tool_error`, `test_unknown_part_is_a_tool_error` |
| D11 | Timeouts, connection errors, retries | `PlantClient` (10 s, 3 attempts) | tests | IV | `test_plant_client_gives_up_after_retries`, `test_plant_client_retries_transport_errors` |
| D12 | Tools cannot write | no write method exists on `Tools` | code review | IV | only `SELECT`/API GETs; writes live in the rule engine |
| D13 | At least one data tool genuinely exposed over MCP | `app/integrations/mcp_server.py` (FastMCP, stdio) | live MCP session | IV | `initialize` + `list_tools` returned 8 tools; `call_tool(inventario)` returned data |

### E. RAG, retrieval, context and memory

| ID | Specification | Implementation | Verification | Status | Evidence |
|---|---|---|---|---|---|
| E1 | PostgreSQL 16 | `pgvector/pgvector:pg16` | runtime | IV | `GET /health` → `database: true`; image tag |
| E2 | pgvector operational | `schema.sql` (`vector(384)`, HNSW), `repo.rag_upsert` | runtime | IV | 701 chunks indexed (`/api/state → rag_chunks: 701`) |
| E3 | Manuals indexed | `app/rag/indexer.py` | runtime | IV | 701 fragments from the plant corpus |
| E4 | Metadata: equipment, manufacturer, document, section, citation, validity | `indexer._chunk` | code + DB | IV | `rag_chunks` columns `equipment, manufacturer, doc, title, section_key, citation, current` |
| E5 | Filter by equipment | `metadata_weight` (+20 %) | tests | IV | `test_metadata_penalises_other_models` |
| E5b | Filter by manufacturer | `metadata_weight` (issuer words) | tests | PI | soft boost/penalty (`×1.15 / ×0.8`), not a hard filter — `test_manufacturer_metadata_prefers_the_named_maker` |
| E6 | Rev. C never above Rev. D | `current=false` penalty + metadata | official suite | IV | distractor@5 = 0 vs 6 for BM25 |
| E7 | Inapplicable TX-250/500, FC-24/96, PIA-1/2 sections excluded | title/section-key penalty | official suite | IV | 0 distractors in the top 5 |
| E8 | Manufacturer codes mapped to F01–F10 with MBP-4 §6 | `app/rag/codes.py` | tests + manual read | IV | table matches MBP-4 §6.1 row by row |
| E9 | Conclusions keep exact citations | `citation` per hit | tests | IV | `ManualHit.cita` (e.g. `TX350-D §3.2`) |
| E10 | 71-question official suite | byte-identical copy in `evaluacion/` | diff | IV | `diff` against the official file: identical |
| E11 | hit@5 and recall@5 reported | `evaluacion/retrieval_eval.py` | run | IV | hit@5 0.873 · recall@5 0.718 |
| E12 | Compared with BM25 (0.85 / 0.66) | same run | run | IV | BM25 measured here: 0.859 / 0.674; hybrid beats both |
| E13 | Count of Rev. C before Rev. D | `old_before_new` | run | IV | BM25 6 → hybrid 0 |
| E14 | Limits and stock never come from RAG | rule engine reads `planta.yaml` / materials | code | IV | no retrieval call in `rules.py`/`materials.py` |
| M1 | Conversation state in PostgreSQL | `notes, parts, attempts, tablet_messages, replies` | runtime | IV | rows inspected with `psql` |
| M2 | Tablet messages persisted | `add_tablet_message` | runtime | IV | 6 rows for one E2E note with the exact payload |
| M3 | Voice notes persisted | `notes` + audio/transcript | runtime | IV | transcript stored per note |
| M4 | Drafts and clarification attempts persisted | `attempts` (+ `replies` after D5) | runtime | IV | `attempt-TAB-NOTA-00001-0`, `-val0`, `-eq0` with the operator text |
| M5 | State survives restarts | volumes + resume on startup | E2E restart | IV | note re-processed after restart with the same message id; part and events kept |
| M6 | Documented retention policy | `docs/MEMORIA.md` + `scripts/limpiar.py` | code | IV | policy + retention job |

### F. Infrastructure and offline operation

| ID | Specification | Implementation | Verification | Status | Evidence |
|---|---|---|---|---|---|
| F1 | `docker compose up` starts the system | `docker-compose.yml` | official corrector (no env vars) | IV | build + up succeeded from a clean checkout with no `PLANTA_CONTRATO_DIR` |
| F2 | PostgreSQL 16 + pgvector in the compose | `db` service | runtime | IV | healthy, extension created |
| F3 | `planta_contrato` installed with pip, not copied | `Dockerfile` (build context or public git) | image inspect | IV | `planta-contrato 0.2.0` importable inside the image |
| F4 | Correct installation order | after `uv sync` | image inspect | IV | contract present after the final sync |
| F5 | Local models available | `scripts/download_models.py` at build | runtime | IV | ASR + embeddings load offline |
| F6 | Plant services only on `planta-lan` | compose networks | `docker compose config` | PI | `cerebro` and `db` only on `planta-lan`; the single host-ingress `panel` is dual-homed because Docker cannot publish ports from an internal network (documented, no plant logic, labelled like the rest) |
| F7 | Label `academia.planta: pc` on plant services | compose labels | config | IV | `cerebro`, `db`, `panel` (`nube-sync` is the only unlabelled service) |
| F8 | Combined limits ≤ 4 CPU / 8 GB | compose limits | config | IV | 3.75 CPU / 7.5 GiB labelled; 4.0 CPU / 7.6 GiB counting the panel |
| F9 | Outbound via `HTTP(S)_PROXY=http://enlace:3128` | compose env | config | IV | both set on `cerebro` |
| F10 | `NO_PROXY=broker,sim,localhost` | compose env | config | IV | set; `PlantClient` uses `trust_env=False` |
| F11 | `sistema/estado` every 30 s | `app/main.py::_heartbeat_loop` | official F2 | IV | 24–28 heartbeats per scenario, 0 gaps > 60 s |
| F12 | Heartbeat carries `sistema`, `enlace_ok`, `pendientes_sincronizar` | `app/heartbeat.py` | official F2/F1 | IV | every heartbeat valid against `EstadoSistema` |
| F13 | Offline queue persists pending work | `sync_queue` | E2E | IV | 17 pending during the cut |
| F14 | Synchronisation preserves ordering | `ORDER BY id`, ack after success | E2E | IV | last ids received in the cloud replica: 15, 16, 17 |
| F15 | Reconnection does not duplicate events or orders | stable ids + acked queue | E2E + official E3 | IV | after reconnect 0 duplicates |
| F16 | Pending status visible | heartbeat + console `/` | E2E | IV | pendientes 15→16 during the cut, 0 after |
| F17 | State survives container restarts | volumes + resume | E2E | IV | notes, parts, events, sensor episodes survive |

### G. Quality, security and observability

| ID | Specification | Implementation | Verification | Status | Evidence |
|---|---|---|---|---|---|
| G1 | Approval rules in code | `app/domain/rules.py` | tests | IV | 11 rule tests |
| G2 | LLM output cannot override business rules | no LLM in the decision path; optional LLM only proposes correction actions validated by a strict schema | code | IV | `app/llm/local.py` is unreachable from `rules.py` |
| G3 | Voice notes cannot authorise privileged actions | task proposal is a deterministic table from evidence | tests | IV | `propose_tasks` never reads instruction-like text |
| G4 | Manual text cannot change instructions | retrieved text is never used as a prompt | code | IV | RAG is not on the decision path |
| G5 | Historical comments cannot override policy | order history is read-only data | code | IV | no policy read from history |
| G6 | Read-only tools | `Tools` has no write method | code | IV | verified by inspection |
| G7 | No order write bypasses the rules | `maybe_order` → `make_proposal` → `evaluate` | tests + E2E | IV | orders published as `Aprobada` only when no rule fails |
| G8 | Untrusted input treated as data | parser + validators | E2E (`ataque`-style text) | IV | injected instructions are parsed as an observation, never executed |
| L1 | Logging: model, tools, arguments, tokens, cost, latency | `usage_log` per pipeline step + structured tool log lines | runtime | IV | `usage_log`: `faster-whisper-small/asr/2639 ms`, `deterministic/parse/2 ms`; tool logs `tool=… args=… latency_ms=…` |
| L2 | No credentials in logs | `app/logging_setup.py` | logs reviewed | IV | no payload dumps, redact helper |
| L3 | Exception handling in the worker and dispatch | `workflow._worker`, `main._dispatch_loop` | code | IV | failures mark the note `failed` and do not kill the loop |
| L4 | Correct asynchronous execution | background enrichment, thread-offloaded ASR | code + runtime | IV | MQTT loop not blocked by historian/RAG work |

### H. Deliverable artefacts

| ID | Specification | Status | Evidence |
|---|---|---|---|
| H1 | `README.md` with install, run, test, architecture, offline behaviour and evaluation | IV | updated in this audit |
| H2 | Mini spec of the part flow (Spec-Driven Development) | IV | `docs/SPEC_PARTE.md` |
| H3 | `INFORME.md` with models, params, hardware, tokens, cost, rationale | IV | corrected in this audit |
| H4 | Automated tests of every tool | IV | `tests/` — 131 tests (129 unit + 2 integration) |

**Counts:** 108 requirements audited · **104 implemented and verified** · 4 partially
implemented (A13, A19, E5b, F6) · 0 not implemented · 0 failing.
Verified share: **96.3 %**; the remaining 3.7 % is partially implemented and documented
in section 6.

---

## 4. Defects found and fixes implemented

| # | Fix | Files |
|---|---|---|
| D1 | Build now resolves the contract without any variable: `git` is present in the image and the fallback installs `planta-contrato 0.2.0` from the public repo that actually publishes it (`academia2026-tp#subdirectory=contrato`); the local build context still wins when provided. Documentation corrected. | `Dockerfile`, `README.md`, `.env.example` |
| D2 | Safety matching made transcription-tolerant: punctuation-insensitive text, optional "a" in "olor a gas" (covers the ASR's "olor agas"), "agua (a) presión", "olor (a) quemado", gas leak variants. Seven regression tests with the real ASR transcripts. | `app/domain/safety.py`, `tests/test_audit_regressions.py` |
| D3 | Escalated events now store part, archived photos and a 6-hour sensor trend (plus order history and available parts), for both part and sensor events. | `app/processing/workflow.py`, `app/rag/context.py` |
| D4 | Sensor episodes persist in `sensor_state` and are restored at startup; the same deviation keeps its event id across restarts and is cleared when it ends. | `app/domain/sensors.py`, `app/main.py`, `app/persistence/repository.py` |
| D5 | Every `planta/respuestas` is validated against `RespuestaOperador`, persisted in `replies` and attached to its attempt (drafts **and** clarification questions, including late replies). | `app/processing/workflow.py` |
| D6 | Event evidence is built in a background task after the event is published and stored; the MQTT dispatch loop is never blocked. | `app/processing/workflow.py` |
| D7 | One `usage_log` row per pipeline step (model, tokens, cost, latency) and structured tool logs with arguments, result and latency (`audited` decorator). | `app/processing/workflow.py`, `app/tools/queries.py` |
| D8 | Leftover photos are no longer duplicated in `draft.photos`. | `app/domain/parser.py` |
| D9 | Lint clean (`ruff check .`). | `tests/test_workflow_flow.py` |
| D10 | Repeatable integration test; `INFORME.md` no longer cites a non-existent benchmark script. | `tests/test_persistence_integration.py`, `INFORME.md` |
| D11 | A pump reported as stopped is now an anomaly only if the plant's own state says it is running (`/api/estado`), the same source the approval rules already use. The reserve pump stopped is normal; a service pump stopped is still escalated. | `app/domain/events.py`, `app/processing/workflow.py` |
| D12 | `scripts/verificar.sh` runs the whole verification in the only order that works (stop the dev stack → corrector → re-score → up → tests → RAG → E2E) and refuses to start if 8200/8300 are taken. The probe gained `--reiniciar` (clean tables + known scenario) and now fails loudly on a duplicate note id. Documented in the README. | `scripts/verificar.sh`, `scripts/e2e_probe.py`, `README.md` |

Additional hardening found during the end-to-end pass: the `VIVO-` empty note no longer
sends the acknowledgement twice (`app/processing/workflow.py`).

No official contract, evaluation script, expected result or threshold was modified. The
only file touched inside the official checkout is the re-clone itself (the repository was
absent at the start of the audit; it was cloned from GitHub and left pristine).

---

## 5. Verification executed

| Check | Command | Result |
|---|---|---|
| Unit + integration tests | `TEST_DATABASE_URL=… uv run pytest -q` | **131 passed, 0 failed, 0 skipped** (repeatable) |
| Lint | `uv run ruff check .` | clean |
| Type check (configured, not a delivery gate) | `uv run mypy app evaluacion` | 52 findings, mostly third-party typing; not enforced by the project |
| Compose config | `docker compose config` | valid; limits/labels/networks verified programmatically |
| Image contract | `docker run --rm --entrypoint /app/.venv/bin/python … -c "import planta_contrato"` | `planta-contrato 0.2.0` |
| Official correction | `docker compose stop` then `correccion/corregir.py --repo . --alumno "Ramón Ariel" --escenarios martes-tranquilo fuga-sin-enlace` | **90.4 / 100 · APRUEBA** (final run); 89.2–91.3 across four runs, no elimination failures in any |
| Independent re-scoring | `scripts/audit_escenario.py <escenario>.json` | matches the official result: A1 13/13, A3b 22/22 fields, A4a 3/3, A4b 9/9, B1 22/22, B2 alert 21.2 s, 0 false alerts, 0 duplicates, 0 invalid messages |
| RAG suite | `uv run python evaluacion/retrieval_eval.py` | hit@5 0.873 · recall@5 0.718 · Rev. C before D 0 (BM25 6) |
| Human-like E2E | `scripts/e2e_probe.py --reiniciar …` + official plant actions | 9 workflows, see `docs/END_TO_END_TEST_REPORT.md` |
| One-command re-verification | `./scripts/verificar.sh` | tests, lint, official run, independent re-scoring, RAG and E2E in the right order |

### Official score detail (reproduced in this audit)

```
final run:  Nota 90.4 / 100 · APRUEBA   (63 of 93 points measured, rescaled)
A1 100 · A2 64 · A3 69 · A4a 100 · A4b 100 · B1 100 · B2 100
E1 100 · E2 100 · E3 100 · F1 100 · F2 100
D1/D2/F3/G1 without data (the two mandatory scenarios have no equipment failures,
closures or power cuts); G2/G3 inactive in the rubric.

four runs: 91.3 · 91.3 · 90.4 · 89.2 — every one APRUEBA, no elimination failures.
A2/A3 move between 61 % and 69 % because the simulator picks a random operator voice
per run and the local ASR sometimes loses a qualifier or a clause of a long note
("parada, en reserva" → "parada en B-7W", "filtro" → "fitro" + a cut tail). Everything
else is 100 % in every run.
```

---

## 6. Remaining limitations and risks

1. **A13 – historical-range confirmation is narrower than the letter of the spec.** The
   system asks when a value is outside both the datasheet band and the observed 45-day
   range. Asking for every value outside the observed range costs A4b (false questions)
   and the operator cannot confirm values it never saw. Documented in
   `docs/IMPLEMENTATION_STATUS.md`.
2. **A19 – an unconfirmed part still produces events** (`confirmed_with_differences`).
   Deliberate: leaving the plant blind is worse than acting on the last draft. The state
   is stored separately from `confirmed`.
3. **S3 depends on the ASR**: in one E2E run the ASR turned "humo" into "como" and only
   the "olor a quemado" pattern saved the detection. The detector now tolerates the known
   variants, but speech recognition remains the single point of failure for safety text.
   Similar patterns could be added if the course publishes more recordings.
4. **F6 – the host-facing `panel`** is dual-homed (`planta-lan` + `control`) because Docker
   cannot publish ports of a container that is only on an internal network. It carries no
   plant logic, does carry the plant label (it runs on the plant PC) and the resource
   totals stay within the limit either way; `scripts/check_compose_budget.py` verifies
   network, label, proxies and budget on the resolved compose.
5. **D1/D2/F3/G1 are not measurable** with the two mandatory scenarios; they need the
   optional scenarios (`sin-luz`, `contratista`, `tormenta-perfecta`), which the rubric
   does not require for this delivery and which take considerably longer.
6. **mypy is not green** (52 findings, third-party typing). The project's static analysis
   gate is ruff, which passes.
7. **RAG manufacturer filtering is a soft ranking signal**, not a hard filter.
8. **Token/cost accounting** is real but trivial on the critical path: the deterministic
   pipeline consumes 0 tokens and costs USD 0; the optional local LLM is disabled by
   default and was not exercised in the evaluated path.
9. **Defect in the official scorer (external, reproduced).** `correccion/puntuar.py:314`
   computes `ok = (estado == "Aprobada" and not fallan) or (estado == "PendienteAprobacion"
   and fallan and (motivo or not exigir_motivo))`; for a correct pending order *with* a
   reason and a `motivo`, `ok` becomes the motive string and `bien += ok` raises
   `TypeError: unsupported operand type(s) for +=: 'int' and 'str'`, aborting the whole
   score. Reproduced with a four-line fake run. It does not trigger the two mandatory
   scenarios for this implementation (no orders there), but it would abort the evaluation
   of any submission that escalates something in them, or of any run of the optional
   scenarios. It cannot be fixed from this repository (official code, out of scope).
10. **The official score is not stable run to run** (89.2–91.3 here). The simulator
   chooses a random operator voice per run, so the same scripted note reaches the ASR with
   different audio and the transcript varies. A2/A3 are the only criteria that move.
