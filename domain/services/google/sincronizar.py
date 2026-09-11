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
from hashlib import sha256
from zoneinfo import ZoneInfo

from domain.entities.user_activity import ActividadUsuario
from domain.ports.outbound.google_calendar_port import (
    ErrorDeGoogle,
    EventoRemoto,
    GoogleCalendarPort,
)
from domain.ports.outbound.google_event_repository_port import (
    EventoImportado,
    GoogleEventsRepositoryPort,
)
from domain.ports.outbound.google_token_repository_port import (
    GoogleTokensRepositoryPort,
)
from domain.ports.outbound.user_activity_repository_port import (
    ActividadUsuarioRepositoryPort,
)

#: Cuantos dias se amplian por lado la ventana de una pasada completa.
_AMPLIACION = timedelta(days=7)

#: La zona en la que viven los `desde`/`hasta` del router. Son los dias del
#: usuario (la app los arma con `rangoDelMes` en hora local), asi que la
#: ventana se interpreta en LA HORA DEL USUARIO, no en UTC: con medianoche
#: UTC un evento del ultimo dia del rango despues de las 19:00 (Peru, UTC-5)
#: quedaba fuera del `del_rango` y se perdia sin rastro. America/Lima no
#: tiene horario de verano: el offset es fijo, no hay doblez.
_ZONA_LOCAL = ZoneInfo("America/Lima")


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
    token_google: str,
    jwt_supabase: str,
    user_id: str,
    google: GoogleCalendarPort,
    tokens: GoogleTokensRepositoryPort,
    eventos: GoogleEventsRepositoryPort,
    actividades: ActividadUsuarioRepositoryPort,
    desde: date,
    hasta: date,
) -> Sincronizacion:
    """Trae los cambios de Google, actualiza el cache y devuelve el rango.

    DOS credenciales de dominios distintos y NO intercambiables:

    - `token_google`: el access token de la API de Google. Solo para el
      puerto `google`.
    - `jwt_supabase`: el JWT del usuario en Supabase. Solo para los
      repositorios, que lo usan como identidad RLS en PostgREST.

    Mezclarlos rompe todo en vivo aunque los fakes no lo noten: por eso
    existen como parametros separados desde la firma.

    Una pasada por CADA calendario: Google entrega syncToken por calendario
    y un evento solo es unico dentro de su calendario, asi que mezclarlos
    rompe la marca y la deduplicacion. El 410 NO es un fallo: Google diciendo
    'esa marca ya no vale' se borra y se repite completa para ese calendario.
    """
    calendarios = google.list_calendarios(token_google)

    todos: list[EventoRemoto] = []
    alguna_completa = False
    for calendario in calendarios:
        marca = tokens.sync_token(jwt_supabase, calendario.id)
        completa = False

        if marca:
            try:
                ventana = google.list_events(
                    token_google,
                    _a_momento(desde),
                    _a_momento(hasta + timedelta(days=1)),
                    calendar_id=calendario.id,
                    sync_token=marca,
                )
            except ErrorDeGoogle as exc:
                if exc.clase != "gone":
                    raise
                # La marca de ESTE calendario murio: se borra y la de abajo
                # hace la pasada completa del calendario, sin tocar la de
                # los demas.
                tokens.borrar_sync_token(jwt_supabase, calendario.id)
                marca = None

        if not marca:
            completa = True
            ventana = google.list_events(
                token_google,
                _a_momento(desde - _AMPLIACION),
                _a_momento(hasta + timedelta(days=1) + _AMPLIACION),
                calendar_id=calendario.id,
            )

        if ventana.sync_token and completa:
            # La marca nueva se persiste SOLO si la pasada fue completa: la
            # incremental no renueva la marca (contrato existente) y si la
            # guardara se podrian saltar cambios entre marcas.
            tokens.guardar_sync_token(
                jwt_supabase, user_id, ventana.sync_token, calendario.id
            )
        todos.extend(ventana.eventos)
        alguna_completa = alguna_completa or completa

    _aplicar_cambios(jwt_supabase, user_id, eventos, actividades, _deduplicar(todos))
    return Sincronizacion(
        eventos=eventos.del_rango(
            jwt_supabase, _a_momento(desde), _a_momento(hasta + timedelta(days=1))
        ),
        fue_completa=alguna_completa,
    )


def _deduplicar(remotos: list[EventoRemoto]) -> list[EventoRemoto]:
    """Mismo evento real llegando desde dos calendarios, una sola fila.

    Ocurre con los calendarios compartidos: la misma clase en el calendario
    del trabajo y en el personal aparece dos veces con el mismo inicio, fin y
    titulo (el id, en cambio, puede diferir). Se conserva el PRIMERO, que el
    orquestador garantiza que es el del calendario principal, y se suelta el
    duplicado. Dos eventos DISTINTOS que casualmente coinciden en hora y
    titulo son tan parecidos que no vale la pena dibujarlos dos veces.
    """
    vistos: set[tuple] = set()
    unicos: list[EventoRemoto] = []
    for evento in remotos:
        # todo_el_dia no tiene hora: se identifica por su fecha.
        momento = evento.inicio.date() if evento.todo_el_dia else (evento.inicio, evento.fin)
        clave = (momento, evento.titulo)
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(evento)
    return unicos


def _aplicar_cambios(
    jwt_supabase,
    user_id,
    eventos_repo,
    actividades_repo,
    remotos,
) -> None:
    eventos_repo.upsert(
        jwt_supabase,
        user_id,
        [
            EventoImportado(
                id=e.id,
                titulo=e.titulo,
                inicio=e.inicio,
                fin=e.fin,
                calendar_id=e.calendar_id,
                todo_el_dia=e.todo_el_dia,
            )
            for e in remotos
        ],
    )

    # Cada evento se materializa como actividad de Lotus: un bloque fijo con
    # su hora, para que aparezca en el calendario propio y el horario se arme
    # alrededor (no queda "solo en la vista mensual").
    for e in remotos:
        actividades_repo.save(jwt_supabase, _a_actividad(user_id, e))


_MAX_TITULO = 200


def _a_actividad(user_id: str, evento: EventoRemoto) -> ActividadUsuario:
    """Del evento remoto a una actividad fija guardable.

    Un evento de Google llega YA expandido (singleEvents=true): una instancia
    por fecha concreta. Se materializa como actividad con `fecha_unica` — el
    paralelo de Lotus para "pasa este dia" — y la ocurrencia se genera al
    vuelo en el calendario propio.

    `days_config` conserva la hora como la guarda el cliente (ISO en UTC, que
    el solver convierte a local con su desfase). `dias_habilitados` queda
    vacio a proposito: si no, el flattener repeteria el parcial todos los
    jueves; la fecha ya lo fija.

    El id es DETERMINISTA: deriva del evento (user + calendario + event_id),
    así un re-sync pisa la misma fila en vez de crear una copia. La garantia
    fuerte la da el indice unico parcial (user, calendar, event) de la BD.
    """
    local = evento.inicio.astimezone(_ZONA_LOCAL)
    dia = _NOMBRE_DIA[local.weekday()]
    hora_inicio = evento.inicio.astimezone(timezone.utc)
    hora_fin = evento.fin.astimezone(timezone.utc)
    duracion = max(0, int((evento.fin - evento.inicio).total_seconds() // 60))

    if evento.todo_el_dia:
        config: dict = {}
    else:
        config = {
            dia: {
                "partitions": [
                    {
                        "startHour": hora_inicio.isoformat(),
                        "endHour": hora_fin.isoformat(),
                        "durationTime": duracion,
                    }
                ],
                "groupId": 0,
            }
        }

    return ActividadUsuario(
        id=_id_de_evento(user_id, evento),
        propietario_id=user_id,
        nombre=evento.titulo[: _MAX_TITULO] or "(sin titulo)",
        tipo="FIXED",
        area="estudio",
        dias_habilitados=[],
        config_por_dia=config,
        fecha_unica=_fecha_unica(evento),
        google_event_id=evento.id,
        google_calendar_id=evento.calendar_id,
    )


_NOMBRE_DIA: tuple[str, ...] = (
    "Lunes",
    "Martes",
    "Miercoles",
    "Jueves",
    "Viernes",
    "Sabado",
    "Domingo",
)


def _id_de_evento(user_id: str, evento: EventoRemoto) -> str:
    semilla = f"{user_id}|{evento.calendar_id}|{evento.id}"
    return "google-" + sha256(semilla.encode()).hexdigest()[:48]


def _fecha_unica(evento: EventoRemoto) -> str:
    """El día en el huso del usuario; un evento multi-día se ancla al inicio."""
    if not evento.todo_el_dia:
        return evento.inicio.astimezone(_ZONA_LOCAL).date().isoformat()
    # Todo el día: Google manda `fin` EXCLUSIVO — el 10 al 11 es solo el 10.
    return evento.inicio.date().isoformat()


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
    # Medianoches LOCALES: la base guarda timestamptz y el rango tiene que ser
    # interpretado SIEMPRE igual, aqui, en del_rango y en la ventana que se le
    # pide a Google. UTC restaba cinco horas al mes del usuario (y sumaba otras
    # cinco al final), y eso hacia aparecer/desaparecer dias en los bordes.
    return datetime(fecha.year, fecha.month, fecha.day, tzinfo=_ZONA_LOCAL)
