from domain.entities.activity import Actividad
from domain.entities.enums import Dificultad


class SuggestService:

    def sugerir(
        self,
        tiempo_libre_minutos: int,
        tareas: list[Actividad],
    ) -> list[dict]:
        result = []
        for t in tareas:
            encaja = t.duracion_estimada <= tiempo_libre_minutos
            razon = ""

            if encaja:
                if t.dificultad == Dificultad.ALTA:
                    razon = "Tarea exigente — requiere bloque de concentración"
                elif t.prioridad >= 3:
                    razon = "Alta prioridad — recomendada para este espacio"
                elif t.duracion_estimada <= tiempo_libre_minutos * 0.5:
                    razon = "Tarea corta — ideal para llenar el bloque"
                else:
                    razon = "Duración adecuada para el tiempo disponible"
            else:
                razon = (
                    f"Necesita {t.duracion_estimada} min, "
                    f"disponible {tiempo_libre_minutos} min"
                )

            result.append({
                "id_actividad": t.id,
                "nombre": t.nombre,
                "tipo": t.tipo,
                "duracion_estimada": t.duracion_estimada,
                "dificultad": t.dificultad,
                "prioridad": t.prioridad,
                "encaja": encaja,
                "razon": razon,
            })

        result.sort(key=lambda x: (-x["encaja"], -x["prioridad"], x["duracion_estimada"]))
        return result
