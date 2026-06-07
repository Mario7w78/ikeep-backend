# Implementación de Rangos de Horas Preferidas (Frontend)

## Contexto

El backend ya soporta una restricción dura para tareas optimizables: el usuario puede definir una **ventana de tiempo** (`hora_preferida_inicio` / `hora_preferida_fin`) dentro de la cual el optimizador debe ubicar la tarea.

Si no se definen estos campos, el comportamiento es el mismo que antes (ventana completa del usuario).

## Campos nuevos en `Actividad`

```json
{
  "id": "t1",
  "nombre": "Estudiar Algebra",
  "tipo": "tarea",
  "dia": 0,
  "hora_inicio": 0,
  "hora_fin": 0,
  "duracion_estimada": 60,
  "dificultad": "media",
  "prioridad": 1,
  "ubicacion_id": null,
  "fecha_limite": null,
  "hora_preferida_inicio": 540,   // ← NUEVO (minutos desde medianoche, 09:00)
  "hora_preferida_fin": 720       // ← NUEVO (12:00)
}
```

- Tipo: `int | null` (minutos desde medianoche, 0 = 00:00, 540 = 09:00, 720 = 12:00)
- Ambos campos deben enviarse juntos o ambos `null`
- Si solo se envía uno, el backend usa el horario completo del usuario como fallback

## Reglas de validación (backend)

| Condición | Resultado |
|---|---|
| Ambos campos `null` | Sin restricción, usa horario completo del usuario |
| Ambos campos definidos | Ventana hard constraint: la tarea DEBE caber dentro |
| Ventana < duración de la tarea | `ValueError` → respuesta 422 con mensaje de error |
| Ventana parcialmente fuera del horario del usuario | Se recorta automáticamente a la intersección |

## Qué necesita el frontend

### 1. Toggle "Restringir horario"

Un switch o checkbox por cada tarea optimizable que diga algo como:

> "Restringir a un rango de horas"

Cuando está desactivado, no se envían los campos (o se envían como `null`).

### 2. Selector de rango de horas

Cuando el toggle está activado, mostrar dos selectores de hora (inicio y fin):

```
[ 09:00 ▾ ]  —  [ 12:00 ▾ ]
```

**Formato de presentación al usuario:** horas legibles (HH:MM).

**Formato al enviar al backend:** minutos desde medianoche.

Ejemplos de conversión:

| Hora visual | Valor API |
|---|---|
| 06:00 | 360 |
| 08:30 | 510 |
| 09:00 | 540 |
| 12:00 | 720 |
| 13:30 | 810 |
| 15:00 | 900 |
| 18:00 | 1080 |
| 20:00 | 1200 |

### 3. Validación en el frontend

Antes de enviar, validar que:

```
hora_preferida_fin - hora_preferida_inicio >= duracion_estimada
```

Si no se cumple, mostrar un warning inline:

> "La ventana seleccionada ({X} min) es más corta que la duración estimada ({Y} min)"

### 4. UX recomendada

- **Default:** toggle desactivado (sin restricción)
- **Al activar:** preseleccionar ventana de 2 horas centrada en el horario del usuario
- **Deshabilitar el toggle** si la duración estimada es mayor a las 24 horas (no aplica)
- **Mostrar la duración de la ventana** al lado de los selectores: "Ventana: 3h 00min"

### 5. Ejemplo de payload completo

```json
{
  "actividades_fijas": [],
  "actividades_optimizables": [
    {
      "id": "t1",
      "nombre": "Estudiar Algebra",
      "tipo": "tarea",
      "dia": 0,
      "hora_inicio": 0,
      "hora_fin": 0,
      "duracion_estimada": 60,
      "dificultad": "media",
      "prioridad": 1,
      "hora_preferida_inicio": 540,
      "hora_preferida_fin": 720
    },
    {
      "id": "t2",
      "nombre": " Leer apuntes",
      "tipo": "tarea",
      "dia": 2,
      "hora_inicio": 0,
      "hora_fin": 0,
      "duracion_estimada": 45,
      "dificultad": "baja",
      "prioridad": 2,
      "hora_preferida_inicio": null,
      "hora_preferida_fin": null
    }
  ],
  "ubicaciones": [],
  "tiempos_traslado": [],
  "contexto_usuario": { ... }
}
```

## Endpoint afectado

`POST /api/v1/schedule/generate` — el schema `Actividad` ahora incluye los dos campos opcionales. No hay cambios en la URL ni en la estructura de la request.
