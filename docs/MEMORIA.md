# Política de memoria y persistencia

## Qué se guarda

| Tabla | Contenido | Para qué |
|---|---|---|
| `notes` | id, `ts` de la nota (no el reloj de la máquina), operador, recorrida, audio, fotos, flag `live`, estado, transcripción | trazabilidad del parte y reanudación |
| `transcripts` (en `notes`) | texto completo del ASR | auditoría de la interpretación |
| `parts` | estado del parte, filas con TAG/variable/valor/unidad/observación/foto | parte confirmado y evidencia |
| `attempts` | cada borrador/pregunta, sus filas y la respuesta recibida | reconstruir el diálogo y medir correcciones |
| `tablet_messages` | mensajes enviados con su pantalla exacta | idempotencia y auditoría de la interfaz |
| `replies` | respuestas del operador por `mensaje_id` (también las que llegan tarde) | idempotencia y auditoría de la conversación |
| `events` | evento, tipo, equipo, origen, `nota_ids`, resumen y contexto | detección y evidencia |
| `orders` | orden, equipo, tareas, estado y payload publicado | reglas, deduplicación y reinicio |
| `decisions` | decisión, reglas incumplidas y estado de planta al decidir | auditoría de aprobaciones |
| `sensor_state` | ventana sostenida por sensor | histéresis y no duplicar eventos |
| `sync_queue` | elementos pendientes de la réplica en nube | operación sin enlace |
| `usage_log` | modelo, tarea, tokens, latencia y costo de cada paso (ASR, parser, LLM opcional) | observabilidad e INFORME |
| `rag_chunks` | fragmentos, metadatos, cita, vigencia y embedding | recuperación documental |

No se guardan credenciales ni secretos. Los logs no incluyen tokens, contraseñas ni
payloads completos de configuración.

## Cuánto se guarda

- **Operación y evidencia** (`notes`, `parts`, `attempts`, `tablet_messages`, `replies`,
  `events`, `orders`, `decisions`): 12 meses. Es el registro auditable de la operación.
- **Audio y fotos** en `/data/media`: 90 días; luego se conservan solo los metadatos y
  las rutas. El borrado físico se hace con el job de retención.
- **Transcripciones**: 90 días; el parte confirmado y sus filas quedan 12 meses.
- **`usage_log`**: 12 meses (costo y latencia).
- **`sync_queue` ackeados**: 30 días; los pendientes se conservan hasta ser entregados.
- **`rag_chunks`**: vigentes mientras el documento lo esté; las revisiones vencidas se
  conservan con `current = false` para poder explicar la trampa de versiones.
- **`sensor_state`**: solo el estado actual; el historial de sensores vive en la planta.

## Borrado y minimización

- El operador se guarda por nombre porque el parte lo exige; no se guardan datos
  personales adicionales.
- Las fotos se archivan por nota y se pueden borrar por nota sin romper el parte.
- `scripts/limpiar.py` (job de retención) borra archivos y filas fuera de ventana.
  Se ejecuta a mano en la PC de planta; no está en el camino crítico.
- La réplica en nube recibe solo eventos, órdenes y digests de sensores; nunca audio,
  fotos ni la transcripción completa.

## Por qué esta política

La planta necesita explicar cada decisión (quién informó, qué se interpretó, qué se
mostró, qué contestó el operador y qué regla se aplicó) durante al menos un ciclo anual
de mantenimiento. Al mismo tiempo, el audio y las fotos son los datos más pesados y
sensibles: se retienen solo lo necesario para auditoría reciente. La verdad de campo
(`/api/verdad`) no se persiste: en modo corrección está cerrada y el sistema no puede
depender de ella.

## Qué se consulta por RAG y qué por API o SQL

La regla es simple: **el RAG explica, la API y el SQL deciden**.

| Consulta | Canal | Motivo |
|---|---|---|
| Límites de operación (alarma alta/baja, disparo) | `GET /api/planta` → `snapshot.limits` | Son números exactos que definen una alarma; el manual Rev. C tiene otros límites y está vencido. Un fragmento recuperado por similitud no es una fuente válida para decidir un desvío. |
| Stock, costo y lista de materiales | datos estructurados (`Materiales`, `/api/inventario`) | El stock cambia y se consulta por código; el RAG devolvería texto narrativo desactualizado. |
| Historial de sensores y de órdenes | `GET /api/historian/...`, `/api/ordenes` | Series temporales: se agregan por ventana, no se buscan por similitud. |
| Catálogo de tareas, precios, aprobación | datos estructurados del contrato | La decisión debe ser determinista y auditable. |
| "¿Qué dice el manual sobre…?", "¿qué significa este código de falla?", "¿qué tareas recomienda el fabricante para esta bomba?" | RAG (pgvector + BM25) con cita de sección | El conocimiento está en prosa, disperso y con trampas (manuales de otros modelos, revisión vencida). |

Por eso el contexto del evento escalado guarda `sections` con la cita de cada fragmento
usado, y el límite que disparó el evento se lee del snapshot, no del texto. Si la búsqueda
no encuentra respaldo, la conclusión se emite sin cita y así se ve; nunca se inventa una
sección.
