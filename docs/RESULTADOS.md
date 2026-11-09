# Resultados de la evaluación oficial

Corrida ejecutada con la planta en modo corrección y el sistema levantado desde el
`docker-compose.yml` del repo:

```bash
PLANTA_CONTRATO_DIR="$PWD/academia2026-tp/contrato" \
.venv/bin/python academia2026-tp/correccion/corregir.py \
  --repo . --alumno "Ramón Ariel" \
  --escenarios martes-tranquilo fuga-sin-enlace \
  --sin-construir --salida "$PWD/var/corrida6"
```

`--sin-construir` reutiliza la imagen ya construida con los modelos horneados (el
`Dockerfile` del repo es el que la construye). La corrida completa queda en
`var/corrida6/` (`informe.md`, `resultado.json`, un JSON por escenario y los logs).

## Nota

**91,3 / 100 · APRUEBA** (mínimo 60). **Sin faltas eliminatorias.**

Se midieron 63 de 93 puntos: los escenarios `martes-tranquilo` y `fuga-sin-enlace` no
tienen fallas de equipo ni cierres, por lo que D1, D2, F3 y G1 no aplican y la nota se
reescala. `sin_alerta_de_seguridad` y `sistema_mudo` no se dispararon.

| Criterio | Peso | Valor | Puntos |
|---|---:|---:|---:|
| A1 Cobertura | 5 | 100 % | 5,00 |
| A2 Borrador al primer intento | 10 | 69 % | 6,94 |
| A3 Parte final correcto | 8 | 69 % | 5,56 |
| A4a Pregunta cuando hace falta | 4 | 100 % | 4,00 |
| A4b No pregunta de más | 3 | 100 % | 3,00 |
| B1 Sin novedad / Escalado | 10 | 100 % | 10,00 |
| B2 Alerta de seguridad | 10 | 100 % | 10,00 |
| E1 Sigue andando sin enlace | 3 | 100 % | 3,00 |
| E2 Pendientes visibles | 3 | 100 % | 3,00 |
| E3 Sin duplicados | 4 | 100 % | 4,00 |
| F1 Mensajes válidos | 2 | 100 % | 2,00 |
| F2 Latido | 1 | 100 % | 1,00 |

## Lectura de los resultados

### Parte por voz (A)

- **A1 100 %**: todas las notas del operador tuvieron una pantalla de tablet. Incluye
  las notas que solo traen observaciones: se muestra un borrador informativo con filas
  sin valor y la pregunta de equipo cuando el operador dijo "la bomba".
- **A2/A3 69 %**: en `martes-tranquilo` se confirmaron 8 de 9 notas y en
  `fuga-sin-enlace` 2 de 4. Las tres notas no confirmables son:
  - `NOTA-00008` y `NOTA-00006`: solo dicen "está parada, en reserva"; no tienen ninguna
    fila con valor. El operador virtual solo emite `confirmo` cuando compara filas con
    valor; no hay nada que comparar.
  - `NOTA-00001`: es la condición insegura S1; su único ítem tiene `valor = null`.
  El sistema muestra el borrador y registra el parte; el límite es del mecanismo de
  confirmación del simulador, no del flujo. El resto de las notas se confirmó, incluidas
  las que necesitaron corrección de valores ocultos (goteo) o de unidades.
- **A4a/A4b 100 %**: se preguntó en las notas ambiguas y no se preguntó de más en las
  claras. El ajuste clave fue distinguir una ambigüedad explícita ("la bomba") de una
  cláusula donde el ASR perdió el nombre del equipo.

### Detección (B)

- **B1 100 %**: una decisión por equipo y nota, `SinNovedad` en todos los casos de estos
  escenarios; el pico aislado y "parada, en reserva" no escalaron.
- **B2 100 %**: la alerta S1 salió en menos de 30 s reales, con aviso en la tablet y
  `espera_respuesta: false`. La corrida no registró falsas alarmas.

### Sin enlace (E)

- **E1 100 %**: las notas durante el corte tuvieron respuesta en la tablet dentro de la
  ventana del corte. El aviso "Nota recibida. Procesando..." se publica al recibir la
  nota y mantiene el reloj de la planta en modo lento mientras corre el ASR local.
- **E2 100 %**: durante el corte el latido informó `enlace_ok=false` con pendientes > 0
  y volvió a cero con el enlace restablecido.
- **E3 100 %**: sin eventos ni órdenes duplicadas.

### Robustez (F)

- **F1 100 %**: 76 mensajes publicados en `martes-tranquilo` y 23 en `fuga-sin-enlace`,
  todos válidos contra `planta_contrato`.
- **F2 100 %**: latido regular cada 30 s, sin huecos.

### Lo que estos escenarios no ejercitan

`martes-tranquilo` y `fuga-sin-enlace` no tienen fallas de equipo, cortes de luz ni
cierres. Por eso D1, D2, F3 y G1 quedan "sin datos" en la corrida. Están implementados y
cubiertos por pruebas unitarias (`tests/test_rules_orders.py`, `tests/test_sync_history.py`,
`tests/test_events_sensors.py`); una corrida con `tormenta-perfecta`, `sin-luz` o
`contratista` los ejercita de punta a punta.

## Evaluaciones complementarias

- **ASR local**: 102 notas del banco, WER 0,251 (incluye dígitos vs. palabras), latencia
  media 1,86 s y máxima 6,48 s; extracción exacta de las 8 notas de `martes-tranquilo`
  (incluidas las variantes con dígitos "09", "1,3" y el verbo "medió").
- **RAG**: hit@5 0,873 / recall@5 0,718 / MRR 0,678 contra BM25 0,859 / 0,674 / 0,581;
  distractor@5 (Rev. C antes que D) 0 contra 6 de 71. Informe:
  `evaluacion/informe_retrieval.json`.
- **Pruebas**: 109 passed, 1 skipped (`uv run pytest -q`). El skip es la prueba de
  integración de Postgres, que requiere `TEST_DATABASE_URL`.
