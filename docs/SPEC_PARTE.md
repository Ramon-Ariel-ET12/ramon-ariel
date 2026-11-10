# Mini spec · flujo del parte de recorrida

Este documento es la especificación de trabajo del camino crítico: una nota de voz se
convierte en un parte confirmado, y recién entonces genera eventos. El contrato de
mensajes es `planta_contrato` (paquete instalado con pip); acá se describe el
comportamiento del sistema, no se duplican los modelos.

## 1. Entradas

| Entrada | Tópico | Validación |
|---|---|---|
| Nota de voz | `planta/recorridas` (`NotaRecorrida`) | `planta_contrato.NotaRecorrida`; se descarta duplicado por `id` |
| Audio | `http://sim:8100{audio_url}` | WAV 16 kHz mono; descarga directa en `planta-lan` |
| Fotos | `http://sim:8100{foto}` | descarga best-effort; se asocian por orden de aparición y se archivan en `/data/media/photos/<nota>/` |
| Respuesta del operador | `planta/respuestas` (`RespuestaOperador`) | texto libre + audio; se asocia por `mensaje_id` |
| Definición de planta | `GET /api/planta` | TAG, nombres informales, unidad del manómetro local, límites de alarma |
| Historial | `GET /api/historian/{tag}/{variable}` | 45 días, ventana de 6 h para tendencia; rango observado (mín–máx) de la ventana, con margen del 5 % |

## 2. Estados del parte

```
recibida → procesando → Borrador (tablet)
        → Confirmado | Confirmado con diferencias | Fallido
```

Los nombres de estado en PostgreSQL son `received`, `processing`, `confirmed`, `failed`;
`parts.status` guarda `confirmed` o `confirmed_with_differences`.

- **Borrador**: existe al menos una pantalla con filas mostrada al operador.
- **Confirmado**: el operador respondió una confirmación reconocible sobre el último
  borrador con filas numéricas.
- **Confirmado con diferencias**: se agotaron los intentos o el tiempo global sin
  confirmación; se conserva el último borrador, se registra el motivo y se emiten
  eventos para no dejar la planta ciega. Es un estado de degradación visible.
- Las notas con **filas sin valor** (solo observaciones) no tienen nada que corregir:
  se muestran y se confirman al recibir la respuesta; si no hay filas, no se manda
  pantalla y se emite un evento `SinNovedad` a nivel planta.
- Si la nota **traía audio y no se pudo descargar o transcribir**, no se publica
  `SinNovedad`: se avisa en la tablet, el parte queda `unreadable` y la nota `failed`.

## 3. Tablet

El sistema decide qué mostrar; la planta solo dibuja y hace sonar. Los ids son
deterministas por nota para que un reinicio no duplique el diálogo:

| Tipo | id | `pantalla` | `espera_respuesta` | Efecto |
|---|---|---|---|---|
| Nota recibida | `TAB-<nota>-processing` | sin filas | `false` | aviso inmediato; mantiene el reloj de la planta en modo lento durante el ASR |
| Borrador | `TAB-<nota>-<intento>` | filas del parte (con y sin valor) | `true` | el operador confirma o corrige |
| Pregunta de equipo | `TAB-<nota>-eq<n>` | `opciones` con TAG + nombre | `true` | se resuelve el TAG y se re-parsea la cláusula |
| Pregunta de valor | `TAB-<nota>-val<n>` | `opciones` (reparado y original) | `true` | el valor que contesta el operador **reemplaza** al reparado (p. ej. 18 → 1,8 salvo que diga "dieciocho") |
| Confirmación histórica | `TAB-<nota>-hist<n>` | `opciones` (Sí / No) | `true` | el valor nuevo reemplaza la lectura; un "no" sin valor la borra; sin respuesta queda marcada `historical_unconfirmed` |
| Aviso de seguridad | `ALERTA-<nota>` | fila `condicion_insegura` | `false` | procedimiento de emergencia + radio |
| Acuse | `TAB-<nota>-ok` | sin filas | `false` | parte guardado |

Reglas de interfaz derivadas de la corrección automática:

- Un borrador **siempre** lleva filas (incluidas las observaciones) y **nunca**
  `opciones`; así no se cuenta como pregunta de más.
- Solo se pregunta ante una ambigüedad real (equipo o valor) o un valor fuera del
  rango histórico.
- El acuse y el aviso de seguridad no esperan respuesta y no llevan filas con valor.

## 4. Extracción

1. **Transcripción** local con faster-whisper (español, VAD, prompt de dominio).
2. **Seguridad** primero, en código, antes de cualquier modelo: S1 agua a presión,
   S2 olor a gas, S3 humo/fuego, S4 persona lesionada, con ventana de negación. El
   texto se normaliza sin puntuación y los patrones aceptan las variantes que produce
   el ASR ("olor agas", "agua, presión", "olor quemado", "se rompió el niple",
   "huele a gas", "se lastimó"). El detector corre también sobre la transcripción
   parcial: el primer segmento que nombra un disparador publica la alerta y el aviso
   en la tablet sin esperar al audio completo.
3. **Parser determinista** por cláusulas:
   - equipo actual persistente entre cláusulas;
   - una fila por equipo y variable;
   - números hablados (`ciento doce`, `mil seiscientos veinte`, `uno con cuatro`,
     `cero nueve`, `uno y medio`);
   - unidades: `kilos`→kg/cm², manómetro local por equipo (kg/cm²/psi/bar), `grados`,
     `metros`, `gotas por minuto`; abreviaturas con punto del ASR ("1600 p.c.") no cortan
     la cláusula;
   - ambigüedad de equipo (`la bomba` sin número) y de valor (diferencial ≥ 10).
4. **Correcciones**: la unidad que dice el operador elige la variable (psi → descarga,
   grados → rodamiento, gotas → goteo), así la corrección alcanza la fila correcta
   aunque su valor haya llegado `null`. `Te faltó …` completa una fila existente sin
   duplicarla. Si la corrección no cambia el borrador (el operador leyó una pantalla
   vieja), el borrador se reenvía una vez para que pueda confirmar.
5. **LLM local opcional** solo para respuestas libres que el lector determinista no
   entiende; su salida se valida con un esquema Pydantic `extra="forbid"` y nunca
   decide reglas de negocio ni la alerta.

## 5. Correcciones

Se reconocen las cinco formas que usa el operador de la planta:

| Texto | Acción |
|---|---|
| `La uno estaba en ciento quince kilos, no en ciento doce.` | `set` valor/unidad del equipo |
| `Te faltó la dos, que estaba en ciento veinte gotas por minuto.` | `add` fila faltante |
| `Eso de ciento doce era de la uno, no de la dos.` | `move` fila entre equipos |
| `Lo del filtro B es en kilos, no en bar.` | `unit` cambia la unidad |
| `Lo del pulmón no lo dije.` | `remove` fila sobrante |

El `set` elige la fila por la unidad que dijo el operador (psi/bar/kilos → presión de
descarga, grados → rodamiento, gotas → goteo); si esa fila existe con valor `null`
(porque el ASR perdió la lectura) se completa, y si no existe se agrega. El `add`
completa una fila `(equipo, variable)` ya presente en lugar de duplicarla. Una
corrección que no cambia nada reenvía el borrador una vez para que el operador
confirme; dos correcciones sin efecto cortan el diálogo.

Una respuesta que llega después de `NOTE_TIMEOUT_S` se guarda en `replies` y en el
intento para auditoría, pero ya no modifica el parte: los eventos publicados tienen id
determinista y no se pueden reemplazar. Por eso el presupuesto cubre las preguntas y
un reenvío completo.

El operador compara por TAG y valor (con conversión de unidad); la variable no se
compara. Las filas sin valor no participan de la confirmación, pero sí se muestran.

## 6. Condiciones de corte y presupuesto

| Condición | Valor | Efecto |
|---|---|---|
| `NOTE_TIMEOUT_S` | 180 s reales por nota | presupuesto global; la transcripción y la descarga de fotos corren bajo `asyncio.wait_for`, así que una llamada colgada no bloquea al worker |
| `MAX_ATTEMPTS` | 6 borradores | se finaliza con estado `confirmed_with_differences` |
| `MAX_NOTE_STEPS` | 8 pasos de revisión | el bucle corta en `min(MAX_ATTEMPTS, MAX_NOTE_STEPS)`; ídem estado |
| `TOKEN_BUDGET` | 8 000 tokens de LLM por nota | al agotarse, el LLM se desactiva para esa nota (los tokens se acumulan de lo que devuelve cada llamada) |
| timeout de `PlantClient` | 10 s + 3 intentos | error tipado; la nota no bloquea el worker |
| timeout de espera de respuesta | 40 s en el borrador, 20 s en las preguntas (4 s mínimo) | se registra y se sigue |

El presupuesto es global: cubre la pregunta de equipo (hasta 40 s), la confirmación
histórica (hasta 20 s) y al menos un reenvío del borrador. Con 90 s el operador
contestaba después del corte y su corrección se descartaba.

Los dos presupuestos (`MAX_NOTE_STEPS` y `TOKEN_BUDGET`) se aplican en
`NoteWorkflow._review_loop` y están cubiertos por pruebas
(`tests/test_workflow_flow.py::test_step_budget_caps_the_review_loop` y
`::test_token_budget_disables_the_local_llm`).

## 7. Eventos y órdenes

- Un parte confirmado genera **un evento por equipo** (`SinNovedad` o `Escalado`) con
  id `uuid5(parte, equipo, tipo)`, `nota_ids` y `ts` de la nota.
- `Escalado` lleva contexto persistido: filas, fotos, tendencia de sensores.
- `AlertaSeguridad` es terminal y no genera orden.
- Los eventos de sensores se agregan por minuto simulado y requieren una ventana
  sostenida (5 min, ≥ 3 muestras, histéresis); un pico aislado no genera evento.
- Una orden se propone desde una tabla determinista evidencia → tarea. Se publica
  primero `Borrador` (con equipo y tareas) y después `Aprobada` o
  `PendienteAprobacion` con motivo. Las reglas se evalúan con el estado de bombas
  leído de `/api/estado` inmediatamente antes de decidir.
- El evento `Escalado` guarda su contexto: las filas del parte del equipo, las fotos
  archivadas, la tendencia de los últimos 6 h por sensor (`n, min, max, last`, con
  unidad), el historial de órdenes y los repuestos disponibles. La evidencia se arma en
  segundo plano, después de publicar el evento, para no frenar el bucle MQTT.
- El episodio de un sensor se persiste en `sensor_state` (`active`, `since`, `event_id`):
  un reinicio en medio de un desvío no vuelve a anunciarlo.

## 8. Sin enlace

Transcripción, seguridad, parser, detección y alertas son locales. Lo que necesita
salir se encola en `sync_queue` y se drena al replicador de nube a través del proxy
`enlace:3128`. `enlace_ok` se lee del puerto de control del enlace. La cola incluye
eventos, órdenes, partes y digests de sensores; `pendientes_sincronizar` es su
profundidad.

## 9. Idempotencia y reinicio

- `notes.id`, `events.id`, `orders.id`, `tablet_messages.id` son únicos.
- Al arrancar: se reanudan notas pendientes, se re-publican órdenes abiertas con el
  mismo id y estado (nunca `Borrador`) y se reintenta la conexión a Postgres.
- El corte de luz mata los contenedores etiquetados `academia.planta: pc`; los datos
  quedan en el volumen y la orden pendiente sobrevive.
