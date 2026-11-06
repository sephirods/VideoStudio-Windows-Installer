# Contrato del Asistente Programador — VideoStudio Pro

Este documento rige de forma estricta y permanente el comportamiento, flujo de trabajo y buenas prácticas del **Asistente de IA (Programador)** en este repositorio y entorno de desarrollo.

---

## REGLA #1: PREVENCIÓN DE ARCHIVOS MONOLÍTICOS (< 1000 LÍNEAS) Y MODULARIZACIÓN ESTRICTA
- **Límite de tamaño:** NUNCA crear ni permitir que un archivo supere las 1000 líneas de código ni mezcle múltiples responsabilidades.
- **Descomposición modular:** Descomponer siempre el código en módulos pequeños y cohesivos (separando interfaz, lógica de pipeline, APIs, tipos y utilidades).
- **Refactorización previa:** Si un archivo existente supera las 1000 líneas o se vuelve monolítico, refactorizarlo extrayendo submódulos específicos antes de añadir nueva funcionalidad.

---

## REGLA #2: PROHIBICIÓN ABSOLUTA DE SIMPLIFICAR, RESUMIR O REESCRIBIR CÓDIGO (FIDELIDAD VERBATIM 100%)
- **Estrictamente prohibido:** Ningún asistente o IA puede jamás "resumir", "simplificar", "recrear de memoria" ni reescribir código existente.
- **Extracción verbatim 1:1:** Toda refactorización, modularización o traslado de código debe realizarse estrictamente por extracción física 1:1 de los bloques de líneas exactos del archivo de origen, garantizando que no se altere ni un solo carácter, parámetro, variable, manejador de errores, regex o lógica de negocio.
- **Validación:** Cualquier cambio debe ser verificado mediante diff línea por línea antes de considerarse terminado.

---

## REGLA #3: INSPECCIÓN EXHAUSTIVA ANTES DE EDITAR
- **Lectura completa:** NUNCA modificar o sobrescribir bloques de código o scripts sin haber inspeccionado previamente el archivo completo línea por línea.
- **Preservación:** Preservar siempre las reglas de ordenación, tipados, manejadores de excepciones y rutas existentes.

---

## REGLA #4: PROHIBICIÓN ABSOLUTA DE REALIZAR CAMBIOS SIN PERMISO EXPLÍCITO
- **Autorización previa obligatoria:** JAMÁS, bajo NINGUNA circunstancia, se deben realizar cambios de código, modificaciones de interfaz (UI/UX), edición de archivos o ejecuciones en el servidor o cliente sin antes explicar detalladamente la propuesta al usuario y recibir su autorización explícita ("adelante", "aprobado", "hazlo").
- **Excepción:** Únicamente cuando el usuario ordene expresamente terminar hasta el final sin preguntar.
- **Respeto al diseño:** Respetar al 100% la estructura visual, estética y de diseño establecida por el usuario sin agregar, quitar o alterar elementos sin permiso previo.

---

## REGLA #5: RESPALDO OBLIGATORIO EN GIT ANTES DE MODIFICAR
- **Commit preventivo:** SIEMPRE, antes de realizar cualquier modificación de código o en cualquier archivo del proyecto, realizar y confirmar primero un `git commit` de respaldo con el estado actual ANTES de tocar una sola línea de código.
- Solo tras confirmar el respaldo limpio en Git se procederá con las modificaciones autorizadas.

---

## REGLA #6: NOMENCLATURA OBLIGATORIA DE VERSIONES EN COMMITS DE GIT
- **Prohibido:** Mensajes genéricos, aleatorios o sin prefijo claro.
- **Formato semántico estricto:**
  - `[v1.0.0] - Descripción de versión mayor / hito base`
  - `[v1.1.0] - Descripción de nueva funcionalidad o módulo desplegado`
  - `[v1.1.1] - Descripción de corrección o ajuste específico`

---

## REGLA #7: PROHIBICIÓN ABSOLUTA DE FALLBACKS FALSOS, SIMULACIONES O ERRORES SILENCIADOS
- **Cero simulaciones:** Prohibido implementar fallbacks ficticios, textos simulados por defecto o capturas vacías que oculten fallos (`try { ... } catch (_) {}`).
- **Transparencia técnica:** Si una función, API, FFmpeg, motor de IA o script falla, debe lanzar y reportar el error técnico real de inmediato al usuario, sin disfraces ni valores inventados.

---

## REGLA #8: GRAFO DE CONOCIMIENTO DEL PROYECTO (KNOWLEDGE_GRAPH.md) Y ACTUALIZACIÓN CONTINUA
- **Consulta previa obligatoria:** Antes de inspeccionar a ciegas o modificar archivos, consultar `KNOWLEDGE_GRAPH.md` para entender el mapa de arquitectura, responsabilidades de archivos y endpoints involucrados.
- **Mantenimiento vivo:** Cada vez que se agregue, modifique, renombre o elimine un archivo, función clave, endpoint o ID del DOM, es 100% obligatorio actualizar `KNOWLEDGE_GRAPH.md` en el mismo cambio. Si no existe en el directorio de trabajo, crearlo.

---

## REGLA #9: PROHIBICIÓN DE EXCUSAS DE CACHÉ
- **Responsabilidad de raíz:** NUNCA culpar, justificar ni mencionar a la caché (del navegador, del servidor o de componentes) como causa o explicación de que un cambio no se visualice o falle. El agente tiene la responsabilidad absoluta de encontrar la verdadera causa en el código y los archivos.

---

## REGLA #10: MANEJO DE CODIFICACIÓN UTF-8 Y SINTAXIS EN WINDOWS POWERSHELL
- **UTF-8 estricto:** Configurar siempre el procesamiento de datos y la codificación de archivos y consola en UTF-8 estricto para evitar errores de decodificación (`charmap`) con tildes, la letra ñ y caracteres especiales.
- **Sintaxis de comandos:** En Windows PowerShell, escapar y entrecomillar adecuadamente comandos y cadenas para evitar errores de interpretación por comillas anidadas o barras invertidas.

---

## REGLA #11: RESPUESTA INMEDIATA AL USUARIO (INTERRUPCIÓN DE PROCESOS)
- **Prioridad absoluta al chat:** Si el usuario escribe en cualquier momento, el agente priorizará responder al instante, deteniendo, pausando o pasando a segundo plano cualquier comando o proceso de larga duración para no dejarlo esperando.

---

## REGLA #12: ANÁLISIS EXHAUSTIVO Y RESOLUCIÓN AL PRIMER INTENTO (EVITAR PARCHES CIEGOS)
- **Análisis completo:** NUNCA realizar modificaciones habiendo leído de manera superficial o parcial.
- Comprender las dependencias (scripts, estilos, APIs y eventos) para resolver los problemas correctamente en el primer intento y evitar iteraciones o consumo innecesario de recursos.

---

## REGLA #13: APROBACIÓN PREVIA DE IMÁGENES Y ASSETS
- SIEMPRE, antes de cambiar, reemplazar o después de generar cualquier imagen o recurso visual del proyecto, presentársela al usuario en el chat antes de aplicarla o guardarla definitivamente.

---

## REGLA #14: PRUEBAS MULTI-RESOLUCIÓN EN LA APLICACIÓN DE ESCRITORIO
- Verificar que la maquetación visual responda de forma fluida y sin desbordamientos al redimensionar la ventana de VideoStudio (desde resoluciones compactas de laptop hasta pantallas de escritorio grandes).

---

## REGLA #15: LAS 10 REGLAS ESTRICTAS DE EXPLICACIÓN Y AUTORIZACIÓN PREVIA
1. **Explicación previa obligatoria:** Antes de tocar archivos o ejecutar comandos, explicar en español claro qué cambio se va a realizar y para qué sirve.
2. **Prohibición de tareas silenciosas:** NUNCA ejecutar scripts o cambios en segundo plano sin haberlo avisado previamente.
3. **Espera de confirmación:** Detenerse y esperar un "sí", "adelante" o "aprobado" antes de ejecutar.
4. **Atención inmediata:** Responder al usuario en cuanto escriba.
5. **Transparencia de contenidos:** Identificar siempre los archivos, rutas o registros afectados.
6. **Prohibición de asunciones:** NUNCA asumir que un archivo o registro es sobrante o de prueba sin orden del usuario.
7. **Detalle específico:** Indicar el nombre exacto del archivo y la mejora técnica concreta.
8. **Eficiencia:** Proponer la alternativa más limpia y directa.
9. **Reporte transparente:** Mostrar el resultado real y comprobable tras cada acción autorizada.
10. **Reversión inmediata:** Si un cambio autorizado no es del agrado del usuario, revertirlo inmediatamente con Git.

---

## REGLA #16: MODULARIZACIÓN ESTRICTA DE ASSETS, HTML, CSS Y JAVASCRIPT
- NUNCA insertar estilos CSS masivos en línea dentro de etiquetas HTML ni bloques gigantes de JavaScript embebido.
- Separar el código en archivos independientes estructurados por responsabilidad (CSS por layouts/componentes, JS por módulos/utilidades, assets organizados).
- Declarar variables (`const` y `let`) al inicio de cada archivo o ámbito correspondiente.

---

## REGLA #17: SINCRONIZACIÓN OBLIGATORIA CON EL REPOSITORIO REMOTO
- NUNCA comenzar una sesión de trabajo o modificación de archivos sin verificar primero el estado del repositorio remoto.
- Ejecutar `git fetch` y `git pull` antes de implementar o editar cambios para asegurar que se trabaja sobre la versión más reciente y evitar sobreescrituras.
