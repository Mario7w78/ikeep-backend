# ikeep-backend

Backend del sistema **IKEEP** — optimización de horarios académicos usando Google OR-Tools CP-SAT con arquitectura hexagonal (Ports & Adapters).

---

## Tabla de Contenidos

- [Arquitectura](#arquitectura)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Setup](#setup)
- [Servicios](#servicios)
  - [1. ScheduleOptimizer (`generar`)](#1-scheduleoptimizer-generar)
  - [2. RescheduleService (`replanificar`)](#2-rescheduleservice-replanificar)
  - [3. SuggestService (`sugerir`)](#3-suggestservice-sugerir)
- [API Endpoints](#api-endpoints)
  - [GET /health](#get-health)
  - [POST /api/v1/horarios/generar](#post-apiv1horariosgenerar)
  - [POST /api/v1/horarios/replanificar](#post-apiv1horariosreplanificar)
  - [POST /schedule/suggest-task](#post-schedulesuggest-task)
- [Sistema de Restricciones](#sistema-de-restricciones)
  - [Restricciones Duras (RD)](#restricciones-duras-rd)
  - [Restricciones Blandas (RB)](#restricciones-blandas-rb)
- [Validaciones](#validaciones)
- [Diagrama de Flujo](#diagrama-de-flujo)

---

## Arquitectura

```
 ┌─────────────────────────────────────────────────┐
 │                    FastAPI                       │
 │  (routers, DTOs, DI, mappers)                   │
 ├─────────────────────────────────────────────────┤
 │               Domain Services                   │
 │  ScheduleOptimizer │ RescheduleService          │
 │  SuggestService                                 │
 ├─────────────────────────────────────────────────┤
 │          Domain Entities + Ports                 │
 │  (dataclasses, interfaces abstractas)            │
 ├─────────────────────────────────────────────────┤
 │          Infrastructure Adapters                │
 │  SQLAlchemy │ httpx │ Settings                   │
 └─────────────────────────────────────────────────┘
```

**Principios:**
- **Hexagonal**: `domain/` no importa nada de `infrastructure/` ni `schemas/`
- **DTOs vs Entidades**: `schemas/` usan Pydantic (validación HTTP), `domain/entities/` usan dataclasses (lógica pura)
- **Mappers**: `infrastructure/adapters/inbound/api/mappers.py` convierte entre ambos mundos
- **DI**: `infrastructure/adapters/inbound/api/dependencies.py` inyecta servicios en los routers

---

## Estructura del Proyecto

```
ikeep-backend/
├── main.py                          # Entry point, create_app()
├── requirements.txt
├── .env                             # Variables de entorno (no versionar)
│
├── domain/
│   ├── entities/
│   │   ├── enums.py                 # EstadoSolucion, TipoActividad, Dificultad
│   │   ├── activity.py             # Actividad (dataclass)
│   │   ├── location.py             # Ubicacion (dataclass)
│   │   ├── user_context.py         # ContextoUsuario, BloqueSueno
│   │   ├── travel_time.py          # TiempoTraslado
│   │   ├── schedule_request.py     # SolicitudHorario
│   │   ├── schedule_response.py    # BloqueTiempo, RespuestaHorario
│   │   └── reschedule_request.py   # SolicitudReplanificacion
│   ├── ports/
│   │   ├── inbound/
│   │   │   ├── scheduler_port.py   # AbstractSchedulerService
│   │   │   └── reschedule_port.py  # AbstractRescheduleService
│   │   └── outbound/
│   │       ├── actividad_repository_port.py
│   │       └── clima_api_port.py
│   └── services/
│       ├── schedule_service.py     # ScheduleOptimizer (~545 líneas)
│       ├── reschedule_service.py   # RescheduleService
│       └── suggest_service.py      # SuggestService
│
├── infrastructure/
│   ├── config/
│   │   └── settings.py             # Pydantic Settings (.env)
│   └── adapters/
│       ├── inbound/api/
│       │   ├── dependencies.py     # get_scheduler_service, get_reschedule_service
│       │   ├── mappers.py          # solicitud_to_domain, reschedule_to_domain, etc.
│       │   └── v1/
│       │       ├── health_router.py
│       │       ├── schedule_router.py
│       │       ├── reschedule_router.py
│       │       └── suggest_router.py
│       └── outbound/
│           ├── external/clima_api.py   # Cliente httpx para API climática
│           └── persistence/
│               ├── database.py         # SQLAlchemy engine + session
│               ├── orm_models.py       # ActividadModel (SQLAlchemy)
│               └── actividad_repository.py
│
└── schemas/
    ├── activity.py                # Actividad, TipoActividad, Dificultad (Pydantic)
    ├── location.py                # Ubicacion
    ├── user_context.py            # ContextoUsuario, BloqueSueno
    ├── travel_time.py             # TiempoTraslado
    ├── schedule_request.py        # SolicitudHorario
    ├── schedule_response.py       # BloqueTiempo, RespuestaHorario
    ├── reschedule_request.py      # SolicitudReplanificacion
    └── suggest_task.py            # SugerirTareaRequest, SugerenciaTarea, SugerirTareaResponse
```

---

## Setup

```bash
# 1. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar .env
cat > .env <<EOF
DATABASE_URL=sqlite:///./ikeep.db
ROUTES_API_KEY=tu_api_key
SCHEDULER_TIMEOUT=10
EOF

# 4. Ejecutar
uvicorn main:app --reload --port 8000
```

---

## Servicios

### 1. ScheduleOptimizer (`generar`)

**Archivo:** `domain/services/schedule_service.py`

Servicio principal. Usa Google OR-Tools CP-SAT para modelar y resolver el problema de scheduling como un programa de optimización con restricciones.

**Flujo paso a paso:**

```
SolicitudHorario
       │
       ▼
┌─────────────────────────────┐
│ 1. Validaciones             │  ← pre-solver
│   • Actividades fijas       │
│     no solapadas            │
│   • Tareas caben            │
│     en horario disponible   │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ 2. Construir travel_lookup  │  ← matriz { (origen, destino): minutos }
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ 3. Variables de decisión    │
│   Por cada tarea flexible:  │
│   • start_i (integer)       │
│   • end_i = start_i + dur   │
│   • presence_i_d (bool x día)│
│     → sum(presence) == 1    │
│   • interval_i_d (optativo) │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ 4. Restricciones duras      │  ← RD-01 a RD-07
│   • RD-01: NoOverlap        │
│   • RD-02: Fixed activities │
│     (intervalos fijos)      │
│   • RD-03: Ubicaciones      │
│   • RD-04: Traslados        │
│     (gap mínimo entre acts) │
│   • RD-05: Horario activo   │
│   • RD-06: Bloques sueño    │
│   • RD-07: Descanso mínimo  │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ 5. Restricciones blandas    │  ← RB-01 a RB-10
│   • Variables de violación  │  (con penalización)
│   • model.Minimize(         │
│       Σ weight_i * viol_i)  │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ 6. Solver OR-Tools          │
│   max_time_in_seconds       │
│   Solve(model)              │
└─────────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ 7. Build Response           │
│   • Leer valores del solver │
│   • Insertar bloques viaje  │
│   • Ordenar por día/hora    │
└─────────────────────────────┘
       │
       ▼
RespuestaHorario
```

**Manejo de resultados del solver:**

| Estado OR-Tools | Estado Response | HTTP |
|---|---|---|
| `OPTIMAL` | `OPTIMA` | 200 |
| `FEASIBLE` | `FACTIBLE` | 200 |
| `INFEASIBLE` | `INFACTIBLE` | 409 |
| `UNKNOWN` (timeout) | `DESCONOCIDO` | 409 |

---

### 2. RescheduleService (`replanificar`)

**Archivo:** `domain/services/reschedule_service.py`

Permite re-optimizar el horario cuando una actividad se ve afectada (ej: se cancela una clase y se libera tiempo).

**Flujo paso a paso:**

```
SolicitudReplanificacion
  • horario_actual: RespuestaHorario  (bloques ya generados)
  • actividad_afectada_id: str         (cuál se elimina)
  • tiempo_perdido_minutos: int        (tiempo extra disponible)
  • contexto_usuario: ContextoUsuario
       │
       ▼
┌──────────────────────────────────┐
│ 1. Reconstruir SolicitudHorario  │
│                                  │
│   Por cada bloque en             │
│   horario_actual:                │
│                                  │
│   a) Si es el bloque afectado:   │
│      • NO lo incluye             │
│      • Agrega una tarea flexible │
│        con duración =             │
│        duración original +        │
│        tiempo_perdido_minutos     │
│      • Marca como TAREA          │
│                                  │
│   b) Si es bloque de viaje:      │
│      • LO SALTEA                 │
│                                  │
│   c) Si es otro bloque fijo:     │
│      • Lo incluye como           │
│        actividad fija            │
│      (id, nombre, tipo, dia,     │
│       inicio, fin, ubicación)    │
│                                  │
│   d) Si es otro bloque           │
│      flexible:                   │
│      • Lo incluye como           │
│        actividad fija también    │
│        (para mantenerlo donde    │
│        estaba)                    │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│ 2. Delegar en ScheduleOptimizer  │
│    optimizer.generar(nueva_solic)│
└──────────────────────────────────┘
       │
       ▼
RespuestaHorario
```

**Ejemplo de uso:** Si "Clase de Matemáticas" de 2h se cancela, se puede llamar a replanificar con `actividad_afectada_id="mat1"` y `tiempo_perdido_minutos=120` para que el optimizador reubique ese tiempo en otra tarea.

---

### 3. SuggestService (`sugerir`)

**Archivo:** `domain/services/suggest_service.py`

Algoritmo heurístico liviano (sin OR-Tools) que sugiere qué tareas pendientes encajan en un bloque de tiempo libre.

**Flujo paso a paso:**

```
SugerirTareaRequest
  • tiempo_libre_minutos: int
  • tareas_pendientes: list[Actividad]
       │
       ▼
┌──────────────────────────────┐
│ Por cada tarea pendiente:    │
│                              │
│ ¿duración <= tiempo_libre?   │
│   ├── Sí → encaja=True       │
│   │        razón: "Duración  │
│   │        adecuada..."      │
│   │                          │
│   └── No → encaja=False      │
│            razón: "Necesita  │
│            X min, disponible │
│            solo Y min"       │
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ Ordenar resultado:           │
│ 1° Las que encajan (True)    │
│ 2° Mayor prioridad           │
│ 3° Menor duración            │
│ 4° Dentro del día preferido  │
└──────────────────────────────┘
       │
       ▼
SugerirTareaResponse
  • sugerencias: list[SugerenciaTarea]
```

---

## API Endpoints

### GET /health

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "version": "1.0.0"}
```

---

### POST /api/v1/horarios/generar

Genera un horario optimizado a partir de actividades fijas, tareas pendientes, ubicaciones y contexto del usuario.

**Request:**
```json
{
  "actividades_fijas": [
    {
      "id": "mat1",
      "nombre": "Matematicas",
      "tipo": "clase",
      "dia": 1,
      "hora_inicio": 480,
      "hora_fin": 540,
      "ubicacion_id": "aula101",
      "prioridad": 1,
      "duracion_estimada": 60,
      "dificultad": "media"
    }
  ],
  "tareas_pendientes": [
    {
      "id": "prog1",
      "nombre": "Programacion",
      "tipo": "trabajo",
      "dia": 3,
      "hora_inicio": 0,
      "hora_fin": 0,
      "ubicacion_id": "casa",
      "prioridad": 2,
      "duracion_estimada": 120,
      "dificultad": "media"
    }
  ],
  "ubicaciones": [
    {"id": "aula101", "nombre": "Aula 101", "latitud": -33.456, "longitud": -70.648},
    {"id": "casa", "nombre": "Casa", "latitud": -33.440, "longitud": -70.660}
  ],
  "tiempos_traslado": [
    {"origen_id": "aula101", "destino_id": "casa", "tiempo_estimado_minutos": 30}
  ],
  "contexto_usuario": {
    "nivel_energia": 5,
    "horario_inicio": 420,
    "horario_fin": 1080,
    "bloques_sueno": [
      {"dia": 1, "inicio": 0, "fin": 420}
    ]
  }
}
```

**Response (200 OPTIMA):**
```json
{
  "estado": "OPTIMA",
  "bloques": [
    {
      "id_actividad": "mat1",
      "nombre": "Matematicas",
      "tipo": "clase",
      "dia": 1,
      "hora_inicio": 480,
      "hora_fin": 540,
      "ubicacion_id": "aula101"
    },
    {
      "id_actividad": "viaje_mat1_prog1",
      "nombre": "Viaje a Programacion",
      "tipo": "trabajo",
      "dia": 1,
      "hora_inicio": 540,
      "hora_fin": 570,
      "ubicacion_id": "aula101"
    },
    {
      "id_actividad": "prog1",
      "nombre": "Programacion",
      "tipo": "trabajo",
      "dia": 3,
      "hora_inicio": 480,
      "hora_fin": 600,
      "ubicacion_id": "casa"
    }
  ],
  "mensaje": ""
}
```

**Response (409 INFACTIBLE):**
```json
{
  "detail": "No se encontró una solución con las restricciones actuales. Verifica que las actividades fijas no solapen los bloques de sueño, que haya tiempo disponible para cada tarea, y que el horario activo tenga suficiente capacidad."
}
```

**Response (409 DESCONOCIDO — timeout):**
```json
{
  "detail": "El optimizador no encontró solución en 5s. Reduce la cantidad de tareas o aumenta el tiempo límite."
}
```

---

### POST /api/v1/horarios/replanificar

Re-planifica el horario cuando una actividad se ve afectada (se elimina y su tiempo se redistribuye).

**Request:**
```json
{
  "horario_actual": {
    "estado": "OPTIMA",
    "mensaje": "",
    "bloques": [
      {"id_actividad": "mat1", "nombre": "Matematicas", "tipo": "clase", "dia": 1, "hora_inicio": 480, "hora_fin": 540, "ubicacion_id": "aula101"},
      {"id_actividad": "prog1", "nombre": "Programacion", "tipo": "trabajo", "dia": 3, "hora_inicio": 480, "hora_fin": 600, "ubicacion_id": "casa"}
    ]
  },
  "actividad_afectada_id": "prog1",
  "tiempo_perdido_minutos": 60,
  "contexto_usuario": {
    "nivel_energia": 5,
    "horario_inicio": 420,
    "horario_fin": 1080,
    "bloques_sueno": []
  }
}
```

---

### POST /schedule/suggest-task

Sugiere qué tareas pendientes encajan en un bloque de tiempo libre.

**Request:**
```json
{
  "tiempo_libre_minutos": 90,
  "tareas_pendientes": [
    {"id": "t1", "nombre": "Proyecto Final", "tipo": "trabajo", "dia": 0, "hora_inicio": 0, "hora_fin": 0, "prioridad": 1, "duracion_estimada": 180, "dificultad": "alta"},
    {"id": "t2", "nombre": "Leer Capitulo 3", "tipo": "tarea", "dia": 0, "hora_inicio": 0, "hora_fin": 0, "prioridad": 3, "duracion_estimada": 45, "dificultad": "baja"},
    {"id": "t3", "nombre": "Ejercicios Algebra", "tipo": "trabajo", "dia": 0, "hora_inicio": 0, "hora_fin": 0, "prioridad": 2, "duracion_estimada": 60, "dificultad": "media"}
  ],
  "dia_preferido": 3
}
```

**Response:**
```json
{
  "sugerencias": [
    {
      "id_actividad": "t2",
      "nombre": "Leer Capitulo 3",
      "tipo": "tarea",
      "duracion_estimada": 45,
      "dificultad": "baja",
      "prioridad": 3,
      "encaja": true,
      "razon": "Tarea corta, ideal para aprovechar 90 min libres."
    },
    {
      "id_actividad": "t3",
      "nombre": "Ejercicios Algebra",
      "tipo": "trabajo",
      "duracion_estimada": 60,
      "dificultad": "media",
      "prioridad": 2,
      "encaja": true,
      "razon": "Duración adecuada para el tiempo disponible (60 ≤ 90 min)."
    },
    {
      "id_actividad": "t1",
      "nombre": "Proyecto Final",
      "tipo": "trabajo",
      "duracion_estimada": 180,
      "dificultad": "alta",
      "prioridad": 1,
      "encaja": false,
      "razon": "Necesita 180 min, pero solo hay 90 min disponibles."
    }
  ]
}
```

---

## Sistema de Restricciones

### Restricciones Duras (RD)

Deben cumplirse obligatoriamente. Si no es posible, el solver retorna `INFEASIBLE`.

| ID | Nombre | Implementación | Descripción |
|---|---|---|---|
| **RD-01** | No solapamiento | `_add_no_overlap()` → `model.AddNoOverlap(intervals)` | Ninguna actividad (fija, flexible, sueño, descanso) puede superponerse en el mismo día |
| **RD-02** | Actividades fijas | `_add_fixed()` → `model.AddFixedInterval()` | Las actividades con hora definida se modelan como intervalos fijos en el día exacto |
| **RD-03** | Ubicaciones | (en `_add_fixed` / `_add_flexible_task`) | Cada actividad tiene una `ubicacion_id` asociada |
| **RD-04** | Tiempo de traslado | `_add_travel_constraints()` → booleans de orden + gap mínimo | Si dos actividades en distinta ubicación están en el mismo día, `start_j ≥ end_i + travel_time`. Se generan bloques visibles `viaje_X_Y` en la respuesta |
| **RD-05** | Horario activo | `_add_sleep_blocks()` + rangos en tasks | Las actividades solo pueden programarse entre `horario_inicio` y `horario_fin` (por defecto 7:00–18:00 = 420–1080 min) |
| **RD-06** | Bloques de sueño | `_add_sleep_blocks()` → intervalos fijos | El usuario define rangos de sueño; el solver no puede colocar actividades ahí |
| **RD-07** | Descanso mínimo | `_add_rest_blocks()` → intervalos obligatorios | Al menos un bloque de 30 min de descanso por día activo |

### Restricciones Blandas (RB)

Se penalizan con pesos configurables. El solver minimiza la suma total de penalizaciones.

| ID | Nombre | Peso default | Descripción |
|---|---|---|---|
| **RB-01** | Energía vs Dificultad | 10 | Penaliza tareas difíciles (`ALTA`) en días con energía baja (< 4) |
| **RB-02** | Concentración | 8 | Penaliza si una tarea consume ≥ 80% del horario activo de un día |
| **RB-03** | Preferencia horaria | 6 | Penaliza tareas fuera del horario "ideal" del usuario (si está definido) |
| **RB-04** | Tiempo muerto | 4 | Penaliza gaps largos (> 60 min) entre actividades consecutivas |
| **RB-05** | Post-esfuerzo | 10 | Penaliza tareas exigentes después de turnos ≥ 4h continuas |
| **RB-06** | Desajuste duración | 5 | Penaliza si una tarea no llena adecuadamente el bloque asignado |
| **RB-08** | Carga consecutiva | 3 | Penaliza diferencias grandes de carga entre días consecutivos |
| **RB-09** | Cambios de ubicación | 7 | Penaliza múltiples cambios de ubicación en un mismo día |
| **RB-10** | Fecha límite | 9 | Penaliza postergar tareas con `fecha_limite` cercana |

---

## Validaciones

Antes de llamar al solver, el `ScheduleOptimizer` ejecuta dos validaciones tempranas:

### 1. Solapamiento de actividades fijas

**Método:** `_validate_fixed_overlaps()`

Verifica que no haya dos actividades fijas en el mismo día con horarios que se sobrepongan.

```
Error: Actividades fijas solapadas el día 1:
       'Mate' termina a las 540 min pero 'Fisica' empieza a las 530 min
```

**HTTP 422** — se rechaza antes de construir el modelo.

### 2. Duración vs capacidad diaria

**Método:** `_validate_task_duration()`

Verifica que ninguna tarea tenga duración mayor al horario activo disponible por día.

```
Error: La tarea 'Proyecto' dura 9999 min,
       pero el horario disponible es de solo 660 min/día
```

**HTTP 422** — se rechaza antes de construir el modelo.

### 3. Infactibilidad del modelo

Si el solver retorna `INFEASIBLE`, se devuelve un mensaje descriptivo:

```
HTTP 409: No se encontró una solución con las restricciones actuales.
          Verifica que las actividades fijas no solapen los bloques de sueño,
          que haya tiempo disponible para cada tarea,
          y que el horario activo tenga suficiente capacidad.
```

### 4. Timeout

Si el solver retorna `UNKNOWN` (excedió `max_time_in_seconds`):

```
HTTP 409: El optimizador no encontró solución en 5s.
          Reduce la cantidad de tareas o aumenta el tiempo límite.
```

El timeout se configura via `.env`:
```
SCHEDULER_TIMEOUT=10    # segundos
```

---

## Diagrama de Flujo

```
Cliente HTTP
     │
     ▼
┌─────────────────────────────────────────────────────┐
│                    FastAPI                           │
│                                                     │
│  POST /api/v1/horarios/generar                      │
│     │                                               │
│     ├─► schedule_router.py                          │
│     │     │                                         │
│     │     ├─► solicitud_to_domain(request)          │
│     │     │     (Pydantic → dataclass)              │
│     │     │                                         │
│     │     ├─► scheduler.generar(solicitud_domain)   │
│     │     │     │                                   │
│     │     │     ├─► validate_fixed_overlaps()        │
│     │     │     ├─► validate_task_duration()        │
│     │     │     │                                   │
│     │     │     ├─► Construir modelo CP-SAT         │
│     │     │     │   ├─ Variables de decisión        │
│     │     │     │   ├─ RD-01 a RD-07 (hard)         │
│     │     │     │   ├─ RB-01 a RB-10 (soft)         │
│     │     │     │   └─ Minimize(Σ pesos)            │
│     │     │     │                                   │
│     │     │     ├─► solver.Solve(model)             │
│     │     │     │                                   │
│     │     │     └─► _build_response()               │
│     │     │         ├─ Leer valores del solver      │
│     │     │         ├─ Insertar bloques de viaje    │
│     │     │         └─ Ordenar por día/hora         │
│     │     │                                         │
│     │     └─► HTTP response                         │
│     │         ├─ 200 OPTIMA / FACTIBLE             │
│     │         ├─ 409 INFACTIBLE / DESCONOCIDO      │
│     │         └─ 422 ValueError                    │
│     │                                               │
│  POST /api/v1/horarios/replanificar                 │
│     │                                               │
│     ├─► reschedule_router.py                        │
│     │     │                                         │
│     │     ├─► reschedule_to_domain(request)         │
│     │     ├─► reschedule.replanificar()             │
│     │     │     ├─► _to_actividad() (bloque → act) │
│     │     │     ├─► Reconstruir SolicitudHorario    │
│     │     │     └─► optimizer.generar()             │
│     │     └─► HTTP response                         │
│     │                                               │
│  POST /schedule/suggest-task                        │
│     │                                               │
│     ├─► suggest_router.py                           │
│     │     │                                         │
│     │     ├─► SuggestService.sugerir()              │
│     │     │     ├─► Filtrar por duración            │
│     │     │     ├─► Ordenar por prioridad+dif       │
│     │     │     └─► Devolver sugerencias            │
│     │     └─► HTTP 200                              │
│     │                                               │
│  GET /health                                        │
│     │                                               │
│     └─► health_router.py → {"status": "ok"}        │
│                                                     │
└─────────────────────────────────────────────────────┘
```
