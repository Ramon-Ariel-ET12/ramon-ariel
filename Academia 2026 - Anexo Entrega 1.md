# Academia Novit 2026 — Anexo de TP

## Anexo de entregas

TP Planta de inyección: contenido de cada entrega.


Anexo Entregas

TP Planta de inyección: contenido de cada
entrega.

Desarrollo de Agentes IA y Software Agéntico · Noviembre 2026   novitsoftware.com
## 01 Cronograma
                                 MÓDULOS YA                                            ESCENARIOS QUE TIENE
ENTREGA         FECHA                             FOCO
                                 DADOS                                                 QUE PASAR

                                                  Sistema conectado, parte por voz,    martes-tranquilo,
1               10/11            1.1 a 2.4
                                                  detección, tools y MCP, RAG medido   fuga-sin-enlace
## 03 Entrega 1
Sistema conectado, parte por voz y detección.

Repo y ejecución
    •​ Repo público en GitHub llamado nombre-apellido. En la raíz: README.md, docker-compose.yml y
      tests/.
    •​ docker compose up levanta el sistema al lado de la planta. Los servicios de planta:
        –​ van solo en planta-lan (red external) y llevan el label academia.planta: pc;
        –​ suman entre todos un límite de 4 CPU y 8 GB;
        –​ salen a internet por HTTP(S)_PROXY=http://enlace:3128, con NO_PROXY=broker,sim,localhost.
    •​ Usa planta_contrato instalado con pip, no una copia de los modelos.
    •​ Manda el latido sistema/estado cada 30 s con sistema, enlace_ok y pendientes_sincronizar.
    •​ PostgreSQL 16 con pgvector dentro del compose.
### A. Parte por voz (completo)
    •​ Escucha planta/recorridas y baja el audio y las fotos de http://sim:8100{audio_url}.
    •​ Transcribe con un modelo local de la lista cerrada. Tiene que ser local desde ahora: en
      fuga-sin-enlace el enlace se cae a los 10 minutos.
    •​ Extrae con structured output validado a FilaParte:
        –​ una fila por equipo y variable, aunque la nota los mezcle;
        –​ hora igual al ts de la nota, no el reloj de la máquina;
        –​ fotos asociadas a la fila que corresponde.
    •​ Nombres informales: los resuelve contra GET /api/planta ("la dos", "el de la izquierda", "la de
      reserva"). Si queda ambiguo ("la bomba" a secas), pregunta.
    •​ Unidades:
        –​ "kilos" son kg/cm²;
        –​ los manómetros locales van en kg/cm² en la B-101, psi en la B-102 y bar en la B-103;
        –​ un diferencial dicho "dieciocho" en lugar de "uno ocho" se pregunta.
    •​ Rango histórico: lo saca de GET /api/historian/{tag}/{variable} (45 días). Un valor fuera de rango
      pide confirmación antes de guardarse.

 •​ Tablet:
      –​ manda el borrador en MensajeTablet.pantalla.filas, con opciones cuando hay que elegir;
      –​ entiende planta/respuestas escrito como se habla en campo ("No, la uno estaba en ciento quince
        kilos") y vuelve a mandar el borrador corregido;
      –​ el parte pasa de Borrador a Confirmado.
 •​ Notas VIVO-… (grabadas en clase): no tienen parte esperado y pueden no traer nada para
   reportar.
### B. Detección en planta (en código, sin LLM)
 •​ Cada parte confirmado y cada desvío de planta/sensores/# genera un EventoSistema: id
   idempotente, origen parte o sensor, nota_ids.
 •​ Límites: los de planta.yaml o /api/planta, no los del manual Rev. C. Con los mismos datos, la
   decisión da siempre lo mismo.
 •​ Sin novedad o Escalado. El escalado lleva su contexto: parte, fotos y tendencia de las últimas
   horas.
      –​ Se escala una anomalía sostenida, no un pico aislado.
      –​ "parada, en reserva" no es una anomalía.
 •​ Alerta de seguridad (S1 a S4: agua a presión, olor a gas, humo o fuego, persona lesionada):
      –​ la detecta un detector local, sin nube;
      –​ avisa en la tablet que se aplique el procedimiento de emergencia, con el aviso por radio al
        supervisor (espera_respuesta: false);
      –​ publica AlertaSeguridad en menos de 30 s reales;
      –​ sin falsas alarmas: cada una resta.

Tools y MCP (1.3)
 •​ Tools de solo lectura con Pydantic estricto (extra="forbid"):
      –​ equipos;
      –​ historial de sensores;
      –​ historial de órdenes;
      –​ inventario, stock y lista de materiales;
      –​ catálogo de tareas;
      –​ búsqueda en manuales.
 •​ Al menos una expuesta por un servidor MCP.
 •​ Manejo de errores, timeouts y reintentos en cada tool.
 •​ Tests automatizados de cada tool en tests/.

Control y evaluación (1.4)
 •​ Condiciones de corte, presupuesto de pasos y tokens, y timeout global por nota.

 •​ Una mini spec del flujo del parte en el repo (Spec-Driven Development).
 •​ Primera evaluación contra /api/verdad: aciertos por campo, y si preguntó solo en las notas que
   tenían ambigüedad.

RAG, contexto y memoria (2.1 a 2.4)
 •​ Indexa datos/documentos en pgvector con metadatos de equipo, fabricante, documento, sección,
   cita y vigente.
 •​ Trampas del corpus que tiene que manejar:
      –​ la Rev. C de la bomba está vencida y tiene otros límites;
      –​ hay secciones de TX-250, TX-500, FC-24, FC-96 y de PIA-1 y PIA-2 que no aplican;
      –​ los códigos de falla del fabricante se traducen a F01 a F10 con MBP-4 §6.
 •​ Mide recall@k con evaluacion/retrieval.json (71 preguntas) usando
   corpus.evaluar.evaluar(buscar, suite). Lo compara con la línea de base BM25 (hit@5 0,85 y
   recall@5 0,66) y reporta cuántas veces aparece la Rev. C antes que la D.
 •​ Cada conclusión cita la sección del manual de la que sale (TX350-D §3.2).
 •​ Justifica qué se consulta por RAG y qué por API o SQL: límites y stock no salen del RAG.
 •​ Context builder diseñado, aunque el análisis completo recién entra en la Entrega 2.
 •​ Memoria:
      –​ el estado de la conversación de cada nota (mensaje de tablet, nota, borrador e intento) persistido
        en Postgres;
      –​ una política escrita de qué se recuerda y por cuánto tiempo.

Cómo se verifica
 •​ corregir.py --escenarios martes-tranquilo fuga-sin-enlace mide los criterios A1 a A4b, B1, B2, F1
   y F2.
 •​ Eliminatorias que aplican: sin_alerta_de_seguridad y sistema_mudo.

       ACADEMIA NOVIT 2026

       Enseñamos lo que sabemos.

       Desarrollo de Agentes IA y Software Agéntico. Formación anual,
       gratuita, abierta y 100% online.
