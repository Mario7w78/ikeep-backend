# API Backend — Documentación para Frontend

**Base URL:** `http://localhost:8000`
**Auth:** Ninguna
**Tiempos:** en minutos desde medianoche (`480` = 08:00, `540` = 09:00)
**Días:** 0-6 (0 = Monday, 6 = Sunday)

---

## 1. `GET /health`

Sin parámetros. Solo verifica conectividad.

**Respuesta 200:**
```json
{ "status": "ok", "version": "1.0.0" }
```

---

## 2. `POST /api/v1/horarios/generar`

Generar horario óptimo ubicando tareas flexibles alrededor de actividades fijas.
Usa Programación por Restricciones (OR-Tools CP-SAT) para minimizar penalizaciones
de energía, concentración, traslados, etc.

**Request body:**
```json
{
  "actividades_fijas": [          // REQUERIDO - Clases, trabajo con horario fijo
    {
      "id": "str",                 // ID único de la actividad
      "nombre": "str",             // Nombre descriptivo
      "tipo": "clase",             // "clase" | "trabajo" | "tarea"
      "dia": 0,                    // 0-6 (Lun-Dom)
      "hora_inicio": 480,          // minutos desde medianoche (480 = 08:00)
      "hora_fin": 540,             // minutos desde medianoche (540 = 09:00)
      "ubicacion_id": "str|null",  // ID de ubicación (opcional)
      "prioridad": 0,              // 0-5, mayor = más importante
      "duracion_estimada": 60,     // en minutos
      "fecha_limite": "str|null",  // ISO 8601 o null
      "dificultad": "media"        // "baja" | "media" | "alta"
    }
  ],
  "actividades_optimizables": [    // REQUERIDO - Actividades flexibles a ubicar
    // Mismo formato que Actividad
  ],
  "ubicaciones": [                 // Opcional - Para cálculo de traslados
    {
      "id": "str",
      "nombre": "str",
      "latitud": -34.603,          // decimal
      "longitud": -58.381          // decimal
    }
  ],
  "tiempos_traslado": [            // Opcional - Tiempos explícitos entre ubicaciones
    {
      "origen_id": "str",          // ID ubicación origen
      "destino_id": "str",         // ID ubicación destino
      "tiempo_estimado_minutos": 15
    }
  ],
  "contexto_usuario": {            // Opcional (todos los campos tienen defaults)
    "nivel_energia": 2,            // 1-3: 1=baja, 2=media, 3=alta. Default: 2
    "horario_inicio": 480,         // default: 480 (08:00)
    "horario_fin": 1200,           // default: 1200 (20:00)
    "bloques_sueno": [             // Opcional - Bloques de sueño por día
      {
        "dia": 0,                  // 0-6
        "inicio": 0,               // minutos desde medianoche (0 = 00:00)
        "fin": 420                 // minutos desde medianoche (420 = 07:00)
      }
    ],
    "historial_energia": [         // Opcional - Historial de energía (últimos 14 días)
      {
        "timestamp": "2026-06-01T08:00:00+00:00",  // ISO 8601
        "nivel": 3,               // 1-3: 1=baja, 2=media, 3=alta
        "dia_semana": 0,           // 0-6
        "contexto": "Después del café"  // string|null, opcional
      }
    ]
  }
}
```

**Respuesta 200:**
```json
{
  "estado": "OPTIMA",           // "OPTIMA" | "FACTIBLE"
  "mensaje": "",                // Mensaje adicional (vacío en éxito)
  "bloques": [
    {
      "id_actividad": "str",    // ID de la actividad
      "nombre": "str",
      "tipo": "clase",          // "clase" | "trabajo" | "tarea"
      "dia": 0,                 // 0-6
      "hora_inicio": 480,       // minutos desde medianoche
      "hora_fin": 540,
      "ubicacion_id": "str|null"
    }
  ]
}
```

**Errores:**

| Status | Tipo | Cuándo |
|--------|------|--------|
| 422 | `ValidationException` | Actividades fijas solapadas, tarea más larga que el día |
| 409 | `SolverException` | No se encontró horario factible o timeout (5s default) |
| 500 | `InternalServerError` | Error inesperado (ver logs) |

**Shape de error (todos los endpoints):**
```json
{
  "error": "SolverException",    // Nombre de la excepción
  "message": "No se encontró...",// Descripción legible
  "detail": {}                   // Detalle adicional (opcional)
}
```

---

## 3. `POST /api/v1/horarios/replanificar`

Replanificar cuando una actividad se cancela, se corta o se libera tiempo.
Re-ejecuta el optimizador con las actividades restantes + el tiempo extra.

**Request body:**
```json
{
  "horario_actual": {             // REQUERIDO - Horario actual del usuario
    "estado": "OPTIMA",           // Estado del horario actual
    "mensaje": "",
    "bloques": [                  // Lista de bloques actuales
      {
        "id_actividad": "c1",
        "nombre": "Algebra",
        "tipo": "clase",
        "dia": 0,
        "hora_inicio": 480,
        "hora_fin": 540,
        "ubicacion_id": null
      }
    ]
  },
  "actividad_afectada_id": "t1", // REQUERIDO - ID de la actividad afectada
  "tiempo_perdido_minutos": 30,   // REQUERIDO - Minutos que se perdieron/liberaron
  "contexto_usuario": {           // Opcional
    "nivel_energia": 2,
    "horario_inicio": 480,
    "horario_fin": 1200,
    "bloques_sueno": [],
    "historial_energia": []
  }
}
```

**Respuesta:** Misma estructura que `/generar` (RespuestaHorario con bloques).

**Comportamiento:**
- Las actividades de tipo `clase` se mantienen fijas (no se reubican)
- Las actividades `trabajo`/`tarea` se reubican con duración ajustada
- Si `actividad_afectada_id` no existe en el horario actual, se ignora
- Si no hay actividades optimizables, retorna el horario sin cambios

---

## 4. `POST /schedule/suggest-actividades-optimizables`

Sugerir qué actividad optimizable encaja en un bloque de tiempo libre.
Ordena por: encaja primero → mayor prioridad → menor duración.

**Request body:**
```json
{
  "tiempo_libre_minutos": 45,     // REQUERIDO - Minutos disponibles
  "actividades_optimizables": [   // REQUERIDO - Lista de actividades
    {
      "id": "t1",
      "nombre": "Estudiar",
      "tipo": "tarea",
      "dia": 0,
      "hora_inicio": 480,
      "hora_fin": 540,
      "duracion_estimada": 60,
      "dificultad": "alta",
      "prioridad": 3
    }
  ],
  "dia_preferido": 0              // Opcional (0-6, default: 0) — actualmente no afecta el filtrado
}
```

**Respuesta 200:**
```json
{
  "sugerencias": [
    {
      "id_actividad": "t1",
      "nombre": "Estudiar",
      "tipo": "tarea",
      "duracion_estimada": 60,
      "dificultad": "alta",
      "prioridad": 3,
      "encaja": true,             // true si duración <= tiempo_libre
      "razon": "Actividad exigente — requiere bloque de concentración"
    }
  ]
}
```

**Razones posibles:**
- `"Actividad exigente — requiere bloque de concentración"` — dificultad alta
- `"Alta prioridad — recomendada para este espacio"` — prioridad >= 3
- `"Actividad corta — ideal para llenar el bloque"` — ≤ 50% del tiempo libre
- `"Duración adecuada para el tiempo disponible"` — encaja genérico
- `"Necesita X min, disponible Y min"` — no encaja

---

## Tipos compartidos

| Tipo | Valores | Notas |
|------|---------|-------|
| `TipoActividad` | `"clase"`, `"trabajo"`, `"tarea"` | `clase` = fija, las demás = flexibles |
| `Dificultad` | `"baja"`, `"media"`, `"alta"` | Afecta penalización de energía |
| `EstadoSolucion` | `"OPTIMA"`, `"FACTIBLE"` | Solo estos 2 llegan en éxito |

---

## Consideraciones para el frontend

### Tiempo y días
- **Convertir minutos** a formato legible: `480 → 08:00`, `540 → 09:00`, `1200 → 20:00`
- **Fórmula:** `horas = Math.floor(minutos / 60)`, `mins = minutos % 60`
- **Días 0-6**: mapear a nombres localizados (`0 → "Lunes"`, `6 → "Domingo"`)

### Manejo de errores
- **409** en `/generar` y `/replanificar` = no hay horario posible → mostrar "No se pudo generar el horario con las actividades actuales"
- **422** = datos inválidos → revisar campos del request
- **500** = error interno → reintentar o mostrar "Error del servidor"
- Todos los errores devuelven `{ error, message, detail }` — parsear `message` para el usuario

### Energía del usuario
- `nivel_energia` usa rango 1-3: **1** = baja, **2** = media, **3** = alta
- `historial_energia` clasifica patrones de los últimos 14 días: TRANSCRIPTORIO (< 20% días con nivel 1), TENDENCIA (20-60%), CRONICO (> 60%)
- El patrón afecta cómo el optimizador ubica tareas difíciles (`dificultad: "alta"`)
- Si no se envía historial, se asume TRANSCRIPTORIO (mejor escenario)

### Traslados
- Si se envían `ubicaciones` + `tiempos_traslado`, el optimizador inserta bloques de viaje automáticamente
- Si solo se envían `ubicaciones` sin tiempos, calcula distancia Haversine (~30km/h)
- Si no se envía nada, no considera traslados

### Optimización
- El timeout del solver es de **5 segundos** — si hay muchas tareas puede retornar `FACTIBLE` en vez de `OPTIMA`
- Las tareas de tipo `clase` nunca se reubican — son anclas del horario
- El descanso mínimo de **30 minutos por día** se garantiza automáticamente

### Autenticación
- **No hay autenticación** — todos los endpoints son públicos (desarrollo)
