"""Los endpoints de Google, sin red ni base: overrides y fakes.

El router habla con puertos, asi que los tests le enchufan dobles en memoria
por dependency_overrides — el mismo truco del resto de la suite. Lo que se
verifica aca es el CONTRATO HTTP: codigos de respuesta, formas de cuerpo,
la taxonomia de errores y que un fallo de Google nunca toque otra cosa.
"""

from datetime import date, datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.ports.outbound.google_calendar_port import (
    ErrorDeGoogle,
    EventoRemoto,
    VentanaDeEventos,
)
from domain.ports.outbound.google_event_repository_port import (
    EventoImportado,
    GoogleEventsRepositoryPort,
)
from domain.ports.outbound.google_token_repository_port import (
    GoogleTokensRepositoryPort,
    TokensDeConexion,
)
from cryptography.fernet import Fernet

from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.inbound.api.v1.google_router import (
    get_google_client,
    get_google_events_repository,
    get_google_tokens_repository,
    router,
)
from infrastructure.config import settings as settings_module

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt-de-supabase"
FERNET_KEY = Fernet.generate_key().decode()

DESDE = date(2026, 8, 1)
HASTA = date(2026, 8, 31)


class GoogleFalso:
    def __init__(self):
        self.respuestas: list[VentanaDeEventos] = []
        self.errores: list[ErrorDeGoogle] = []
        self.refreshes: list[tuple[object, object]] = []
        self.revocados: list[str] = []
        self.tokens_de_exchange = None

    def exchange_code(self, code, verifier, redirect_uri):
        if self.errores:
            raise self.errores.pop(0)
        return self.tokens_de_exchange

    def refresh_access_token(self, refresh_token):
        if self.errores:
            raise self.errores.pop(0)
        self.refreshes.append(refresh_token)
        return self.tokens_de_exchange or _tokens_nuevos()

    def list_events(self, access_token, desde, hasta, sync_token=None):
        if self.errores:
            raise self.errores.pop(0)
        return self.respuestas.pop(0)

    def revoke(self, token):
        self.revocados.append(token)


def _tokens_nuevos():
    from domain.ports.outbound.google_calendar_port import TokensDeGoogle

    return TokensDeGoogle(
        refresh_token="rt-nuevo",
        access_token="at-nuevo",
        access_expira_en=datetime.now(timezone.utc) + timedelta(hours=1),
    )


class TokensFalsos(GoogleTokensRepositoryPort):
    def __init__(self, conexion: TokensDeConexion | None = None):
        self.conexion = conexion
        self.marca = None
        self.borrado = False
        self.marca_borrada = False

    def guardar(self, _t, tokens):
        self.conexion = tokens

    def obtener(self, _t):
        return self.conexion

    def borrar(self, _t):
        self.borrado = True
        self.conexion = None

    def sync_token(self, _t):
        return self.marca

    def guardar_sync_token(self, _t, _u, marca):
        self.marca = marca

    def borrar_sync_token(self, _t):
        self.marca = None
        self.marca_borrada = True


class EventosFalsos(GoogleEventsRepositoryPort):
    def __init__(self):
        self.guardados: list[EventoImportado] = []

    def upsert(self, _t, user_id, eventos):
        self.user_id_recibido = user_id
        for e in eventos:
            self.guardados = [x for x in self.guardados if x.id != e.id] + [e]

    def del_rango(self, _t, desde, hasta):
        return [e for e in self.guardados if e.inicio < hasta and e.fin > desde]

    def borrar_todo(self, _t):
        self.guardados.clear()


@pytest.fixture
def configuracion(monkeypatch):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        settings_module.Settings(
            VERIFY_SCHEMA_ON_STARTUP=False,
            GOOGLE_CLIENT_ID="cliente",
            GOOGLE_CLIENT_SECRET="secreto",
            GOOGLE_STATE_SECRET="secreto-del-state",
            GOOGLE_TOKEN_FERNET_KEY=FERNET_KEY,
            SUPABASE_URL="https://sup.test",
            SUPABASE_ANON_KEY="anon",
            SUPABASE_SERVICE_ROLE_KEY="servicio",
            GOOGLE_REDIRECT_URI="https://ikeep-backend.onrender.com/api/v1/google/oauth/callback",
        ),
    )


def _conexion_viva() -> TokensDeConexion:
    from infrastructure.adapters.outbound.google.token_cipher import cifrar

    return TokensDeConexion(
        user_id=USUARIO.id,
        refresh_token_cifrado=cifrar("el-refresh-token"),
        access_token="at-vigente",
        access_expira_en=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


@pytest.fixture
def cliente(configuracion, google_falso, tokens_falsos, eventos_falsos):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_google_client] = lambda: google_falso
    app.dependency_overrides[get_google_tokens_repository] = lambda: tokens_falsos
    app.dependency_overrides[get_google_events_repository] = lambda: eventos_falsos
    with TestClient(app) as c:
        yield c


@pytest.fixture
def google_falso(configuracion):
    return GoogleFalso()


@pytest.fixture
def tokens_falsos(configuracion):
    return TokensFalsos()


@pytest.fixture
def eventos_falsos(configuracion):
    return EventosFalsos()


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------

class TestInicio:
    def test_devuelve_una_url_con_state_y_pkce(self, cliente):
        cuerpo = cliente.get("/api/v1/google/oauth/inicio").json()

        assert "accounts.google.com/o/oauth2/v2/auth" in cuerpo["auth_url"]
        assert "code_challenge_method=S256" in cuerpo["auth_url"]
        assert "access_type=offline" in cuerpo["auth_url"]
        assert "state=" in cuerpo["auth_url"]

    def test_el_redirect_uri_es_el_del_entorno(self, cliente):
        cuerpo = cliente.get("/api/v1/google/oauth/inicio").json()

        assert (
            "redirect_uri=https%3A%2F%2Fikeep-backend.onrender.com"
            "%2Fapi%2Fv1%2Fgoogle%2Foauth%2Fcallback" in cuerpo["auth_url"]
        )

    def test_sin_credenciales_es_503_config_y_no_crash(self, cliente, monkeypatch):
        monkeypatch.setattr(
            settings_module,
            "_settings",
            settings_module.Settings(VERIFY_SCHEMA_ON_STARTUP=False),
        )

        r = cliente.get("/api/v1/google/oauth/inicio")

        assert r.status_code == 503
        assert r.json()["detail"].startswith("[config]")


class TestCallback:
    def _state_valido(self, secreto="secreto-del-state"):
        return pyjwt.encode(
            {"sub": USUARIO.id, "cv": "verificador"},
            secreto,
            algorithm="HS256",
        )

    def test_un_callback_sano_guarda_el_refresh_cifrado(
        self, cliente, google_falso, tokens_falsos, monkeypatch
    ):
        # El upsert del callback es la unica escritura privilegiada; se
        # intercepta para no salir a una base que en tests no existe.
        guardados = {}
        monkeypatch.setattr(
            "infrastructure.adapters.inbound.api.v1.google_router."
            "guardar_como_servicio",
            lambda t: guardados.update({"tokens": t}),
        )
        google_falso.tokens_de_exchange = _tokens_nuevos()

        r = cliente.get(
            "/api/v1/google/oauth/callback",
            params={"code": "codigo", "state": self._state_valido()},
            follow_redirects=False,
        )

        assert r.status_code in (302, 307)
        assert "status=ok" in r.headers["location"]
        tokens = guardados["tokens"]
        assert tokens.user_id == USUARIO.id
        # El refresh token NUNCA descansa en claro.
        assert tokens.refresh_token_cifrado.startswith("gAAA")

    def test_un_state_forjado_no_gasta_el_codigo(
        self, cliente, google_falso, tokens_falsos
    ):
        r = cliente.get(
            "/api/v1/google/oauth/callback",
            params={"code": "robado", "state": "forjado-a-mano"},
            follow_redirects=False,
        )

        assert "status=state_invalido" in r.headers["location"]
        assert google_falso.tokens_de_exchange is None  # no hubo exchange

    def test_un_state_vencido_se_rechaza(self, cliente, monkeypatch):
        vencido = pyjwt.encode(
            {
                "sub": USUARIO.id, "cv": "v",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=11),
            },
            "secreto-del-state",
            algorithm="HS256",
        )

        r = cliente.get(
            "/api/v1/google/oauth/callback",
            params={"code": "c", "state": vencido},
            follow_redirects=False,
        )

        assert "status=state_invalido" in r.headers["location"]


class TestEstado:
    def test_sin_conexion_dice_conectado_false(self, cliente):
        cuerpo = cliente.get("/api/v1/google/estado").json()
        assert cuerpo == {"conectado": False}

    def test_con_tokens_dice_conectado_true(self, cliente, tokens_falsos):
        tokens_falsos.conexion = _conexion_viva()

        cuerpo = cliente.get("/api/v1/google/estado").json()

        assert cuerpo == {"conectado": True}


class TestDesconectar:
    def test_desconectado_borra_todo_y_revoca(
        self, cliente, google_falso, tokens_falsos, eventos_falsos
    ):
        tokens_falsos.conexion = _conexion_viva()
        eventos_falsos.guardados.append(EventoImportado(
            id="e", titulo="t",
            inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
        ))

        r = cliente.delete("/api/v1/google/oauth")

        assert r.status_code == 204
        assert len(google_falso.revocados) == 1
        assert tokens_falsos.borrado is True
        assert tokens_falsos.marca_borrada is True
        assert eventos_falsos.guardados == []

    def test_nunca_conectado_es_no_op_sin_llamar_a_google(
        self, cliente, google_falso
    ):

        r = cliente.delete("/api/v1/google/oauth")

        assert r.status_code == 204
        assert google_falso.revocados == []


# --------------------------------------------------------------------------
# Calendario
# --------------------------------------------------------------------------

def _evento_remoto(id_, dia_inicio, dias=1, todo_el_dia=False):
    inicio = datetime(2026, 8, dia_inicio, tzinfo=timezone.utc)
    if todo_el_dia:
        fin = datetime(2026, 8, dia_inicio + dias, tzinfo=timezone.utc)
    else:
        fin = datetime(2026, 8, dia_inicio, 23, tzinfo=timezone.utc)
    return EventoRemoto(id=id_, titulo=f"T-{id_}", inicio=inicio, fin=fin,
                        todo_el_dia=todo_el_dia)


class TestCalendarioGoogle:
    def _ventana(self, *eventos):
        return VentanaDeEventos(list(eventos), sync_token="st-1")

    def test_desconectado_es_200_y_cero_llamadas(
        self, cliente, google_falso, tokens_falsos
    ):
        r = cliente.get("/api/v1/calendario/google?desde=2026-08-01&hasta=2026-08-31")

        assert r.status_code == 200
        assert r.json() == {"conectado": False}
        assert google_falso.respuestas == []  # ni un pedido a Google

    def test_rango_invertido_y_enorme_son_422(self, cliente, tokens_falsos):
        tokens_falsos.conexion = _conexion_viva()

        invertido = cliente.get(
            "/api/v1/calendario/google?desde=2026-08-09&hasta=2026-08-03"
        )
        enorme = cliente.get(
            "/api/v1/calendario/google?desde=2026-01-01&hasta=2026-12-31"
        )

        assert invertido.status_code == 422
        assert enorme.status_code == 422

    def test_devuelve_los_eventos_con_su_expansion_por_dia(
        self, cliente, google_falso, tokens_falsos
    ):
        tokens_falsos.conexion = _conexion_viva()
        google_falso.respuestas.append(
            self._ventana(_evento_remoto("multi", 3, dias=3, todo_el_dia=True))
        )

        cuerpo = cliente.get(
            "/api/v1/calendario/google?desde=2026-08-01&hasta=2026-08-31"
        ).json()

        ids = [e["id"] for e in cuerpo["eventos"]]
        assert ids == ["multi"]
        # Del 3 al 5: tres dias, fin EXCLUSIVO de Google descontado.
        assert cuerpo["dias"]["multi"] == [
            "2026-08-03", "2026-08-04", "2026-08-05",
        ]

    def test_deja_marca_para_la_proxima_incremental(
        self, cliente, google_falso, tokens_falsos
    ):
        tokens_falsos.conexion = _conexion_viva()
        google_falso.respuestas.append(self._ventana())

        cliente.get("/api/v1/calendario/google?desde=2026-08-01&hasta=2026-08-31")

        assert tokens_falsos.marca == "st-1"

    def test_un_refresh_rechazado_pide_reconectar_con_401(
        self, cliente, google_falso, tokens_falsos
    ):
        from infrastructure.adapters.outbound.google.token_cipher import cifrar

        tokens_falsos.conexion = TokensDeConexion(
            user_id=USUARIO.id,
            refresh_token_cifrado=cifrar("revocado"),
            # Sin access token util: toca renovar, y Google dice que no.
            access_token=None,
            access_expira_en=None,
        )
        google_falso.errores.append(ErrorDeGoogle("invalid_grant", "muerto"))

        r = cliente.get("/api/v1/calendario/google?desde=2026-08-01&hasta=2026-08-31")

        assert r.status_code == 401

    def test_cuota_es_503_y_distinguible(self, cliente, google_falso, tokens_falsos):
        tokens_falsos.conexion = _conexion_viva()
        tokens_falsos.marca = "st-previa"  # fuerza el camino incremental
        google_falso.errores.append(ErrorDeGoogle("quota", "429"))

        r = cliente.get(
            "/api/v1/calendario/google?desde=2026-08-02&hasta=2026-08-03"
        )

        assert r.status_code == 503
        assert "[quota]" in r.json()["detail"]

    def test_google_caido_es_503_de_red(self, cliente, google_falso, tokens_falsos):
        tokens_falsos.conexion = _conexion_viva()
        google_falso.errores.append(ErrorDeGoogle("red", "timeout"))

        r = cliente.get(
            "/api/v1/calendario/google?desde=2026-08-02&hasta=2026-08-03"
        )

        assert r.status_code == 503
        assert "[red]" in r.json()["detail"]

    def test_sin_configuracion_de_credenciales_tambien_es_503(
        self, cliente, google_falso, tokens_falsos, monkeypatch
    ):
        # El usuario SI esta conectado pero el servidor perdio sus claves:
        # tiene que verse como problema del despliegue, no de la conexion.
        tokens_falsos.conexion = _conexion_viva()
        monkeypatch.setattr(
            settings_module,
            "_settings",
            settings_module.Settings(VERIFY_SCHEMA_ON_STARTUP=False),
        )
        google_falso.errores.append(ErrorDeGoogle("config", "sin client_id"))

        r = cliente.get("/api/v1/calendario/google?desde=2026-08-01&hasta=2026-08-31")

        assert r.status_code == 503
        assert "[config]" in r.json()["detail"]

    def test_un_access_token_vencido_se_renova_una_vez_y_sigue(
        self, cliente, google_falso, tokens_falsos
    ):
        from infrastructure.adapters.outbound.google.token_cipher import cifrar

        tokens_falsos.conexion = TokensDeConexion(
            user_id=USUARIO.id,
            refresh_token_cifrado=cifrar("el-refresh-token"),
            access_token="at-vencido",
            access_expira_en=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        google_falso.tokens_de_exchange = _tokens_nuevos()
        google_falso.respuestas.append(self._ventana())

        r = cliente.get(
            "/api/v1/calendario/google?desde=2026-08-01&hasta=2026-08-31"
        )

        assert r.status_code == 200
        assert len(google_falso.refreshes) == 1


class TestAislamientoDelCalendarioPropio:
    def test_las_rutas_del_calendario_propio_no_existen_en_este_router(self):
        # La garantia de aislamiento empieza por el mapa: /calendario es de
        # calendar_router y nada de Google la comparte.
        caminos = {r.path for r in router.routes}
        assert "/api/v1/calendario" not in caminos
