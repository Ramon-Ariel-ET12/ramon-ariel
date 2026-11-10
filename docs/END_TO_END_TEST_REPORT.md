# End-to-end test report — Delivery 1

Human-like verification of the PIA-3 assistant against the **official simulator**, with the
real MQTT bus, real synthesised operator audio, the local ASR model, the PostgreSQL state
and the official link simulator. No call in these workflows is mocked.

## How the tests were driven

The plant records a voice note through its own supported action, exactly as the operator
page does:

```
POST http://localhost:8100/api/control/accion
{"accion": "nota", "params": {"texto": "<what the operator dictates>",
                              "items": [<field truth>], "fotos": ["/media/fotos/…"]}}
```

The simulator synthesises the audio (piper), publishes a real `NotaRecorrida` on
`planta/recorridas`, and its **virtual operator** answers the tablet with field language on
`planta/respuestas`. The probe (`scripts/e2e_probe.py`) subscribes to `sistema/#` and prints
every tablet message, event, order and heartbeat as it happens; `scripts/audit_escenario.py`
recomputes the metrics from the raw register.

Environment: plant scenario `martes-tranquilo` (no injected failures), clock at ×1–×2 for
the manual notes, `planta` and `pia-asistente` stacks up, link controlled through
`POST /api/control/accion {"accion":"enlace"}` (the official link simulator).

---

## Scenario 1 — Normal inspection

**Initial conditions.** Fresh state, link up, plant running normally.

**Steps.** Dictated: "La uno está en ciento doce kilos de descarga."

**Expected.** Draft with one row (B-101, discharge pressure, 112 kg/cm², note timestamp),
operator confirmation, `SinNovedad`, no anomaly.

**Actual.** `TAB-NOTA-00001-0` at 2.0 s with exactly that row; operator confirmed; event
`SinNovedad` for B-101 at 21.4 s; acknowledgement `TAB-NOTA-00001-ok`.

**Status: PASS.**
```
[ 2.0s] TABLET TAB-NOTA-00001-0 espera=True filas=1
         fila: {"tag":"B-101","variable":"presion_descarga_local","valor":112.0,"unidad":"kg/cm2"}
[21.4s] EVENTO SinNovedad equipo=B-101 origen=parte nota_ids=['NOTA-00001']
[21.5s] TABLET TAB-NOTA-00001-ok espera=False  texto: Parte guardado.
```

---

## Scenario 2 — Ambiguous equipment ("la bomba")

**Steps.** Dictated: "La bomba está en ciento doce kilos de descarga."

**Expected.** The system must not guess: it asks which pump and offers the three options.
The operator answers in field language; the draft is rebuilt with the right TAG and
confirmed.

**Actual.** `TAB-NOTA-00001-eq0` at 2.1 s with `opciones = ["la uno (B-101)", "la dos
(B-102)", "la tres (B-103)"]`; the operator answered; the draft `TAB-NOTA-00001-0` arrived
with `B-101 / 112 kg/cm2` and was confirmed; event `SinNovedad`.

**Status: PASS.**
```
[ 2.1s] TABLET TAB-NOTA-00001-eq0 espera=True filas=0
         opciones=['la uno (B-101)', 'la dos (B-102)', 'la tres (B-103)']
[36.2s] TABLET TAB-NOTA-00001-0 filas=1
         fila: {"tag":"B-101","variable":"presion_descarga_local","valor":112.0,"unidad":"kg/cm2"}
[56.5s] EVENTO SinNovedad equipo=B-101
```

---

## Scenario 3 — Units and ambiguous values

**Steps.** Dictated: "La dos está en mil seiscientos veinte psi de descarga y la tres está
en ocho bar de descarga. El filtro A me dio dieciocho de diferencial."
Field truth: B-102 1620 psi, B-103 8 bar, F-201A 1.8 kg/cm².

**Expected.** Each reading keeps the unit of its own gauge; "dieciocho" is asked, not read
as 18; out-of-band values ask for confirmation; events accordingly.

**Actual.**
```
fila: {"tag":"B-102","variable":"presion_descarga_local","valor":1620.0,"unidad":"psi"}
fila: {"tag":"B-103","variable":"presion_descarga_local","valor":8.0,"unidad":"bar",
       "observacion":"presión de descarga baja"}
fila: {"tag":"F-201A","variable":"presion_diferencial","valor":1.8,"unidad":"kg/cm2",
       "observacion":"diferencial alto"}
events: SinNovedad B-102 · Escalado B-103 · Escalado F-201A
orders: Aprobada F-201A ['T-F-CAR'] · PendienteAprobacion B-103 ['I-VIB']
        motivo: "tarea no estándar para B-103: I-VIB; la tarea I-VIB la hace contratista; requiere contratista"
tablet: TAB-NOTA-00001-val0 (value question, "¿El diferencial fue uno coma ocho o dieciocho?")
        TAB-NOTA-00001-hist0 / -hist1 (out-of-band confirmation)
```
The value question was asked for "dieciocho" and the stored value is 1.8; 8 bar was
correctly judged below the 95 kg/cm² operating minimum, and the order for a non-standard
task went to the planner with an explicit reason — the approval rules applied in code.

**Status: PASS.**

---

## Scenario 4 — Correction by voice

**Steps.** Dictated "…ciento doce kilos…, le saqué foto al manómetro" while the field truth
was 115 kg/cm² (the operator misreads and the system must let the operator correct).

**Expected.** First draft 112; the operator corrects in field language; second draft 115;
confirmation; the timestamp and the photo are preserved.

**Actual.**
```
[ 2.3s] TABLET TAB-NOTA-00001-0  fila valor=112.0
[16.8s] TABLET TAB-NOTA-00001-1  fila valor=115.0        ← operator: "No, la uno estaba en ciento quince kilos"
[46.6s] EVENTO SinNovedad equipo=B-101
parts.rows[0].photo = "/data/media/photos/NOTA-00001/01.jpg"
events.context.photos = ["/data/media/photos/NOTA-00001/01.jpg"]
```
The archived photo is attached to the corrected row, the note timestamp is unchanged and
the event carries the photo.

**Status: PASS.**

---

## Scenario 5 — Sustained sensor anomaly versus isolated spike

**Steps.** Readings injected on the official topic `planta/sensores/{tag}/{variable}` with
the plant clock paused (so the simulator adds no samples of its own):
1. isolated spike: 112 → **130** → 112 kg/cm² on B-102 (limit 125);
2. sustained deviation: five samples at 130 kg/cm², one simulated minute apart;
3. continued deviation: three more samples at 131;
4. recovery: six samples at 112.

**Expected.** No event for the spike; exactly one `Escalado` for the sustained deviation;
no duplicate while it continues; the episode closes when the values recover.

**Actual.**
```
spike   → 0 events
sustained → 1 event: Escalado B-102 origen=sensor
            "Desvío sostenido de presion_descarga en B-102: alarma alta durante 5 minutos."
continued → still 1 event (same id)
recovery  → sensor_state: active=false, since=NULL, event_id=NULL
```
The escalated event context contains the 6-hour trend per variable (`n, min, max, last`,
with units), the order history and the available parts.

**Status: PASS.**

---

## Scenario 6 — Safety emergencies (S1–S4), including offline

**Steps.** Each unsafe condition raised with the simulator's own action
(`{"accion":"seguridad","codigo":"S1…S4","equipo":"…"}`), which dictates the official text
with synthesised audio. S1 was repeated with the link **down**.

**Expected.** Emergency instruction on the tablet, `espera_respuesta: false`, radio notice
to the shift supervisor, `AlertaSeguridad` in under 30 real seconds, no false alerts.

**Actual.**

| Code | Text heard by the ASR | Detected | Alert latency | `espera_respuesta` |
|---|---|---|---|---|
| S1 (link up) | "se rompió algo en la descarga de la de la punta, sale agua, presión para todos lados…" | S1 | official run: 20–21 s · E2E: 3.0 s | false |
| S1 (link down) | same | S1 | 3.0 s | false |
| S2 | "Hay **olor agas** fuerte del lado del pontón…" (first run) / "olor a gas fuente" (second) | S2 | 2.5 s | false |
| S3 | "Sale **como** del motor de la del fondo, hay olor a quemado" | S3 | 2.5 s | false |
| S4 | "**Ni** compañero se golpeó la mano… está sangrando" | S4 | 2.5 s | false |

```
ALERTA-NOTA-00003 espera=False
texto: "CONDICION INSEGURA S4 en PLANTA. Aplique el procedimiento de emergencia:
        alerte por radio al supervisor de turno, asegure la zona y no se acerque.
        La alerta de seguridad ya quedo registrada."
events: AlertaSeguridad B-101 origen=parte · 0 false alerts in the official scenarios
```
The first S2 attempt **failed** (the ASR wrote "olor agas" and the note was published as
`SinNovedad`). That defect was fixed (see `docs/DELIVERY_1_AUDIT.md` D2) and every code was
re-tested individually afterwards.

The probe needs a clean bench: `scripts/e2e_probe.py --reiniciar` empties the assistant
tables and puts the plant in `martes-tranquilo` ×1 first. Without it the simulator reuses
`NOTA-00001`, the assistant correctly deduplicates by id and the tablet stays silent; the
probe now reports that instead of looking like a broken system.

**Status: PASS after the fix.**

---

## Scenario 7 — Offline operation and ordered resynchronisation

**Steps.** Link cut with the official simulator (`accion: enlace, estado: caido`), then a
normal note and an S1 safety note; finally the link was restored.

**Expected.** Local transcription, drafting, detection and alert keep working; the outbound
queue grows and becomes visible; on reconnection it drains in order with no duplicates.

**Actual.**
```
heartbeats during the cut: enlace_ok=False, pendientes 15 → 16 → 17
normal note:  draft with the correct row at 2.2 s, SinNovedad event, all with the link down
S1 note:      AlertaSeguridad + tablet emergency notice 3.0 s after the note, link down
restore:      pending 17 → 0 acked; cloud replica received ids 15, 16, 17 in order
duplicates:   0 (grouped by type+equipment+note)
```
`GET /api/state` reported `pending_sync` 0 after the drain; the app never depended on the
cloud to detect or to alert.

**Status: PASS.**

---

## Scenario 8 — Restart and persistence

**Steps.**
1. A note was left `processing` with a question on the tablet; the `cerebro` container was
   restarted mid-dialog.
2. A sustained vibration deviation was active; the container was restarted while it
   continued.

**Expected.** The note resumes with the same deterministic message ids and no duplicate
rows; the sensor episode keeps its event id and is not announced twice.

**Actual.**
```
before restart: notes NOTA-00001 status=processing · tablet TAB-…-processing, TAB-…-eq0
after  restart: same note resumed and re-processed · tablet_messages still 2 rows (same ids)
sensor before: 1 Escalado, sensor_state(event_id=3f0cfec5-…, active=t)
sensor after : still 1 Escalado, same event_id, active=t  (no duplicate)
```
Notes, parts, attempts, tablet messages, replies and events are all in PostgreSQL and
survive the restart.

**Status: PASS.**

---

## Scenario 9 — `VIVO-` notes

**Steps.**
1. A real recording (the audio of a previous operator note) uploaded through the official
   operator endpoint, producing `VIVO-20261109-065540-392`.
2. A 3-second silent recording, producing `VIVO-20261109-065644-214`.

**Expected.** No expected part exists for these notes; the system must not invent
measurements and must not ask unnecessary questions when there is nothing to report.

**Actual.**
```
(1) transcribed "La dos en 1.590 libras de descarga" → draft B-102 1590 psi → SinNovedad
(2) transcribed "" → "Nota recibida. No hay datos para el parte." · no rows · no event · no question
```
For (1) the draft was shown and the part stored; no value was invented. For (2) the part is
stored empty and the plant gets a clear notice.

**Status: PASS.**

---

## Summary

| # | Workflow | Result |
|---|---|---|
| 1 | Normal inspection | PASS |
| 2 | Ambiguous equipment | PASS |
| 3 | Units and ambiguous values | PASS |
| 4 | Correction by voice + photo | PASS |
| 5 | Spike vs sustained sensor deviation | PASS |
| 6 | Safety S1–S4 (incl. offline) | PASS after fixing S2 detection |
| 7 | Offline operation and resync | PASS |
| 8 | Restart and persistence | PASS |
| 9 | `VIVO-` notes | PASS |

**Issues found in this phase:** S2 missed when the ASR glued "a gas" into "agas" (fixed and
re-tested), duplicated acknowledgement on empty `VIVO-` notes (fixed), and the observation
that S3 can rely on "olor a quemado" when the ASR loses the word "humo" (documented as a
residual risk).
