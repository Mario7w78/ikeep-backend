# API Backend — Documentación para Frontend

**Base URL:** `http://localhost:8000`
**Auth:** Ninguna
**Tiempos:** en minutos desde medianoche (`480` = 08:00, `540` = 09:00)
**Días:** 0-6 (Monday=0, Sunday=6)

---

## 1. `GET /health`

Sin parámetros. Solo verifica conectividad.

**Respuesta:**
```json
{ "status": "ok", "version": "1.0.0" }
```

---

## 2. `POST /api/v1/horarios/generar`

Generar horario óptimo ubicando tareas flexibles alrededor de actividades fijas.

**Request body:**
```json
{
  "actividades_fijas": [          // REQUERIDO - Clases, trabajo con horario fijo
    {
      "id": "str",
      "nombre": "str",
      "tipo": "clase | trabajo | tarea",
      "dia": 0,                   // 0-6
      "hora_inicio": 480,         // minutos desde medianoche
      "hora_fin": 540,
      "ubicacion_id": "str | null",
      "prioridad": 0,
      "duracion_estimada": 60,
      "fecha_limite": "str | null",
      "dificultad": "baja | media | alta"
    }
  ],
  "actividades_optimizables": [Actividad],  // REQUERIDO - Actividades flexibles a ubicar
  "ubicaciones": [                   // Opcional
    { "id": "str", "nombre": "str", "latitud": 0.0, "longitud": 0.0 }
  ],
  "tiempos_traslado": [              // Opcional
    { "origen_id": "str", "destino_id": "str", "tiempo_estimado_minutos": 0 }
  ],
  "contexto_usuario": {              // Opcional (tiene defaults)
    "nivel_energia": 5,              // 1-10 (default: 5)
    "horario_inicio": 480,           // default: 480 (08:00)
    "horario_fin": 1200,             // default: 1200 (20:00)
    "bloques_sueno": [               // Opcional
      { "dia": 0, "inicio": 0, "fin": 480 }
    ]
  }
}
```

**Respuesta 200:**
```json
{
  "estado": "OPTIMA | FACTIBLE | INFACTIBLE | DESCONOCIDO",
  "mensaje": "str",
  "bloques": [
    {
      "id_actividad": "str",
      "nombre": "str",
      "tipo": "clase | trabajo | tarea",
      "dia": 0,
      "hora_inicio": 480,
      "hora_fin": 540,
      "ubicacion_id": "str | null"
    }
  ]
}
```

**Errores:** 422 (validación), 409 (infactible/timeout), 500 (error interno)

---

## 3. `POST /api/v1/horarios/replanificar`

Replanificar cuando una actividad se cancela o se libera tiempo.

**Request body:**
```json
{
  "horario_actual": {               // REQUERIDO - Mismo formato que RespuestaHorario
    "estado": "str",
    "mensaje": "str",
    "bloques": [BloqueTiempo]
  },
  "actividad_afectada_id": "str",  // REQUERIDO - ID de la actividad cancelada/afectada
  "tiempo_perdido_minutos": 60,    // REQUERIDO - Minutos liberados
  "contexto_usuario": ContextoUsuario  // Opcional
}
```

**Respuesta:** Misma que `/generar` (RespuestaHorario con bloques).

---

## 4. `POST /schedule/suggest-actividades-optimizables`

Sugerir qué actividad optimizable hacer en un bloque de tiempo libre.

**Request body:**
```json
{
  "tiempo_libre_minutos": 45,      // REQUERIDO - Minutos disponibles
  "actividades_optimizables": [Actividad],  // REQUERIDO
  "dia_preferido": 0               // Opcional (0-6)
}
```

**Respuesta 200:**
```json
{
  "sugerencias": [
    {
      "id_actividad": "str",
      "nombre": "str",
      "tipo": "clase | trabajo | tarea",
      "duracion_estimada": 60,
      "dificultad": "baja | media | alta",
      "prioridad": 0,
      "encaja": true,
      "razon": "str"
    }
  ]
}
```

---

## Tipos compartidos

| Tipo | Valores |
|------|---------|
| `TipoActividad` | `"clase"`, `"trabajo"`, `"tarea"` |
| `Dificultad` | `"baja"`, `"media"`, `"alta"` |
| `EstadoSolucion` | `"OPTIMA"`, `"FACTIBLE"`, `"INFACTIBLE"`, `"DESCONOCIDO"` |

## Consideraciones para el frontend

- **No hay autenticación** — todos los endpoints son públicos
- **Convertir minutos** a formato legible: `480 → 08:00`, `540 → 09:00`, etc.
- **Días 0-6**: mapear a nombres de día en UI
- **Errores 409** en `/generar` y `/replanificar` indican que no se encontró horario factible — mostrar mensaje amigable
- **Campos opcionales** con defaults: puedes omitirlos en la primera versión
