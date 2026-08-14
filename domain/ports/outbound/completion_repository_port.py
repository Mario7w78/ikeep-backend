from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from domain.services.rewards.completion import EstadoCompletado, OrigenCompletado


@dataclass(frozen=True)
class ConteosPorArea:
    #: Desde siempre. Es el tamano del petalo, y nunca baja.
    historico: dict[str, int] = field(default_factory=dict)
    #: Solo la ventana reciente. Es la forma de la flor, y si cambia.
    recientes: dict[str, int] = field(default_factory=dict)


class CompletadosRepositoryPort(ABC):
    """Que dijo el usuario sobre cada ocurrencia, y que dia.

    Una fila por (actividad, dia). Una actividad es una definicion recurrente,
    asi que lo que se afirma siempre es sobre una ocurrencia.

    `SIN_RESOLVER` no se guarda: es la ausencia de fila. No se puede escribir
    "no se" en la base porque nadie lo afirmo nunca.
    """

    @abstractmethod
    def marcar(
        self,
        access_token: str,
        user_id: str,
        activity_id: str,
        fecha: date,
        estado: EstadoCompletado = EstadoCompletado.HECHA,
        origen: OrigenCompletado = OrigenCompletado.MANUAL,
    ) -> None:
        """Idempotente: decir lo mismo dos veces es una sola afirmacion."""

    @abstractmethod
    def desmarcar(self, access_token: str, activity_id: str, fecha: date) -> None:
        """Vuelve la ocurrencia a SIN_RESOLVER borrando la fila.

        Tocar por error no deberia ser definitivo, y deshacer no es lo mismo
        que decir "no la hice": eso ultimo es `marcar` con NO_HECHA.
        """

    @abstractmethod
    def del_dia(self, access_token: str, fecha: date) -> list[str]:
        """Los ids HECHOS ese dia.

        Solo los hechos: una ocurrencia marcada como no hecha es una respuesta
        del usuario, no progreso.
        """

    @abstractmethod
    def estados_del_dia(self, access_token: str, fecha: date) -> dict[str, str]:
        """Que se dijo de cada ocurrencia de ese dia.

        El cierre del dia lo necesita para no volver a preguntar por lo que ya
        tiene respuesta, y `del_dia` no alcanza porque ahi las no hechas y las
        sin resolver se ven igual.
        """

    @abstractmethod
    def dias_con_actividad(self, access_token: str, desde: date) -> set[date]:
        """Los dias con al menos una hecha. Es lo que dibuja el historial."""

    @abstractmethod
    def conteos_por_area(self, access_token: str, desde: date) -> "ConteosPorArea":
        """Cuanto se hizo de cada area de vida, en dos escalas.

        Son dos porque el loto necesita dos cosas distintas y una sola
        respondería mal a las dos:

        - `historico` es el TAMANO del petalo. Acumula desde siempre y por eso
          nunca encoge: ver un petalo achicarse porque dejaste de correr es
          exactamente el reproche que este diseno evita.
        - `recientes` es la FORMA de la flor. Mira una ventana, y por eso si
          cambia: es lo que hace que la flor diga algo sobre tu vida ahora y
          no sobre la de hace dos anos.

        Lo que abre el loto no es el volumen, es el equilibrio — asi que la
        apertura sale de `recientes` y el tamano de `historico`.

        Ninguna racha puede decir esto: se pueden llevar treinta dias seguidos
        estudiando y tres semanas sin moverse ni ver a nadie, y la racha
        felicita igual.
        """
