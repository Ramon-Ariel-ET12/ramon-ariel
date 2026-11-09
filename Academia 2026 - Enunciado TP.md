# Academia Novit 2026 — Enunciado de TP

## Planta de inyección de agua

Parte de recorrida por voz, detección en planta y órdenes de trabajo.


Planta de inyección de agua

Parte de recorrida por voz, detección en
planta y órdenes de trabajo.

Desarrollo de Agentes IA y Software Agéntico · Octubre 2026   novitsoftware.com
## 01 Contexto
Recuperación secundaria en un yacimiento maduro
Una operadora petrolera (empresa hipotética) produce en un yacimiento maduro de la Cuenca del
Golfo San Jorge. El yacimiento produce con recuperación secundaria: el agua que sale de los pozos
junto con el petróleo se separa, se trata y se vuelve a inyectar al reservorio por pozos inyectores para
sostener la presión.

La inyección se hace desde una planta con tres bombas alternativas de alta presión, dos en servicio y
una en reserva, filtros de cartucho y un tanque pulmón. Si una bomba sale de servicio y la de reserva
no está disponible, la planta inyecta menos agua de la programada.

Un operador de planta hace la recorrida dos veces por turno. Lee los instrumentos que no están
conectados al sistema de control, como manómetros locales, niveles y temperaturas tomadas con
termómetro infrarrojo. También escucha ruidos, busca pérdidas y revisa acoples, correas y
empaquetaduras. Hoy anota en una planilla de papel y la carga en el sistema al terminar el turno: el
parte llega tarde, con errores de tipeo y sin fotos. Cuando algo anda mal, el aviso a mantenimiento
dice poco más que “la bomba 2 pierde”.

    ASÍ SUENA UNA NOTA DE VOZ

    “La dos está en ciento doce de descarga, ah, y el filtro B me dio uno ocho de diferencial. La tres
    sigue goteando por la empaquetadura, le saqué foto.”

Las bombas y los filtros tienen además sensores conectados al sistema de control de la planta:
presiones de succión y descarga, temperatura del aceite del cárter, vibración y presión diferencial de
filtros. Esas mediciones quedan registradas con su hora.

La planta está lejos de la base y el enlace de datos es intermitente: se corta varias veces por semana y
puede quedar caído durante horas. Dentro de la planta hay red local y una PC en la sala de control, sin
GPU, con 4 núcleos y 8 GB de memoria disponibles para este sistema.

Parte del mantenimiento lo hace una contratista. Cobra cuando un inspector de la operadora certifica
el trabajo y le emite la habilita, el documento con el que factura.

    QUÉ NECESITA LA OPERADORA

    Parte por voz. Que el operador de planta dicte el parte mientras recorre y que el formulario
    se complete solo, con su confirmación antes de guardarse.

    Detección en planta. Que las anomalías se detecten en la planta aunque el enlace esté
    caído, y que una condición insegura se señale en el momento.

    Órdenes con evidencia. Que ante una anomalía el planificador de mantenimiento reciba un
    borrador de orden de trabajo con la evidencia, las causas probables según el manual del
    fabricante y los repuestos disponibles.

    Certificación con evidencia. Que cada trabajo se cierre con lo que se hizo y lo que se usó, y
    que el trabajo de una contratista se certifique contra la orden y el contrato.
## 02 Requerimientos Funcionales
### A. Parte de recorrida por voz
 •​ Notas de voz. El operador graba notas durante la recorrida. Una nota puede mezclar varios
   equipos y datos en cualquier orden, como la del ejemplo del contexto.
 •​ Esquema fijo. Cada nota se convierte en un parte con equipo (TAG), variable, valor, unidad, hora,
   observación y fotos asociadas.
 •​ Nombres informales. “La dos”, “la de reserva” o “el filtro de la izquierda” se resuelven contra el
   listado de equipos de la planta. Si un nombre queda ambiguo, el sistema pregunta.
 •​ Unidades. Las unidades ausentes o ambiguas se resuelven o se preguntan. En campo la presión se
   dice en “kilos” (kg/cm²), y en la planta también hay manómetros en psi y en bar.
 •​ Rango histórico. Un valor fuera del rango histórico del equipo pide confirmación antes de
   guardarse. El rango sale del historial del equipo.
 •​ Confirmación. El operador revisa el parte armado y lo confirma o lo corrige, también por voz.
### B. Detección en planta
 •​ Eventos. Cada parte confirmada y cada desvío de los sensores genera un evento que se evalúa en
   la planta.
 •​ Dentro de rango. Si los valores están dentro de los rangos de operación, el evento queda
   registrado como Sin novedad y todo se resuelve dentro de la planta.
 •​ Anomalía. Si hay un desvío o una anomalía sostenida, el evento pasa a Escalado con su contexto:
   el parte, las fotos y la tendencia de los sensores del equipo en las últimas horas.
 •​ Límites. Los límites de alarma de cada equipo están en su hoja de datos y los rangos históricos en
   su historial. Una decisión que depende de un límite numérico da siempre el mismo resultado con
   los mismos datos.

    CONDICIÓN INSEGURA

    Si el parte describe una pérdida con proyección de agua a presión, olor a gas, humo o fuego,
    o una persona lesionada, el sistema le indica en el momento al operador que aplique el
    procedimiento de emergencia, que incluye el aviso por radio al supervisor de turno, y
    registra la Alerta de seguridad. Esta respuesta funciona sin enlace y sin modelos en la nube.
### C. Análisis de la anomalía y borrador de orden de trabajo
 •​ Evidencia. Para cada evento Escalado, el sistema analiza el parte confirmado, las fotos y la
   tendencia de los sensores.
 •​ Manuales. Consulta los manuales del fabricante, en especial la tabla de fallas (síntoma, causa
   probable, acción recomendada) y los límites de operación. Cada conclusión cita la sección del
   manual de la que sale.
 •​ Historial. Consulta el historial de órdenes del equipo: una falla que se repite cambia la causa
   probable y la acción.
 •​ Causas probables. Devuelve las causas en orden, cada una con la evidencia que la respalda y lo
   que falta para confirmar. Si la evidencia no alcanza para identificar una causa, la acción
   recomendada es una inspección, por ejemplo un análisis de vibraciones con colector o una
   revisión de válvulas.
 •​ Borrador de orden. Arma la orden con el equipo, las tareas, si hay que detener el equipo, si la
   detención reduce la inyección (depende de que la bomba de reserva esté disponible), los
   repuestos con disponibilidad y costo unitario, y la evidencia.
 •​ Repuestos. Cada repuesto de la orden figura en la lista de materiales del equipo y en el
   inventario.
### D. Reglas de aprobación
Una orden se aprueba sin intervención humana solo si cumple todas estas condiciones:

 •​ Tarea estándar. La tarea está en el catálogo de tareas estándar del plan de mantenimiento del
   equipo, como el cambio de cartuchos de un filtro o la reposición de aceite del cárter.
 •​ Inyección. La inyección se mantiene: el equipo sigue en marcha, o la bomba de reserva lo
   reemplaza.
 •​ Stock. Todos los repuestos están en el almacén del yacimiento.
 •​ Costo. El costo total de repuestos es menor a USD 2.500.
 •​ Personal propio. La tarea la hace el personal de la planta, sin contratista externo.

En cualquier otro caso la orden queda pendiente de aprobación del planificador, con el motivo
explícito. Una orden cuyas fotos muestran daño estructural grave va siempre a revisión humana.

Mientras una orden está pendiente, el proceso queda suspendido y persistido: sobrevive a un reinicio
del sistema y se reanuda cuando el planificador la aprueba o la rechaza.
### E. Operación sin enlace
 •​ En la planta. El parte por voz, la detección y la alerta de condición insegura funcionan sin enlace.
 •​ Cola. Lo que necesita salir de la planta queda en cola y se procesa cuando vuelve el enlace, en
   orden y sin duplicar eventos ni órdenes.
 •​ Pendientes. El sistema muestra qué quedó pendiente de sincronizar.
 •​ Tu decisión. Qué corre en la PC de planta y qué corre en la nube lo decidís vos, dentro de las
   restricciones de hardware y de modelos, y lo justificás en el README.
### F. Seguridad y trazabilidad
 •​ Reglas en código. Las reglas de aprobación se aplican en código. Una orden se aprueba solo por
   esas reglas, diga lo que diga el texto que llega al modelo: una nota de voz, un comentario del
   historial o una página de un manual.
 •​ Solo lectura. Las herramientas de consulta (inventario, historial, sensores) son de solo lectura. La
   única escritura sobre órdenes pasa por las reglas de aprobación.
 •​ Registro. Cada decisión queda registrada con el modelo usado, las herramientas llamadas y sus
   argumentos, los tokens, el costo y el tiempo de cada paso.
### G. Cierre y certificación
 •​ Cierre por voz. El técnico, propio o de la contratista, cierra la orden con una nota de voz y fotos:
   qué hizo, qué repuestos usó y cómo dio la prueba final, por ejemplo “probé a ciento diez kilos, sin
   pérdida”. El sistema arma el parte de cierre con las tareas hechas, los repuestos usados, las horas y
   el resultado de la prueba.
 •​ Control contra la orden. El sistema compara el cierre con la orden, tareas pedidas contra hechas
   y repuestos reservados contra usados, y marca cada diferencia.
 •​ Cierre propio. Un trabajo de personal propio lo cierra el supervisor de mantenimiento, con las
   diferencias a la vista.
 •​ Certificación. Un trabajo de la contratista lo revisa el inspector de la operadora, con las
   diferencias a la vista: lo certifica o lo observa. Una orden observada vuelve a la contratista con el
   motivo.
 •​ Habilita. La certificación emite la habilita, con número y monto, que es lo que la contratista
   necesita para facturar. El monto sale de la orden y de la lista de precios del contrato, aunque el
   cierre de la contratista diga otra cosa.
## 03 Estados
 ENTIDAD        ESTADO                 SIGNIFICADO

 Parte          Borrador               Armado desde las notas de voz, sin confirmar.

 Parte          Confirmado             El operador lo validó. Recién entonces genera eventos.

 Evento         Sin novedad            Valores dentro de rango. Queda registrado. Terminal.

                                       Hay anomalía. Espera el análisis, en cola si no hay enlace, y termina
 Evento         Escalado
                                       asociado a una orden de trabajo.

                                       Condición insegura. Sigue por el procedimiento de emergencia.
 Evento         Alerta de seguridad
                                       Terminal.

 Orden          Borrador               Generada por el análisis, antes de aplicar las reglas.

                Pendiente de
 Orden                                 Espera al planificador. Proceso suspendido y persistido.
                aprobación

 Orden          Aprobada               Cumplió las reglas o las aprobó el planificador. Lista para ejecutar.

 Orden          Rechazada              La rechazó el planificador. Terminal.

 Orden          Ejecutada              El técnico la cerró por voz. Espera el cierre o la certificación.

 Orden          Observada              El inspector encontró diferencias. Vuelve a la contratista.

 Orden          Cerrada                Trabajo propio, cerrado por el supervisor. Terminal.

 Orden          Certificada            Trabajo de contratista, certificado y con su habilitación. Terminal.
## 04 Restricciones
 •​ Modelos. Solo los de la lista cerrada que publicamos. Incluye modelos de transcripción y de
   lenguaje que entran en la PC de planta, y modelos en la nube de NVIDIA con visión. Los modelos
   locales corren con la versión y la configuración que fijamos.
 •​ Hardware de planta. Sin GPU, 4 núcleos y 8 GB de memoria. El entorno de planta se simula con
   contenedores limitados a esos recursos.
 •​ Lenguaje. Python 3.11 o superior, con LangChain para el núcleo de agentes.
 •​ Datos y RAG. PostgreSQL 16 con pgvector. Los manuales se indexan con metadatos de equipo,
   fabricante y sección.
 •​ Herramientas. Contratos con esquemas estrictos en Pydantic.

 •​ MCP. Al menos una herramienta de acceso a datos (inventario, historial o sensores) se expone por
   Model Context Protocol.
 •​ Ejecución. Todo el sistema se levanta con docker compose up.
## 05 Lo Que Te Damos
 •​ Notas de voz. Recorridas grabadas con ruido de planta, cada una con el parte esperado.
 •​ Fotos. Pérdidas por empaquetadura, correas, acoples, manómetros y filtros.
 •​ Sensores. Historial de la planta en CSV, con anomalías conocidas.
 •​ Equipos. TAG, nombres informales y hoja de datos con límites de alarma.
 •​ Manuales. Bombas y filtros, con tabla de fallas, preparados para el TP.
 •​ Materiales. Lista de materiales por equipo, stock por almacén, costos y catálogo de tareas
   estándar.
 •​ Órdenes. Historial de órdenes de trabajo.
 •​ Contrato. Lista de precios del contrato de mantenimiento y cierres por ejemplo de la contratista,
   algunos con diferencias.
 •​ Simulador de enlace. Corta la salida a internet del entorno de planta.
## 06 Qué Entregás
 •​ Repositorio. Público en GitHub, con el nombre nombre-apellido (por ejemplo, axel-martinez). El
   link se carga en el formulario de entregas.
 •​ Estructura. En la raíz van README.md, docker-compose.yml y la carpeta tests/. El resto de la
   estructura la definís vos.
 •​ README. Cómo levantar y probar el sistema, y la justificación de qué corre en la planta y qué en
   la nube.
 •​ Pruebas. Tests automatizados de las herramientas y una suite de evaluación que corre sobre
   nuestros datos y reporta aciertos, costo y latencia.

 •​ Informe Técnico. Un archivo INFORME.md en donde se especifiquen los modelos usados para
   cada tarea. En el caso de uso de LLMs locales indicar nombre, proveedor, versión, cantidad de
   parámetros y en qué hardware se usó para la pruebas (Desktop, Notebook, CPU, RAM, GPU). En
   el caso de uso de modelos en la nube indicar nombre, proveedor, versión y página web de
   referencia. En ambos casos determinar el consumo de tokens por tarea y un costo aproximado (en
   el caso de LLMs en la nube). Y al final una conclusión de porqué se eligieron los modelos
   propuestos como solución.

       ACADEMIA NOVIT 2026

       Enseñamos lo que sabemos.
       Desarrollo de Agentes IA y Software Agéntico. Formación anual,
       gratuita, abierta y 100% online.
