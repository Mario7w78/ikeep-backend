"""Tests del endpoint conversacional."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.services.assistant.conversation import (
    Propuesta,
    ResultadoConversacion,
)
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.inbound.api.v1.assistant_router import (
    get_conversation_service_factory,
    router,
)
from schemas.assistant import Borrador

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt-del-usuario"


@pytest.fixture
def servicio():
    return Mock()


@pytest.fixture
def client(servicio):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_conversation_service_factory] = (
        lambda: lambda _token, _modelo: servicio
    )

    with TestClient(app) as c:
        yield c


class TestAutenticacion:
    def test_exige_token(self, servicio):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_conversation_service_factory] = (
            lambda: lambda _t, _m: servicio
        )

        with TestClient(app) as c:
            respuesta = c.post("/api/v1/asistente/conversar", json={"mensaje": "hola"})

        assert respuesta.status_code == 401


class TestConversar:
    def test_devuelve_una_pregunta(self, client, servicio):
        servicio.responder.return_value = ResultadoConversacion(
            tipo="pregunta",
            mensaje="Que dias?",
            borrador=Borrador(name="Calculo"),
            turnos=[{"role": "user", "content": "calculo"}],
        )

        respuesta = client.post(
            "/api/v1/asistente/conversar", json={"mensaje": "clase de calculo"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["tipo"] == "pregunta"
        assert respuesta.json()["mensaje"] == "Que dias?"

    def test_devuelve_el_borrador_para_que_el_cliente_lo_reenvie(self, client, servicio):
        """El backend es stateless: la memoria de la conversacion viaja."""
        servicio.responder.return_value = ResultadoConversacion(
            tipo="pregunta",
            mensaje="Que dias?",
            borrador=Borrador(name="Calculo"),
            turnos=[],
        )

        respuesta = client.post(
            "/api/v1/asistente/conversar", json={"mensaje": "calculo"}
        )

        assert respuesta.json()["borrador"]["name"] == "Calculo"

    def test_recibe_el_borrador_previo(self, client, servicio):
        servicio.responder.return_value = ResultadoConversacion(
            tipo="pregunta", mensaje="ok", borrador=Borrador(), turnos=[]
        )

        client.post(
            "/api/v1/asistente/conversar",
            json={"mensaje": "los martes", "borrador": {"name": "Calculo"}},
        )

        assert servicio.responder.call_args.kwargs["borrador"].name == "Calculo"

    def test_devuelve_una_propuesta(self, client, servicio):
        servicio.responder.return_value = ResultadoConversacion(
            tipo="propuesta",
            mensaje=None,
            borrador=Borrador(name="Calculo"),
            turnos=[],
            propuesta=Propuesta(tipo="crear", borrador=Borrador(name="Calculo")),
        )

        respuesta = client.post("/api/v1/asistente/conversar", json={"mensaje": "dale"})

        assert respuesta.json()["tipo"] == "propuesta"
        assert respuesta.json()["propuesta"]["tipo"] == "crear"

    def test_una_eliminacion_lleva_el_id(self, client, servicio):
        servicio.responder.return_value = ResultadoConversacion(
            tipo="propuesta",
            mensaje=None,
            borrador=Borrador(),
            turnos=[],
            propuesta=Propuesta(tipo="eliminar", activity_id="act-9"),
        )

        respuesta = client.post("/api/v1/asistente/conversar", json={"mensaje": "borra"})

        assert respuesta.json()["propuesta"]["activity_id"] == "act-9"


class TestValidacion:
    def test_rechaza_un_mensaje_vacio(self, client, servicio):
        respuesta = client.post("/api/v1/asistente/conversar", json={"mensaje": ""})

        assert respuesta.status_code == 422
        servicio.responder.assert_not_called()

    def test_rechaza_un_mensaje_desmedido(self, client, servicio):
        respuesta = client.post(
            "/api/v1/asistente/conversar", json={"mensaje": "a" * 2000}
        )

        assert respuesta.status_code == 422

    def test_rechaza_un_historial_desmedido(self, client, servicio):
        """Sin tope, un cliente podria hacer crecer el prompt sin limite."""
        respuesta = client.post(
            "/api/v1/asistente/conversar",
            json={
                "mensaje": "hola",
                "turnos": [{"role": "user", "content": "x"}] * 100,
            },
        )

        assert respuesta.status_code == 422

    def test_sin_borrador_arranca_uno_vacio(self, client, servicio):
        servicio.responder.return_value = ResultadoConversacion(
            tipo="pregunta", mensaje="ok", borrador=Borrador(), turnos=[]
        )

        respuesta = client.post("/api/v1/asistente/conversar", json={"mensaje": "hola"})

        assert respuesta.status_code == 200
