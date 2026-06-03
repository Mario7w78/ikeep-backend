"""Tests for ErrorHandlerMiddleware.

Verifies that domain exceptions, validation errors, and unexpected
errors are properly caught and returned as structured JSON.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.adapters.inbound.api.middleware import (
    ErrorHandlerMiddleware,
    DomainException,
    SolverException,
    ValidationException,
)


@pytest.fixture
def app():
    """Create a minimal app with the error middleware for testing."""
    app = FastAPI()
    app.add_middleware(ErrorHandlerMiddleware)

    @app.get("/ok")
    def ok():
        return {"status": "ok"}

    @app.get("/domain-error")
    def domain_error():
        raise DomainException("Schedule is invalid", detail={"field": "tasks"})

    @app.get("/solver-error")
    def solver_error():
        raise SolverException("No feasible solution found")

    @app.get("/validation-error")
    def validation_error():
        raise ValidationException("Invalid duration")

    @app.get("/value-error")
    def value_error():
        raise ValueError("Bad input data")

    @app.get("/type-error")
    def type_error():
        raise TypeError("Unexpected type")

    @app.get("/runtime-error")
    def runtime_error():
        raise RuntimeError("Something broke")

    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


class TestErrorHandlerMiddleware:
    def test_ok_returns_normal_response(self, client):
        response = client.get("/ok")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_domain_exception_returns_422(self, client):
        response = client.get("/domain-error")
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "DomainException"
        assert data["message"] == "Schedule is invalid"
        assert data["detail"] == {"field": "tasks"}

    def test_solver_exception_returns_409(self, client):
        response = client.get("/solver-error")
        assert response.status_code == 409
        data = response.json()
        assert data["error"] == "SolverException"
        assert "No feasible solution" in data["message"]

    def test_validation_exception_returns_422(self, client):
        response = client.get("/validation-error")
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "ValidationException"

    def test_value_error_returns_422(self, client):
        response = client.get("/value-error")
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "ValidationException"
        assert data["message"] == "Bad input data"

    def test_type_error_returns_500(self, client):
        """TypeError is caught by Starlette's exception handler before our middleware."""
        response = client.get("/type-error")
        assert response.status_code == 500

    def test_unhandled_error_returns_500(self, client):
        response = client.get("/runtime-error")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "InternalServerError"
        assert "unexpected" in data["message"].lower()

    def test_error_response_has_consistent_shape(self, client):
        """All error responses should have error, message, and optionally detail."""
        for path in ["/domain-error", "/solver-error", "/value-error", "/runtime-error"]:
            response = client.get(path)
            data = response.json()
            assert "error" in data, f"Missing 'error' in response from {path}"
            assert "message" in data, f"Missing 'message' in response from {path}"
