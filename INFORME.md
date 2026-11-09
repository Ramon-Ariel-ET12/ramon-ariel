# INFORME técnico · modelos y costos

## 1. Decisión de arquitectura de modelos

La primera entrega exige que el parte por voz, la detección y la alerta de condición
insegura funcionen **sin enlace y sin GPU**, en una PC de planta de 4 núcleos y 8 GB.
Por eso:

- La transcripción y la extracción corren **en la planta**.
- La detección de seguridad y las reglas de aprobación son **código determinista**, no
  un modelo: una alerta falsa cuesta más que una detección perdida y el resultado debe
  ser idéntico con los mismos datos.
- El único modelo de lenguaje es **opcional** y secundario: interpreta respuestas
  libres que el lector determinista no entiende. Nunca decide una regla ni una alerta.

> **Nota de alcance.** El enunciado menciona una "lista cerrada" de modelos, pero esa
> lista no fue provista en el repositorio, en los anexos ni en el sitio público. Se
> eligen modelos locales de uso libre que entran en el hardware exigido, y todos los
> identificadores son configurables por variable de entorno para poder sustituirlos si
> la cátedra publica la lista.

## 2. Modelos usados

### 2.1 Transcripción (local, CPU)

| Campo | Valor |
|---|---|
| Nombre | `Systran/faster-whisper-small` |
| Arquitectura | Whisper small (encoder-decoder Transformer) |
| Proveedor | Systran / comunidad OpenAI Whisper; runtime CTranslate2 |
| Versión del runtime | `faster-whisper 1.2.1`, `ctranslate2 4.8.5` |
| Parámetros | 244 M |
| Licencia | MIT |
| Página | <https://huggingface.co/Systran/faster-whisper-small> |
| Ejecución | contenedor `cerebro`, CPU, `compute_type=int8`, 4 hilos, VAD, `beam_size=5`, `language=es` |
| Memoria aproximada | 0,8–1,2 GB |
| Descarga | horneada en build; `local_files_only=True` en runtime |

Entrada: WAV 16 kHz mono servido por `sim:8100`. Prompt de dominio con TAGs, variables
y unidades para mejorar números y nombres de equipo. La latencia se mide en
`scripts/benchmark_asr.py`; el resultado está en la sección 3.

### 2.2 Embeddings del RAG (local, CPU)

| Campo | Valor |
|---|---|
| Nombre | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| Proveedor | Sentence-Transformers / UKPLab |
| Versión del runtime | `fastembed 0.9.1` (ONNX Runtime, sin PyTorch) |
| Parámetros | 118 M |
| Dimensión | 384 |
| Licencia | Apache-2.0 |
| Página | <https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2> |
| Ejecución | CPU, ONNX, 701 fragmentos indexados en pgvector (HNSW) |
| Memoria aproximada | 0,2–0,4 GB |

Se combina con BM25 en español y re-ranking por metadata (vigencia, fabricante,
equipo, modelo). La evaluación está en la sección 4.

### 2.3 Modelo de lenguaje local opcional

| Campo | Valor |
|---|---|
| Nombre | `Qwen/Qwen2.5-0.5B-Instruct` |
| Proveedor | Alibaba Qwen |
| Versión | Qwen2.5, 0,49 B parámetros |
| Licencia | Apache-2.0 |
| Página | <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct> |
| Runtime | `transformers 5.22.2` + `torch 2.15.0+cpu`, `langchain-huggingface`, CPU |
| Uso | interpretar respuestas libres del operador cuando el lector determinista no encuentra una acción; salida JSON validada con Pydantic `extra="forbid"` |
| Activación | `LLM_ENABLED=true` y build con `--build-arg DOWNLOAD_LLM=1`; por defecto `false` y no horneado en el camino evaluado |
| Memoria aproximada | 1,5–2,5 GB en float32 |

No se usa para: detectar seguridad, decidir la tarea, aprobar órdenes, calcular
límites ni interpretar valores del parte. Esas decisiones son código.

### 2.4 Modelos en la nube

Esta entrega **no usa modelos en la nube**. La réplica `nube-sync` es un servicio de
archivo, no un modelo. Los modelos de visión de NVIDIA previstos por el enunciado
corresponden al análisis de fotos de la Entrega 2.

## 3. Consumo y latencia del ASR

Se ejecuta:

```bash
uv run python scripts/benchmark_asr.py --dir academia2026-tp/datos/voces \
  --model var/models/faster-whisper-small
```

| Métrica | Resultado |
|---|---|
| Notas medidas | 102 (todas las voces del banco provisto) |
| WER medio (palabras) | 0,251 (incluye dígitos vs. palabras: "112" contra "ciento doce") |
| Aciertos de extracción sobre las 8 notas de `martes-tranquilo` | 8/8 exactas (TAG, valor y unidad) |
| Latencia media / máxima | 1,86 s / 6,48 s por nota |
| Hardware | Desktop, CPU sin GPU, 12 hilos disponibles; contenedor limitado a 3 CPU |
| RAM del proceso | ~1 GB |

## 4. Consumo y latencia del RAG

```bash
uv run python evaluacion/retrieval_eval.py
```

| Métrica | BM25 base (curso) | Este sistema |
|---|---|---|
| hit@5 | 0,85 | **0,873** |
| recall@5 | 0,66 | **0,718** |
| MRR | — | **0,678** |
| Distractor@5 (Rev. C antes que D) | ~6 de 71 | **0** |
| Preguntas | 71 | 71 |

La línea de base medida en este repo es hit@5 0,859 / recall@5 0,674 / MRR 0,581, consistente
con la referencia del curso. La combinación BM25 + vector (peso 0,1) + re-ranking por metadata
mejora la recuperación y elimina las trampas de versión: ninguna sección de la Rev. C queda
antes que la vigente en el top 5.

Costo: USD 0 (modelo local, sin API).

## 5. Tokens y costo del LLM local

El camino evaluado no consume tokens de un LLM: la extracción es determinista. El
modelo opcional se mide con:

```bash
uv run python scripts/benchmark_llm.py \
  --model var/models/qwen2.5-0.5b-instruct
```

| Tarea | Tokens de entrada | Tokens de salida | Latencia | Costo |
|---|---|---|---|---|
| Interpretar una respuesta libre | no ejecutado en la entrega | — | — | USD 0 (local) |

El modelo no se hornea por defecto (`DOWNLOAD_LLM=0`) para no sumar ~1 GB al build de
una ruta que no lo necesita. La ruta determinista cubre todas las respuestas del
operador de la simulación; el LLM queda como mejora opcional y su medición se hace con
el comando anterior.

En la nube el costo sería 0 porque no se usan modelos pagos en esta entrega. El sistema
registra igualmente tokens, latencia y costo por llamada en `usage_log`, y los muestra
en la central (`/`).

## 6. Conclusión

La corrida oficial de la primera entrega obtuvo **91,3 / 100 (APRUEBA)** en
`martes-tranquilo` y `fuga-sin-enlace`, sin faltas eliminatorias, con alerta de
seguridad, operación sin enlace y latido al 100 %. El detalle está en
[`docs/RESULTADOS.md`](docs/RESULTADOS.md).

La combinación elegida prioriza lo que la primera entrega mide: **disponibilidad local**
y **determinismo**. `faster-whisper small` en int8 entra en la PC de planta y da texto
suficiente para un vocabulario de campo acotado; el parser determinista convierte ese
texto en filas verificables sin depender de la latencia ni de la variabilidad de un
LLM. El modelo de lenguaje queda como una ayuda acotada y auditable para el lenguaje
libre, no como el núcleo de las decisiones. El RAG usa un embedding multilingüe pequeño
(384 dimensiones) que cabe en el presupuesto y permite comparar contra la línea de base
BM25 con las mismas citas y metadatos.

Si la cátedra publica la lista cerrada de modelos, el reemplazo es directo:
`ASR_MODEL`, `EMBEDDING_MODEL` y `LLM_MODEL` son variables de entorno y el contrato de
mensajes no cambia.
