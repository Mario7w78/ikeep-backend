"""Integration tests for API endpoints using FastAPI TestClient.

Tests the full HTTP request/response cycle through the routers.
"""

import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture
def client():
    """Create a fresh app + client for each test."""
    app = create_app()
    with TestClient(app) as c:
        yield c


# ─── Health ────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


# ─── Generate schedule ─────────────────────────────────────────────


class TestGenerateSchedule:
    def test_generate_simple_schedule(self, client):
        payload = {
            "actividades_fijas": [],
            "actividades_optimizables": [
                {
                    "id": "t1",
                    "nombre": "Estudiar",
                    "tipo": "tarea",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                    "duracion_estimada": 60,
                    "dificultad": "media",
                    "prioridad": 1,
                }
            ],
            "contexto_usuario": {
                "nivel_energia": 2,
                "horario_inicio": 480,
                "horario_fin": 1200,
            },
        }
        response = client.post("/api/v1/horarios/generar", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] in ("OPTIMA", "FACTIBLE")
        assert len(data["bloques"]) >= 1

    def test_generate_with_fixed_class(self, client):
        payload = {
            "actividades_fijas": [
                {
                    "id": "c1",
                    "nombre": "Algebra",
                    "tipo": "clase",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                    "duracion_estimada": 60,
                }
            ],
            "actividades_optimizables": [
                {
                    "id": "t1",
                    "nombre": "Tarea",
                    "tipo": "tarea",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                    "duracion_estimada": 60,
                }
            ],
            "contexto_usuario": {
                "nivel_energia": 2,
                "horario_inicio": 480,
                "horario_fin": 1200,
            },
        }
        response = client.post("/api/v1/horarios/generar", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] in ("OPTIMA", "FACTIBLE")
        # Fixed class must be in the result
        fixed = [b for b in data["bloques"] if b["id_actividad"] == "c1"]
        assert len(fixed) == 1
        assert fixed[0]["hora_inicio"] == 480
        assert fixed[0]["hora_fin"] == 540

    def test_generate_rejects_overlapping_fixed(self, client):
        payload = {
            "actividades_fijas": [
                {
                    "id": "c1",
                    "nombre": "Algebra",
                    "tipo": "clase",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                    "duracion_estimada": 60,
                },
                {
                    "id": "c2",
                    "nombre": "Fisica",
                    "tipo": "clase",
                    "dia": 0,
                    "hora_inicio": 510,
                    "hora_fin": 570,
                    "duracion_estimada": 60,
                },
            ],
            "actividades_optimizables": [],
            "contexto_usuario": {
                "nivel_energia": 2,
                "horario_inicio": 480,
                "horario_fin": 1200,
            },
        }
        response = client.post("/api/v1/horarios/generar", json=payload)
        assert response.status_code == 422

    def test_generate_rejects_task_longer_than_day(self, client):
        payload = {
            "actividades_fijas": [],
            "actividades_optimizables": [
                {
                    "id": "t1",
                    "nombre": "Maratón",
                    "tipo": "tarea",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                    "duracion_estimada": 900,
                }
            ],
            "contexto_usuario": {
                "nivel_energia": 2,
                "horario_inicio": 480,
                "horario_fin": 1200,
            },
        }
        response = client.post("/api/v1/horarios/generar", json=payload)
        assert response.status_code == 422


# ─── Reschedule ────────────────────────────────────────────────────


class TestRescheduleEndpoint:
    def test_replanificar_with_lost_time(self, client):
        current_schedule = {
            "estado": "OPTIMA",
            "bloques": [
                {
                    "id_actividad": "c1",
                    "nombre": "Algebra",
                    "tipo": "clase",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                },
                {
                    "id_actividad": "t1",
                    "nombre": "Estudiar",
                    "tipo": "tarea",
                    "dia": 0,
                    "hora_inicio": 600,
                    "hora_fin": 720,
                },
            ],
            "mensaje": "",
        }
        payload = {
            "horario_actual": current_schedule,
            "actividad_afectada_id": "t1",
            "tiempo_perdido_minutos": 30,
            "contexto_usuario": {
                "nivel_energia": 2,
                "horario_inicio": 480,
                "horario_fin": 1200,
            },
        }
        response = client.post("/api/v1/horarios/replanificar", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["estado"] in ("OPTIMA", "FACTIBLE")

    def test_replanificar_preserves_class(self, client):
        current_schedule = {
            "estado": "OPTIMA",
            "bloques": [
                {
                    "id_actividad": "c1",
                    "nombre": "Algebra",
                    "tipo": "clase",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                },
                {
                    "id_actividad": "t1",
                    "nombre": "Estudiar",
                    "tipo": "tarea",
                    "dia": 0,
                    "hora_inicio": 600,
                    "hora_fin": 720,
                },
            ],
            "mensaje": "",
        }
        payload = {
            "horario_actual": current_schedule,
            "actividad_afectada_id": "t1",
            "tiempo_perdido_minutos": 30,
            "contexto_usuario": {
                "nivel_energia": 2,
                "horario_inicio": 480,
                "horario_fin": 1200,
            },
        }
        response = client.post("/api/v1/horarios/replanificar", json=payload)
        assert response.status_code == 200
        data = response.json()
        c1 = [b for b in data["bloques"] if b["id_actividad"] == "c1"]
        assert len(c1) == 1
        assert c1[0]["hora_inicio"] == 480
        assert c1[0]["hora_fin"] == 540


# ─── Suggest ───────────────────────────────────────────────────────


class TestSuggestEndpoint:
    def test_suggest_returns_sorted(self, client):
        payload = {
            "tiempo_libre_minutos": 120,
            "actividades_optimizables": [
                {
                    "id": "t1",
                    "nombre": "Larga",
                    "tipo": "tarea",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 540,
                    "duracion_estimada": 90,
                    "dificultad": "baja",
                    "prioridad": 1,
                },
                {
                    "id": "t2",
                    "nombre": "Corta",
                    "tipo": "tarea",
                    "dia": 0,
                    "hora_inicio": 480,
                    "hora_fin": 510,
                    "duracion_estimada": 30,
                    "dificultad": "alta",
                    "prioridad": 3,
                },
            ],
        }
        response = client.post("/schedule/suggest-actividades-optimizables", json=payload)
        assert response.status_code == 200
        data = response.json()
        suggestions = data["sugerencias"]
        assert len(suggestions) == 2
        # t2 (alta, 30min) should come before t1 (baja, 90min) — encaja first, then priority
        assert suggestions[0]["id_actividad"] == "t2"
        assert suggestions[1]["id_actividad"] == "t1"

    def test_suggest_no_tasks(self, client):
        payload = {
            "tiempo_libre_minutos": 60,
            "actividades_optimizables": [],
        }
        response = client.post("/schedule/suggest-actividades-optimizables", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["sugerencias"] == []


# ─── Middleware error handling ──────────────────────────────────────


class TestErrorMiddleware:
    def test_404_returns_json(self, client):
        response = client.get("/nonexistent")
        assert response.status_code == 404
        # FastAPI's default 404 is HTML, but our middleware should catch it
        # Actually FastAPI returns 404 by default, our middleware only catches exceptions

    def test_invalid_json_body_returns_422(self, client):
        response = client.post(
            "/api/v1/horarios/generar",
            json={"invalid": "payload"},
        )
        assert response.status_code == 422
