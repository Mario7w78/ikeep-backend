"""La sincronizacion pura: fakes en memoria, cero red, cero mocks.

Los dobles de aca no simulan HTTP ni tablas: son diccionarios con las mismas
firmas que los puertos. Si un test necesita un mock para pasar, el diseno
tiene un problema; aca no hace falta ninguno.
"""

from datetime import date, datetime, timezone

import pytest

from domain.ports.outbound.google_calendar_port import (
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
TOKEN = "jwt"
USUARIO = "usuario-1"


class GoogleFalso:
    """El puerto de Google, contestando lo que le cargan.

    Los errores se consumen UNA vez: el 410 de la primera llamada no puede
    repetirse en el reintento completo, igual que en la vida real.
    """

    def __init__(self, respuestas=None, errores=None):
        self.respuestas = list(respuestas or [])
        self.errores = list(errores or [])
        self.llamadas = []

    def exchange_code(self, *a, **k):  # pragma: no cover - no se usa aqui
        raise NotImplementedError

    def refresh_access_token(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def revoke(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def list_events(self, access_token, desde, hasta, sync_token=None):
        self.llamadas.append({"sync_token": sync_token, "desde": desde, "hasta": hasta})
        if self.errores:
            raise self.errores.pop(0)
        return self.respuestas.pop(0)


class TokensFalsos:
    def __init__(self, marca_inicial=None):
        self.marca = marca_inicial
        self.marcas_guardadas = []
        self.marcas_borradas = 0

    # Los metodos que no usa sincronizar no existen: si alguien los llamara,
    # el test romperia en la cara. Eso es lo que queremos.
    def guardar(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def obtener(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def borrar(self, *_a):  # pragma: no cover
        raise NotImplementedError

    def sync_token(self, _t):
        return self.marca

    def guardar_sync_token(self, _t, _u, marca):
        self.marca = marca
        self.marcas_guardadas.append(marca)

    def borrar_sync_token(self, _t):
        self.marca = None
        self.marcas_borradas += 1


class EventosFalsos:
    def __init__(self):
        self.guardados: list[EventoImportado] = []

    def upsert(self, _t, user_id, eventos):
        ids = {e.id for e in self.guardados}
        for e in eventos:
            if e.id in ids:
                self.guardados = [e if x.id == e.id else x for x in self.guardados]
            else:
                self.guardados.append(e)

    def del_rango(self, _t, desde, hasta):
        return [
            e
            for e in self.guardados
            if e.inicio < hasta and e.fin > desde
        ]

    def borrar_todo(self, *_a):  # pragma: no cover
        raise NotImplementedError


def _evento(id_="e1", dia=3, hora_inicio=10, duracion_horas=1, todo_el_dia=False):
    inicio = datetime(2026, 8, dia, hora_inicio, tzinfo=timezone.utc)
    if todo_el_dia:
        fin = datetime(2026, 8, dia + 1, tzinfo=timezone.utc)
    else:
        fin = datetime(
            2026, 8, dia, hora_inicio + duracion_horas, tzinfo=timezone.utc
        )
    return EventoRemoto(id=id_, titulo=f"titulo-{id_}", inicio=inicio, fin=fin)


@pytest.fixture
def mundo():
    google = GoogleFalso()
    tokens = TokensFalsos()
    eventos = EventosFalsos()
    return {"google": google, "tokens": tokens, "eventos": eventos}


class TestPrimeraPasada:
    def test_es_completa_y_deja_marca(self, mundo):
        mundo["google"].respuestas.append(
            VentanaDeEventos([_evento()], sync_token="st-nueva")
        )

        resultado = sincronizar(
            TOKEN, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"],
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
            TOKEN, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"],
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
        )

        resultado = sincronizar(
            TOKEN, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"],
            DESDE, HASTA,
        )

        assert [e.id for e in resultado.eventos] == ["dentro"]


class TestPasadaIncremental:
    def test_con_marca_no_se_pide_ventana_nueva_marca(self, mundo):
        mundo["tokens"].marca = "st-vieja"
        mundo["google"].respuestas.append(VentanaDeEventos([]))

        resultado = sincronizar(
            TOKEN, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"],
            DESDE, HASTA,
        )

        assert resultado.fue_completa is False
        assert mundo["tokens"].marcas_guardadas == []
        assert mundo["google"].llamadas[0]["sync_token"] == "st-vieja"

    def test_un_cambio_llega_al_cache_y_al_rango(self, mundo):
        mundo["tokens"].marca = "st-vieja"
        # El evento ya estaba; el incremental trae su version nueva.
        mundo["eventos"].upsert(
            TOKEN,
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
            TOKEN, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"],
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
            TOKEN, USUARIO, mundo["google"], mundo["tokens"], mundo["eventos"],
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
                TOKEN, USUARIO, mundo["google"], mundo["tokens"],
                mundo["eventos"], DESDE, HASTA,
            )

        assert capturado.value.clase == "quota"
        assert mundo["tokens"].marcas_borradas == 0


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
