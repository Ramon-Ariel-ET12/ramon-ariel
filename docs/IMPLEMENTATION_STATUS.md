# Estado de implementación · Entrega 1

Este archivo es el resumen de estado. La matriz completa requisito por requisito, con el
método de verificación y la evidencia de cada fila, está en
[`DELIVERY_1_AUDIT.md`](DELIVERY_1_AUDIT.md). La prueba de punta a punta con el operador
virtual está en [`END_TO_END_TEST_REPORT.md`](END_TO_END_TEST_REPORT.md).

## Resultado

**91,3 / 100 · APRUEBA** en la corrida oficial del **2026-11-10 17:39** (commit `b9fa0ff`) y **88,8 ·
APRUEBA** en la verificación posterior sobre `5cdbbd9`, ambas sin eliminatorias; la primera queda archivada en la
carpeta de corridas del corrector (`academia2026-tp/correccion/corridas/academiaNovit2026/`),
sin faltas eliminatorias, en `martes-tranquilo` y `fuga-sin-enlace`, con el comando canónico
del corrector y sin variables de entorno. Corridas anteriores: 88,8 / 89,2 / 82,4 / 73,5. Detalle:
[`RESULTADOS.md`](RESULTADOS.md).

| Comprobación | Resultado |
|---|---|
| Requisitos auditados | 98 (matriz de la auditoría independiente) |
| Implementados y verificados | 84 |
| Parciales documentados | 12 |
| No verificable | 1 (B2a: la lista cerrada de modelos no está publicada) |
| Pruebas | 169 pruebas, 0 fallos con `TEST_DATABASE_URL` (168 + 1 de integración) |
| Lint | `ruff check .` limpio |
| Build sin variables | `docker compose build` instala `planta-contrato 0.2.0` |
| RAG | hit@5 0,873 · recall@5 0,718 · Rev. C antes que D: 0 |
| Verificación completa | `./scripts/verificar.sh` (7/7 pasos) |

## Correcciones de esta revisión

| Requisito | Cambio |
|---|---|
| B7 (correcciones) | El `set` elige la fila por la variable que implica la unidad y alcanza filas con valor `null`; el `add` completa una fila existente en vez de duplicarla; una corrección sin efecto reenvía el borrador en lugar de cortar el diálogo. Reproducido con `NOTA-00014` y `NOTA-00083`. |
| B6/B7 (presupuesto) | `NOTE_TIMEOUT_S` pasa a 180 s: cubre pregunta de equipo, confirmación histórica y un reenvío completo. Antes, a los 90 s la respuesta del operador llegaba después del corte y se descartaba. |
| E1d (timeout global) | La transcripción y la descarga de fotos corren bajo `asyncio.wait_for` con el tiempo restante de la nota; una llamada colgada no bloquea al worker. |
| C4 (seguridad) | Patrones S1–S4 ampliados (rotura de niple/brida/caño, “huele a gas”, “se lastimó”, “inconsciente”), negación `sin/ni` corregida y alerta publicada desde la transcripción parcial. |
| B4/A4a (parser) | La “y” espuria entre la lectura y la variable (`1600 p.c. y de descarga`) ya no corta la cláusula. |
| F2b (RAG) | El filtro de “otro modelo” ya no oculta la sección cuando la pregunta la nombra (PIA-1/PIA-2). |
| F2c (RAG) | Los códigos de fabricante se expanden a F01–F10 en la consulta léxica (MBP-4 §6). |
| F1 (metadatos) | Los 243 fragmentos de historial derivan equipo del título y fabricante de `/api/planta` (no del emisor de un manual ajeno): 681/701 con metadatos, 222 de historial con fabricante correcto. |
| F2a (RAG) | Un fragmento con `vigente=false` (108 de la Rev. C) no se devuelve en ninguno de los dos caminos: filtro en SQL y en el índice en memoria. |
| C3b/F6 (contexto) | El contexto del evento escalado persiste `sections` con la cita, y el panel la muestra ("fuentes: TX350-D §3.2"). |
| Tools (23) | `audited()` aplica timeout duro y un reintento a las ocho tools, con tests del camino lento y del reintento exitoso. |
| C3b/F6 (contexto) | `build_event_context` recibe el buscador: el evento escalado guarda las secciones citadas. |
| D2 (tools) | Contratos `strict=True`: se rechazan cadenas donde se espera un número. |
| B8 (VIVO) | Pruebas de nota VIVO vacía (sin evento) y con una lectura real. |

## Parciales (documentados, no ocultos)

| Requisito | Por qué queda parcial |
|---|---|
| B6c | El valor fuera de rango pide confirmación, pero la confirmación se pide solo si está fuera de la banda de la hoja de datos **y** del rango observado de 45 días; preguntar todo valor nuevo resta en A4b. |
| B7e | Si el operador no contesta, el parte se guarda como `confirmed_with_differences` y **sí** genera eventos, para no dejar la planta ciega; el estado queda separado en `parts.status`. |
| A2/A3 | La nota varía con la voz del simulador y el operador virtual no confirma borradores sin valores. |
| B2a | La lista cerrada de modelos no está publicada en el material de la cátedra: no se puede verificar la conformidad. |
| F2b | El filtro por fabricante de documentos es una señal de ranking (×1,15/×0,8), no un filtro duro. |
| A2b | `panel` (ingreso desde el host) está en `planta-lan` + `control` porque Docker no publica puertos de una red `internal`; `cerebro` y `db` cumplen y todos los servicios de planta llevan `academia.planta: pc`. |

## Limitaciones conocidas

- La detección de seguridad depende de la transcripción. El detector tolera las variantes
  reales del ASR y corre sobre texto parcial, pero una palabra completamente perdida puede
  requerir ampliar patrones.
- La primera nota de una corrida tarda más: el índice RAG se construye al arrancar y compite
  por las mismas 3 CPU que el ASR. En la corrida medida la alerta S1 salió a los 20,4 s
  (límite 30 s).
- La central de aprobación/certificación (G2/G3) y las decisiones del planificador no
  tienen canal en el contrato: corresponden a la Entrega 2.
- `mypy` está configurado pero no se usa como puerta de calidad; la puerta del proyecto es
  `ruff`, que pasa.
- D1/D2/F3/G1 no se pueden medir con los dos escenarios obligatorios; requieren
  `sin-luz`, `contratista` o `tormenta-perfecta`.
- El puntuador oficial tiene un defecto reproducible: una orden `PendienteAprobacion` con
  `motivo` hace `bien += ok` con un string y aborta la corrección con `TypeError`. Con los
  dos escenarios obligatorios este sistema no publica órdenes, así que no se dispara.
