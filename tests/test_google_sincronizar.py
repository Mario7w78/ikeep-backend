"""La sincronizacion pura: fakes en memoria, cero red, cero mocks.

Los dobles de aca no simulan HTTP ni tablas: son diccionarios con las mismas
firmas que los puertos. Si un test necesita un mock para pasar, el diseno
tiene un problema; aca no hace falta ninguno.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from domain.ports.outbound.google_calendar_port import (
    CalendarioRemoto,
    ErrorDeGoogle,
    EventoRemoto,
    VentanaDeEventos,
)
from domain.ports.outbound.google_event_repository_port import EventoImportado
from domain.services.google.sincronizar import (
    NoConectado,
    dias_solapados,
    sincronizar,
)

DESDE = date(2026, 8, 1)
HASTA = date(2026, 8, 31)
# Dos credenciales de dominios DISTINTOS (F1): la de Google va al puerto de
# Google; el JWT va a los repositorios. Valores distinguibles a proposito:
# si se cruzan, los asserts lo ven.
TOKEN_GOOGLE = "at-de-google"
JWT_SUPABASE = "jwt-de-supabase"
USUARIO = "usuario-1"


class GoogleFalso:
    """El puerto de Google, contestando lo que le cargan.

    Los errores se consumen UNA vez: el 410 de la primera llamada no puede
    repetirse en el reintento completo, igual que en la vida real.

    Con UN calendario los errores son una lista plana. Con varios pueden ser
    un dict `{calendar_id: [errores]}` para que cada calendario tenga los
    suyos; `respuestas` siempre es la secuencia de ventanas que contesta cada
    llamada a list_events, en orden de llegada.
    """

    def __init__(self, respuestas=None, errores=None, calendarios=None):
        self.respuestas = list(respuestas or [])
        # Lista plana (un calendario) o dict por calendar_id (varios).
        self.errores = (
            dict(errores) if isinstance(errores, dict) else list(errores or [])
        )
        self.calendarios = calendarios or [
            CalendarioRemoto(id="primary", nombre="Principal", es_principal=True)
        ]
        # Solo las llamadas a list_events: las de calendarios van aparte para
        # no confundir asserts que cuentan pasadas de eventos.
        self.llamadas = []
        self.llamadas_calendarios = []

    def exchange_code(self, *a, **k):  # pragma: no cover - no se usa aqui
        raise NotImplementedError

    def refresh_access_token(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def revoke(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def list_calendarios(self, access_token):
        self.llamadas_calendarios.append(access_token)
        return self.calendarios

    def list_events(self, access_token, desde, hasta, calendar_id, sync_token=None):
        self.llamadas.append({
            "access_token": access_token,
            "calendar_id": calendar_id,
            "sync_token": sync_token,
            "desde": desde,
            "hasta": hasta,
        })
        if isinstance(self.errores, dict):
            errores = self.errores.get(calendar_id) or []
            if errores:
                raise errores.pop(0)
        elif self.errores:
            raise self.errores.pop(0)
        return self.respuestas.pop(0)


class TokensFalsos:
    def __init__(self, marca_inicial=None):
        self.marcas = {"primary": marca_inicial} if marca_inicial else {}
        self.marcas_guardadas = []
        self.marcas_borradas = 0
        self.jwt_recibidos: list[str] = []

    @property
    def marca(self):
        return self.marcas.get("primary")

    @marca.setter
    def marca(self, valor):
        if valor is None:
            self.marcas.pop("primary", None)
        else:
            self.marcas["primary"] = valor

    # Los metodos que no usa sincronizar no existen: si alguien los llamara,
    # el test romperia en la cara. Eso es lo que queremos.
    def guardar(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def obtener(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def borrar(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def sync_token(self, jwt, calendar_id):
        self.jwt_recibidos.append(jwt)
        return self.marcas.get(calendar_id)

    def guardar_sync_token(self, jwt, _u, marca, calendar_id):
        self.jwt_recibidos.append(jwt)
        self.marcas[calendar_id] = marca
        self.marcas_guardadas.append((calendar_id, marca))

    def borrar_sync_token(self, jwt, calendar_id=None):
        self.jwt_recibidos.append(jwt)
        if calendar_id is None:
            self.marcas.clear()
        else:
            self.marcas.pop(calendar_id, None)
        self.marcas_borradas += 1


class EventosFalsos:
    def __init__(self):
        self.guardados: list[EventoImportado] = []
        self.jwt_recibidos: list[str] = []

    def upsert(self, jwt, user_id, eventos):
        self.jwt_recibidos.append(jwt)
        clave = lambda e: (e.calendar_id, e.id)
        idades = {clave(e) for e in self.guardados}
        for e in eventos:
            if clave(e) in idades:
                self.guardados = [e if clave(x) == clave(e) else x for x in self.guardados]
            else:
                self.guardados.append(e)

    def del_rango(self, jwt, desde, hasta):
        self.jwt_recibidos.append(jwt)
        return [
            e
            for e in self.guardados
            if e.inicio < hasta and e.fin > desde
        ]

    def borrar_todo(self, *_a):  # pragma: no cover
        raise NotImplementedError


class ActividadesFalsas:
    """El puerto de actividades de Lotus, guardando en memoria.

    Replica el upsert por `id` del adaptador real: materializar dos veces el
    mismo evento (mismo id determinista) pisa la fila, no duplica.
    """

    def __init__(self):
        self.guardadas: list = []
        self.jwt_recibidos: list[str] = []
        self.borradas_con_eventos: list[list[str]] = []

    def save(self, jwt, actividad):
        self.jwt_recibidos.append(jwt)
        for i, existente in enumerate(self.guardadas):
            if existente.id == actividad.id:
                self.guardadas[i] = actividad
                return actividad
        self.guardadas.append(actividad)
        return actividad

    def delete(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def borrar_importadas_desde_google(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def borrar_importadas_con_eventos(self, jwt, event_ids):
        self.jwt_recibidos.append(jwt)
        self.borradas_con_eventos.append(list(event_ids))
        self.guardadas = [
            g for g in self.guardadas if g.google_event_id not in event_ids
        ]


def _evento(id_="e1", dia=3, hora_inicio=10, duracion_horas=1, todo_el_dia=False, calendar_id="primary"):
    inicio = datetime(2026, 8, dia, hora_inicio, tzinfo=timezone.utc)
    if todo_el_dia:
        fin = datetime(2026, 8, dia + 1, tzinfo=timezone.utc)
    else:
        fin = datetime(
            2026, 8, dia, hora_inicio + duracion_horas, tzinfo=timezone.utc
        )
    return EventoRemoto(
        id=id_, titulo=f"titulo-{id_}", inicio=inicio, fin=fin,
        calendar_id=calendar_id, todo_el_dia=todo_el_dia,
    )


def _instancia_de_serie(id_, dia, serie, hora_inicio=10, duracion_horas=1, titulo="Clase Recurrente"):
    """Una instancia de una serie recurrente (con recurring_event_id)."""
    return EventoRemoto(
        id=id_,
        titulo=titulo,
        inicio=datetime(2026, 8, dia, hora_inicio, tzinfo=timezone.utc),
        fin=datetime(2026, 8, dia, hora_inicio + duracion_horas, tzinfo=timezone.utc),
        calendar_id="primary",
        recurring_event_id=serie,
    )


@pytest.fixture
def mundo():
    google = GoogleFalso()
    tokens = TokensFalsos()
    eventos = EventosFalsos()
    actividades = ActividadesFalsas()
    return {
        "google": google,
        "tokens": tokens,
        "eventos": eventos,
        "actividades": actividades,
    }


class TestPrimeraPasada:
    def test_es_completa_y_deja_marca(self, mundo):
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento()], sync_token="st-nueva")
        )

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"], mundo["actividades"],
            DESDE, HASTA,
        )

        assert resultado.fue_completa is True
        assert mundo["tokens"].marca == "st-nueva"
        llamada = mundo["google"].llamadas[0]
        assert llamada["sync_token"] is None

    def test_la_ventana_completa_va_ampliada_para_pillar_bordes(self, mundo):
        # Un evento del 30/7 al 2/8 cruza el borde del mes: sin ampliacion,
        # la pasada completa no lo traeria y el dia 1 quedaria vacio.
        mundo["google"].respuestas.append(VentanaDeEventos([]))

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"], mundo["actividades"],
            DESDE, HASTA,
        )

        llamada = mundo["google"].llamadas[0]
        assert llamada["desde"].date() < DESDE
        assert llamada["hasta"].date() > HASTA

    def test_lo_traido_se_sirve_del_rango(self, mundo):
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento("dentro", dia=10), _evento("afuera", dia=3)],
                             sync_token="s")
        )
        # 'afuera' cae dentro igualmente (dia 3 de agosto); usamos uno de julio.
        mundo["google"].respuestas[-1].eventos[1] = EventoRemoto(
            id="julio",
            titulo="viejo",
            inicio=datetime(2026, 7, 5, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 7, 5, 11, tzinfo=timezone.utc),
            calendar_id="primary",
        )

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"], mundo["actividades"],
            DESDE, HASTA,
        )

        assert [e.id for e in resultado.eventos] == ["dentro"]


class TestMaterializacionDeActividades:
    """Los eventos importados viven como actividades de Lotus en la BD.

    El item 5: un bloque de Google no es solo una mancha gris en el mes, es
    una actividad `FIXED` con su fecha, su hora y el area por defecto. La
    deduplicacion se apoya en el id determinista: re-sincronizar pisa la misma
    fila en vez de crear una copia.
    """

    def test_cada_evento_se_convierte_en_actividad_fija(self, mundo):
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento("e1", dia=3, hora_inicio=10, duracion_horas=2)])
        )

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        assert len(mundo["actividades"].guardadas) == 1
        actividad = mundo["actividades"].guardadas[0]
        assert actividad.tipo == "FIXED"
        assert actividad.nombre == "titulo-e1"
        assert actividad.area == "estudio"
        assert actividad.fecha_unica == "2026-08-03"

    def test_la_hora_del_evento_se_conserva_en_el_config(self, mundo):
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento(dia=3, hora_inicio=10, duracion_horas=2)])
        )

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        config = mundo["actividades"].guardadas[0].config_por_dia["Lunes"]
        particion = config["partitions"][0]
        # Usa la parte horaria; la fecha cambia pero la hora (10:00..12:00) no.
        assert "10:00" in particion["startHour"]
        assert "12:00" in particion["endHour"]
        assert particion["durationTime"] == 120

    def test_un_evento_de_todo_el_dia_sin_hora_no_rompe(self, mundo):
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento(dia=3, todo_el_dia=True)])
        )

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        actividad = mundo["actividades"].guardadas[0]
        assert actividad.fecha_unica == "2026-08-03"
        assert actividad.config_por_dia == {}
        assert actividad.tipo == "FIXED"

    def test_resincronizar_no_duplica_la_misma_actividad(self, mundo):
        # Primera pasada completa, luego una incremental que trae el mismo
        # evento renombrado: la fila es la misma, no una copia.
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento("e1", dia=3)], sync_token="st-1")
        )
        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        mundo["tokens"].marcas["primary"] = "st-1"
        mundo["google"].respuestas.append(
            VentanaDeEventos([
                EventoRemoto(
                    id="e1", titulo="renombrado",
                    inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
                    fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
                    calendar_id="primary",
                )
            ])
        )
        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        assert len(mundo["actividades"].guardadas) == 1
        assert mundo["actividades"].guardadas[0].nombre == "renombrado"

    @pytest.fixture
    def mundo2(self):
        calendarios = [
            CalendarioRemoto(id="primary", nombre="Principal", es_principal=True),
            CalendarioRemoto(id="trab1", nombre="Trabajo"),
        ]
        google = GoogleFalso(calendarios=calendarios)
        tokens = TokensFalsos()
        eventos = EventosFalsos()
        actividades = ActividadesFalsas()
        return {
            "google": google,
            "tokens": tokens,
            "eventos": eventos,
            "actividades": actividades,
        }

    def test_mismo_evento_en_dos_calendarios_no_crea_dos_actividades(self, mundo2):
        clase = dict(
            titulo="Clase Calc",
            inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
        )
        mundo2["google"].respuestas.extend([
            VentanaDeEventos([EventoRemoto(id="a-1", calendar_id="primary", **clase)]),
            VentanaDeEventos([EventoRemoto(id="b-1", calendar_id="trab1", **clase)]),
        ])

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo2["google"], mundo2["tokens"],
            mundo2["eventos"], mundo2["actividades"], DESDE, HASTA,
        )

        assert len(mundo2["actividades"].guardadas) == 1
        guardada = mundo2["actividades"].guardadas[0]
        assert guardada.google_event_id == "a-1"
        assert guardada.google_calendar_id == "primary"

    def test_el_id_determinista_distingue_usuarios(self):
        # El mismo evento de dos usuarios tiene ids distintos: el hash lleva
        # el user_id dentro. Como recalcar el id no cuenta la historia en un
        # solo usuario, verificamos que las semillas sean distintas.
        from domain.services.google.sincronizar import _id_de_evento

        evento = EventoRemoto(
            id="e", titulo="t",
            inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
        )
        assert _id_de_evento("u1", evento) != _id_de_evento("u2", evento)
        assert _id_de_evento("u1", evento).startswith("google-")


class TestSeriesRecurrentes:
    """Las instancias de UNA serie recurrente se condensan en UNA actividad
    semanal (dias_habilitados + hora), en vez de una fila por sesion (D9).

    Es la queja del usuario: 8-9 filas por curso aparecian como "duplicados"
    en la lista. Google expande cada repeticion con singleEvents=true y la
    marca con recurring_event_id; aca se vuelven a juntar.
    """

    def test_varias_instancias_de_la_misma_serie_son_una_actividad(self, mundo):
        # La misma clase recurrente: lunes 3, lunes 10, lunes 17 de agosto,
        # todas a las 10:00 con el mismo recurring_event_id.
        mundo["google"].respuestas.append(
            VentanaDeEventos([
                _instancia_de_serie("a1", dia=3, serie="serie-calc"),
                _instancia_de_serie("a2", dia=10, serie="serie-calc"),
                _instancia_de_serie("a3", dia=17, serie="serie-calc"),
            ])
        )

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        assert len(mundo["actividades"].guardadas) == 1
        actividad = mundo["actividades"].guardadas[0]
        assert actividad.dias_habilitados == ["Lunes"]
        assert actividad.fecha_unica is None
        # La hora viaja en el config (la serie es semanal, no un parcial).
        config = actividad.config_por_dia["Lunes"]
        particion = config["partitions"][0]
        assert "10:00" in particion["startHour"]
        assert "11:00" in particion["endHour"]

    def test_la_serie_guarda_todos_los_dias_de_la_semana(self, mundo):
        # La clase se da lunes y miercoles: ambos dia_habilitados, ambos config.
        mundo["google"].respuestas.append(
            VentanaDeEventos([
                _instancia_de_serie("a1", dia=3, serie="s"),
                _instancia_de_serie("a2", dia=5, serie="s"),
                _instancia_de_serie("a3", dia=10, serie="s"),
                _instancia_de_serie("a4", dia=12, serie="s"),
            ])
        )

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        actividad = mundo["actividades"].guardadas[0]
        # 3/8 = lunes, 5/8 = miercoles.
        assert actividad.dias_habilitados == ["Lunes", "Miercoles"]
        assert set(actividad.config_por_dia) == {"Lunes", "Miercoles"}

    def test_la_hora_del_bloque_viaja_en_el_config_de_la_serie(self, mundo):
        # Aunque la instancia se mueva de semana, la hora es SIEMPRE la de
        # Google (10:00), no el default de 08:00 del solver.
        mundo["google"].respuestas.append(
            VentanaDeEventos([
                _instancia_de_serie("a1", dia=3, serie="s", hora_inicio=7),
                _instancia_de_serie("a2", dia=10, serie="s", hora_inicio=7),
            ])
        )

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        actividad = mundo["actividades"].guardadas[0]
        particion = actividad.config_por_dia["Lunes"]["partitions"][0]
        assert "07:00" in particion["startHour"]
        assert "08:00" in particion["endHour"]

    def test_el_id_de_la_serie_es_estable_y_determinista(self, mundo):
        mundo["google"].respuestas.append(
            VentanaDeEventos([_instancia_de_serie("a1", dia=3, serie="s")])
        )
        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )
        primero = mundo["actividades"].guardadas[0].id

        # El mismo usuario + misma serie + otra sesion: MISMA fila.
        mundo["google"].respuestas.append(
            VentanaDeEventos([_instancia_de_serie("a2", dia=10, serie="s")])
        )
        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        assert [a.id for a in mundo["actividades"].guardadas] == [primero]

    def test_las_filas_por_sesion_anteriores_se_limpian(self, mundo):
        # Ya existian las 4 filas por-sesion (una por cada lunes, cada una con
        # su google_event_id = el id de ESA instancia); el re-sync con la
        # nueva logica las borra dejando solo la serie semanal.
        instancias = [
            _instancia_de_serie("a1", dia=3, serie="serie-calc"),
            _instancia_de_serie("a2", dia=10, serie="serie-calc"),
            _instancia_de_serie("a3", dia=17, serie="serie-calc"),
            _instancia_de_serie("a4", dia=24, serie="serie-calc"),
        ]
        for instancia in instancias:
            mundo["actividades"].save(
                JWT_SUPABASE,
                _a_actividad_vieja_por_sesion("reservado", USUARIO, instancia),
            )
        mundo["google"].respuestas.append(VentanaDeEventos(instancias))

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
            mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        # Quedan las 4 instancias viejas SI la limpieza no corrio; con ella,
        # solo la serie (que ademas reemplaza la ultima fila por su id nuevo).
        ids = {a.id for a in mundo["actividades"].guardadas}
        assert len(ids) == 1
        actividad = mundo["actividades"].guardadas[0]
        assert actividad.dias_habilitados == ["Lunes"]
        assert mundo["actividades"].borradas_con_eventos
        assert len(mundo["actividades"].borradas_con_eventos[0]) == 4


def _a_actividad_vieja_por_sesion(_id_reservado, user_id, evento):
    """Reconstruye UNA fila por-sesion del diseño anterior.

    El google_event_id es el id de la instancia (a1, a2, ...), igual que en
    el esquema viejo; el id de la ACTIVIDAD era un hash del evento (que ya no
    coincide con el id de la serie, por eso la limpieza tiene que borrarla).
    """
    from domain.entities.user_activity import ActividadUsuario

    return ActividadUsuario(
        id=f"google-{evento.id}-sesion",
        propietario_id=user_id,
        nombre=evento.titulo,
        tipo="FIXED",
        area="estudio",
        dias_habilitados=[],
        config_por_dia={
            "Lunes": {
                "partitions": [{
                    "startHour": evento.inicio.isoformat(),
                    "endHour": evento.fin.isoformat(),
                    "durationTime": 60,
                }],
                "groupId": 0,
            }
        },
        fecha_unica=evento.inicio.date().isoformat(),
        google_event_id=evento.id,
        google_calendar_id="primary",
    )


class TestPasadaIncremental:
    def test_con_marca_no_se_pide_ventana_nueva_marca(self, mundo):
        mundo["tokens"].marca = "st-vieja"
        mundo["google"].respuestas.append(VentanaDeEventos([]))

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"], mundo["actividades"],
            DESDE, HASTA,
        )

        assert resultado.fue_completa is False
        assert mundo["tokens"].marcas_guardadas == []
        assert mundo["google"].llamadas[0]["sync_token"] == "st-vieja"

    def test_un_cambio_llega_al_cache_y_al_rango(self, mundo):
        mundo["tokens"].marca = "st-vieja"
        # El evento ya estaba; el incremental trae su version nueva.
        mundo["eventos"].upsert(
            JWT_SUPABASE,
            USUARIO,
            [EventoImportado(
                id="e1", titulo="viejo",
                inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
                fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
            )],
        )
        nuevo = EventoRemoto(
            id="e1", titulo="renombrado",
            inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
        )
        mundo["google"].respuestas.append(VentanaDeEventos([nuevo]))

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"], mundo["actividades"],
            DESDE, HASTA,
        )

        assert len(resultado.eventos) == 1
        assert resultado.eventos[0].titulo == "renombrado"


class TestSyncTokenVencido:
    def test_el_410_borra_la_marca_y_repite_completo(self, mundo):
        mundo["tokens"].marca = "st-muerta"
        mundo["google"].errores.append(ErrorDeGoogle("gone", "la marca expiro"))
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento()], sync_token="st-fresca")
        )

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"], mundo["actividades"],
            DESDE, HASTA,
        )

        # Una sola pasada efectiva: la completa. El usuario ve su calendario
        # igual, como si nada hubiera pasado.
        assert resultado.fue_completa is True
        assert mundo["tokens"].marcas_borradas == 1
        assert mundo["tokens"].marca == "st-fresca"
        assert len(mundo["google"].llamadas) == 2
        assert mundo["google"].llamadas[1]["sync_token"] is None

    def test_otros_errores_de_google_no_se_tragan(self, mundo):
        # La cuota no se arregla re-sincronizando: sube y el router decide.
        mundo["tokens"].marca = "st-vieja"
        mundo["google"].errores.append(ErrorDeGoogle("quota", "429"))

        with pytest.raises(ErrorDeGoogle) as capturado:
            sincronizar(
                TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"], mundo["tokens"],
                mundo["eventos"], mundo["actividades"], DESDE, HASTA,
            )

        assert capturado.value.clase == "quota"
        assert mundo["tokens"].marcas_borradas == 0


class TestCredencialesSeparadas:
    """F1: el token de Google y el JWT de Supabase son dominios distintos.

    El defecto original: UNA credencial alimentaba los dos mundos y en vivo
    PostgREST recibia un token opaco de Google. Los fakes que ignoraban el
    parametro no podian verlo; estos asserts si.
    """

    def test_el_token_de_google_va_solo_al_puerto_y_el_jwt_a_los_repos(
        self, mundo,
    ):
        mundo["google"].respuestas.append(VentanaDeEventos([]))

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"],
            mundo["tokens"], mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        # Sink de Google: SOLO el access token de Google.
        assert mundo["google"].llamadas, "Google nunca fue llamado"
        assert all(
            llamada["access_token"] == TOKEN_GOOGLE
            for llamada in mundo["google"].llamadas
        )
        # Sinks de Supabase: SOLO el JWT del usuario.
        assert mundo["tokens"].jwt_recibidos == [JWT_SUPABASE]
        assert mundo["eventos"].jwt_recibidos.count(JWT_SUPABASE) >= 1

    def test_las_dos_credenciales_nunca_se_cruzan_en_pasada_incremental(
        self, mundo,
    ):
        # Camino incremental + guardado de marca: toca los dos dominios.
        mundo["tokens"].marca = "st-vieja"
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento()], sync_token="st-nueva")
        )

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"],
            mundo["tokens"], mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        assert TOKEN_GOOGLE not in mundo["tokens"].jwt_recibidos
        assert JWT_SUPABASE not in [
            l["access_token"] for l in mundo["google"].llamadas
        ]
        # Comportamiento existente: la pasada incremental NO guarda marca.
        assert mundo["tokens"].marcas_guardadas == []
        assert mundo["tokens"].marca == "st-vieja"

    def test_en_el_reintento_tras_410_tambien_van_separados(self, mundo):
        mundo["tokens"].marca = "st-muerta"
        mundo["google"].errores.append(ErrorDeGoogle("gone", "la marca expiro"))
        mundo["google"].respuestas.append(VentanaDeEventos([_evento()]))

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo["google"],
            mundo["tokens"], mundo["eventos"], mundo["actividades"], DESDE, HASTA,
        )

        # Las dos pasadas (incremental muerta + completa) contra Google con
        # su token; todo toque a repos, con el JWT.
        assert {l["access_token"] for l in mundo["google"].llamadas} == {TOKEN_GOOGLE}
        assert set(mundo["tokens"].jwt_recibidos) == {JWT_SUPABASE}
        assert set(mundo["eventos"].jwt_recibidos) == {JWT_SUPABASE}


class TestMultiCalendario:
    """Una pasada por calendario, cada uno con su marca y su dedupe."""

    @pytest.fixture
    def mundo2(self):
        calendarios = [
            CalendarioRemoto(id="primary", nombre="Principal", es_principal=True),
            CalendarioRemoto(id="trab1", nombre="Trabajo"),
        ]
        google = GoogleFalso(calendarios=calendarios)
        tokens = TokensFalsos()
        eventos = EventosFalsos()
        actividades = ActividadesFalsas()
        return {
            "google": google,
            "tokens": tokens,
            "eventos": eventos,
            "actividades": actividades,
        }

    def test_cada_calendario_recibe_su_llamada_y_su_id(self, mundo2):
        mundo2["google"].respuestas.extend([
            VentanaDeEventos([_evento(calendar_id="primary")], sync_token="st-1"),
            VentanaDeEventos([_evento(dia=12, calendar_id="trab1")], sync_token="st-2"),
        ])

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo2["google"], mundo2["tokens"],
            mundo2["eventos"], mundo2["actividades"], DESDE, HASTA,
        )

        assert mundo2["google"].llamadas_calendarios == [TOKEN_GOOGLE]
        assert [l["calendar_id"] for l in mundo2["google"].llamadas] == [
            "primary", "trab1",
        ]
        assert sorted(e.calendar_id for e in resultado.eventos) == [
            "primary", "trab1",
        ]

    def test_el_mismo_evento_en_dos_calendarios_se_deduplica(self, mundo2):
        # La misma clase compartida: mismo inicio, fin y titulo, id distinto.
        clase = dict(
            titulo="Clase Calc",
            inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
        )
        mundo2["google"].respuestas.extend([
            VentanaDeEventos([
                EventoRemoto(id="a-1", calendar_id="primary", **clase)
            ], sync_token="s"),
            VentanaDeEventos([
                EventoRemoto(id="b-1", calendar_id="trab1", **clase)
            ], sync_token="s"),
        ])

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo2["google"], mundo2["tokens"],
            mundo2["eventos"], mundo2["actividades"], DESDE, HASTA,
        )

        assert len(resultado.eventos) == 1
        # Se conserva la copia del PRIMERO: el calendario principal.
        assert resultado.eventos[0].calendar_id == "primary"

    def test_el_titulo_vacio_no_colisiona_por_error(self, mundo2):
        # Un evento sin titulo ("(sin titulo)") no debe fusionar dos eventos
        # distintos que comparten hora pero son de dias diferentes.
        mundo2["google"].respuestas.extend([
            VentanaDeEventos([_evento(id_="x", dia=3), _evento(id_="y", dia=4)], sync_token="s"),
            VentanaDeEventos([]),
        ])

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo2["google"], mundo2["tokens"],
            mundo2["eventos"], mundo2["actividades"], DESDE, HASTA,
        )

        assert [e.id for e in resultado.eventos] == ["x", "y"]

    def test_un_410_en_un_calendario_no_toca_los_demas(self, mundo2):
        # 'trab1' ya tenia marca; Google responde 410 SOLO para ese calendario
        # (primary completa va primero y no debe verse afectada).
        mundo2["tokens"].marcas["trab1"] = "st-muerta"
        mundo2["google"].errores = {"trab1": [ErrorDeGoogle("gone", "marca muerta")]}
        mundo2["google"].respuestas.extend([
            VentanaDeEventos([_evento(calendar_id="primary")], sync_token="st-p"),
            VentanaDeEventos([_evento(id_="trab", calendar_id="trab1")], sync_token="st-fresca"),
        ])

        resultado = sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo2["google"], mundo2["tokens"],
            mundo2["eventos"], mundo2["actividades"], DESDE, HASTA,
        )

        # primary completa (1) + trab incremental muerta (1) + trab completa (1).
        assert len(mundo2["google"].llamadas) == 3
        assert mundo2["google"].llamadas[1]["sync_token"] == "st-muerta"
        assert mundo2["google"].llamadas[2]["sync_token"] is None
        assert mundo2["tokens"].marcas["trab1"] == "st-fresca"
        assert mundo2["tokens"].marcas_borradas == 1
        assert sorted(e.calendar_id for e in resultado.eventos) == ["primary", "trab1"]

    def test_las_marcas_son_por_calendario(self, mundo2):
        # 'trab1' ya sincronizo; 'primary' todavia no. Cada uno con su camino.
        mundo2["tokens"].marcas["trab1"] = "st-trabajo"
        mundo2["google"].respuestas.extend([
            VentanaDeEventos([_evento(calendar_id="primary")], sync_token="st-primaria"),
            VentanaDeEventos([], sync_token=None),
        ])

        sincronizar(
            TOKEN_GOOGLE, JWT_SUPABASE, USUARIO, mundo2["google"], mundo2["tokens"],
            mundo2["eventos"], mundo2["actividades"], DESDE, HASTA,
        )

        assert mundo2["google"].llamadas[0]["sync_token"] is None   # primary completa
        assert mundo2["google"].llamadas[1]["sync_token"] == "st-trabajo"  # trab incremental
        assert mundo2["tokens"].marcas["primary"] == "st-primaria"
        # La incremental no renueva su marca (contrato existente).
        assert mundo2["tokens"].marcas["trab1"] == "st-trabajo"


class TestDiasSolapados:
    def test_un_evento_que_cruza_varios_dias_aparece_en_cada_uno(self):
        evento = EventoRemoto(
            id="e", titulo="t",
            inicio=datetime(2026, 8, 3, 22, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 6, 2, tzinfo=timezone.utc),
        )

        assert dias_solapados(evento, DESDE, HASTA) == {
            date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6),
        }

    def test_se_recorta_al_rango_por_los_dos_lados(self):
        evento = EventoRemoto(
            id="e", titulo="t",
            inicio=datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 4, 10, tzinfo=timezone.utc),
        )

        dias = dias_solapados(evento, date(2026, 8, 1), date(2026, 8, 3))

        assert dias == {date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)}

    def test_todo_el_dia_de_un_solo_dia_es_un_dia(self):
        # Google manda el fin EXCLUSIVO: start.date=10, end.date=11 significa
        # SOLO el 10. Sin restar el dia, pintaria dos veces.
        evento = EventoRemoto(
            id="e", titulo="t",
            inicio=datetime(2026, 8, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 11, tzinfo=timezone.utc),
            todo_el_dia=True,
        )

        assert dias_solapados(evento, DESDE, HASTA) == {date(2026, 8, 10)}

    def test_todo_el_dia_de_varios_dias_cuenta_los_dias_reales(self):
        # Del 10 al 12 (fin exclusivo) son el 10 y el 11.
        evento = EventoRemoto(
            id="e", titulo="t",
            inicio=datetime(2026, 8, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 12, tzinfo=timezone.utc),
            todo_el_dia=True,
        )

        assert dias_solapados(evento, DESDE, HASTA) == {
            date(2026, 8, 10), date(2026, 8, 11),
        }

    def test_un_fin_a_medianoche_no_ocupa_el_dia_siguiente(self):
        evento = EventoRemoto(
            id="e", titulo="t",
            inicio=datetime(2026, 8, 10, 20, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc),
        )

        assert dias_solapados(evento, DESDE, HASTA) == {date(2026, 8, 10)}

    def test_fuera_del_rango_es_ningun_dia(self):
        evento = EventoRemoto(
            id="e", titulo="t",
            inicio=datetime(2026, 9, 10, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 9, 10, 11, tzinfo=timezone.utc),
        )

        assert dias_solapados(evento, DESDE, HASTA) == set()
