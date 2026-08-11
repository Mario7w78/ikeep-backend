# Kerotime — Plan de trabajo y traspaso de sesión

> **Documento de traspaso.** Última actualización: 2026-08-11.
> Para retomar en otra máquina, lee las secciones **Estado actual** y **Puesta en marcha**
> antes que nada, y sigue en **Fase 1**.

---

## Context

Kerotime (ex iKeep) son dos repos:

| Repo | Ruta local | Stack | Rama |
|---|---|---|---|
| `ikeep-backend` | `…/GitHub/ikeep-backend` | Python 3.13, FastAPI, OR-Tools CP-SAT, hexagonal, stateless | `main` |
| `iKeep-frontend` | `…/GitHub/iKeep-frontend` | React Native + Expo SDK 55, TypeScript strict, Zustand, Supabase | `dev` |

Producción: `https://ikeep-backend.onrender.com` (Render free tier).

El motor de optimización funciona y la arquitectura de ambos repos es correcta. El problema no es la arquitectura: falta la capa de producto, el asistente tiene un defecto estructural de diseño de datos, y el wizard expone el vocabulario interno del optimizador.

**Objetivos del usuario:** enganchar gente · que la app funcione bien · que sea atractiva · que el asistente no olvide · mascota animada tipo Duolingo · wizard de creación intuitivo.

**Decisiones tomadas:** asistente primero · **quedarse en Groq/Cerebras/Mistral** (sin migrar a Claude) · **mascota con Lottie**, aún no producida · contexto = **producto real para lanzar**.

---

# ESTADO ACTUAL

## Fase 0 — COMPLETA ✅

Baselines verificados al cierre:

| | Antes | Después |
|---|---|---|
| Tests backend | 249 verdes + 3 rojos | **258 verdes, 0 rojos** |
| Tests frontend | 53 verdes | **56 verdes** |
| `tsc --noEmit` | 19 errores | 19 errores (**0 nuevos**, todos preexistentes) |

### ⚠️ TODO ESTÁ SIN COMMITEAR

Si la máquina actual se pierde o se limpia, **este trabajo se va con ella**. Antes de cambiar de máquina hay que commitear y pushear.

**Backend** (rama `main` — conviene crear rama antes de commitear):
```
 M infrastructure/adapters/inbound/api/v1/schedule_router.py
 M infrastructure/adapters/outbound/llm/openai_compatible_adapter.py
 M infrastructure/config/settings.py
 M main.py
 M schemas/parse_nl.py
 M tests/test_container.py
 M tests/test_openai_compatible_adapter.py
?? .dockerignore
?? .env.example
?? Dockerfile
?? infrastructure/adapters/inbound/api/rate_limit.py
?? tests/test_rate_limit.py
```

**Frontend** (rama `dev`):
```
 M app.json
 M package.json
 M src/infrastructure/api/ParseNLApiService.ts
 M src/infrastructure/api/__tests__/ParseNLApiService.test.ts
 M src/presentation/components/atoms/CreateActivity/DayButton.tsx
 M src/presentation/components/molecules/CreateActivity/TimePartitionForm.tsx
 M src/presentation/components/organisms/CreateActivity/TimeConfigStep.tsx
 M src/presentation/hooks/useTimeForm.ts
 M src/presentation/screens/AIChat/AIChatView.tsx
 M src/presentation/screens/Activity/activityCreation/CreateActivityView.tsx
 M src/presentation/utils/timeUtils.ts
?? src/infrastructure/api/apiConfig.ts
```

`.env` **no** está versionado en ninguno de los dos (correcto). En la máquina nueva hay que recrearlos — ver **Puesta en marcha**.

### Qué se hizo exactamente

**Backend — seguridad y estabilidad**
- **Rate limit por IP** en `infrastructure/adapters/inbound/api/rate_limit.py` (nuevo). Ventana deslizante de 60s, 20 req/min configurable vía `RATE_LIMIT_PER_MINUTE` (0 desactiva). Acotado a rutas que contengan `parse-nl`, así `/generar` (CPU propia) y `/health` (ping + cron) quedan libres. Honra `X-Forwarded-For` porque Render termina TLS en su proxy. Barrido de IPs ociosas por encima de 10.000 entradas. **6 tests propios** en `tests/test_rate_limit.py`.
- **CORS** montado en `main.py` (antes no había ninguno → un frontend web no podía consumir la API). `allow_credentials=False` a propósito: la auth será Bearer, y `"*"` + credentials lo rechaza el navegador.
- **Logging configurado** con `logging.basicConfig` en `main.py`. Antes **todos los `logger.info/warning` del código se descartaban** por la config por defecto de Python — se perdían las trazas de failover y circuit breaker.
- Orden de middleware: CORS → RateLimit → ErrorHandler, para que hasta un 429 o un 500 lleven cabeceras CORS.
- **Límites de input** en `schemas/parse_nl.py`: `text` `max_length=1000`, `history` `max_length=40`, `agenda_context` `max_length=8000`, `ConversationMessage.content` `max_length=2000`.
- **Timeout y max_tokens** en `openai_compatible_adapter.py`: `REQUEST_TIMEOUT_SECONDS=25.0`, `max_retries=0` (los reintentos los hace `FailoverAdapter`), `MAX_OUTPUT_TOKENS=1500`.
- **Event loop desbloqueado**: quitado el `async` de `parse_actividad_nl_conversation` en `schedule_router.py`, que llamaba un cliente HTTP síncrono y bloqueaba uvicorn durante toda la latencia del LLM.
- **`.env.example`, `Dockerfile`, `.dockerignore`** creados (no existía ninguno, ni CI).
- `settings.py` gana `LOG_LEVEL`, `CORS_ORIGINS`, `RATE_LIMIT_PER_MINUTE` y la propiedad `cors_origin_list`.

**Frontend — infra**
- **`AbortController` conectado al fetch** en `ParseNLApiService.ts`. Antes se creaba y se descartaba (admitido en un comentario), así que el timeout no existía.
  - **Ojo con la trampa que esto tenía**: como el fetch no abortaba nunca, un cold start de 45s *acababa funcionando*. Activar el timeout de 30s tal cual habría hecho que los cold starts fallaran **siempre**. Por eso se emparejó con **timeouts escalonados**: 60s el primer intento (`COLD_START_TIMEOUT_MS`), 25s los reintentos (`WARM_TIMEOUT_MS`).
- **`src/infrastructure/api/apiConfig.ts`** (nuevo): única fuente de verdad de la URL del backend + `warmUpBackend()`.
- **Ping de calentamiento** en `AIChatView.tsx` (`useEffect` al montar). El usuario tarda ≥5s en escribir; ese tiempo despierta el server.
- `package.json`: añadidos scripts `test`, `test:watch`, `typecheck` (existían jest y 7 archivos de test, pero no había forma de correrlos).
- `app.json`: `userInterfaceStyle` `"light"` → `"dark"` y splash `#ffffff` → `#2C2E3C` (era una app dark-only declarando light, con flash blanco al arrancar).
- **3 tests nuevos** en `ParseNLApiService.test.ts`, incluido el de regresión del abort con fake timers.

**Frontend — quick wins del wizard**
- **Confirmación de descarte** en las 3 vías de cierre (X, backdrop, swipe de 130px) **más el back de hardware de Android**, que era una 4ª vía no contemplada. `isDirty` distingue crear (nombre/días/paso) de editar (nombre cambiado o navegación hacia adelante). El `PanResponder` se construye una sola vez, así que lee `isDirty`/`requestClose` por refs; en swipe sucio hace *snap back* antes de preguntar.
- **Hora por defecto redondeada**: nuevo `nextRoundHour()` en `timeUtils.ts`. Antes se sembraba con `new Date()` → 15:47, presentado como valor real, obligando a corregir dos ruedas siempre.
- **Chips de viaje**: default `0` en vez de `null`. La comparación es `partition.travelTo === chip.value`, así que con `null` ni siquiera "Sin" salía seleccionado y la fila parecía un campo obligatorio pendiente.
- **Deselección de día visible** en `DayButton.tsx`: `configured` ahora controla solo el borde y `selected` solo el fondo. Antes `configured` ganaba y el tap parecía no hacer nada.
- **Validación de bloque de duración cero** en `validatePartitions`.
- **Feedback de éxito**: estado `justSaved` con check + háptica de éxito + 750ms antes de cerrar. Antes el sheet se cerraba sin ninguna señal.
- **Fuera el parpadeo infinito** de los tabs de día no visitados (`Animated.loop` de opacidad sin explicación) → punto estático. De paso se colapsó la rama duplicada del render.
- `minuteInterval={5}` también en el picker de fin (lo tenía solo el de inicio).

### Hallazgos importantes de la Fase 0

Tres cosas que no estaban en el diagnóstico inicial y salieron al implementar:

1. **El venv del backend estaba roto.** Le faltaban `dependency-injector` y `openai`, y no tenía ni `pip`. `main.py` no importaba en absoluto. Eso explicaba los tests que aparecían en rojo a nivel de archivo en `.pytest_cache/lastfailed`. Reconstruido con `ensurepip` + `pip install -r requirements.txt`. **En la máquina nueva hay que rehacerlo — ver Puesta en marcha.**

2. **Dos tests de `test_container.py` estaban mal escritos** (preexistente): hacían `@patch("openai.OpenAI")` pero el adapter hace `from openai import OpenAI`, así que el patch nunca tomaba efecto y se construía el cliente real sin credenciales. Corregido el target del patch a `infrastructure.adapters.outbound.llm.openai_compatible_adapter.OpenAI`.

3. **Bug real de cruce de medianoche en el frontend.** `updateActivePartition` calculaba la duración con `Math.max(0, …)` sobre la diferencia cruda de timestamps. Como ambos pickers están en la fecha de hoy, un bloque 23:00→01:00 daba negativo y se **clampeaba a 0**, guardándose vacío. El resto del código (`areOverlapping`, el solver, `test_midnight_crossing.py` con 918 líneas) ya soporta el wrap. Migrado a `calculateDurationAcrossMidnight`.

**Corrección a una afirmación anterior:** dije que "Kerotime" no aparecía en ningún repo. En el backend es cierto, pero **el frontend ya está renombrado** — `package.json` y `app.json` dicen `kerotime-app`. Lo que sigue como iKeep es el backend y el dominio de producción.

### Pendiente de Fase 0 (fuera del código)

- [ ] Cron externo (UptimeRobot o GitHub Actions cada 10 min) golpeando `/health` en horario activo, para que Render no duerma.
- [ ] Configurar `CORS_ORIGINS` con el dominio real cuando exista uno (hoy queda en `*`).

---

# PUESTA EN MARCHA EN LA MÁQUINA NUEVA

## Backend

```bash
cd ikeep-backend
python -m venv .venv
```

Si el venv ya existe pero le falta `pip` (fue el caso en la máquina anterior):

```bash
.venv/Scripts/python.exe -m ensurepip --upgrade
```

Instalar dependencias y verificar:

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

```bash
.venv/Scripts/python.exe -c "import main; print(main.app.title)"
```

Correr los tests (esperado: **258 passed**):

```bash
.venv/Scripts/python.exe -m pytest -q --no-header
```

Levantar en local:

```bash
.venv/Scripts/python.exe -m uvicorn main:app --reload
```

**`.env`**: copiar de `.env.example`. Lo único imprescindible es al menos una de `GROQ_API_KEY` / `CEREBRAS_API_KEY` / `MISTRAL_API_KEY`; sin ellas la app arranca pero falla en la primera llamada al LLM. Las claves están en el `.env` de la máquina vieja y en el dashboard de Render.

## Frontend

Usa **pnpm** (hay `pnpm-workspace.yaml` y `pnpm-lock.yaml`).

```bash
cd iKeep-frontend
pnpm install
```

Tests (esperado: **56 passed, 7 suites**):

```bash
pnpm test
```

Typecheck (esperado: **19 errores preexistentes**, ninguno nuevo):

```bash
pnpm typecheck
```

Arrancar:

```bash
pnpm start
```

**`.env`**: necesita `EXPO_PUBLIC_SUPABASE_URL` y `EXPO_PUBLIC_SUPABASE_ANON_KEY`. Sin ellas el cliente cae a placeholders con un `console.warn` y la auth no funciona. Están en el dashboard de Supabase.

**Nota sobre los tests**: la primera corrida con la caché de babel fría puede hacer fallar `NLConversationStep.test.tsx` por el timeout de 5000ms del primer test. No es un fallo real — volver a correr.

---

# PLAN DE TRABAJO

## Fase 1 — Backend: motor conversacional con tool calling (4-6 días) ← **SIGUIENTE**

Se construye **en paralelo** al endpoint viejo, que sigue intacto hasta la Fase 5.

### El arreglo central del "se olvida"

**Causa raíz confirmada:** `useChatStore.ts:312-316` mapea el historial a `{role, content, type}` donde `content` es **solo el texto legible**. Cuando el backend produjo un `result` con `{name, schedule, duracion, difficulty, priority, location, travel_to}`, ese JSON **nunca vuelve al modelo** en el turno siguiente. El modelo tiene que re-derivar la entidad desde prosa que no la contiene. La prueba está en `llm_parser_service.py:535`, una regla que le ruega al modelo *"No ignores ni olvides la información provista en los turnos anteriores"* — nadie escribe eso si el dato está ahí.

Dos agravantes: el historial se **aplana a texto** (líneas 291-297 y 615-618) en vez de usar el array `messages` nativo; y el prompt es un f-string monolítico de **340 líneas**. El límite de "4 intercambios" (líneas 640-645, 698-700) es un parche contra el bucle de preguntas que causa la pérdida de estado.

**Dos cambios que van juntos:**

1. **`messages` nativo con bloques verbatim.** El historial pasa a ser un array de turnos donde los `tool_call` del asistente y sus `tool_result` se guardan **tal cual**. En el turno N+1 el modelo recibe de vuelta su propio JSON estructurado, no una paráfrasis.
2. **Tool `actualizar_borrador`.** El modelo la llama en cualquier turno donde extrae información nueva, incluso mientras sigue preguntando. Emite un `draft_patch` parcial; el **cliente** lo aplica con un reducer determinista. El draft es la memoria; el historial es solo conversación.

Con esto, `missing_fields` y el discriminador `response_type` desaparecen — **los slots vacíos del draft *son* la lista de faltantes** — y el límite de 4 intercambios se elimina.

### Catálogo de tools

Las de **lectura** se ejecutan en el cliente contra los stores y su resultado vuelve al modelo en el mismo turno. Las de **propuesta** terminan el turno y renderizan la tarjeta de confirmación existente.

| Tool | Clase | Efecto |
|---|---|---|
| `actualizar_borrador` | interna | Aplica `draft_patch`. Sin UI. Corazón del slot filling. |
| `consultar_agenda` | lectura | Habilita *"¿qué tengo mañana?"* |
| `buscar_actividad` | lectura | Fuzzy match normalizando acentos. Reemplaza el matching por substring de `useChatStore.ts:384-402`. |
| `sugerir_tarea` | lectura | Reusa `handleSuggestTask` (ya existe). |
| `proponer_actividad` | propuesta | Emite el mismo `pendingActivity` de hoy. |
| `proponer_modificacion` | propuesta | `isModification:true`. |
| `proponer_eliminacion` | propuesta | **Caso de uso nuevo.** |
| `proponer_regeneracion` | propuesta | **Caso de uso nuevo.** |

Texto plano sin tools = pregunta o charla. No hace falta una tool para eso.

### Contexto: JSON con ids, no prosa

Hoy `useChatStore.ts:270-303` serializa la agenda como prosa española **sin ids**. Sin ids no se puede modificar ni eliminar de forma fiable — esa es la razón estructural de que el asistente hoy solo sepa crear.

El bloque dinámico pasa a JSON con `ahora {fecha, dia, hora_min}`, `agenda[]` **con `id`**, `huecos_libres_hoy`, `borrador` actual, `ya_pregunte[]` (rompe preguntas repetidas) y `energia` (de `EnergyHistoryService`, que ya existe y hoy no se usa en el chat). `huecos_libres_hoy` habilita *"tengo 2 horas libres, ¿qué hago?"* sin llamadas extra.

### Truncado por tokens

Reemplaza `if len(history) > 12` (`llm_parser_service.py:636`) y `MAX_HISTORY_EXCHANGES = 4` (`useChatStore.ts:309`). Presupuesto: ~3.5K system + ≤2.5K contexto + ≤8K historial + ≤2K salida.

Regla dura: **un `tool_call` y su `tool_result` se podan juntos o no se podan.** Podar es seguro porque el estado vive en el draft, no en la prosa.

### Archivos

Nuevos en `ikeep-backend`:
```
domain/ports/outbound/conversational_llm_port.py    # puerto hermano; NO tocar LLMPort (lo usan suggest/reschedule)
domain/services/assistant/{tools,system_prompt,context_builder,context_budget,conversation_service}.py
schemas/assistant.py
infrastructure/adapters/outbound/llm/{openai_tools_adapter,conversational_failover_adapter}.py
infrastructure/adapters/inbound/api/v1/assistant_router.py
```
Tocados: `container.py` (wiring; el `wiring_config` de las líneas 26-32 debe incluir el router nuevo), `main.py`, `settings.py`.

Endpoint `POST /api/v1/asistente/conversar` **con auth JWT de Supabase** (validar firma con `SUPABASE_JWT_SECRET`). Cierra el agujero del endpoint público — el rate limit de Fase 0 es una mitigación, no la solución.

### Reglas que bajan de prompt a código

- Conversión AM/PM → el schema declara `0-1439` y Pydantic valida rango. Se van las 6 líneas de *"¡NUNCA confundas 1 pm con 1 am!"* (549-551).
- `is_fixed && is_anchor` → `model_validator`, no el `if` defensivo de la línea 775.
- `duracion == pref_fin - pref_inicio → is_fixed` (líneas 723-747) → validator de dominio. Elimina las **3 copias casi idénticas** del loop de `ParsedSchedule`.

### Consecuencias de quedarse en Groq/Cerebras

1. **Se pierde el prompt caching.** La reestructuración se justifica por **calidad y fiabilidad**, no por costo.
2. **El riesgo pasa al tool calling multi-turno de Llama 3.3 70B**, que es irregular. Mitigación de diseño: **toda la lógica determinista vive en Python/TypeScript, no en el modelo.** El modelo solo extrae y decide. La suite de conversaciones doradas mide empíricamente qué proveedor va primero — hoy el orden Groq→Cerebras→Mistral está fijado sin evidencia.

---

## Fase 2 — Frontend: estado y cliente del asistente (3-4 días)

**`confirmPendingActivity` (`useChatStore.ts:475-647`) no se toca.** Las tools de propuesta emiten el mismo `pendingActivity`, así que la validación de solapamientos, la creación y el rollback siguen funcionando.

Nuevos:
```
src/domain/entities/conversation.types.ts     # ActivityDraft, ConversationState, LlmTurn
src/application/services/draftReducer.ts      # applyDraftPatch
src/application/services/toolExecutor.ts      # tools de lectura contra los stores
src/application/mappers/draftToFormState.ts   # reusa mapParsedResponseToFormState (parseNlMapper.ts:74)
src/infrastructure/api/AssistantApiService.ts # usa apiConfig.ts, ya creado en Fase 0
```
Tocados: `useChatStore.ts` (solo `sendMessage`, línea 255), `src/di/Dependencies.ts`.

**Clave:** `messages[]` (render) y `llmTurns[]` (modelo) son **dos representaciones paralelas** enlazadas por id. Nunca se deriva una de la otra parseando texto.

**Merge del draft:** shallow merge **excepto `schedule`, que se reemplaza entero** — nunca mergear por índice; es la fuente de los bugs de "cambié el lunes y se duplicó el miércoles".

**Persistencia:** `zustand/middleware` `persist` sobre AsyncStorage con `partialize` para `{messages, llmTurns, draft}`. Campo `v: 1`: si al hidratar no coincide, descartar el draft y conservar solo los mensajes de render.

**Cancelación:** `AbortController` real expuesto como `cancelMessage()`. Hoy no existe. (El patrón de escalonado de timeouts ya está en `apiConfig.ts`.)

**Feature flag `ASSISTANT_V2`** en `Dependencies.ts` para poder volver atrás.

---

## Fase 3 — Casos de uso nuevos y descubrimiento (3-4 días)

- `MessageBubble.tsx` (741 líneas) — extraer la tarjeta de actividad (líneas 170-366) a `ActivityProposalCard.tsx` y añadir `DeleteConfirmCard`, `RegenerateConfirmCard`, `AgendaAnswerCard`.
- `useChatStore.ts` — `confirmPendingActivity` gana un `switch (kind)`: `create`/`modify` sin cambios; `delete` → `handleDeleteActivity` + `handleGenerateSchedule` con el mismo rollback; `regenerate` → `handleGenerateSchedule(energyData, true)`.
- `NLConversationStep.tsx` — **chips de sugerencia** sobre el input vacío: *"¿Qué tengo mañana?"* · *"Tengo 2 horas libres"* · *"Reorganiza mi semana"*. **Palanca de descubrimiento**: hoy el usuario no tiene forma de saber que el asistente hace algo más que crear.
- `HomeView.tsx` — entrada al chat con una pregunta contextual del día.

---

## Fase 4 — Rediseño del wizard (5-7 días)

Va después de la Fase 3 a propósito: reutiliza `ActivityProposalCard` y `ConflictPreview` en vez de duplicarlos.

**Contexto del problema:** crear *"clase de álgebra, martes de 10 a 12"* cuesta **~14 interacciones** en 4 pantallas. Por el chat cuesta **1 mensaje + 1 tap**. Los quick wins de Fase 0 aliviaron la fricción más aguda pero no tocaron la estructura.

### Principio 1 — Un solo eje de decisión, no dos taxonomías

Hoy conviven "Identidad" (Clase/Trabajo/Tarea) y "Tipo" (Fijo/Optimizable), acopladas por efectos secundarios ocultos en `useTimeForm.ts:60-89` que **pisan prioridad y dificultad** y encima esconden la sección donde se eligieron. Y la tarjeta "Fijo" se describe como *"Anclado a una hora"* mientras el toggle *"Anclaje de día"*, 140 líneas más abajo, significa lo contrario.

- **Identidad = solo etiqueta** (ícono + color). No toca `isFixed`, ni `difficulty`, ni `priority`.
- **Una sola pregunta de comportamiento**, en lenguaje llano:

| Opción visible | Estado interno |
|---|---|
| "Siempre a la misma hora" | `isFixed: true` |
| "Yo elijo el día, tú la hora" | `isAnchor: true` |
| "Cuando mejor encaje" | flexible puro |

Cada una con una frase de ejemplo debajo (*"Ej. tu clase de Cálculo, todos los martes 10-12"*).

### Principio 2 — Divulgación progresiva: 2 pasos, no 4

**Paso 1 — "¿Qué y cuándo?"**: nombre → días → el eje único → horas (si es fija) o duración.
**Paso 2 — Resumen editable**, reutilizando `ActivityProposalCard`, con **"Opciones avanzadas"** plegado: dificultad, prioridad, fecha límite, traslado, ventana preferida y turnos múltiples.

Objetivo medible: de ~14 interacciones a **~6**.

### Principio 3 — Errores inline, nunca `Alert.alert`

Reemplazar `showAlert` (`CreateActivityView.tsx:110-112`) y los `Alert.alert` de `useTimeForm.ts` por mensajes bajo el campo afectado. Para solapamientos, **reusar `ConflictPreview`** (`MessageBubble.tsx:369`) — ya existe y es persistente, a diferencia del Alert que desaparece y encima **cambia el día activo bajo los pies del usuario** (`CreateActivityView.tsx:428-431`).

### Principio 4 — Edición rápida

Tap en cualquier campo del resumen → editar → guardar, sin atravesar pasos.

Arreglar la pérdida en el round-trip: `CreateActivityView.tsx:191` + `useTimeForm.ts:431-432` hacen que **toda actividad fija se relea siempre como prioridad "alta" y dificultad "media"**.

### Principio 5 — Borrador persistente

Mover el estado del wizard de `useState` locales a un store zustand con `persist`. La confirmación de descarte de Fase 0 es el parche; el borrador es la solución.

### Principio 6 — Vocabulario único entre wizard y chat

Glosario en `src/presentation/theme/copy.ts`, importado por ambos:

| Concepto | Wizard | Chat | Unificar en |
|---|---|---|---|
| `!isFixed` | "Optimizable" | "Horario Flexible" | **"Flexible"** |
| días de una fija | "Días programados" | "Días asignados" | **"Días"** |
| partición | "Horario"/"turno"/"capas"/"bloques horarios" | "Planificación propuesta" | **"Turno"** |
| `travelTo` | "Viaje antes" / "Traslado:" | — | **"Traslado"** |
| `"media"` | "Normal" (dificultad) / "Media" (prioridad) | — | **"Media"** |
| miércoles | "X" (paso 2) / "Mié" (paso 3) | — | **"Mié"** |

Corregir `"Confirmá"` (voseo, `SummaryStep.tsx:107`).

### Principio 7 — Reconectar los dos caminos

`ChooseModeStep` (código muerto) revela que el puente existió y se abandonó. Reponerlo bidireccional: **"Prefiero decírselo a Sapo"** en el wizard, **"Ajustar detalles"** en la tarjeta del chat.

### Archivos

Reescritos: `CreateActivityView.tsx` (933→~400 líneas), `NameIdentityStep.tsx` → `WhatAndWhenStep.tsx`, `SummaryStep.tsx` → reusa `ActivityProposalCard`.

`TimePartitionForm.tsx` (967 líneas, el archivo más grande del repo) se parte: el caso simple queda en el paso 1; turnos múltiples, traslado y ventana preferida van a `AdvancedOptionsSheet.tsx`. Eso deshace los **seis `useState` de visibilidad de pickers** y el `ScrollView` anidado dentro de otro dentro de un sheet con `PanResponder`.

Borrar: `PriorityDeadlineStep.tsx`, `ChooseModeStep.tsx`, `NLInputStep.tsx`, `NLSummaryStep.tsx` (~750 líneas muertas), el `CustomCalendar` duplicado y los ~180 líneas de estilos `nl*` huérfanos en `CreateActivityView.tsx:843-931`.

---

## Fase 5 — Corte y limpieza del asistente (1-2 días)

Con la Fase 3 validada en dispositivo: quitar el flag; eliminar `parse_conversational()` (`llm_parser_service.py:277-794`, ~520 líneas) y la ruta vieja; **conservar `parse()` y `_build_few_shot_prompt()`** (líneas 36-273).

Barrer código muerto del backend: `infrastructure/adapters/outbound/persistence/` completo (3 archivos que **ni siquiera importarían** — `sqlalchemy` no está en `requirements.txt`), `gemini_llm_adapter.py` y `groq_llm_adapter.py` (no cableados, ~96 líneas duplicadas del adapter real, con 323 líneas de tests sobre código muerto), `dependencies.py`, `domain_to_actividad_request()` en `mappers.py:45-66`.

Frontend: `AsyncStorageActivityRepository.ts`, `PopUpAlert`/`ChipGroup`/`SelectableCard` (0 referencias), el chequeo `isLight` de `HomeView.tsx:81` que nunca es true.

También: los 19 errores de `tsc` son casi todos `createStyles = (colors) =>` sin tipar. Es un barrido mecánico que vale la pena hacer aquí.

---

## Fase 6 — Ciclo de recompensa (3-4 días) · prerequisito de la mascota

**Sin esto no hay engagement ni mascota que valga.** Hoy **no se puede marcar una actividad como completada** — no hay campo `completada` ni en el backend ni en Supabase. Sin ese evento no hay rachas, ni progreso, ni celebración, y **no hay nada que la mascota pueda festejar**. Duo funciona porque hay un "terminaste la lección".

1. **Completar actividades.** Campo `completed_at` en Supabase + método en la entidad `Activity` + checkbox/swipe en `HomeView` y `ScheduleView`.
2. **Rachas.** Días consecutivos con ≥1 actividad completada. Badge en el header de Home.
3. **Progreso diario.** Anillo o barra "3 de 5 completadas hoy".
4. **Feedback inmediato:** `expo-haptics` en cada acción significativa (Fase 0 añadió el primero de verdad, en el guardado del wizard); confetti al completar el día; sonido opcional (requiere `expo-audio`).
5. **Notificaciones de re-enganche.** Ya existe `ExpoNotificationScheduler` con recordatorios semanales. Añadir resumen matutino y aviso de racha en riesgo.
6. **Rescatar `StatsView`** — hoy es un placeholder de 49 líneas comentado del navigator (`AppNavigator.tsx:43,64`).

---

## Fase 7 — Mascota Lottie (3-5 días + producción del arte)

El arte aún no existe. Para no bloquearse: **construir el componente con su máquina de estados ahora, stubbeado con el sapo actual, y soltar los `.json` cuando estén.**

`src/presentation/components/atoms/Mascot/Sapo.tsx`:
```ts
type SapoState = 'idle' | 'thinking' | 'happy' | 'celebrating' | 'sad' | 'sleeping' | 'waving';
```
Instalar `lottie-react-native` y `react-native-reanimated` (hoy **no está instalado**, y es lo que da vida a todo lo demás).

**Set mínimo a producir (7 `.json`):**

| Estado | Disparador | Duración | Loop |
|---|---|---|---|
| `idle` | reposo en Home y chat | 2-3s | sí |
| `thinking` | esperando al asistente | 1s | sí |
| `happy` | actividad completada | 1.5s | no |
| `celebrating` | día completado / racha nueva | 2.5s | no |
| `sad` | racha perdida | 2s | no |
| `sleeping` | de noche, sin pendientes | 3s | sí |
| `waving` | onboarding y primer saludo | 2s | no |

**Spec para el arte:** exportar desde After Effects con Bodymovin; sin expresiones ni efectos no soportados (solo transform, path, trim paths); 512×512 px, 30fps; **cada `.json` bajo 150 KB**; paleta limitada a los colores del tema para poder recolorear. Verificar en lottiefiles.com/preview antes de integrar.

**Assets actuales:** `sapoBase64.ts` es un PNG de **89×101 px** como data URI (pixelado en pantallas modernas) y `sapo.svg` está suelto en la raíz sin usar. Consolidar en `assets/mascot/`.

**Dónde aparece:** Home (reacciona al progreso), chat (`thinking` reemplaza el `TypingIndicator` con delay artificial de 800ms de `NLConversationStep.tsx:98-111`), celebración al completar, onboarding y estados vacíos.

---

## Fase 8 — Atractivo visual (4-6 días)

- **Tokens de diseño.** Hoy hay **95 colores hex hardcodeados** fuera de `theme/colors.tsx`, **59 `rgba()` literales** y **cero** tokens de spacing, radius y tipografía. Crear `theme/tokens.ts` y migrar por pantalla.
- **Arreglar el sistema de temas.** Conviven un `ThemeProvider` reactivo y un objeto `Theme` estático mutado in-place con `Object.assign` (`colors.tsx:176-215`) — el propio comentario admite que los componentes que lo importan no se actualizan. `AppNavigator.tsx:225,228` lo usa en un `StyleSheet.create` de módulo, así que el splash y la tab bar se congelan en el tema por defecto.
- **Temas de verdad.** Los 4 presets comparten exactamente los mismos fondos (`#2C2E3C`/`#34364A`/`#40425A`) y solo cambian el acento. Añadir un tema claro real y `prefers-color-scheme`. (Fase 0 alineó `app.json` con la realidad dark-only; esto es lo que lo convierte en una decisión y no en una limitación.)
- **Fuente custom.** No hay ninguna (`fontFamily`: 0 resultados en `src/`); todo usa la del sistema con pesos `800`/`900`.
- **Movimiento.** Con Reanimated ya instalado: entradas escalonadas de listas, skeletons en vez de spinners, micro-interacción de escala en botones.
- **Romper los archivos gigantes.** Los 6 mayores suman 5.042 líneas = **25% de todo `src/`**. Entre 40% y 60% de cada uno es un `createStyles()` al final — extraerlos a `.styles.ts` es mecánico.

---

# VERIFICACIÓN

**Fase 0 (hecho):** ver baselines arriba.

**Fases 1-3 — conversaciones doradas.** Verificación central. Fixtures YAML en `ikeep-backend/tests/golden/`, corridas primero contra un `FakeConversationalAdapter` scripteado (CI, determinista) y luego contra el modelo real (`scripts/eval_assistant.py`, N=3, fuera de CI).

12 casos mínimos: acumulación multi-turno · corrección tardía conservando duración · delegación de horario · consulta *"¿qué tengo mañana?"* · eliminación · eliminación ambigua con 2 matches · regeneración · solapamiento con confirmación previa · múltiples actividades en un turno · charla off-topic · traslado (`travelTo=0`, no `null`) · *"toda la tarde"* → `840-1200`.

El aserto que hoy fallaría siempre:
```yaml
- usuario: "los martes"
  espera:
    draft_conserva: ["name", "activityType"]   # ← el test del "se olvida"
```

**No assertar el texto exacto** de las preguntas: se rompe con cada cambio de prompt y no protege nada. El contrato es el **draft resultante** y las **tools invocadas**. Umbral de merge: ≥90% pass@3.

**Fase 4 — wizard.** Prueba de recorrido cronometrada: crear *"álgebra, martes 10-12"* contando taps (objetivo ≤6, hoy ~14). Editar solo el nombre (objetivo 2 taps, hoy 5 + riesgo de bloqueo). Crear con conflicto y verificar error inline persistente. Cerrar a medias y reabrir → el borrador vuelve. Round-trip de una fija con prioridad "baja" → sigue siendo "baja".

**Fases 6-8:** verificación en dispositivo real (dev build), no solo simulador — Lottie, haptics y notificaciones se comportan distinto. Perfilar 60fps en gama media.

---

# RESUMEN DE PRIORIDADES

| Orden | Trabajo | Estado |
|---|---|---|
| 1 | Fase 0 — higiene, seguridad y quick wins | ✅ **Completa** (sin commitear) |
| 2 | Fases 1-2 — arregla el "se olvida" de raíz | ⬅️ **Siguiente** |
| 3 | Fase 3 — casos de uso nuevos + descubrimiento | Pendiente |
| 4 | Fase 4 — rediseño del wizard | Pendiente |
| 5 | Fase 6 — ciclo de recompensa | Pendiente |
| 6 | Fase 7 — mascota | Pendiente |
| 7 | Fases 5 y 8 — limpieza y pulido | Continuo |

Si solo pudieras hacer cuatro cosas: **turnos verbatim con `actualizar_borrador`** · **agenda en JSON con ids** · **un solo eje de decisión en el wizard** · **marcar actividades como completadas**.

---

# ESTADO AL 2026-08-11

| Fase | Estado | Nota |
|---|---|---|
| 0 — Higiene | ✅ | |
| 0.5 — El backend manda sobre los datos | ✅ | No estaba en el plan original |
| 1 — Motor conversacional | ✅ | 12 conversaciones doradas |
| 2 — Cliente del asistente | ✅ | `USA_ASISTENTE_V2` encendido |
| 3 — Casos de uso y descubrimiento | ✅ salvo `AgendaAnswerCard` | Ver abajo |
| 4 — Rediseño del wizard | ✅ | Los 7 principios; 4 pasos → 2 |
| 5 — Corte y limpieza | 🟡 parcial | Solo lo seguro. Ver abajo |
| 6 — Ciclo de recompensa | 🟡 el núcleo | Completar, racha y progreso |
| 7 — Mascota | ⏸️ congelada | Migración a Rive, decisión del usuario |
| 8 — Atractivo visual | 🟡 los cimientos | Tokens y arreglo del tema |

## Lo que queda, y por qué

**`AgendaAnswerCard` (Fase 3)** — no se puede construir con el contrato de hoy:
`ConversarResponse` devuelve texto, no una agenda estructurada. Haría falta que
`consultar_agenda` suba su resultado a la respuesta. Mientras tanto el
asistente contesta en prosa, que funciona.

**Corte del asistente viejo (Fase 5)** — el plan lo condiciona a "Fase 3
validada en dispositivo", y eso no pasó. Quitar el flag ahora dejaría sin
camino de vuelta. Lo seguro sí se hizo: mapper y paquete de persistencia
muertos, y los 15 errores de `tsc` bajaron a **0**.

**Fase 6** — el núcleo está: tabla `activity_completions`, endpoints de
`/api/v1/logros`, racha con sus reglas de borde, progreso del día y la casilla
en Home. Faltan confeti, notificaciones de re-enganche y rescatar `StatsView`.

Sobre el plan original: pedía un campo `completed_at` en `activities`. **No
sirve** — una actividad es una definición recurrente, así que marcarla el
martes la dejaría completada para siempre y el jueves no habría nada que
completar. Se hizo con una fila por (actividad, día), que es lo que además
permite calcular la racha.

**Fase 8** — están los cimientos: `theme/tokens.ts` y la eliminación del objeto
`Theme` estático que se congelaba en el preset por defecto. Falta migrar los 95
hex sueltos, el tema claro de verdad, la fuente custom y el movimiento — esto
último espera a que entre Reanimated con Rive.

## Hallazgos que no estaban en el plan

**Las horas viajan en UTC pero significan local.** Los turnos se guardan como
texto ISO; el cliente los lee con `getHours()`, que da hora local, así que el
ciclo cierra mientras todo pase por el teléfono. En cuanto el servidor los lee,
son cinco horas de corrimiento en UTC-5. Por eso `/aplicar` y `/logros` exigen
la fecha o el desfase del cliente en vez de suponerlos. `GET /energia/hoy`
sigue con el bug, usando medianoche UTC.

**El modelo afirmaba haber hecho cosas que no hizo.** Nada se guarda hasta que
el usuario confirma una propuesta, así que "quedó actualizada" en un turno sin
propuesta es falso por construcción. Se detecta y se corrige en código
(`domain/services/assistant/text.py`), no en el prompt — el prompt ya prohibía
markdown y el modelo lo escribía igual.

**El ejecutor era el frontend.** Confirmar en el chat disparaba tres viajes de
red y compensaba a mano en un store de Zustand. Ahora hay
`POST /api/v1/asistente/aplicar`, detrás de `USA_APLICAR_EN_BACKEND` (apagado).

## Pendiente fuera del código

- Aplicar la migración `20260811090000_activity_completions.sql` en Supabase.
- Cronjob a `/health` cada 10 min (arranque en frío medido: **51,3 s**).
- Encender `USA_APLICAR_EN_BACKEND` tras probar en dispositivo.
- Medir Cerebras y Groq con las conversaciones doradas: el orden de failover
  sigue sin justificarse con datos.
- Diagnosticar el 500 de `PUT /api/v1/horario` (falta la línea del log).
