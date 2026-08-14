"""Los seis estados de una ocurrencia, y las reglas que los protegen.

Hasta ahora una actividad estaba marcada o no lo estaba. Esa binariedad es la
causa de todos los casos raros: el telefono apagado, el dia que se abre a las
once de la noche, la semana de parciales. Una actividad sin marcar se parecia
a una no hecha, y no son lo mismo.

`SIN_RESOLVER` es el estado que faltaba y el mas importante de los seis. "No
se" y "no" son datos distintos: la racha, el crecimiento del sapo y la
correlacion entre energia y cumplimiento los leen de forma diferente, y
confundirlos arruina los tres.

Nada de esto se le pide al modelo ni se resuelve en la interfaz: es logica
determinista y vive en codigo, donde se puede probar.
"""

from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any


class EstadoCompletado(str, Enum):
    #: El bloque todavia no empezo.
    PENDIENTE = "pendiente"
    #: Hay una sesion abierta.
    EN_CURSO = "en_curso"
    #: El bloque termino y nadie dijo nada. Es la AUSENCIA de una fila, no un
    #: valor guardado: no se puede escribir "no se" en la base porque nadie lo
    #: afirmo nunca.
    SIN_RESOLVER = "sin_resolver"
    #: Se hizo. Solo por sesion, check manual o cierre del dia.
    HECHA = "hecha"
    #: El usuario dijo que no. Solo explicito.
    NO_HECHA = "no_hecha"
    #: Ese dia no correspondia. Viene de la excepcion del calendario, no de
    #: una decision sobre si se hizo.
    CANCELADA = "cancelada"


class OrigenCompletado(str, Enum):
    """De donde vino la afirmacion.

    Con el tiempo permite saber si lo hecho por sesion se cumple distinto que
    lo marcado a mano. Esa si es una respuesta util.

    No hay origen "automatico" a proposito: nunca se marca como hecha sola. La
    correlacion entre energia y cumplimiento es lo unico que esta app puede
    hacer y ninguna app de habitos puede; rellenarla con suposiciones la
    vuelve inservible.
    """

    SESION = "sesion"
    MANUAL = "manual"
    CIERRE = "cierre"


class MotivoRechazo(str, Enum):
    FUTURO = "futuro"
    FUERA_DE_PLAZO = "fuera_de_plazo"


#: Cuanto hacia atras se puede marcar. Dos dias cubre el fin de semana largo y
#: el telefono que se quedo sin bateria; mas alla de eso, marcar es recordar
#: mal. Marcar una semana entera hacia atras es ficcion, y la ficcion envenena
#: el dato.
DIAS_DE_GRACIA = 2


def validar_marcado(fecha: date, hoy: date) -> MotivoRechazo | None:
    """Si esa fecha admite todavia una afirmacion. `None` = si.

    Devuelve el motivo en vez de lanzar porque quien llama tiene que poder
    explicarselo al usuario: "ese dia ya cerro" y "todavia no paso" piden
    mensajes distintos.
    """
    if fecha > hoy:
        return MotivoRechazo.FUTURO
    if fecha < hoy - timedelta(days=DIAS_DE_GRACIA):
        return MotivoRechazo.FUERA_DE_PLAZO
    return None


def estado_de_la_ocurrencia(
    *,
    fecha: date,
    hoy: date,
    termino: bool,
    fila: dict[str, Any] | None,
    cancelada: bool,
    en_curso: bool = False,
) -> EstadoCompletado:
    """En que estado esta una ocurrencia concreta.

    `fila` es lo guardado en `activity_completions`, o `None` si no hay nada.
    Su ausencia es informacion: significa que nadie dijo nada todavia.
    """
    if cancelada:
        return EstadoCompletado.CANCELADA

    # Lo que el usuario afirmo manda sobre el reloj: marcar algo antes de que
    # termine el bloque es legitimo, se pudo haber adelantado.
    if fila is not None:
        return (
            EstadoCompletado.NO_HECHA
            if fila.get("estado") == EstadoCompletado.NO_HECHA.value
            else EstadoCompletado.HECHA
        )

    if en_curso:
        return EstadoCompletado.EN_CURSO

    # Un dia anterior a hoy ya termino, sea cual sea la hora del bloque.
    if termino or fecha < hoy:
        return EstadoCompletado.SIN_RESOLVER

    return EstadoCompletado.PENDIENTE


def hoy_del_usuario(desfase_utc_minutos: int, ahora: "datetime | None" = None) -> date:
    """Que dia es para quien esta pidiendo.

    El servidor no puede saberlo: usar su propia medianoche es el mismo error
    que ya tuvo `GET /energia/hoy`, que en Lima contaba como martes lo que se
    reporto a las 20:00 del lunes. El cliente manda su desfase y aca se
    aplica.
    """
    momento = ahora or datetime.now(timezone.utc)
    return (momento + timedelta(minutes=desfase_utc_minutos)).date()
