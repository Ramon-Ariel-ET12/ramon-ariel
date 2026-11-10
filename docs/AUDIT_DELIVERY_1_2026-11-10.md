# Delivery 1 — Independent Acceptance Audit

> **Superseded snapshot (2026-11-10, before remediation).** This file records the state
> that audit measured; the fixes it lists in §7 are already applied. The audit of record
> for the current code is [`DELIVERY_1_AUDIT.md`](DELIVERY_1_AUDIT.md).

**Project:** `academiaNovit2026` (PIA-3 plant assistant) · **Audited:** 2026-11-10
**Reference:** `academia2026-tp` (plant simulator, contract, correction tool) — cloned in-repo, gitignored.
**Audit stance:** read-only. No project file was modified. Every PASS below is backed by a command I ran or a database/bus observation, not by a README claim.

---

## 1. Executive summary

> Audit snapshot of 2026-11-10, before any change. The fixes already applied after the
> audit are listed in §7; the statuses above describe the code **as audited**.

### Verdict: **NOT READY**

The system is genuinely operational and the official automated correction **passes with no elimination condition** (88.8/100, `aprueba: true`). The blockers to "READY" are narrow but mandatory: the delivery artefact (public repo) cannot be evidenced, two declared execution limits are not enforced, the RAG evaluation does not use the required `corpus.evaluar.evaluar` entry point, and three infrastructure conformance details (labels / network / resource caps for `panel` and `nube-sync`) are only partially met.

| Metric | Count |
|---|---|
| Requirements audited | 115 |
| **PASS** (implemented *and* evidenced) | **87** |
| **PARTIAL** (works, but the requirement is not fully satisfied) | **25** |
| **FAIL** | **1** (E1c token budget) |
| **NOT VERIFIED** | **1** (B2a approved closed model list) |
| **BLOCKED** | **1** (A1d public repo/naming — no git remote) |

**Elimination conditions:** `sin_alerta_de_seguridad` → **not triggered** (AlertaSeguridad for NOTA-00001, fuga-sin-enlace). `sistema_mudo` → **not triggered** (76 valid messages in martes-tranquilo, 42 in fuga-sin-enlace, 0 invalid).

### Most critical problems

1. **No git remote** — the mandatory "public GitHub repository named `nombre-apellido`" cannot be verified from this workspace; there is no evidence the submission artefact exists.
2. **Token budget and step budget are declared, not enforced** — `TOKEN_BUDGET` and `MAX_NOTE_STEPS` exist in `app/config.py` but are never read; `docs/SPEC_PARTE.md` asserts they are enforced.
3. **RAG evaluation is a private re-implementation** — it reproduces the course BM25/hit/recall/distractor methodology (and the numbers match), but it never calls `corpus.evaluar.evaluar(buscar, suite)` as the assignment requires.
4. **Safety alert latency margin is thin** — measured **24.0 s** against a 30 s hard limit, and detection depends entirely on the transcript containing the trigger phrase. A missed alert is an elimination condition.
5. **A measurement can be silently dropped** — reproduced from the official transcript of NOTA-00011: ASR writes "1600 p.c." and the `p.c.` punctuation splits the clause, so the B-102 reading disappears with **no row, no ambiguity question**. This is exactly the A4a=75% (1 of 2 ambiguous notes asked) and A2=64% the corrector measured.
6. **Out-of-range and ambiguous-value confirmations are asked but ignored** — the operator's answer is stored and discarded; the value never changes.

### Not audited / out of Delivery 1

Deliverables C (orders), D (approval rules) and G (closure/certification) of the master statement belong to later deliveries. The corrector's D1/D2/F3/G1 are "sin datos" in both mandatory scenarios — this is expected, not a defect, and is not counted as failure here.

---

## 2. Requirements compliance matrix

Status keys: **P** = PASS · **A** = PARTIAL · **F** = FAIL · **NV** = NOT VERIFIED · **BL** = BLOCKED.
Validation: `pytest` = 131 passed / 0 failed / 0 skipped (with live Postgres); `run` = saved official correction; `live` = observation on the running stack; `cfg` = `docker compose config`.

### A. Repository, deployment and infrastructure

| ID | Requirement | Status | Evidence | Validation | Issue |
|---|---|---|---|---|---|
| A1a | `README.md` at root | P | `README.md` (16 KB) | file exists | — |
| A1b | `docker-compose.yml` at root | P | `docker-compose.yml` | `docker compose config` exit 0 | — |
| A1c | `tests/` at root with automated tests | P | 15 files, `tests/test_*.py` | `pytest` 131 collected | — |
| A1d | Public repo named `nombre-apellido` | **BL** | `git remote -v` → empty; HEAD `c2efa19` | command | No remote configured: submission artefact unverifiable from here |
| A2a | `docker compose up` brings up system + plant | P | full official run at HEAD | `run` | — |
| A2b | Plant services **only** on external `planta-lan` | **A** | `docker-compose.yml:10,43,68,87` | `cfg` | `panel` joins `planta-lan`+`control`; `nube-sync` sits only on `control` (declared cloud-side) |
| A2c | Label `academia.planta: pc` | **A** | `docker-compose.yml:12,45` | `cfg` | Present on `cerebro` and `db` only; absent on `panel` (plant-PC ingress) and `nube-sync` |
| A2d | Combined CPU ≤ 4 | P | `cpus: 3 / 0.75 / 0.25` | `cfg` → total 4.0 | At the exact limit |
| A2e | Combined memory ≤ 8 GB | **A** | `6g + 1536m + 128m` | `cfg` → 7 625 MiB | `nube-sync` has no limit; the sum is unbounded if it is counted as a plant-side service |
| A2f | `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` | P | `docker-compose.yml:22-24` | `cfg` | Values exactly as required |
| A2g | No bypass of network/proxy design | P | `PlantClient` `trust_env=False` (plant-local), `CloudSync` `trust_env=True` (proxy), models baked | code + `live` sync 200 OK through `enlace` | — |
| A3a | `planta_contrato` installed with pip | P | `Dockerfile` contract layer | `docker compose exec cerebro python -c "import planta_contrato"` → `0.2.0` at `/app/.venv/.../planta_contrato` | — |
| A3b | Contract models not copied/reimplemented | P | `app/contract.py:11-33` re-exports; `app/domain/models.py` is internal-only | `grep` for `class EstadoSistema/MensajeTablet/EventoSistema` outside the reference repo → none | — |
| A3c | Heartbeat every 30 s | P | `app/main.py:76-86`, `app/config.py:47` | `live` capture: gaps **30.009 s** (extra beats on activity) | Additional beats per publish (12.8 s gap observed) — harmless for F2 |
| A3d | Heartbeat contains `sistema`, `enlace_ok`, `pendientes_sincronizar` | P | `app/heartbeat.py:8-14` | `live` capture, keys exactly these + `ts` | — |
| A4a | PostgreSQL 16 in compose | P | `docker-compose.yml:42` `pgvector/pgvector:pg16` | `psql` → `PostgreSQL 16.15` | — |
| A4b | pgvector installed and enabled | P | `app/persistence/schema.sql:3`; HNSW index `:140-141` | `psql` → `vector 0.8.7`; 701 chunks | — |
| A4c | DB init and persistence functional | P | volume `assistant-db`; idempotent migrations `app/persistence/db.py:42-48` | `live` 12 tables; restart survival observed in logs | — |

### B. Voice-based shift reports

| ID | Requirement | Status | Evidence | Validation | Issue |
|---|---|---|---|---|---|
| B1a | Subscribes `planta/recorridas` | P | `app/integrations/mqtt.py:36`, `app/main.py:127` | `live`: notes 00002–00012 processed | — |
| B1b | Downloads audio + photos from `http://sim:8100{url}` | P | `app/integrations/plant_api.py:51-52`, `app/processing/workflow.py:181-190,236-252` | `live`: ASR latency rows in `usage_log`; photos archived | — |
| B1c | Missing/malformed media handled | **A** | `workflow.py:181-205` returns `""`; `:394-406` then emits `SinNovedad` | code | A note whose audio fails is reported as "sin novedad" — a silent failure that reads as "plant normal" |
| B1d | No external connectivity needed for audio | P | models burnt into image, `HF_HUB_OFFLINE=1` (`Dockerfile`) | `run` fuga-sin-enlace link down | — |
| B2a | Local model from the assignment's closed list | **NV** | `app/processing/asr.py:41-51` faster-whisper small | code | The closed list is not published in the provided material (INFORME says so); conformance cannot be verified |
| B2b | No cloud transcription; no silent cloud fallback | P | `asr.py` only local; no provider client in deps | code + `live` `usage_log` model `/models/faster-whisper-small` | — |
| B2c | Works with link lost (`fuga-sin-enlace`) | P | official run | `run`: 4/4 notes got drafts; alert raised | — |
| B3a | **Structured output** validated to `FilaParte` | **A** | `workflow.py:231` `row.to_contract()` → `MensajeTablet` validation `publisher.py:26-35`; extraction itself is `app/domain/parser.py` (rules) | `run` F1 = 0 invalid messages | There is no LLM structured-output extraction: the LLM is disabled by default and only used for replies. Deterministic parsing is defensible, but it is not "structured output" as asked |
| B3b | One row per equipment and variable | P | `parser.py:147-174` merge index | `run` A3b 18/18 + 4/4 fields; `live` NOTA-00011 4 rows/4 items | — |
| B3c | Row time = note `ts`, not machine clock | P | `parser.py:231`; events use note `ts` (`events.py:82`) | `run`, `live`: event `ts` equals `notes.ts` | — |
| B3d | Photos associated to the right row | P | `parser.py:337-348`; `workflow.py:236-252` | `pytest::test_draft_does_not_duplicate_photos` | Heuristic (clause with "foto", else last row) |
| B3e | Invalid/incomplete output handled safely | **A** | `parser.py:273-278` drops a clause when `detect_variable` is `None` | reproduced NOTA-00011 transcript: B-102 reading lost, no flag, no question | Silent data loss instead of an ambiguity |
| B4a | Informal names resolved via `GET /api/planta` | P | `main.py:57-66`, `plant_api.py:54-55`, `equipment.py:30-51` | `live` snapshot 7 equipment; `run` operator names resolved | — |
| B4b | "la dos" / "el de la izquierda" / "la de reserva" | P | `equipment.py` alias variants | live parse: B-102, F-201A, B-103 | — |
| B4c | Ambiguous ("la bomba") → ask, never guess | **A** | `equipment.py:100-114`; `workflow.py:302-330` | `run`: NOTA-00008 asked (eq0, 3 options); NOTA-00011 not asked | A4a = 75%: one ambiguous note produced no question because the reading was dropped first (B3e) |
| B5a | "kilos" = kg/cm² | P | `units.py:16-25` | live parse `112 kilogramos` → `kg/cm2` | — |
| B5b | Local gauge per TAG: B-101 kg/cm², B-102 psi, B-103 bar | P | `parser.py:83-94` + `datos/planta.yaml:19,28,37` | live parse: `la dos en 112 de descarga` → `112 psi` | — |
| B5c | Differential "dieciocho" triggers a question | P | `parser.py:293-316` | reproduced: value 1.8 + `Ambiguity(kind=value, raw=18)` | — |
| B5d | Units consistent through extraction→storage→confirmation | **A** | `workflow.py:302-330` asks, then `draft.ambiguities=[]` without applying the answer | code | The operator's answer to the value question is discarded |
| B6a | Historical range via `GET /api/historian/{tag}/{variable}` | P | `plant_api.py:60-67`, `history.py:65-67` | `curl` → 30 689 samples for B-101/presion_descarga over 45 d | — |
| B6b | 45-day window | P | `history.py:66` | `curl` with 45 d range | — |
| B6c | Out-of-range asks for confirmation before save | **A** | `history.py:79-101`, `workflow.py:361-371` | code | It asks, but the reply is neither required nor applied: the row is saved regardless |
| B6d | Confirmation cannot be bypassed accidentally | **A** | same | code | Not bypassable (always asks) but also not honoured — the confirmation is theatrical when the value is actually wrong |
| B7a | Draft sent in `MensajeTablet.pantalla.filas` | P | `workflow.py:227-241` | `run`: draft messages with `filas`; `live` DB | — |
| B7b | Selectable options whenever a decision is required | **A** | `workflow.py:229` options only for equipment questions | `run`: eq0 has 3 options | Value question (18 vs 1.8) and historical confirmation send **no** options although they require a decision |
| B7c | Understands field-language corrections | P | `replies.py:50-132` | `run`: "Te faltó la uno… Te faltó la dos…" → 2 rows added, draft resent (TAB-00011-1) confirmed; `pytest::test_replies` covers "No. La uno estaba en ciento quince kilos" | — |
| B7d | Updates the draft and resends it | P | `workflow.py:275-300` | `run` NOTA-00011: 2 → 4 rows, second draft confirmed | — |
| B7e | `Borrador` → `Confirmado` only after confirmation | **A** | `workflow.py:164-172` | code + SPEC §2 | On timeout/attempt exhaustion the part is stored `confirmed_with_differences` **and emits events** — documented trade-off, but it is not "only after confirmation" |
| B8a | `VIVO-…` needs no expected report | P | `workflow.py:132-138,394-406` | code | — |
| B8b | `VIVO-…` may contain nothing reportable | P | `_handle_empty` notices, no event | code | — |
| B8c | No fabricated measurements/events for VIVO | P | no event constructed on the VIVO branch | code | — |

### C. Plant anomaly detection (deterministic code, no LLM decision)

| ID | Requirement | Status | Evidence | Validation | Issue |
|---|---|---|---|---|---|
| C1a | Every confirmed part generates an `EventoSistema` | P | `workflow.py:409-440` | `live` DB: 17 events, one per equipment per note | — |
| C1b | Plant / sensor / `#` deviations generate events | P | `main.py:124-152`, `sensors.py:102-143` | code + `pytest::test_events_sensors` | — |
| C1c | Idempotent event ids | P | `events.py:71-72`, `sensors.py:130` (uuid5) | `run` E3 duplicates = 0 | — |
| C1d | Duplicate messages → no duplicate events | P | `repository.create_note` + `enqueue` dedupe; `insert_event ON CONFLICT` | `live` log: "duplicate note ignored" ×2 | — |
| C1e | Origin `parte` / `sensor` | P | `events.py:86,125`; `sensors.py:137` | `live` DB events `origin=parte` | — |
| C1f | Relevant `nota_ids` included | P | `events.py:87,127` | `run` events carry `nota_ids` | — |
| C2a | Limits from `planta.yaml` / `/api/planta` | P | `main.py:57-66`, `domain/plant.py` | `live` snapshot from API; fallback file | — |
| C2b | No limits from manual Rev. C | P | no manual text feeds decisions; `snapshot` is the only limit source | `grep` | — |
| C2c | Same data → same decision | P | pure functions in `events.py`/`sensors.py` | `pytest` | — |
| C2d | No nondeterministic LLM in detection | P | LLM only in `_review_loop` for unreadable replies | code | — |
| C3a | `SinNovedad` / `Escalado` classification | P | `events.py:108-129` | `run` B1 = 100% (18/18 + 4/4) | — |
| C3b | Escalated event carries part + photos + sensor trend | **A** | `workflow.py:423-440,444-462`, `rag/context.py:63-87` | `pytest::test_escalated_event_carries_photos_and_sensor_trend` | Implemented, unit-verified; **no** `Escalado` ever occurred in the two official scenarios (DB: 17/17 `SinNovedad`) |
| C3c | Sustained anomalies escalate | **A** | `sensors.py:20-59` (5 min, ≥3 samples, ≥80%) | `pytest` only | No runtime scenario exercised it |
| C3d | Isolated spikes do not escalate on their own | **A** | `sensors.py:46-53` | `pytest` only | Same; note the part path escalates on a **single** out-of-limit reading while calling it "anomalía sostenida" (`events.py:117`) |
| C3e | "parada, en reserva" is not an anomaly | P | `events.py:31-40`, `parser.py:372-376`; pump-state disambiguation | `run` B1 100%; `live` B-103 notes → `SinNovedad` | — |
| C4a | Local S1–S4 detection | P | `safety.py:19-75` | `pytest` on the four official texts incl. real ASR variants | — |
| C4b | Tablet shows emergency instructions | P | `safety.py:78-85`, `workflow.py:381-383` | `run` tablet notice 0.5 s, `espera_respuesta=false` | — |
| C4c | Supervisor radio notice | P | the same message instructs the radio call (`emergency_text`) | `run` payload | No separate radio channel exists in the contract; text is the mechanism |
| C4d | `espera_respuesta = false` | P | `workflow.py:382` | `run` audit | — |
| C4e | `AlertaSeguridad` < 30 real seconds | P | publish path `workflow.py:373-393` | `run`: **24.0 s** | Only 6 s of margin; depends on ASR speed/length |
| C4f | Few false positives | P | patterns + negation window `safety.py:52-75` | `run`: 0 false alarms; `pytest` ordinary notes | — |
| C4g | Works without link | P | regex + local ASR, no network | `run` fuga-sin-enlace (link down) | — |

### D. Tools and MCP

| ID | Requirement | Status | Evidence | Validation | Issue |
|---|---|---|---|---|---|
| D1a | Equipment tool (read-only) | P | `tools/queries.py:95-104` | code | — |
| D1b | Sensor history tool | P | `:106-118` | `pytest::test_sensor_history` | — |
| D1c | Work-order history tool | P | `:120-134` | `pytest::test_order_history` | — |
| D1d | Inventory tool | P | `:136-145` | `pytest::test_inventory_stock_and_bom`; MCP call | — |
| D1e | Stock tool | P | `:147-153` | same | — |
| D1f | Bill of materials tool | P | `:155-164` | same | — |
| D1g | Task catalog tool | P | `:166-180` | no dedicated test | Read-only |
| D1h | Manual search tool | P | `:182-191` | MCP probe returned cited hits | — |
| D2a | Strict Pydantic, `extra="forbid"` | **A** | `tools/contracts.py:8-9` on every model | `pytest::test_strict_input_contracts` | `TaskInfo.repuestos: list[dict]` (`:124`) is untyped; several enums are bare `str` |
| D2b | Reject unexpected fields | P | `extra="forbid"` | `pytest` | — |
| D2c | Reject invalid values / enforce types | **A** | bounds on `limite`, `k`; free strings elsewhere | code | e.g. `StockQuery.almacen` accepts any string; no `ge=0` on quantities |
| D3 | At least one tool exposed by an MCP server | P | `integrations/mcp_server.py:68-126` (FastMCP, stdio, 8 tools) | real `mcp` client probe: `initialize`, `list_tools` (8), `call_tool inventario` (17 parts), `stock` error → `isError=true`, `buscar_manuales` cited | — |
| D4a | Error handling per tool | P | `ToolError` + `audited` decorator `queries.py:50-73` | `pytest` unknown part/sensor | — |
| D4b | Timeout configuration | P | `PlantClient(timeout=10)`, httpx 8 s in sync | code | — |
| D4c | Retry behaviour | P | `plant_api.py:28-42` (3 attempts) | `pytest::test_plant_client_retries_transport_errors` | — |
| D4d | Unavailable-service handling | P | `PlantUnavailable`, fallbacks | `pytest` | — |
| D4e | Validation of external responses | **A** | `SensorHistory`/`OrderHistory` build typed models but `sensores`/`orders` raw keys are used directly (`queries.py:117,129`) | code | A malformed plant payload raises a raw `KeyError`, not a typed error |
| D4f | Automated tests in `tests/` for every tool | **A** | `tests/test_tools.py`, `test_audit_regressions.py` | `grep` | No tool-level tests for `equipos`, `catalogo_tareas`, `buscar_manuales` |

### E. Agent execution control and evaluation

| ID | Requirement | Status | Evidence | Validation | Issue |
|---|---|---|---|---|---|
| E1a | Explicit stop conditions | P | `workflow.py:275` loop guard + deadline | code | — |
| E1b | Maximum step budget | **A** | `max_attempts` = 6 enforced (`workflow.py:275`) | code | `MAX_NOTE_STEPS` (`config.py:45`) is never read |
| E1c | Token budget | **F** | `token_budget` (`config.py:46`) never read | `grep` over `app/` | Declared and documented as enforced, but there is no enforcement path |
| E1d | Global timeout per note | P | `note_timeout_s` (`workflow.py:135,283`) | code | — |
| E2a | Repository contains a concise workflow spec | P | `docs/SPEC_PARTE.md` | read | — |
| E2b | Spec accurately describes the implementation | **A** | SPEC §1 "p1–p99" vs `history.py:36-42` (min/max); §6 claims `MAX_NOTE_STEPS`/`TOKEN_BUDGET` enforced; §3 "25 s wait" vs `workflow.py:283` (40 s) | diff | Doc drift on limits and range rule |
| E3a | Can be evaluated against `/api/verdad` | P | `evaluacion/evaluar_parte.py` | `docker compose exec cerebro python -m evaluacion.evaluar_parte` → ran | — |
| E3b | Accuracy per extracted field | P | same | `live` dev: 11/15 (73.3%); official run (independent audit script): 18/18 and 4/4 | — |
| E3c | Question asked only when genuinely ambiguous | **A** | `evaluar_parte.py:71-76` | live: 1/1 ambiguous asked | Metric is coarse (`count(*) > 1` tablet messages) |
| E3d | Unnecessary questions avoided | **A** | only the official A4b measures it (100%) | `run` | The first-party evaluator has no false-question metric |

### F. RAG, context and memory

| ID | Requirement | Status | Evidence | Validation | Issue |
|---|---|---|---|---|---|
| F1a | Documents indexed in PostgreSQL/pgvector | P | `schema.sql:122-141`, `rag/indexer.py`, `search.py:51-79` | `psql`: 701 chunks, HNSW index, `vector 0.8.7` | — |
| F1b | Metadata equipment/manufacturer/document/section/citation/`vigente` | P | `rag/indexer.py:29-46`; `rag_chunks` columns | `psql`: **458/458** document chunks have manufacturer + equipment; 243 `historial` chunks legitimately have none | — |
| F2a | Rev. C (superseded) not preferred | P | `bm25.py:78-84` (×0.6) | eval: distractor@5 **0** (baseline 6) | — |
| F2b | TX-250/TX-500/FC-24/FC-96/PIA-1/PIA-2 sections not applied wrongly | P | `bm25.py:16,85-87` (section-title penalty) | `pytest::test_metadata_penalises_other_models`; distractor@5 = 0 | — |
| F2c | Manufacturer fault codes → F01–F10 (`MBP-4 §6`) | P | `rag/codes.py` | `pytest::test_manufacturer_codes_translate_to_plant_catalogue` | — |
| F3a | Uses `evaluacion/retrieval.json` (71 questions) | P | `evaluacion/retrieval_eval.py:16-20` | run: n=71 | — |
| F3b | Required call `corpus.evaluar.evaluar(buscar, suite)` | **A** | private `evaluate()` copy (`retrieval_eval.py:23-47`) + private `BM25` (`app/rag/bm25.py`) | `grep` → no `corpus.evaluar` anywhere | Methodology and metric names are identical (verified by comparing `planta/corpus/evaluar.py`), but the required entry point is not used |
| F3c | Compare with BM25 baseline hit@5 0.85 / recall@5 0.66 | P | `informe_retrieval.json` | re-ran in container | — |
| F3d | Report hit@5, recall@5, Rev.-C-before-D | P | same | **hit@5 0.873, recall@5 0.718, Rev.C-before-D 0** (baseline measured 0.859 / 0.674 / 6) | — |
| F4 | Conclusions cite the manual section | P | `ManualHit.cita` (`tools/contracts.py:138`), `rag/context.py:73` | MCP probe returned `TX350-D §12.1` etc. | Delivery 1 makes no manual-derived conclusion; the citation path exists |
| F5a | Operational limits **not** from RAG | P | limits only from snapshot (`domain/plant.py`) | code | — |
| F5b | Inventory/stock **not** from RAG | P | `domain/materials.py` + `datos/materiales.yaml`; plant exposes no stock API | code + `/openapi.json` | — |
| F5c | Architectural choice justified | P | `README.md` (plant/cloud split), `docs/IMPLEMENTATION_STATUS.md` | read | — |
| F6 | Context builder designed and implemented to D1 scope | P | `rag/context.py` (rows, photos, 6 h trend, cited sections, order history, parts) | `pytest::test_escalated_event_carries_photos_and_sensor_trend` | Full analysis is explicitly Delivery 2 |
| F7a | Conversation state persisted in Postgres | P | `schema.sql` (`notes`, `parts`, `attempts`, `tablet_messages`, `replies`) | `psql`: rows present for every live note | — |
| F7b | Written retention policy | P | `docs/MEMORIA.md` | read | — |

---

## 3. Critical findings

### P0 — Critical (elimination / safety / system down)

**None observed.** The safety alert fired for the only unsafe note, the tablet got its notice in 0.5 s with `espera_respuesta=false`, and the system published 76 + 42 valid messages across both scenarios.

### P1 — High

**P1-1 · Missing submission artefact (A1d, BLOCKED).**
`git remote -v` is empty. Nothing in the workspace shows a public GitHub repository named `nombre-apellido`, which is a hard delivery requirement. *Change:* add the remote, push, and record the URL in `README.md`.

**P1-2 · Token and step budgets declared but not enforced (E1c FAIL, E1b PARTIAL).**
`app/config.py:45-46` defines `max_note_steps` and `token_budget`; `grep -rn "max_note_steps\|token_budget" app/` returns only the definition. `docs/SPEC_PARTE.md` §6 states the token budget disables the LLM per note. *Why it matters:* the delivery is graded on execution control; a documented-but-absent limit is a false claim. *Change:* enforce both in `_review_loop` / `LocalLLM` (accumulate usage per note, stop when exceeded), or remove the claim and the settings.

**P1-3 · RAG evaluation does not use the required entry point (F3b).**
The assignment names `corpus.evaluar.evaluar(buscar, suite)`. The project ships a copy (`evaluacion/retrieval_eval.py:23-47`) plus its own `BM25`. The numbers are real and reproduce the baseline (0.873 / 0.718 / 0 distractor vs 0.859 / 0.674 / 6), so the *result* is credible — but a grader comparing artefacts sees a re-implementation. *Change:* import `corpus.evaluar` from the provided plant repo (or vendor it unchanged with a provenance header) and call it with the hybrid `buscar`.

**P1-4 · Plant-PC services only partially conform (A2b, A2c, A2e).**
`panel` joins `planta-lan` + `control` and has no `academia.planta: pc` label; `nube-sync` has no resource caps. The composite resource envelope is 7 625 MiB / 4.0 CPU *excluding* `nube-sync`. *Change:* label `panel`; either cap `nube-sync` or document it explicitly as out-of-scope for the plant budget in the README and in the compose comments; keep the CPU sum ≤ 4.

**P1-5 · Safety alert has 6 s of headroom and a single point of failure (C4e).**
Measured 24.0 s against the 30 s limit. The whole chain depends on the ASR producing one of the regex phrases; a dropped word means no alert, which is the `sin_alerta_de_seguridad` elimination. *Change:* publish a provisional `AlertaSeguridad` as soon as a partial/streaming transcript contains any S1–S4 keyword (before the note completes), and widen the pattern set with the ASR variants already observed ("olor agas", "agua, presión", "Ni compañero").

**P1-6 · Silent loss of a measurement on `p.c.`-style punctuation (B3e, B4c, A4a).**
Reproduced with the official NOTA-00011 transcript: `1600 p.c. de descarga` tokenises as `1600 p . c . de descarga`, the clause ends at the first `.`, `detect_variable("ambient la bomba esta en 1600 p")` is `None`, so the clause is skipped: no row and no ambiguity. The corrector scored exactly this as A2 7/9 and A4a 1/2. *Change:* treat `p . c .`, `kg . cm2`, `p s i` and similar equipment/unit spellings as non-breaking inside the tokenizer or the clause splitter, and raise an ambiguity (not silence) when a clause has a number plus an unresolved equipment family.

### P2 — Medium

**P2-1 · Historical-range confirmation is asked but never used (B6c, B6d).**
`workflow.py:361-371` sends the question, awaits, discards the answer; the row is saved unchanged either way. A value the operator denies is still stored and still generates the event. *Change:* parse the reply (`read_reply(..., "question_value")`), apply it, and mark the row `unconfirmed` when no valid answer arrives.

**P2-2 · Value-ambiguity answer is discarded (B5d).**
`_resolve_ambiguities` asks "¿uno coma ocho o dieciocho?" then sets `draft.ambiguities = []` and keeps the repaired value. If the operator says "dieciocho", the system stores 1.8. *Change:* apply `reading.value` with the right unit and re-run the limit check.

**P2-3 · Unconfirmed parts still generate events (B7e).**
`workflow.py:164-172` stores `confirmed_with_differences` and `_finalize` publishes events anyway. This contradicts the state table ("Confirme… Recién entonces genera eventos") and the assignment's `Borrador → Confirmado` rule. The trade-off (don't blind the plant) is legitimate, but it must be a documented, configurable policy — the SPEC currently presents it as degradation without stating the event consequence.

**P2-4 · A note with unreadable media becomes "SinNovedad" (B1c).**
`_transcribe` returns `""` on download/ASR failure; `_handle_empty` then publishes `SinNovedad` for non-VIVO notes (`workflow.py:394-406`). A failed note must not assert the plant is normal. *Change:* emit a distinct degraded event/tablet notice and retry, never `SinNovedad`.

**P2-5 · Strictness gaps in tool contracts (D2a, D2c, D4e).**
`TaskInfo.repuestos: list[dict]`; free-text `almacen`; raw plant keys indexed directly (`queries.py:117,129`) so a malformed payload surfaces as `KeyError`. *Change:* type the nested models, add `Literal`/`pattern` for warehouses, wrap external payload parsing in `ToolError`.

**P2-6 · Missing tool-level tests (D4f).**
`equipos`, `catalogo_tareas` and `buscar_manuales` have no test in `tests/` (grep). The MCP integration test exercises `inventario` only. *Change:* three small tests, including a malformed external payload per D4e.

**P2-7 · Reported score and field accuracy overstate the preserved evidence (E2, docs).**
`README.md:274`, `INFORME.md`, `docs/RESULTADOS.md` and `docs/IMPLEMENTATION_STATUS.md` say **90.4** "última corrida". The preserved official run (the only one at HEAD `c2efa19`) re-scores **88.8**, and the archived `var/corrida*` runs are 73.5 / 82.4 / 89.2. `INFORME.md` also claims 22/22 fields; my independent re-run of the dev-mode `/api/verdad` evaluator today gives **11/15 (73.3%)** on the live `libre` run (the official-run audit gives 18/18 and 4/4). *Change:* publish the score of the run whose artefacts are kept, and state the scenario/conditions for the field-accuracy figure.

### P3 — Low

- **P3-1** `docs/SPEC_PARTE.md` drifts from the code: "p1–p99" (code uses min/max), "25 s wait" (code 40 s), `MAX_NOTE_STEPS`/`TOKEN_BUDGET` enforcement.
- **P3-2** Heartbeat is emitted on every publish in addition to the 30 s cadence (`publisher.py:37-42`); harmless for F2 but not literally "every 30 s".
- **P3-3** A part reading outside limits is summarised as "Anomalía sostenida" (`events.py:117`) although a single operator measurement is not a trend.
- **P3-4** `clean_session=True` (`mqtt.py:23`) means QoS1 traffic published while the assistant is down is lost; only durable state is the DB.
- **P3-5** `mypy` is configured but not a gate (52 findings); `ruff` is the gate.
- **P3-6** `_split_tag_like` and `_alias_variants` contain ASR-specific heuristics ("filto", "fito", "frito", "a uno") that are pragmatic but undocumented in the SPEC.

---

## 4. Test execution report

All commands were run from `/home/ramon-ariel-et12/Projects/academiaNovit2026` on 2026-11-10. Nothing was modified.

| # | Command | Result |
|---|---|---|
| 1 | `TEST_DATABASE_URL=postgresql://pia:...@172.18.0.3:5432/pia uv run pytest -q` | **131 passed**, 0 failed, 0 skipped, 4.14 s (includes the real-Postgres integration test) |
| 2 | `docker compose config` | exit 0; services/networks/labels/limits enumerated; CPU 4.0, memory 7 625 MiB |
| 3 | `docker exec pia-asistente-db-1 psql -U pia -d pia -c "select extname,extversion from pg_extension"` | `vector 0.8.7`; `PostgreSQL 16.15`; 12 tables |
| 4 | `psql … select count(*) … from rag_chunks` | 701 chunks, 593 `current`, 458 with manufacturer+equipment (all document chunks) |
| 5 | `docker exec planta-broker-1 mosquitto_sub -t sistema/estado` (75 s) | two beats, gap **30.009 s**, keys `ts, sistema, enlace_ok, pendientes_sincronizar` |
| 6 | `docker compose exec cerebro python -c "import planta_contrato"` | `planta_contrato 0.2.0` at `/app/.venv/lib/python3.11/site-packages/` |
| 7 | MCP stdio client probe (`initialize`, `list_tools`, `call_tool` ×3) | 8 tools; `inventario` 17 parts; `stock` error → `isError=true`; `buscar_manuales` cited hits |
| 8 | `docker compose exec cerebro python evaluacion/retrieval_eval.py` | **hit@5 0.873 · recall@5 0.718 · MRR 0.678 · distractor@5 0**; BM25 baseline 0.859 / 0.674 / 0.581 / 0.085; Rev.C-before-D 6 → 0 |
| 9 | `uv run python academia2026-tp/correccion/puntuar.py academia2026-tp/correccion/corridas/academiaNovit2026` | **88.8 / 100 · APRUEBA**, `peso_medido 63/93`, `eliminatorias {}`, entrega README/compose/tests = true |
| 10 | `uv run python scripts/audit_escenario.py …/martes-tranquilo.json` | 9 notes, 76 msgs, 0 invalid; A1 9/9, A2 7/9, A3 8/9, A3b **18/18**, A4a 1/2, A4b 7/7, B1 18/18, 0 false alarms, 28 heartbeats / 0 gaps > 60 s, 0 duplicate event groups |
| 11 | `uv run python scripts/audit_escenario.py …/fuga-sin-enlace.json` | 4 notes, 42 msgs, 0 invalid; A1 4/4, A2 2/4, A3 2/4, A3b **4/4**, A4a 1/1, A4b 2/2, B1 4/4, **S1 alert in 24.0 s real, tablet notice 0.5 s, espera_respuesta=false**, 0 false alarms |
| 12 | `docker compose exec cerebro python -m evaluacion.evaluar_parte` | `Notas evaluadas: 8 de 8` · `Aciertos por campo: 11/15 (73.3%)` · `Notas ambiguas con pregunta: 1/1` |
| 13 | Parser reproduction of the NOTA-00011 transcript | rows = `[B-101 112 kg/cm2]`, ambiguities = `[]` → B-102 reading silently lost |
| 14 | Parser spot checks (B-102 default psi, "kilos", "dieciocho", "la bomba") | `112 psi`, `kg/cm2`, `1.8 + value ambiguity (raw 18)`, `3 equipment candidates` |

### Official scenario evaluation

`corregir.py --escenarios martes-tranquilo fuga-sin-enlace` was **not re-run** by me. It would have to replace the running development stack (`docker compose -p planta`, ports 8200/8300) and I did not want to tear down the user's live environment.

I did verify that the preserved run *is* the current code: `meta.json` records commit `c2efa19` (= HEAD), and no source file has an mtime after 17:00 while the run started at 17:10 (only README/INFORME/docs changed after). I then re-scored that run with the official `puntuar.py` and audited it with `scripts/audit_escenario.py` (rows 9–11). **Reported score: 88.8, aprueba, no eliminatory faults.**

To reproduce end-to-end: stop the dev stack (`docker compose stop`), then `./scripts/evaluar.sh` or the canonical `corregir.py` invocation; the run takes ≈7 minutes.

### Environment limitations

- No GPU; plant PC simulated at 3 CPU / 6 GB for `cerebro` in this stack.
- The AWS/cloud side is a local `nube-sync` container, not a real cloud.
- The approved closed model list is not published in the provided material, so B2a remains NOT VERIFIED by design.
- `mypy` not executed as a gate (not part of the acceptance criteria).

---

## 5. Implementation roadmap

Ordered by risk-to-score. Each item is independently verifiable.

| Pri | Req | Files | Expected change | Depends on | Verify with |
|---|---|---|---|---|---|
| 1 | A1d | `README.md`, git config | Create/publish `nombre-apellido` on GitHub, add `origin`, record the URL in the README | — | `git remote -v`; open URL |
| 2 | E1b, E1c | `app/processing/workflow.py`, `app/llm/local.py`, `app/config.py` | Enforce `max_note_steps` in `_review_loop` (stop → `confirmed_with_differences` with reason) and a per-note token counter that disables the LLM when `token_budget` is exhausted; log both to `usage_log` | — | New unit test: lowering the budgets aborts the loop |
| 3 | F3b | `evaluacion/retrieval_eval.py`, `app/rag/bm25.py` | Import `corpus.evaluar` from the provided plant repo (`sys.path`/vendor copy with provenance) and pass the hybrid `buscar`; keep the current report as a cross-check | plant repo present | `python evaluacion/retrieval_eval.py` prints `evaluar` results; metrics unchanged ±0.01 |
| 4 | B3e, B4c, A4a | `app/domain/parser.py`, `app/domain/numbers.py`, `app/domain/equipment.py` | Make unit/tag abbreviations (`p.c.`, `p.s.i.`, `kg.cm2`, `b.101`) non-breaking in `preprocess`/`split_clauses`; when a clause has a number + unresolved equipment family, raise an ambiguity instead of dropping it | — | Regression test with the NOTA-00011 transcript → 2 rows or an equipment ambiguity; re-run the corrector (expect A2 ≥ 8/9, A4a 2/2) |
| 5 | C4e | `app/processing/workflow.py`, `app/domain/safety.py` | Publish a provisional S1–S4 alert from the partial transcript before the full note completes; extend patterns with observed ASR variants | — | e2e probe with an S1 note; measure publish-to-alert latency (< 10 s target) |
| 6 | B6c, B6d, B5d | `app/processing/workflow.py`, `app/processing/replies.py` | Consume the answers to the historical and value questions: apply the value, re-check limits, mark unconfirmed when no valid answer; add Sí/No options where a decision is discrete | item 4 | Unit tests: "No, era ciento quince" changes the row; no answer → row flagged, part not confirmed |
| 7 | A2b, A2c, A2e | `docker-compose.yml` | Label `panel` with `academia.planta: pc`; cap `nube-sync` or document it as outside the plant budget; keep CPU sum ≤ 4 | — | `docker compose config` assertion script |
| 8 | B1c, P2-3 | `app/processing/workflow.py` | Distinguish "media/ASR failure" (degraded notice + retry, no event) from "no reportable data"; make the timeout-event policy explicit and configurable | — | Unit test: audio 404 → no `SinNovedad`, a `degraded` state is stored |
| 9 | D2a, D2c, D4e | `app/tools/contracts.py`, `app/tools/queries.py` | Type `TaskInfo.repuestos` as a model; `Literal`/`pattern` on warehouse and codes; wrap external payload parsing in `ToolError` | — | `pytest` new contract tests |
| 10 | D4f | `tests/` | Add tests for `equipos`, `catalogo_tareas`, `buscar_manuales` (including a malformed external payload) | item 9 | `pytest` |
| 11 | E2b, P3-1 | `docs/SPEC_PARTE.md` | Align p1–p99 vs min/max, wait timeouts, and the limits once item 2 lands | item 2 | Doc review |
| 12 | P2-7 | `README.md`, `INFORME.md`, `docs/RESULTADOS.md`, `docs/IMPLEMENTATION_STATUS.md` | Publish the score of the preserved run (88.8 / current artefacts), state the scenario for the field-accuracy figure | item 4 (new run) | Diff against `resultado.json` |

Grouping: items 2 + 11 + 12 belong to one "honesty of declared controls" change; items 4 + 6 + 5 share the workflow and should land together behind new regression tests; items 7–10 are independent and low-risk.

---

## 6. Final submission checklist

**Must be true before submitting Delivery 1**

- [ ] Public GitHub repo `nombre-apellido` exists; `README.md`, `docker-compose.yml`, `tests/` at root; remote URL in the README (A1).
- [ ] `docker compose up` from a clean machine brings up the system next to the plant; `cerebro`/`db` on `planta-lan` with `academia.planta: pc`; `panel` labelled; total CPU ≤ 4 and memory ≤ 8 GB **including** every student-side service (A2).
- [ ] `planta_contrato` installed with pip at build time; no local copy of the models (A3).
- [ ] Heartbeat on `sistema/estado` every 30 s with `sistema`, `enlace_ok`, `pendientes_sincronizar` (A3).
- [ ] PostgreSQL 16 + `vector` extension created on first start; data survives a restart (A4).
- [ ] Local ASR only; a note dictated with the link down still produces a draft and an event (B1, B2).
- [ ] Every note yields one `FilaParte` per equipment and variable, with the note `ts` and the right photo (B3).
- [ ] Ambiguous equipment is always asked, never guessed; the `p.c.`-style clause loss is fixed (B4, finding P1-6).
- [ ] Units: "kilos"→kg/cm², B-101 kg/cm², B-102 psi, B-103 bar; "dieciocho" asks (B5).
- [ ] Out-of-range values ask **and** honour the answer before saving (B6).
- [ ] Tablet draft in `pantalla.filas`; corrections understood and re-sent; `Borrador → Confirmado` only on confirmation (B7).
- [ ] `VIVO-…` notes need no expected report and fabricate nothing (B8).
- [ ] Every confirmed part and every sustained sensor deviation produces exactly one idempotent event with `origen` and `nota_ids` (C1).
- [ ] Limits only from `planta.yaml`/`/api/planta`; decisions deterministic (C2).
- [ ] Escalated events carry part, photos and trend; "parada, en reserva" is normal (C3).
- [ ] S1–S4 detected locally, tablet notice with `espera_respuesta=false`, `AlertaSeguridad` **< 30 s** (target < 10 s), no false alarms, works with the link down (C4).
- [ ] Eight read-only tools, strict Pydantic, at least one callable over MCP, tests for each (D).
- [ ] Stop condition, step budget, token budget and global timeout enforced in code (E1).
- [ ] Spec matches the code (E2); `/api/verdad` evaluation reports per-field accuracy and precision of questions (E3).
- [ ] pgvector index with full metadata; Rev. C, other-model sections and fault codes handled; `corpus.evaluar.evaluar` used; hit@5 ≥ 0.85, recall@5 ≥ 0.66, Rev. C before D reported (F1–F3).
- [ ] Citations carry the manual section; limits and stock never come from RAG; context builder in place (F4–F6).
- [ ] Conversation state persisted; retention policy written (F7).
- [ ] Final official run executed on the pushed commit: `corregir.py --escenarios martes-tranquilo fuga-sin-enlace`, no `sin_alerta_de_seguridad`, no `sistema_mudo`, score recorded with its artefacts.


---

## 7. Post-audit changes (applied after this report)

These were implemented and verified after the audit snapshot. They do not change the
verdict above, which records the state the audit measured.

| Finding | Change | Verification |
|---|---|---|
| P1-6 / B3e | `app/domain/equipment.py`: a dot after a single letter (`p.c.`, `p.s.i.`) no longer splits the clause, so the reading survives and the bare "la bomba" becomes an ambiguity instead of a silent drop | `tests/test_parser.py::test_unit_abbreviation_with_dots_does_not_split_the_clause` |
| P2-1 / P2-2 / B5d / B6c-d | `app/processing/workflow.py`: the operator's answer to the value and historical questions is now applied (new value replaces the reading, a plain "no" removes it, no answer flags `historical_unconfirmed`); both questions carry options | `tests/test_workflow_flow.py` (value, historical, step and token budget, unreadable audio) |
| P1-2 / E1b-c | `MAX_NOTE_STEPS` and `TOKEN_BUDGET` are enforced in `_review_loop`; the LLM is disabled per note once the budget is spent | `test_step_budget_caps_the_review_loop`, `test_token_budget_disables_the_local_llm` |
| P2-4 / B1c | A note whose audio cannot be downloaded or transcribed is stored `unreadable` and announced, never reported as `SinNovedad` | `test_unreadable_audio_is_not_reported_as_no_novedad` |
| P1-4 / A2b-c-e | `docker-compose.yml`: `panel` labelled `academia.planta: pc`; `db` and `nube-sync` capped; total 4.0 CPU and 7 552 MiB including every student-side service | `docker compose config` |
| P2-5 / D2a-c, D4e | Typed `PartUse` for task spares, `Literal` warehouses, external payloads validated into `ToolError` | `tests/test_tools.py` |
| P2-6 / D4f | Tool-level tests for `equipos`, `catalogo_tareas`, `buscar_manuales` | `tests/test_tools.py` |
| P1-3 / F3b | `evaluacion/retrieval_eval.py` calls `corpus.evaluar.evaluar(buscar, suite)` when the plant repo is present and asserts both evaluators agree | `tests/test_rag.py::test_the_course_evaluator_agrees_with_the_local_copy` |
| P2-7 | README, INFORME, RESULTADOS and IMPLEMENTATION_STATUS now report the archived run (88.8), the 24.0 s alert and the dev-mode field accuracy | documents |
| P3-1 | `docs/SPEC_PARTE.md` aligned with the code (observed range, 40/20 s waits, enforced budgets, `unreadable` status) | document |

Suite after the changes: **143 passed** at that point. On the final tree (`34e1120`) the
same suite runs **169 passed, 0 failed, 0 skipped** with the live Postgres, `ruff check .`
is clean, and both CI workflows are green.

### Resolved on the final tree (`34e1120`; official run on `b9fa0ff`)

- **A1d closed**: published at <https://github.com/Ramon-Ariel-ET12/ramon-ariel> (public,
  `master`, anonymous reads 200 for `README.md`, `docker-compose.yml` and `tests/`).
- **Official re-run done**: 91.3/100, `aprueba: true`, `eliminatorias {}` on
  `martes-tranquilo` + `fuga-sin-enlace`; the archived run and the documents agree.
- **E1b-c**: `MAX_NOTE_STEPS` and `TOKEN_BUDGET` are enforced
  (`app/processing/workflow.py:321,335`) and covered by tests.
- **F3b**: `corpus.evaluar.evaluar` is the evaluator, and the `RAG retrieval` workflow runs
  it in CI (hit@5 0.873 / recall@5 0.718 / distractor 0).
- **P2-7**: docs report the archived run's score, not an earlier one.

Still open, and not closable from this repository:

- **B2a**: conformance with the closed model list cannot be verified until the course
  publishes the list.
- **A2b**: `panel` is dual-homed (`planta-lan` + `planta-control`) and carries the label;
  the single deviation from "solo `planta-lan`" is documented in the README and in
  `docs/VERIFICACION_ANEXO.md` item 3.
