"""La sincronizacion del calendario de Google, sin I/O propio.

Pura no significa que no hable con nadie: significa que TODO lo que hace pasa
por puertos que le inyectan, y por eso se prueba con dobles en memoria y no
con mocks de red. La regla de oro del modulo: decide, no conecta.

La estrategia es la de Google Calendar misma:

- INCREMENTAL: si hay syncToken guardado, se piden solo los cambios. La
  respuesta no viene acotada al mes —Google no acepta ventana y marca a la
  vez—, pero como los cambios se mezclan contra el cache completo, servir el
  rango pedido despues del upsert da el resultado correcto.
- COMPLETA: primera vez o despues de un 410. Se pide una ventana AMPLIADA
  unos dias por lado para que un evento de varios dias que cruza el borde
  del mes llegue entero; recortar al rango es trabajo de `dias_solapados`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from domain.ports.outbound.google_calendar_port import (
    ErrorDeGoogle,
    GoogleCalendarPort,
)
from domain.ports.outbound.google_event_repository_port import (
    EventoImportado,
    GoogleEventsRepositoryPort,
)
from domain.ports.outbound.google_token_repository_port import (
    GoogleTokensRepositoryPort,
)

#: Cuantos dias se amplian por lado la ventana de una pasada completa.
_AMPLIACION = timedelta(days=7)


class NoConectado(Exception):
    """El usuario nunca conecto Google: no hay tokens que usar."""


@dataclass(frozen=True)
class Sincronizacion:
    """El resultado de una pasada: lo que se sirve del rango pedido."""

    eventos: list[EventoImportado]
    #: True si la pasada fue completa (primera vez o tras un 410). Es
    #: informacion, no un error: sirve para entender latencias.
    fue_completa: bool


def sincronizar(
    access_token: str,
    user_id: str,
    google: GoogleCalendarPort,
    tokens: GoogleTokensRepositoryPort,
    eventos: GoogleEventsRepositoryPort,
    desde: date,
    hasta: date,
) -> Sincronizacion:
    """Trae los cambios de Google, actualiza el cache y devuelve el rango.

    El 410 NO es un fallo: Google diciendo 'esa marca ya no vale'. Se borra
    la marca, se repite completa y el usuario ve su calendario igual.
    """
    marca = tokens.sync_token(access_token)

    if marca:
        try:
            ventana = google.list_events(access_token, _a_momento(desde),
                                         _a_momento(hasta + timedelta(days=1)),
                                         sync_token=marca)
        except ErrorDeGoogle as exc:
            if exc.clase != "gone":
                raise
            # La marca murio. Sin marca, la proxima pasada es completa.
            tokens.borrar_sync_token(access_token)
            return _pasada_completa(
                access_token, user_id, google, tokens, eventos, desde, hasta
            )
    else:
        return _pasada_completa(
            access_token, user_id, google, tokens, eventos, desde, hasta
        )

    _aplicar_cambios(access_token, user_id, eventos, ventana.eventos)
    return Sincronizacion(
        eventos=eventos.del_rango(
            access_token, _a_momento(desde), _a_momento(hasta + timedelta(days=1))
        ),
        fue_completa=False,
    )


def _pasada_completa(
    access_token, user_id, google, tokens, eventos, desde, hasta
) -> Sincronizacion:
    ventana = google.list_events(
        access_token,
        _a_momento(desde - _AMPLIACION),
        _a_momento(hasta + timedelta(days=1) + _AMPLIACION),
    )
    _aplicar_cambios(access_token, user_id, eventos, ventana.eventos)

    if ventana.sync_token:
        tokens.guardar_sync_token(access_token, user_id, ventana.sync_token)

    return Sincronizacion(
        eventos=eventos.del_rango(
            access_token, _a_momento(desde), _a_momento(hasta + timedelta(days=1))
        ),
        fue_completa=True,
    )


def _aplicar_cambios(access_token, user_id, eventos_repo, remotos) -> None:
    eventos_repo.upsert(
        access_token,
        user_id,
        [
            EventoImportado(
                id=e.id,
                titulo=e.titulo,
                inicio=e.inicio,
                fin=e.fin,
                todo_el_dia=e.todo_el_dia,
            )
            for e in remotos
        ],
    )


def dias_solapados(evento, desde: date, hasta: date) -> set[date]:
    """Los dias del rango en que el evento aparece, recortado a él.

    Un evento de tres dias aparece UNA vez guardado y TRES veces dibujado;
    esta funcion es esa diferencia. Los extremos del rango cuentan.

    Dos convenciones de borde que si se mezclan pintan dias de mas:

    - Todo el dia: Google manda `fin` EXCLUSIVO (el 10 al 11 es solo el 10).
    - Con hora: un fin a las 00:00 no ocupa el dia siguiente — termina
      cuando empieza.
    """
    if evento.todo_el_dia:
        primero = _fecha_de(evento.inicio)
        ultimo = _fecha_de(evento.fin) - timedelta(days=1)
    else:
        primero = _fecha_de(evento.inicio)
        ultimo = _fecha_de(evento.fin)
        if _es_medianoche(evento.fin):
            ultimo -= timedelta(days=1)

    return {
        dia
        for dia in (primero + timedelta(n) for n in range((ultimo - primero).days + 1))
        if desde <= dia <= hasta
    }


def _fecha_de(momento: datetime) -> date:
    return momento.date() if isinstance(momento, datetime) else momento


def _es_medianoche(momento: datetime) -> bool:
    return (
        isinstance(momento, datetime)
        and momento.hour == 0
        and momento.minute == 0
        and momento.second == 0
    )


def _a_momento(fecha: date) -> datetime:
    # Medianoches UTC: la base guarda timestamptz y el rango tiene que ser
    # interpretado SIEMPRE igual, aqui y en del_rango.
    return datetime(fecha.year, fecha.month, fecha.day, tzinfo=timezone.utc)
