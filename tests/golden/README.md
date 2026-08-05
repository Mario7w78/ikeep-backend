# Conversaciones doradas

Cada archivo `.yaml` describe una conversación completa y lo que debe salir de
ella. Se corren de dos formas, que verifican cosas distintas:

**En CI**, contra un modelo guionado (`test_golden_conversations.py`). El
`guion` de cada turno dice qué devuelve el modelo en cada vuelta, así que la
corrida es determinista y sin red. Verifica la **orquestación**: que el bucle
acumule, ejecute y proponga como corresponde en cada escenario.

**Contra el modelo real** (`scripts/eval_assistant.py`, fuera de CI). El
`guion` se ignora y responde el proveedor de verdad. Verifica que el **modelo**
sepa comportarse con este prompt y estas tools. Es lo único que mide el riesgo
que asumimos al quedarnos en Groq/Cerebras, cuyo tool calling multi-turno es
irregular.

## Qué se asierta y qué no

Se asierta el **borrador resultante** y las **tools invocadas**. Nunca el texto
exacto de las preguntas: se rompe con cada ajuste del prompt y no protege nada.
Que el asistente pregunte "¿qué días?" o "¿cuándo la tenés?" da igual mientras
termine sabiendo los días.

## Formato

```yaml
nombre: descripción corta
turnos:
  - usuario: lo que escribe la persona
    guion:                    # solo para la corrida determinista
      - tools:
          - nombre: actualizar_borrador
            argumentos: {name: Calculo}
      - texto: una pregunta
    espera:
      tipo: pregunta | propuesta
      draft: {campo: valor}   # el borrador debe contener esto
      draft_conserva: [name]  # estos campos no pueden haberse perdido
      tools: [actualizar_borrador]
      propuesta: crear | modificar | eliminar | regenerar
```

## Umbral

Contra el modelo real, N=3 por caso y ≥90% de aprobación para considerar que un
proveedor sirve. El orden Groq → Cerebras → Mistral está puesto sin evidencia;
esta suite es lo que debería decidirlo.
