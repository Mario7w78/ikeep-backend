# iKeep Scheduling API — Documentación Completa

## Índice

1. [Descripción General](#1-descripción-general)
2. [Modelo de Dominio](#2-modelo-de-dominio)
3. [OR-Tools CP-SAT: Motor de Optimización](#3-or-tools-cp-sat-motor-de-optimización)
4. [Restricciones y Penalidades](#4-restricciones-y-penalidades)
5. [Endpoints de la API](#5-endpoints-de-la-api)
6. [Guía de Uso para el Frontend](#6-guía-de-uso-para-el-frontend)
7. [Casos de Uso Típicos](#7-casos-de-uso-típicos)
8. [Manejo de Errores](#8-manejo-de-errores)

---

## 1. Descripción General

iKeep Scheduling es un **optimizador de horarios semanales** para estudiantes universitarios. Usa **Google OR-Tools CP-SAT** para asignar tareas flexibles a días y horarios óptimos, respetando restricciones duras (no solapamiento, traslados, sueño) y minimizando penalidades blandas que modelan **factores de estrés académico**.

### Arquitectura

```
FastAPI (schemas/) → Mappers (DTO↔Domain) → Domain Services (CP-SAT) → Response
```

El sistema tiene **4 endpoints** principales, **3 fases de features** (9 funcionalidades totales), y un modelo de optimización con **7 restricciones duras + 10 penalidades blandas**.

### Features por Fase

| Fase | Feature | Estado |
|------|---------|--------|
| 1 | Energy Pattern Override (patrón manual) | ✅ |
| 1 | Real Priority Weighting (RB-PRIORITY) | ✅ |
| 1 | Optional Day (`dia=None`) | ✅ |
| 2 | Day Range (`dia_desde/dia_hasta`) | ✅ |
| 2 | Permitted/Blocked Days (`dias_permitidos`) | ✅ |
| 2 | Anchor Tasks (`es_ancla`) | ✅ |
| 3 | Per-Day Active Hours (`horario_inicio/fin` por día) | ✅ |
| 3 | Rolling Week (`dia_inicio/dias_totales`) | ✅ |
| 3 | Partial Assignment (omitir tareas si es inviable) | ✅ |

---

## 2. Modelo de Dominio

### Actividad

Representa cualquier bloque en el horario: clase fija, tarea flexible, tarea ancla.

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `id` | `str` | — | Identificador único |
| `nombre` | `str` | — | Nombre legible |
| `tipo` | `"clase" \| "trabajo" \| "tarea"` | — | Tipo de actividad |
| `dia` | `int \| None` | `None` | **Deadline**: día tope (alias obsoleto de `dia_hasta`) |
| `dia_desde` | `int` | `0` | Primer día del rango (F2) |
| `dia_hasta` | `int` | `6` | Último día del rango (F2) |
| `dias_permitidos` | `list[int] \| None` | `None` | Subconjunto de días permitidos (F3) |
| `es_ancla` | `bool` | `False` | Si es ancla, día fijo + hora flexible (F5) |
| `hora_inicio` | `int` | — | Hora de inicio (minutos desde 00:00) |
| `hora_fin` | `int` | — | Hora de fin (minutos desde 00:00) |
| `ubicacion_id` | `str \| None` | `None` | Ubicación física |
| `prioridad` | `int` | `0` | Prioridad (mayor = más importante) |
| `duracion_estimada` | `int` | — | Minutos estimados (para tareas flexibles) |
| `fecha_limite` | `str \| None` | `None` | Fecha límite ISO (reservado) |
| `dificultad` | `"baja" \| "media" \| "alta"` | `"media"` | Dificultad de la tarea |

**Reglas de validación cruzada:**
- `dia` y `dia_hasta` no pueden enviarse juntos. Si se envía `dia`, se copia a `dia_hasta`.
- `0 <= dia_desde <= dia_hasta <= 6`
- `dias_permitidos`: cada valor entre 0-6, se deduplica automáticamente
- `es_ancla=True` requiere un día concreto (`dia` o `dia_desde == dia_hasta`). No puede tener múltiples `dias_permitidos`.

### ContextoUsuario

Describe al estudiante y su energía.

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `nivel_energia` | `int` | `2` | Nivel actual (0-4) |
| `horario_inicio` | `int \| list[int]` | `480` (8:00) | Inicio de horario activo por día |
| `horario_fin` | `int \| list[int]` | `1200` (20:00) | Fin de horario activo por día |
| `bloques_sueno` | `list[BloqueSueno]` | `[]` | Bloques de sueño fijos |
| `historial_energia` | `list[RegistroEnergia]` | `[]` | Historial de últimos 14 días |
| `patron_energia_manual` | `str \| None` | `None` | Override manual del patrón |

**Sobre horario_inicio/horario_fin:**
- Puede ser un solo `int` (se expande a todos los días) o una `list[int]` con un valor por día.
- Si se usa rolling week, la longitud de la lista debe coincidir con `dias_totales`.
- Cada valor: `0 <= horario_inicio[i] < horario_fin[i] <= 1440`.

### BloqueSueno

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `dia` | `int` | Día de la semana |
| `inicio` | `int` | Minuto de inicio |
| `fin` | `int` | Minuto de fin |

### RegistroEnergia

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `timestamp` | `str` | ISO 8601 |
| `nivel` | `int` | Nivel de energía (0-4) |
| `dia_semana` | `int` | Día de la semana |
| `contexto` | `str \| None` | Contexto opcional |

### SolicitudHorario (Request de /generar)

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `actividades_fijas` | `list[Actividad]` | — | Clases y eventos fijos |
| `tareas_pendientes` | `list[Actividad]` | — | Tareas a programar |
| `ubicaciones` | `list[Ubicacion]` | `[]` | Ubicaciones para cálculos de traslado |
| `tiempos_traslado` | `list[TiempoTraslado]` | `[]` | Tiempos de traslado conocidos |
| `contexto_usuario` | `ContextoUsuario` | — | Contexto del estudiante |
| `dia_inicio` | `int` | `0` | Primer día de la ventana (F8) |
| `dias_totales` | `int` | `7` | Cantidad de días (F8) |

### RespuestaHorario (Response)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `estado` | `str` | `"OPTIMA" \| "FACTIBLE" \| "INFACTIBLE" \| "DESCONOCIDO"` |
| `bloques` | `list[BloqueTiempo]` | Bloques asignados (fijos + flexibles) |
| `mensaje` | `str` | Mensaje legible |
| `recomendaciones` | `list[str]` | Sugerencias (solo INFACTIBLE) |
| `tareas_omitidas` | `list[str]` | IDs de tareas que no se pudieron programar (F9) |

### BloqueTiempo

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id_actividad` | `str` | ID de la actividad |
| `nombre` | `str` | Nombre |
| `tipo` | `str` | Tipo |
| `dia` | `int` | Día asignado |
| `hora_inicio` | `int` | Minuto de inicio |
| `hora_fin` | `int` | Minuto de fin |
| `ubicacion_id` | `str \| None` | Ubicación |

---

## 3. OR-Tools CP-SAT: Motor de Optimización

### Qué usamos de CP-SAT

| Componente OR-Tools | Uso en el sistema | Líneas clave |
|---------------------|-------------------|--------------|
| `CpModel` | Modelo principal de optimización | `service.py:61` |
| `CpSolver` | Solver con timeout configurable | `service.py:128-134` |
| `NewBoolVar` | Variable por tarea×día: `p_{task}_{day}` (¿se asigna?) | `service.py:263` |
| `NewIntVar` | Variables de hora de inicio/fin por tarea×día | `service.py:264-265` |
| `NewIntervalVar` | Intervalo opcional (tarea en día y hora) | `service.py:266` |
| `NewOptionalIntervalVar` | Intervalo condicional a BoolVar (para tareas flexibles) | `service.py:266` |
| `NewConstant` | Valores fijos (actividades fijas con hora conocida) | `service.py:177-178` |
| `Add` | Restricciones lineales (==, <=, >=) | Todo el modelo |
| `AddNoOverlap` | RD-01: no solapamiento de intervalos | `service.py:104` |
| `Add(sum(all_p) <= 1)` | RD-05: cada tarea en exactamente 0 o 1 día (F9) | `service.py:272` |
| `OnlyEnforceIf` | Activación condicional de restricciones | `service.py:276-277` |
| `Minimize` | Función objetivo: suma de penalidades | `service.py:131` |
| `solver.Value()` | Lectura de resultado | `service.py:755,803` |
| `max_time_in_seconds` | Timeout del solver | `service.py:129` |
| `OPTIMAL / FEASIBLE / INFEASIBLE / UNKNOWN` | Estados de solución | `service.py:685-689` |

### Concepto del Modelo

**Timeline absoluto:** Todo se convierte a minutos absolutos desde el inicio de la semana (0-10079). Un intervalo que cruza la medianoche (ej: 23:00-01:00) se maneja correctamente porque `abs_duration()` suma 1440 cuando `hora_fin <= hora_inicio`.

**Variables por tarea flexible:**
- Para cada tarea `t` y cada día `d` en su rango válido:
  - `p_{t}_{d}` (BoolVar): 1 si la tarea se asigna al día `d`
  - `s_{t}_{d}` (IntVar): minuto de inicio dentro del horario activo del día
  - `e_{t}_{d}` (IntVar): minuto de fin
  - `iv_{t}_{d}` (OptionalIntervalVar): intervalo que existe solo si `p_{t}_{d} == 1`

**RD-05:** `sum(all_p) <= 1` — cada tarea se asigna a **0 o 1** día (con F9). Sin F9 (omitido=0), el solver nunca omite porque la penalidad es infinita, pero con `omitido > 0` puede saltear tareas.

**Variables de omisión (F9):**
- `omit_{t}` (BoolVar): 1 si la tarea no se programa
- `omit == 1 ⇔ sum(all_p) == 0`
- Penalidad: `omitido_weight * duracion` si se omite

### PenaltyWeights (Configuración del Optimizador)

| Peso | Default | Penalidad |
|------|---------|-----------|
| `rb_01` | 10 | Tareas difíciles × energía baja |
| `rb_02` | 8 | Concentración de horas en un día |
| `rb_03` | 6 | Fuera del horario preferido |
| `rb_04` | 4 | Tiempo muerto (idle) |
| `rb_05` | 10 | Tarea difícil post-esfuerzo |
| `rb_06` | 5 | Desajuste duración/bloque |
| `rb_08` | 3 | Diferencia entre días consecutivos |
| `rb_09` | 7 | Múltiples cambios de ubicación |
| `rb_10` | 9 | Postergar tareas con deadline |
| `rb_priority` | 0 | Prioridad real (desactivado por defecto) |
| `omitido` | 100000 | Penalidad por omitir tarea (× duración) |

---

## 4. Restricciones y Penalidades

### Restricciones Duras (RD) — Siempre se cumplen

| Código | Nombre | Descripción |
|--------|--------|-------------|
| **RD-01** | No solapamiento | Dos intervalos no pueden superponerse en el timeline absoluto. Implementado con `model.AddNoOverlap()`. |
| **RD-02** | Actividades fijas | Las actividades fijas se colocan en su día y hora exactos. Tienen `dia` obligatorio. |
| **RD-03** | Sueño respetado | Los bloques de sueño son inamovibles y no se solapan con ninguna actividad. |
| **RD-04** | Traslados | Si dos actividades consecutivas tienen distinta ubicación, debe haber tiempo suficiente entre ellas para el traslado. |
| **RD-05** | Asignación única | Cada tarea flexible se asigna a **exactamente 1 día** (o 0 si F9 permite omitir). `sum(all_p) <= 1`. |
| **RD-06** | Sueño fijo | Bloques de sueño validados: duración ≤ 12h, no solapan con actividades fijas. |
| **RD-07** | Descanso diario | Se garantiza 1 bloque de descanso de 30 min por día dentro del horario activo. |

### Restricciones Blandas (RB) — Minimizadas en el objetivo

| Código | Peso | Nombre | Factor de Estrés | Fórmula |
|--------|------|--------|------------------|---------|
| **RB-01** | 10 | Energía × Dificultad | Fatiga cognitiva | TRANSCRIPTORIO/TENDENCIA: penaliza ALTA si energía baja (hora_inicio × w). CRÓNICO: ALTA penaliza 2×, no-ALTA penaliza por duración. TENDENCIA además limita a 1 ALTA/día. |
| **RB-02** | 8 | Concentración | Sobrecarga diaria | Penaliza cuando la carga total de tareas en un día supera 360 min (6h). `exceso = max(0, total - 360)` |
| **RB-03** | 6 | Horario preferido | Ritmo circadiano | Penaliza tareas en la primera hora (antes de horario_inicio + 60) o última hora (después de horario_fin - 60). |
| **RB-04** | 4 | Tiempo muerto | Procrastinación | Penaliza el tiempo idle del día: `horario_fin - horario_inicio - total_tareas`. En CRÓNICO se reduce a la mitad. |
| **RB-05** | 10 | Post-esfuerzo | Agotamiento | Penaliza si antes de una tarea ALTA ya se trabajaron más de 240 min (4h). |
| **RB-06** | 5 | Desajuste | Atropellamiento | Penaliza cuando el bloque libre es mucho menor que la tarea: `max(0, rango - dur*3)` |
| **RB-07** | — | Descanso | (garantizado) | 30 min de descanso por día, forzado como durísimo. |
| **RB-08** | 3 | Consistencia | Estrés por inconsistencia | Penaliza la diferencia de carga entre días consecutivos: `|load_dia - load_dia+1|` |
| **RB-09** | 7 | Ubicaciones | Desgaste logístico | Penaliza cada cambio de ubicación dentro del mismo día. |
| **RB-10** | 9 | Postergación | Ansiedad por deadline | Penaliza por día de retraso: `w × (último_día_de_ventana - día_asignado)`. máximo en el día más temprano. |
| **RB-PRIORITY** | 0 | Prioridad | Mala jerarquización | Penaliza tareas de baja prioridad en días tardíos: `(max_priority - tarea_priority) × día × w`. Desactivado por defecto (peso 0). |

---

## 5. Endpoints de la API

---

### `GET /health`

Health check simple.

**Response `200`**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

### `POST /api/v1/horarios/generar`

**Endpoint principal.** Genera un horario óptimo a partir de actividades fijas, tareas pendientes y contexto del usuario.

#### Request Body

```json
{
  "actividades_fijas": [
    {
      "id": "mat01",
      "nombre": "Álgebra Lineal",
      "tipo": "clase",
      "dia": 1,
      "hora_inicio": 540,
      "hora_fin": 660,
      "ubicacion_id": "aula_301"
    }
  ],
  "tareas_pendientes": [
    {
      "id": "t1",
      "nombre": "Practicar parcial de Álgebra",
      "tipo": "tarea",
      "duracion_estimada": 120,
      "dificultad": "alta",
      "prioridad": 5,
      "dia_desde": 0,
      "dia_hasta": 4
    }
  ],
  "ubicaciones": [
    { "id": "aula_301", "nombre": "Aula 301", "latitud": -34.6, "longitud": -58.4 },
    { "id": "casa", "nombre": "Casa", "latitud": -34.61, "longitud": -58.38 }
  ],
  "tiempos_traslado": [
    { "origen_id": "aula_301", "destino_id": "casa", "tiempo_estimado_minutos": 20 }
  ],
  "contexto_usuario": {
    "nivel_energia": 3,
    "horario_inicio": 480,
    "horario_fin": 1200,
    "bloques_sueno": [
      { "dia": 0, "inicio": 1380, "fin": 60 },
      { "dia": 1, "inicio": 1380, "fin": 60 }
    ],
    "historial_energia": [
      { "timestamp": "2026-06-01T10:00:00Z", "nivel": 3, "dia_semana": 1, "contexto": "mañana" },
      { "timestamp": "2026-06-01T15:00:00Z", "nivel": 1, "dia_semana": 1, "contexto": "tarde" }
    ],
    "patron_energia_manual": null
  },
  "dia_inicio": 0,
  "dias_totales": 7
}
```

#### Response `200`

```json
{
  "estado": "OPTIMA",
  "mensaje": "",
  "recomendaciones": [],
  "tareas_omitidas": [],
  "bloques": [
    {
      "id_actividad": "mat01",
      "nombre": "Álgebra Lineal",
      "tipo": "clase",
      "dia": 1,
      "hora_inicio": 540,
      "hora_fin": 660,
      "ubicacion_id": "aula_301"
    },
    {
      "id_actividad": "t1",
      "nombre": "Practicar parcial de Álgebra",
      "tipo": "tarea",
      "dia": 2,
      "hora_inicio": 540,
      "hora_fin": 700,
      "ubicacion_id": "casa"
    },
    {
      "id_actividad": "viaje_mat01_t1",
      "nombre": "Viaje a Practicar parcial de Álgebra",
      "tipo": "trabajo",
      "dia": 2,
      "hora_inicio": 660,
      "hora_fin": 680,
      "ubicacion_id": "aula_301"
    }
  ]
}
```

#### Response `422` (Validation Error)

```json
{
  "detail": "Las tareas pendientes requieren 1200 min totales, pero solo hay 840 min disponibles entre los días activos..."
}
```

#### Response `500` (Error Interno)

```json
{
  "detail": "CP-SAT solver error: ..."
}
```

#### Estados de la respuesta

| `estado` | Significado | Qué contiene `bloques` |
|----------|-------------|----------------------|
| `OPTIMA` | Solución óptima encontrada | Actividades fijas + tareas programadas |
| `FACTIBLE` | Solución factible (subóptima por timeout) | Actividades fijas + tareas programadas |
| `INFACTIBLE` | No se encontró solución | Solo actividades fijas (+ recomendaciones) |
| `DESCONOCIDO` | Timeout sin solución | Solo actividades fijas |

---

### `POST /api/v1/horarios/replanificar`

**Replanificar cuando un evento interrumpe el horario.** Por ejemplo, una clase se cancela y tenés 90 min libres que antes no estaban. El servicio toma el horario actual, saca la actividad afectada, y vuelve a optimizar.

#### Request Body

```json
{
  "horario_actual": {
    "estado": "OPTIMA",
    "mensaje": "",
    "recomendaciones": [],
    "tareas_omitidas": [],
    "bloques": [
      { "id_actividad": "t1", "nombre": "Tarea 1", "tipo": "tarea", "dia": 2, "hora_inicio": 540, "hora_fin": 600, "ubicacion_id": "casa" },
      { "id_actividad": "t2", "nombre": "Tarea 2", "tipo": "tarea", "dia": 3, "hora_inicio": 600, "hora_fin": 660, "ubicacion_id": "casa" }
    ]
  },
  "actividad_afectada_id": "t1",
  "tiempo_perdido_minutos": 30,
  "contexto_usuario": {
    "nivel_energia": 2,
    "horario_inicio": 480,
    "horario_fin": 1200
  },
  "dia_inicio": 0,
  "dias_totales": 7
}
```

**Lógica:**
1. Toma el horario actual
2. **Elimina** la actividad con `id == actividad_afectada_id` si es de tipo `clase`
3. Si es una `tarea` (flexible), la **re-agrega** como tarea pendiente con `duracion_estimada += tiempo_perdido_minutos`
4. Las demás tareas flexibles que ya estaban en el horario se **liberan** y se re-asignan
5. Corre `generar()` con los nuevos datos

**Response:** Igual que `/generar`.

---

### `POST /schedule/suggest-task`

**Sugerir qué tarea hacer en un bloque libre.** No usa CP-SAT, es un servicio rápido de ranking.

#### Request Body

```json
{
  "tiempo_libre_minutos": 90,
  "tareas_pendientes": [
    { "id": "t1", "nombre": "Leer capítulo 3", "tipo": "tarea", "hora_inicio": 0, "hora_fin": 0, "duracion_estimada": 60, "dificultad": "baja", "prioridad": 2 },
    { "id": "t2", "nombre": "Resolver ejercicios", "tipo": "tarea", "hora_inicio": 0, "hora_fin": 0, "duracion_estimada": 120, "dificultad": "alta", "prioridad": 5 },
    { "id": "t3", "nombre": "Resumen de clase", "tipo": "tarea", "hora_inicio": 0, "hora_fin": 0, "duracion_estimada": 30, "dificultad": "media", "prioridad": 3 }
  ]
}
```

> **Nota:** `hora_inicio` y `hora_fin` son requeridos por el schema de Actividad pero se ignoran. Usar `0`.

#### Response `200`

```json
{
  "sugerencias": [
    {
      "id_actividad": "t3",
      "nombre": "Resumen de clase",
      "tipo": "tarea",
      "duracion_estimada": 30,
      "dificultad": "media",
      "prioridad": 3,
      "encaja": true,
      "razon": "Tarea corta — ideal para llenar el bloque"
    },
    {
      "id_actividad": "t1",
      "nombre": "Leer capítulo 3",
      "tipo": "tarea",
      "duracion_estimada": 60,
      "dificultad": "baja",
      "prioridad": 2,
      "encaja": true,
      "razon": "Duración adecuada para el tiempo disponible"
    },
    {
      "id_actividad": "t2",
      "nombre": "Resolver ejercicios",
      "tipo": "tarea",
      "duracion_estimada": 120,
      "dificultad": "alta",
      "prioridad": 5,
      "encaja": false,
      "razon": "Necesita 120 min, disponible 90 min"
    }
  ]
}
```

**Orden:** Las que `encaja=true` primero, luego por `prioridad` descendente, luego por `duracion_estimada` ascendente.

---

## 6. Guía de Uso para el Frontend

### Estrategia General

El sistema tiene 3 niveles de uso, de menos a más sofisticado:

#### 1. Loop Básico (Mínimo Producto Viable)

```
1. El frontend recolecta:
   - Clases fijas del estudiante (materias, horarios)
   - Tareas con duración estimada
   - Rango de días disponible

2. Envía POST /api/v1/horarios/generar

3. Muestra los bloques devueltos en una grilla semanal
```

**Mínimo necesario:**
- `actividades_fijas`: las clases con día y hora exactos
- `tareas_pendientes`: al menos `id`, `nombre`, `duracion_estimada`
- `contexto_usuario.horario_inicio`: 480 (8 AM)
- `contexto_usuario.horario_fin`: 1200 (8 PM)

**Sin energía, sin ubicaciones, sin sueño:** el scheduler funciona igual, solo ignora esas penalidades.

#### 2. Loop Avanzado (Con Energía y Contexto)

```
1. Cada vez que el estudiante usa la app, registrar:
   - POST un RegistroEnergia con nivel percibido
   - Acumular historial de energía

2. Antes de generar, calcular patrón de energía:
   - Si querés control manual: enviar patron_energia_manual
   - Si no: el backend clasifica automáticamente desde el historial

3. Enviar contexto completo a /generar

4. Si el resultado es INFACTIBLE:
   - Mostrar las recomendaciones
   - Sugerir reducir tareas o ampliar horario
```

**Energía:** El clasificador mira los últimos 14 días. Si más del 60% de los registros tienen nivel < 2, clasifica como CRÓNICO (penalidades más severas). Si hay pocos registros, asume TRANSCRIPTORIO.

#### 3. Loop Continuo (Con Replanificación)

```
1. El estudiante sigue el horario generado

2. Cuando algo cambia (se cancela una clase, una tarea tomó más tiempo):
   - Enviar POST /schedule/suggest-task para decidir qué hacer con el tiempo libre
   - O enviar POST /api/v1/horarios/replanificar con el horario actual + el cambio

3. Mostrar el nuevo horario ajustado
```

### Mapeo de Features a UX del Frontend

| Feature | Cómo se ve en el frontend | Campo a enviar |
|---------|--------------------------|---------------|
| **Día opcional** | Checkbox "Sin fecha límite" → el scheduler elige el mejor día | No enviar `dia` (o `null`) |
| **Rango de días** | Slider "Desde Lunes hasta Miércoles" | `dia_desde`, `dia_hasta` |
| **Días bloqueados** | Toggles por día "No estudiar este día" | `dias_permitidos` |
| **Tarea ancla** | Checkbox "Fijar día, hora flexible" | `es_ancla=True` + `dia` |
| **Prioridad** | Estrellita (1-5) de importancia | `prioridad` |
| **Dificultad** | Tag "Fácil / Media / Difícil" | `dificultad` |
| **Patrón energía** | Badge "Transcripción / Tendencia / Crónico" | Automático, o `patron_energia_manual` |
| **Override energía** | Slider manual "Hoy me siento..." | `patron_energia_manual` |
| **Horarios por día** | Selector de rango horario distinto cada día | `horario_inicio` como lista de 7 ints |
| **Rolling week** | DatePicker "Arrancar desde..." + "Duración" | `dia_inicio`, `dias_totales` |
| **Asignación parcial** | Badge "X tareas omitidas" con lista | Automático en respuesta `tareas_omitidas` |
| **Replanificar** | Botón "Algo salió mal, reajustar" | POST `/replanificar` |
| **Sugerir tarea** | Card "Tenés 1h libre, ¿qué hacés?" | POST `/suggest-task` |

### Interpretación de la Respuesta

```javascript
// Ejemplo de manejo en frontend
function handleScheduleResponse(response) {
  switch (response.estado) {
    case 'OPTIMA':
    case 'FACTIBLE':
      renderSchedule(response.bloques);
      if (response.tareas_omitidas.length > 0) {
        showWarning(`Quedaron fuera: ${response.tareas_omitidas.length} tareas`);
      }
      break;

    case 'INFACTIBLE':
      showError('No se pudo armar el horario');
      renderFixedBlocks(response.bloques); // solo actividades fijas
      response.recomendaciones.forEach(r => showTip(r));
      // Sugerir al usuario: reducir tareas o ampliar horario
      break;

    case 'DESCONOCIDO':
      showError('El servidor no encontró respuesta a tiempo');
      break;
  }
}
```

---

## 7. Casos de Uso Típicos

### Caso 1: Estudiante sin deadline (día opcional)

Una tarea "Leer capítulo 3" sin fecha específica. El scheduler elige el mejor día.

```json
{
  "id": "leer3",
  "nombre": "Leer capítulo 3",
  "tipo": "tarea",
  "duracion_estimada": 45,
  "dificultad": "baja",
  "prioridad": 1
}
```

**Resultado:** Se asigna al día con menos carga y mejor slot horario según la energía del estudiante.

### Caso 2: Preparación de parcial con varias tareas ALTA

Tres tareas de dificultad ALTA con prioridad máxima. Bajo patrón TENDENCIA, el scheduler forzará máximo 1 ALTA por día.

```json
{
  "tareas_pendientes": [
    { "id": "p1", "nombre": "Practicar parcial Álgebra", "dificultad": "alta", "prioridad": 5, "duracion_estimada": 120 },
    { "id": "p2", "nombre": "Resolver final Física", "dificultad": "alta", "prioridad": 5, "duracion_estimada": 180 },
    { "id": "p3", "nombre": "Hacer ejercicios Cálculo", "dificultad": "alta", "prioridad": 5, "duracion_estimada": 90 }
  ]
}
```

**Resultado:** Las 3 tareas se distribuyen en al menos 3 días distintos, cada una en el mejor horario según la energía.

### Caso 3: Semana parcial (rolling week + horarios por día)

El estudiante estudia Miércoles a Viernes de 14 a 20.

```json
{
  "dia_inicio": 3,
  "dias_totales": 3,
  "contexto_usuario": {
    "horario_inicio": [480, 480, 480, 840, 840, 480, 480],
    "horario_fin": [1200, 1200, 1200, 1200, 1200, 1200, 1200]
  }
}
```

**Resultado:** Solo se consideran miércoles(3), jueves(4), viernes(5) con horario 14:00-20:00.

### Caso 4: Días bloqueados (días permitidos)

El estudiante no estudia los domingos.

```json
{
  "tareas_pendientes": [
    {
      "id": "t1",
      "nombre": "TP de Historia",
      "duracion_estimada": 90,
      "dias_permitidos": [0, 1, 2, 3, 4, 5]
    }
  ]
}
```

**Resultado:** El solver nunca asigna al día 6 (domingo). La variable BoolVar para ese día ni siquiera se crea.

### Caso 5: Tarea importante con deadline cercano

Un examen el viernes con prioridad alta. Se asigna temprano en la semana.

```json
{
  "tareas_pendientes": [
    {
      "id": "examen",
      "nombre": "Estudiar para examen",
      "duracion_estimada": 180,
      "dificultad": "alta",
      "prioridad": 5,
      "dia": 5
    }
  ]
}
```

**Comportamiento con RB-10:** Penaliza asignar más temprano (mayor urgencia = menos penalidad). Con RB-PRIORITY activo, penaliza asignar en días tardíos si la prioridad es baja.

### Caso 6: Tarea ancla (día fijo, hora flexible)

Terapia los martes a cualquier hora.

```json
{
  "tareas_pendientes": [
    {
      "id": "terapia",
      "nombre": "Terapia",
      "tipo": "tarea",
      "duracion_estimada": 60,
      "es_ancla": true,
      "dia": 2
    }
  ]
}
```

**Resultado:** Se asigna al martes (día 2), pero la hora la elige el solver para minimizar penalidades totales.

### Caso 7: Sobrecarga total (asignación parcial)

El estudiante tiene 800 min de tareas pero solo 600 min disponibles. Con F9 activo, el scheduler elige qué tareas entrar y cuáles saltear.

```json
{
  "tareas_pendientes": [
    { "id": "urgente", "nombre": "TP urgente", "duracion_estimada": 120, "prioridad": 5 },
    { "id": "lectura", "nombre": "Lectura liviana", "duracion_estimada": 60, "prioridad": 1 }
  ]
}
```

**Resultado:** El solver prioriza la tarea urgente y omite la lectura liviana. `tareas_omitidas: ["lectura"]`.

### Caso 8: Replanificación por imprevisto

El estudiante tenía 2h para estudiar pero perdió 30 min.

```json
{
  "horario_actual": { ... },
  "actividad_afectada_id": "t1",
  "tiempo_perdido_minutos": 30,
  "contexto_usuario": { ... }
}
```

**Resultado:** El scheduler remueve t1, añade 30 min extra a su duración, y re-optimiza todo.

### Caso 9: Sugerencia rápida para un hueco

El estudiante tiene 1h libre entre clases.

```json
{
  "tiempo_libre_minutos": 60,
  "tareas_pendientes": [...]
}
```

**Resultado:** Lista rankeada de qué tarea conviene hacer ahora. La que mejor encaja + mayor prioridad.

---

## 8. Manejo de Errores

| Código | Causa | Solución |
|--------|-------|----------|
| **422** | Actividades fijas solapadas | Revisar horarios de clases |
| **422** | Tarea dura más que el horario disponible diario | Acortar tarea o ampliar horario |
| **422** | Capacidad insuficiente (sin F9) | Reducir tareas o ampliar horario |
| **422** | `dia_desde > dia_hasta` | Validar rango en frontend |
| **422** | Anchor sin día específico | Enviar `dia` o igualar `dia_desde == dia_hasta` |
| **422** | `dias_permitidos` con valores > 6 | Validar rango 0-6 |
| **422** | Rolling window: dia_inicio + dias_totales > 7 | Respetar límite de 7 días |
| **422** | `horario_inicio` como lista de longitud incorrecta | Coincidir con `dias_totales` |
| **500** | Error interno del solver | Timeout o error CP-SAT; reintentar |

### Errores No-Bloqueantes (Respuesta 200 con `INFACTIBLE`)

| Situación | Señal | Acción sugerida |
|-----------|-------|-----------------|
| Más tareas que capacidad | `estado: INFACTIBLE` + recomendaciones | Reducir tareas o ampliar horario |
| TENDENCIA + muchas ALTA | Recomendación específica | Distribuir ALTA en más días |
| Sleep + fixed overlaps | Recomendación específica | Ajustar horarios |

---

*Documentación generada a partir del código fuente. Última actualización: Junio 2026.*
