"""El adaptador REST de Google, contra un Google falso (respx).

Nada de red: respx intercepta httpx y contesta lo que Google contestaria,
incluidos los errores con su forma real — el cuerpo `{"error":
"invalid_grant"}` del endpoint de tokens, el 410 del syncToken vencido.
"""

from datetime import datetime, timezone

import httpx
import pytest
import respx

from domain.ports.outbound.google_calendar_port import ErrorDeGoogle
from infrastructure.adapters.outbound.google.calendar_client import (
    HttpxGoogleCalendar,
)
from infrastructure.config import settings as settings_module

URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_EVENTOS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

DESDE = datetime(2026, 8, 1, tzinfo=timezone.utc)
HASTA = datetime(2026, 9, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _google_mockeado():
    # Todo test de este archivo habla con un Google falso: respx intercepta
    # httpx y contesta con la forma real de sus respuestas. Nada de red.
    with respx.mock:
        yield


@pytest.fixture
def credenciales(monkeypatch):
    monkeypatch.setattr(
        settings_module,
        "_settings",
        settings_module.Settings(
            VERIFY_SCHEMA_ON_STARTUP=False,
            GOOGLE_CLIENT_ID="cliente-id",
            GOOGLE_CLIENT_SECRET="cliente-secreto",
        ),
    )


@pytest.fixture
def google(credenciales):
    return HttpxGoogleCalendar()


class TestExchangeCode:
    def test_manda_pkce_y_devuelve_los_tokens(self, google):
        ruta = respx.post(URL_TOKEN).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "at-1",
                    "expires_in": 3600,
                    "refresh_token": "rt-1",
                },
            )
        )

        tokens = google.exchange_code("codigo", "verificador", "lotus://google/callback")

        assert (tokens.access_token, tokens.refresh_token) == ("at-1", "rt-1")
        enviado = ruta.calls[0].request.content.decode()
        for campo in (
            "grant_type=authorization_code",
            "code_verifier=verificador",
            "client_secret=cliente-secreto",
        ):
            assert campo in enviado

    def test_invalid_grant_es_permanente(self, google):
        respx.post(URL_TOKEN).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )

        with pytest.raises(ErrorDeGoogle) as capturado:
            google.exchange_code("viejo", "v", "r")

        assert capturado.value.clase == "invalid_grant"

    def test_sin_credenciales_es_error_de_configuracion(self):
        # Sin el fixture de credenciales: la config del entorno de test viene
        # vacia y eso TIENE que ser un 'config', no un crash.
        from infrastructure.config import settings as sm

        original = sm._settings
        sm._settings = sm.Settings(VERIFY_SCHEMA_ON_STARTUP=False)
        try:
            with pytest.raises(ErrorDeGoogle) as capturado:
                HttpxGoogleCalendar().exchange_code("c", "v", "r")
        finally:
            sm._settings = original

        assert capturado.value.clase == "config"


class TestRefresh:
    def test_el_refresh_token_no_cambia(self, google):
        respx.post(URL_TOKEN).mock(
            return_value=httpx.Response(
                200, json={"access_token": "at-2", "expires_in": 3600}
            )
        )

        tokens = google.refresh_access_token("rt-siempre")

        assert tokens.refresh_token == "rt-siempre"
        assert tokens.access_token == "at-2"

    def test_un_refresh_rechazado_es_invalid_grant(self, google):
        respx.post(URL_TOKEN).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )

        with pytest.raises(ErrorDeGoogle) as capturado:
            google.refresh_access_token("rt-revocado")

        assert capturado.value.clase == "invalid_grant"


class TestListEvents:
    def _respuesta_eventos(self, items, **extra):
        return httpx.Response(200, json={"items": items, **extra})

    def test_pide_single_events_true(self, google):
        ruta = respx.get(URL_EVENTOS).mock(
            return_value=self._respuesta_eventos([], nextSyncToken="st-1")
        )

        ventana = google.list_events("at", DESDE, HASTA)

        enviado = ruta.calls[0].request.url.params
        assert enviado["singleEvents"] == "true"
        assert ventana.sync_token == "st-1"

    def test_la_completa_va_acotada_a_la_ventana(self, google):
        ruta = respx.get(URL_EVENTOS).mock(
            return_value=self._respuesta_eventos([])
        )

        google.list_events("at", DESDE, HASTA)

        params = ruta.calls[0].request.url.params
        assert "timeMin" in params and "timeMax" in params
        assert "syncToken" not in params

    def test_el_incremental_lleva_sync_token_y_no_ventana(self, google):
        # Google rechaza timeMin/timeMax junto con syncToken: la marca trae
        # TODOS los cambios y filtrar es cosa nuestra.
        ruta = respx.get(URL_EVENTOS).mock(
            return_value=self._respuesta_eventos([])
        )

        google.list_events("at", DESDE, HASTA, sync_token="st-vigente")

        params = ruta.calls[0].request.url.params
        assert params["syncToken"] == "st-vigente"
        assert "timeMin" not in params

    def test_sigue_las_paginas_hasta_terminar(self, google):
        pagina_1 = self._respuesta_eventos(
            [{"id": "e1", "summary": "A", "start": {"dateTime": "2026-08-03T10:00:00Z"},
              "end": {"dateTime": "2026-08-03T11:00:00Z"}}],
            nextPageToken="pag-2",
        )
        pagina_2 = self._respuesta_eventos(
            [{"id": "e2", "summary": "B", "start": {"date": "2026-08-05"},
              "end": {"date": "2026-08-06"}}],
            nextSyncToken="st-final",
        )
        ruta = respx.get(URL_EVENTOS).mock(side_effect=[pagina_1, pagina_2])

        ventana = google.list_events("at", DESDE, HASTA)

        assert [e.id for e in ventana.eventos] == ["e1", "e2"]
        assert ventana.sync_token == "st-final"
        assert len(ruta.calls) == 2
        # La segunda pide la pagina que la primera anuncio.
        segunda_url = str(ruta.calls[1].request.url)
        assert "pageToken=pag-2" in segunda_url

    def test_todo_el_dia_se_marca_como_tal(self, google):
        respx.get(URL_EVENTOS).mock(
            return_value=self._respuesta_eventos(
                [{"id": "e", "summary": "Viaje",
                  "start": {"date": "2026-08-10"}, "end": {"date": "2026-08-12"}}],
                nextSyncToken="s",
            )
        )

        evento = google.list_events("at", DESDE, HASTA).eventos[0]

        assert evento.todo_el_dia is True
        assert evento.inicio.date().isoformat() == "2026-08-10"

    def test_un_401_pide_refrescar(self, google):
        respx.get(URL_EVENTOS).mock(return_value=httpx.Response(401))

        with pytest.raises(ErrorDeGoogle) as capturado:
            google.list_events("at-vencido", DESDE, HASTA)

        assert capturado.value.clase == "sesion"

    def test_un_410_significa_sync_token_muerto(self, google):
        respx.get(URL_EVENTOS).mock(return_value=httpx.Response(410))

        with pytest.raises(ErrorDeGoogle) as capturado:
            google.list_events("at", DESDE, HASTA, sync_token="st-muerto")

        assert capturado.value.clase == "gone"

    def test_la_cuota_es_distinguible_de_un_fallo_generico(self, google):
        respx.get(URL_EVENTOS).mock(
            return_value=httpx.Response(
                403, json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}}
            )
        )

        with pytest.raises(ErrorDeGoogle) as capturado:
            google.list_events("at", DESDE, HASTA)

        assert capturado.value.clase == "quota"


class TestRevoke:
    def test_revoca_con_el_token_en_el_cuerpo(self, google):
        ruta = respx.post("https://oauth2.googleapis.com/revoke").mock(
            return_value=httpx.Response(200)
        )

        google.revoke("rt-a-matar")

        assert "token=rt-a-matar" in ruta.calls[0].request.content.decode()

    def test_un_google_alcanzable_pero_enojado_no_es_crash(self, google):
        respx.post("https://oauth2.googleapis.com/revoke").mock(
            return_value=httpx.Response(400, json={"error": "invalid_token"})
        )

        with pytest.raises(ErrorDeGoogle):
            google.revoke("rt-raro")
