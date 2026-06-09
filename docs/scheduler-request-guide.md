# Cómo enviar requests al servicio Scheduler

Endpoint: `POST /api/v1/horarios/generar`

---

## ⚠️ Lo más importante: el modelo mental

El scheduler trabaja con **ventanas activas del usuario** (`horario_inicio` → `horario_fin`).
Esto NO es "hora de despertarse" ni "hora de dormirse". Es **el rango de tiempo disponible para ubicar actividades cada día**.

El sueño es **lo que sobra fuera de esa ventana**.

```
06:00         08:00                             23:00        01:00
 |             |====== VENTANA ACTIVA ===========|            |
 |             |   (acá van las actividades)      |            |
 |             |                                  |            |
 DORMIR        |                                  |   DORMIR   |
 (08:00-06:00) |                                  | (23:00-01:00)
               wake                              bedtime
           (horario_inicio)                  (horario_fin)
```

Cuando la ventana CRUZA medianoche, el sueño se parte en dos segmentos.
El scheduler **infiere automáticamente los bloques de sueño** — el frontend NO los envía.

---

## El request

### Mínimo indispensable

```json
{
  "actividades_fijas": [],
  "actividades_optimizables": [],
  "contexto_usuario": {
    "horario_inicio": 480,
    "horario_fin": 1200
  }
}
```

Eso es todo lo que necesita el scheduler para funcionar. `horario_inicio` = 08:00, `horario_fin` = 20:00.

### Request completo

```json
{
  "actividades_fijas": [
    {
      "id": "clase-mates",
      "nombre": "Álgebra",
      "tipo": "clase",
      "dia": 0,
      "hora_inicio": 480,
      "hora_fin": 540,
      "ubicacion_id": "u1",
      "prioridad": 0,
      "duracion_estimada": 60,
      "dificultad": "media"
    }
  ],
  "actividades_optimizables": [
    {
      "id": "estudiar-1",
      "nombre": "Estudiar para final",
      "tipo": "tarea",
      "dia_desde": 0,
      "dia_hasta": 4,
      "hora_inicio": 480,
      "hora_fin": 1200,
      "duracion_estimada": 120,
      "dificultad": "alta",
      "prioridad": 3
    }
  ],
  "ubicaciones": [
    { "id": "u1", "nombre": "Facultad", "latitud": -34.603, "longitud": -58.381 }
  ],
  "tiempos_traslado": [
    { "origen_id": "u1", "destino_id": "u2", "tiempo_estimado_minutos": 20 }
  ],
  "contexto_usuario": {
    "nivel_energia": 2,
    "horario_inicio": 480,
    "horario_fin": 60,
    "historial_energia": [
      {
        "timestamp": "2026-06-01T08:00:00+00:00",
        "nivel": 3,
        "dia_semana": 0
      }
    ],
    "patron_energia_manual": null
  },
  "dia_inicio": 0,
  "dias_totales": 7
}
```

---

## 💡 Por qué esto funciona (y qué cambió)

### Antes (viejo modelo)

El frontend enviaba `bloques_sueno` explícitamente. El backend no entendía ventanas que cruzaran medianoche. Si querías un horario de 08:00 a 01:00, tenías que calcular manualmente los bloques de sueño en el frontend y mandarlos como `bloques_sueno`.

**Problema**: el frontend tenía que reconstruir la lógica del backend. Si el usuario cambiaba su ventana, el frontend calculaba sueño → mandaba todo. Lógica duplicada, bugs asegurados.

### Ahora (nuevo modelo)

El frontend manda **solo la ventana activa**. El scheduler:

1. Recibe `horario_inicio=480` (08:00) y `horario_fin=60` (01:00)
2. Detecta que `60 <= 480` → la ventana **cruza medianoche**
3. Calcula automáticamente el bloque de sueño: de 01:00 a 08:00 (420 minutos de sueño)
4. Lo usa internamente para constraint de descanso y energía

**Ganancia**: el frontend no necesita entender la convención de cruce de medianoche, ni calcular sueño, ni mandar `dream_blocks`. Solo manda "a qué hora arranca el día activo" y "a qué hora termina".

---

## ⏰ Convención de cruce de medianoche

La regla es simple:

| Situación | `horario_inicio` | `horario_fin` | ¿Cruza? |
|-----------|:-:|:-:|:--------:|
| Mañana temprano → tarde | `480` (08:00) | `1200` (20:00) | ✗ |
| Tarde → noche | `720` (12:00) | `1080` (18:00) | ✗ |
| Noche → madrugada | `1320` (22:00) | `120` (02:00) | ✓ |
| Madrugada → mañana | `60` (01:00) | `480` (08:00) | ✓ |
| Medianoche → 24h después | `0` | `1440` | ✗ (son 24h) |

**La convención**: si `fin <= inicio`, el scheduler interpreta que la ventana cruza la medianoche hacia el día siguiente. Si `fin > inicio`, es una ventana normal dentro del mismo día.

**Validación**: el backend rechaza ventanas de duración 0. Por ejemplo `inicio=480`, `fin=480` → error `422`.

---

## 🎯 Casos concretos

### Caso 1: Estudiante diurno (ventana normal)

Despierta 08:00, se acuesta 23:00.

```json
{
  "horario_inicio": 480,
  "horario_fin": 1380
}
```

No cruza medianoche. Sueño: de 23:00 a 08:00 (9h). Sin inferencia de `dream_blocks` porque no cruza. Las actividades se ubican entre 08:00 y 23:00.

### Caso 2: Trasnochador crónico (ventana con cruce, sueño inferido)

Despierta 10:00, se acuesta 04:00.

```json
{
  "horario_inicio": 600,
  "horario_fin": 240
}
```

Cruza medianoche. El scheduler infiere `DreamBlock(dia=0, inicio=240, fin=600)` → sueño de 04:00 a 10:00 (6h, dentro del máximo de 12h). Las actividades se ubican entre 10:00 y 04:00 del día siguiente.

### Caso 3: Trabajador nocturno (ventana chica que cruza)

Trabaja de 23:00 a 05:00, duerme de 05:00 a 23:00.

```json
{
  "horario_inicio": 1380,
  "horario_fin": 300
}
```

Cruza medianoche. `abs_duration(1380, 300)` = 420 minutos (7h de ventana activa). El sueño inferido sería de 300 a 1380 = 1080 minutos (18h) → **supera el máximo de 12h**, así que NO se infiere `DreamBlock`. En este caso, el frontend PUEDE (y debería) mandar `dream_blocks` explícitos si quiere bloques de sueño.

```json
{
  "horario_inicio": 1380,
  "horario_fin": 300,
  "dream_blocks": [
    { "dia": 0, "inicio": 300, "fin": 1380 }
  ]
}
```

### Caso 4: Días distintos en la semana (lista de horarios)

El usuario tiene horario de semana (08:00-20:00) y fin de semana (10:00-02:00).

```json
{
  "horario_inicio": [480, 480, 480, 480, 480, 600, 600],
  "horario_fin": [1200, 1200, 1200, 1200, 1200, 120, 120]
}
```

Cada día su propia ventana. Los días 5 y 6 (sábado/domingo) cruzan medianoche. El scheduler infiere sueño solo para esos 2 días.

### Caso 5: 24h activo sin descanso

```json
{
  "horario_inicio": 0,
  "horario_fin": 1440
}
```

No cruza (1440 > 0). Duración = 1440 minutos = 24h. El scheduler igual garantiza el descanso mínimo de 30 minutos por día, y las tareas se ubican en toda la ventana de 24h.

### Caso 6: Superposición de ventanas (día tras día)

Si `horario_inicio=1200` (12:00) y `horario_fin=600` (10:00 del día siguiente), la ventana activa del día 0 va desde el mediodía del día 0 hasta las 10:00 del día 1.

El scheduler interpreta esto como que el usuario está activo durante la noche del día 0, lo que significa que las actividades del día 1 empiezan a las 10:00 (después del sueño). La inferencia de sueño del día 0 va de 10:00 (fin) a 12:00 (inicio del día 1, que es el mismo que el inicio del día 0... esperá, esto es confuso).

**En criollo**: cuando mandás ventanas que cruzan medianoche, el scheduler entiende que el usuario está activo de noche. El sueño se infiere como el complemento de la ventana para ese día. El scheduler asegura que las actividades no ocupen el bloque de sueño inferido.

---

## 🚫 Qué NO mandar (y por qué)

### No mandes `dream_blocks`

```diff
- "dream_blocks": [
-   { "dia": 0, "inicio": 0, "fin": 480 }
- ]
```

El scheduler los infiere automáticamente para ventanas que cruzan medianoche. Si los mandás igual, **se usan los tuyos** y se salta la inferencia. Está bien si necesitás control fino, pero en el caso normal no hace falta.

**Excepción**: si la ventana activa es más angosta que 12h y el complemento (sueño inferido) supera 12h, la inferencia se salta y tenés que mandarlos vos (Caso 3 arriba).

### No mandes campos que no cambiaron

`contexto_usuario` tiene defaults (nivel_energia=2, horario_inicio=480, horario_fin=1200). Si el usuario no configuró algo, no lo mandes — el backend usa el default.

---

## ✅ Checklist para implementar en frontend

- [ ] El formulario de configuración del usuario guarda `horario_inicio` (wake) y `horario_fin` (bedtime) como minutos desde medianoche
- [ ] No hay campo separado para bloques de sueño en la UI
- [ ] Si el usuario pone bedtime ANTES que wake (ej: wake 10AM, bedtime 4AM), el request manda `horario_inicio=600, horario_fin=240` (cruza medianoche)
- [ ] Si hay horarios distintos por día de semana, mandar `horario_inicio` y `horario_fin` como listas de 7 ints
- [ ] Parsear la respuesta: `bloques[].hora_inicio` y `hora_fin` en minutos, convertir con `Math.floor(minutos/60): minutos%60`
- [ ] Aceptar `estado: "OPTIMA"` o `"FACTIBLE"` como éxito; solo `"INVIABLE"` es error
- [ ] El error `422` significa que algún campo está mal — no reintentar automáticamente

---

## 🔄 Tabla de relación frontend-backend

| Lo que ve el usuario | Lo que manda el frontend | Lo que hace el backend |
|---|---|---|
| "Me despierto a las 8" | `horario_inicio: 480` | Ventana activa empieza 08:00 |
| "Me acuesto a la 1 AM" | `horario_fin: 60` | Ventana activa termina 01:00 (día siguiente) |
| — (no se ve) | — | Backend infiere sueño 01:00-08:00 |
| "Dormir de 1 a 8" | — | Se respeta automáticamente |
| "El finde me despierto 10 y me acuesto 3 AM" | `horario_inicio: [..., 600, 600], horario_fin: [..., 180, 180]` | Ventanas separadas por día |
