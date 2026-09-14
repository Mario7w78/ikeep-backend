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

COMO SE MATERIALIZAN LAS ACTIVIDADES: los eventos que llegan ya expandidos
con `recurring_event_id` son instancias de UNA MISMA serie recurrente y se
guardan como UNA sola actividad semanal (`dias_habilitados` + la hora por
dia), como una creada a mano: es lo que espera el plan semanal y la lista de
actividades, y evita filas repetidas por sesion. Series del MISMO nombre en
el mismo calendario (Google puede mandar la misma clase como eventos
recurrentes separados, uno por dia) se fusionan en UNA: se unen dias y
bloques de hora, y un mismo dia admite varios bloques distintos. Los eventos
sin recurrencia (un viaje, una consulta) siguen siendo actividades con
`fecha_unica`.

DESDE CUANDO SE CREAN: solo los eventos SUELTOS de esta semana en adelante se
materializan. La pasada incremental le pregunta a Google los cambios desde el
syncToken y la API ignora la ventana (timeMin/timeMax no viajan con la marca),
asi que llegan tambien eventos de meses atras; crearlos como actividades era
el bug del "Control de Sincronizar" que llenaba la lista de actividades con
fechas viejas. Las series semanales NO se filtran: una recurrencia vale por
diseno hacia adelante, no importa cuando la devuelva Google.
"""

from dataclasses import dataclass, replace
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
    hoy: date | None = None,
) -> Sincronizacion:
    """Trae los cambios de Google, actualiza el cache y devuelve el rango.

    DOS credenciales de dominios distintos y NO intercambiables:

    - `token_google`: el access token de la API de Google. Solo para el
      puerto `google`.
    - `jwt_supabase`: el JWT del usuario en Supabase. Solo para los
      repositorios, que lo usan como identidad RLS en PostgREST.

    Mezclarlos rompe todo en vivo aunque los fakes no lo noten: por eso
    existen como parametros separados desde la firma.

    LA VENTANA NO ACOTA LA INCREMENTAL: con syncToken Google ignora
    timeMin/timeMax y devuelve TODOS los cambios desde la marca — incluso
    eventos de hace meses. Aplicar los cambios con ese ruido crearia
    actividades viejas; por eso la materializacion filtra por `hoy`.

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

    _aplicar_cambios(
        jwt_supabase,
        user_id,
        eventos,
        actividades,
        _deduplicar(todos),
        _inicio_de_la_semana(hoy or datetime.now(_ZONA_LOCAL).date()),
    )
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


def _inicio_de_la_semana(hoy: date) -> date:
    """El lunes de la semana de `hoy`: lo mas atras que se planifica.

    "Esta semana hacia adelante" es el lunes inclusive: un evento del lunes
    mismo todavia se materializa, uno del domingo anterior ya no. Los
    eventos sueltos anteriores a ese umbral son historia, no tareas.
    """
    return hoy - timedelta(days=hoy.weekday())


def _aplicar_cambios(
    jwt_supabase,
    user_id,
    eventos_repo,
    actividades_repo,
    remotos,
    umbral,  # el lunes de "esta semana", desde donde se materializa
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

    # Las instancias de una misma serie recurrente (mismo recurring_event_id)
    # se juntan en UNA actividad semanal; los eventos sueltos se guardan con
    # su fecha unica, como antes.
    series: dict[tuple[str, str], list[EventoRemoto]] = {}
    sueltos: list[EventoRemoto] = []
    for e in remotos:
        if e.todo_el_dia:
            # Los de todo el dia (feriados, cumpleaños) NO son actividades:
            # no tienen hora que planificar y solo ensucian la lista del
            # usuario. Siguen en el cache (el upsert de arriba recibe los
            # `remotos` enteros) para que la app pinte el "dia importante".
            continue
        if e.recurring_event_id:
            series.setdefault((e.calendar_id, e.recurring_event_id), []).append(e)
        else:
            sueltos.append(e)

    # Eventos sueltos PASADOS (antes del lunes de esta semana): la pasada
    # incremental los trajo sin querer (Google ignora la ventana con la
    # marca) y materializarlos llenaba la lista con actividades de hace
    # meses. Se dejan en el cache para pintar dias viejos, pero NO se
    # convierten en actividades. Las series NO se filtran: una recurrencia
    # vale hacia adelante aunque Google la devuelva con fechas antiguas.
    vivos, pasados = [], []
    for e in sueltos:
        (vivos if _fecha_unica(e) >= umbral.isoformat() else pasados).append(e)
    if pasados:
        # La copia materializada de un evento pasado (mismo id determinista)
        # de una sincronizacion anterior queda huerfana: se borra para que
        # el arreglo tambien limpie lo ya creado, no solo evite lo nuevo.
        actividades_repo.borrar_importadas_con_eventos(
            jwt_supabase, [e.id for e in pasados]
        )

    actividades: list[ActividadUsuario] = [
        _a_actividad(user_id, e) for e in vivos
    ]
    actividades.extend(
        _fusionar_series_por_titulo(
            user_id,
            [
                _a_actividad_de_serie(user_id, calendario, recurrente, instancias)
                for (calendario, recurrente), instancias in series.items()
            ],
        )
    )

    # Cada actividad se re-materializa desde Google en cada sync; su config
    # se reconstruye SIN el tiempo de viaje (Google no lo conoce). Guardarla
    # tal cual pisaria el viaje que el usuario ya cargo en la version previa,
    # asi que se copian los que ya habia a las particiones equivalentes.
    existentes = (
        {a.id: a for a in actividades_repo.list_all(jwt_supabase)}
        if actividades
        else {}
    )
    for actividad in actividades:
        previa = existentes.get(actividad.id)
        if previa is not None and previa.config_por_dia:
            actividad = _con_viajes_preservados(previa, actividad)
        actividades_repo.save(jwt_supabase, actividad)
        if (
            actividad.fecha_unica is None
            and actividad.google_event_id
            and actividad.google_calendar_id
        ):
            # Serie semanal: la limpieza por instancia solo alcanza la ventana,
            # pero las filas por-sesion de meses atras quedaban como
            # duplicados en la lista de actividades para siempre. Se limpian
            # por calendario + titulo (el id de la serie queda afuera).
            actividades_repo.borrar_importadas_de_serie(
                jwt_supabase, actividad.google_calendar_id, actividad.nombre, actividad.id
            )

    # La copia vieja de cada instancia de serie (una fila por sesion, del
    # diseño anterior) queda huerfana: la serie ahora es UNA fila semanal.
    # Se borran SOLO esas, nunca las sueltas ni las manuales.
    event_ids_de_series = [e.id for e in remotos if e.recurring_event_id]
    if event_ids_de_series:
        actividades_repo.borrar_importadas_con_eventos(jwt_supabase, event_ids_de_series)


_MAX_TITULO = 200


def _a_actividad(user_id: str, evento: EventoRemoto) -> ActividadUsuario:
    """Del evento suelto (sin recurrencia) a una actividad fija guardable.

    Un evento puntual de Google —un parcial, una consulta, un viaje— se
    materializa como actividad con `fecha_unica`: el paralelo de Lotus para
    "pasa este dia". `days_config` conserva la hora como la guarda el cliente
    (ISO en UTC, que el solver convierte a local con su desfase).

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


def _a_actividad_de_serie(
    user_id: str,
    calendar_id: str,
    recurring_event_id: str,
    instancias: list[EventoRemoto],
) -> ActividadUsuario:
    """Una serie recurrente entera como UNA actividad semanal.

    Cada instancia (singleEvents las expande) aporta el dia de la semana y la
    hora en que ocurre; se **condensan** en la plantilla semanal que el resto
    de Lotus ya entiende: `dias_habilitados` para el plan y `config_por_dia`
    con la hora real del bloque para no dibujar todo a las 08:00 (bug que se
    arregla aca: las horas viajan por aca, no por `preferredStartTime`).

    Varias instancias del mismo dia a la misma hora colapsan en una particion;
    a horas distintas quedan como particiones separadas. El id deriva del
    `recurring_event_id` (estable entre sesiones), no del id de cada instancia
    (que cambia por sesion).
    """
    locales = sorted(
        (e.inicio.astimezone(_ZONA_LOCAL), e.fin) for e in instancias
    )

    # Clave de condensacion por HORA LOCAL (sin fecha): dos martes a las 07:00
    # en semanas distintas DEBEN dar la misma clave, o cada instancia se vuelve
    # una particion duplicada que la UI pinta como "el mismo bloque N veces".
    # El valor guardado es el del PRIMER ejemplo (fecha real, mismo display).
    por_dia: dict[str, dict[tuple[int, int, int, int], tuple[str, str]]] = {}
    for inicio_local, fin in locales:
        dia = _NOMBRE_DIA[inicio_local.weekday()]
        if instancias[0].todo_el_dia:
            # Sin hora que pintar: el dia nomás, igual que un evento suelto.
            por_dia.setdefault(dia, {})
            continue
        hora_inicio = inicio_local.astimezone(timezone.utc).isoformat()
        hora_fin = fin.astimezone(timezone.utc).isoformat()
        duracion = max(0, int((fin - inicio_local).total_seconds() // 60))
        clave = (inicio_local.hour, inicio_local.minute, inicio_local.second, duracion)
        por_dia.setdefault(dia, {}).setdefault(clave, (hora_inicio, hora_fin))

    config = {
        dia: {
            "partitions": [
                {"startHour": s, "endHour": e, "durationTime": clave[3]}
                for clave, (s, e) in particiones.items()
            ],
            "groupId": 0,
        }
        for dia, particiones in por_dia.items()
        if particiones
    }

    titulo = instancias[0].titulo[: _MAX_TITULO] or "(sin titulo)"
    # Los dias de la semana en que la serie ocurre, en orden canonico para
    # que el plan semanal no los ordene al azar.
    orden_dias = {nombre: i for i, nombre in enumerate(_NOMBRE_DIA)}
    return ActividadUsuario(
        id=_id_de_serie(user_id, calendar_id, recurring_event_id),
        propietario_id=user_id,
        nombre=titulo,
        tipo="FIXED",
        area="estudio",
        dias_habilitados=sorted(por_dia, key=lambda d: orden_dias[d]),
        config_por_dia=config,
        fecha_unica=None,
        google_event_id=recurring_event_id,
        google_calendar_id=calendar_id,
    )


def _con_viajes_preservados(
    previa: ActividadUsuario, reescrita: ActividadUsuario
) -> ActividadUsuario:
    """Copia los tiempos de viaje que el usuario ya cargó en la versión
    previa a las particiones equivalentes de la actividad re-materializada.

    Google solo sabe de inicio/fin/duración: los `travelTo`/`travelFrom` los
    pone la app. Al re-materializar sin ellos y pisar la fila, la sync borraba
    el viaje editado en cada pasada. La equivalencia por horario es
    intencional: si Google movío el bloque, el bloque nuevo no pierde el viaje
    — "se llega en tantos minutos" sigue siendo dañe para la clase que se
    corre de hora.

    NO se compara la fecha en texto: la app guarda la hora como isoformat JS
    ("...T10:00:00.000Z") y la sync la regenera con manejo de zona distinto
    ("...+00:00"); comparar los strings nunca coincidiría aunque fueran el
    mismo instante. Se normaliza a la hora del día real (en UTC, como viaja
    el campo) y se compara esa.
    """
    viajes = {
        _clave_de_particion(p): {
            "travelTo": p.get("travelTo"),
            "travelFrom": p.get("travelFrom"),
        }
        for config_dia in previa.config_por_dia.values()
        for p in config_dia.get("partitions", [])
        if p.get("travelTo") is not None or p.get("travelFrom") is not None
    }
    if not viajes:
        return reescrita

    config = {}
    for dia, config_dia in reescrita.config_por_dia.items():
        particiones = []
        for particion in config_dia.get("partitions", []):
            viaje = viajes.get(_clave_de_particion(particion))
            particiones.append(
                {**particion, **viaje} if viaje else particion
            )
        config[dia] = {**config_dia, "partitions": particiones}

    return replace(reescrita, config_por_dia=config)


def _clave_de_particion(particion: dict) -> tuple:
    """La hora del día en UTC de una partición: lo que identifica un bloque.

    '2026-08-03T10:00:00.000Z' y '2026-08-03T10:00:00+00:00' son el mismo
    instante pero textos distintos; ambas se normalizan a (10, 0, 0) y a la
    misma duración, así el viaje sobrevive al re-materializado.
    """
    return (
        _hora_del_dia(particion.get("startHour")),
        _hora_del_dia(particion.get("endHour")),
        particion.get("durationTime"),
    )


def _hora_del_dia(valor) -> tuple[int, int, int] | None:
    from datetime import datetime

    if not valor:
        return None
    try:
        # isoformat JS termina en 'Z'; el de Python en '+00:00'. Ambos son
        # UTC (el campo viaja en UTC por contrato).
        texto = valor.replace("Z", "+00:00") if isinstance(valor, str) else None
        momento = datetime.fromisoformat(texto) if texto else valor
        return (momento.hour, momento.minute, momento.second)
    except (ValueError, TypeError):
        return None


def _id_de_serie_por_titulo(user_id: str, calendar_id: str, titulo: str) -> str:
    semilla = f"{user_id}|{calendar_id}|t|{titulo}"
    return "google-" + sha256(semilla.encode()).hexdigest()[:48]


def _fusionar_series_por_titulo(
    user_id: str, series: list[ActividadUsuario]
) -> list[ActividadUsuario]:
    """Series con el MISMO nombre y calendario = UNA actividad de Lotus.

    Google puede mandar la misma clase como eventos recurrentes separados
    (uno por dia, cada uno con su recurring_event_id): sin esta fusion, la
    lista muestra la clase tantas veces como dias, como si fueran actividades
    distintas. Una actividad de Lotus lleva dias_habilitados + la hora por
    dia, asi que se unen los dias y las particiones.

    Un mismo dia con bloques DISTINTOS suma las particiones en vez de pisar
    la primera (la identidad de un bloque es inicio+fin+duracion): un dia
    admite varios bloques de horas diferentes.

    El id se reescribe al del TITULO: determinista entre sesiones y estable
    aunque Google reordene los recurring_event_id. `borrar_importadas_de_serie`
    se encarga luego de limpiar las demas copias del mismo calendario + titulo.
    """
    fusionadas: dict[tuple[str, str], ActividadUsuario] = {}
    for serie in series:
        if not serie.google_calendar_id:
            reescrita = serie
        else:
            reescrita = replace(
                serie,
                id=_id_de_serie_por_titulo(
                    user_id, serie.google_calendar_id, serie.nombre
                ),
            )
        clave = (reescrita.google_calendar_id, reescrita.nombre)
        previa = fusionadas.get(clave)
        if previa is None:
            fusionadas[clave] = reescrita
            continue

        for dia in reescrita.dias_habilitados:
            if dia not in previa.dias_habilitados:
                previa.dias_habilitados.append(dia)
            config_dia = reescrita.config_por_dia.get(dia)
            if not config_dia:
                continue
            destino = previa.config_por_dia.setdefault(
                dia, {"partitions": [], "groupId": 0}
            )
            vistos = {
                (p["startHour"], p["endHour"], p.get("durationTime"))
                for p in destino["partitions"]
            }
            for particion in config_dia.get("partitions", []):
                otra = (
                    particion["startHour"],
                    particion["endHour"],
                    particion.get("durationTime"),
                )
                if otra not in vistos:
                    destino["partitions"].append(particion)
                    vistos.add(otra)
            destino["partitions"].sort(key=lambda p: p["startHour"])

    orden_dias = {nombre: i for i, nombre in enumerate(_NOMBRE_DIA)}
    for previa in fusionadas.values():
        previa.dias_habilitados.sort(key=lambda d: orden_dias[d])
    return list(fusionadas.values())


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


def _id_de_serie(user_id: str, calendar_id: str, recurring_event_id: str) -> str:
    semilla = f"{user_id}|{calendar_id}|r|{recurring_event_id}"
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
