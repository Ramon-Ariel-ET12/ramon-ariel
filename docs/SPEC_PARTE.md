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
| Historial | `GET /api/historian/{tag}/{variable}` | 45 días, ventana de 6 h para tendencia; rango p1–p99 para validación |

## 2. Estados del parte

```
recibida → transcribiendo → interpretando → Borrador (tablet)
        → Confirmado | Confirmado con diferencias | Fallido
```

- **Borrador**: existe al menos una pantalla con filas mostrada al operador.
- **Confirmado**: el operador respondió una confirmación reconocible sobre el último
  borrador con filas numéricas.
- **Confirmado con diferencias**: se agotaron los intentos o el tiempo global sin
  confirmación; se conserva el último borrador, se registra el motivo y se emiten
  eventos para no dejar la planta ciega. Es un estado de degradación visible.
- Las notas con **filas sin valor** (solo observaciones) no tienen nada que corregir:
  se muestran y se confirman al recibir la respuesta; si no hay filas, no se manda
  pantalla y se emite un evento `SinNovedad` a nivel planta.

## 3. Tablet

El sistema decide qué mostrar; la planta solo dibuja y hace sonar. Los ids son
deterministas por nota para que un reinicio no duplique el diálogo:

| Tipo | id | `pantalla` | `espera_respuesta` | Efecto |
|---|---|---|---|---|
| Borrador | `TAB-<nota>-<intento>` | filas del parte (con y sin valor) | `true` | el operador confirma o corrige |
| Pregunta de equipo | `TAB-<nota>-eq<n>` | `opciones` con TAG + nombre | `true` | se resuelve el TAG y se re-parsea la cláusula |
| Pregunta de valor | `TAB-<nota>-val<n>` | sin filas | `true` | se conserva el valor reparado (p. ej. 18 → 1,8) |
| Confirmación histórica | `TAB-<nota>-hist<n>` | sin filas | `true` | valor fuera de rango p1–p99 |
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
   S2 olor a gas, S3 humo/fuego, S4 persona lesionada, con ventana de negación.
3. **Parser determinista** por cláusulas:
   - equipo actual persistente entre cláusulas;
   - una fila por equipo y variable;
   - números hablados (`ciento doce`, `mil seiscientos veinte`, `uno con cuatro`,
     `cero nueve`, `uno y medio`);
   - unidades: `kilos`→kg/cm², manómetro local por equipo (kg/cm²/psi/bar), `grados`,
     `metros`, `gotas por minuto`;
   - ambigüedad de equipo (`la bomba` sin número) y de valor (diferencial ≥ 10).
4. **LLM local opcional** solo para respuestas libres que el lector determinista no
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

El operador compara por TAG y valor (con conversión de unidad); la variable no se
compara. Las filas sin valor no participan de la confirmación, pero sí se muestran.

## 6. Condiciones de corte y presupuesto

| Condición | Valor | Efecto |
|---|---|---|
| `NOTE_TIMEOUT_S` | 90 s reales por nota | se deja de esperar y se finaliza con el último borrador |
| `MAX_ATTEMPTS` | 6 borradores | se finaliza con estado `confirmed_with_differences` |
| `MAX_NOTE_STEPS` | 8 pasos de revisión | ídem |
| `TOKEN_BUDGET` | 8 000 tokens de LLM por nota | el LLM se desactiva para esa nota |
| timeout de `PlantClient` | 10 s + 3 intentos | error tipado; la nota no bloquea el worker |
| timeout de espera de respuesta | 25 s (4 s mínimo) | se registra y se sigue |

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
