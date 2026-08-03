from dataclasses import dataclass


@dataclass(frozen=True)
class Perfil:
    """Los datos personales que el usuario completa en el onboarding.

    Todo salvo el id es opcional porque el trigger de alta crea la fila con
    solo el id: entre registrarse y terminar el onboarding existe un perfil
    vacio, y esa situacion es normal, no un error.

    Las horas se guardan como texto ("07:30") y no como time: es lo que el
    cliente maneja, y convertirlas de ida y vuelta solo agregaria formas de
    perder informacion en el camino.
    """

    id: str
    nombre_usuario: str | None = None
    nivel_energia: int | None = None
    hora_despertar: str | None = None
    hora_dormir: str | None = None

    @property
    def esta_completo(self) -> bool:
        """Si el onboarding termino.

        El cliente trata un perfil incompleto igual que uno inexistente, asi
        que necesita poder distinguirlo sin repetir la regla.
        """
        return (
            self.nivel_energia is not None
            and bool(self.hora_despertar)
            and bool(self.hora_dormir)
        )
