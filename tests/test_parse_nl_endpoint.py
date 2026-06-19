"""Integration tests for POST /api/v1/horarios/parse-nl endpoint.

Tests the full HTTP request/response cycle through the router.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from schemas.parse_nl import ParseNLResponse, ParsedSchedule
from main import create_app


@pytest.fixture
def client():
    """Create a fresh app with mocked LLM adapter for each test."""
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestParseNLEndpoint:
    def test_parse_nl_returns_200_with_valid_input(self, client):
        """Happy path: a valid text returns 200 with parsed data."""
        # Override the container's LLM adapter with a mock
        from unittest.mock import MagicMock
        from domain.ports.outbound.llm_port import LLMPort

        mock_adapter = MagicMock(spec=LLMPort)
        mock_adapter.generate.return_value = ParseNLResponse(
            name="Futbol",
            activity_type="tarea",
            schedule=[ParsedSchedule(day="Lunes", start_time=1080, end_time=1140)],
            location="Polideportivo",
            confidence=0.95,
            missing_fields=[],
        )
        client.app.container.llm_adapter.override(mock_adapter)

        response = client.post(
            "/api/v1/horarios/parse-nl",
            json={"text": "futbol los lunes de 18 a 19"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Futbol"
        assert data["confidence"] == 0.95
        assert len(data["schedule"]) == 1
        assert data["schedule"][0]["day"] == "lunes"

    def test_parse_nl_empty_text_returns_422(self, client):
        """Empty text should return 422 validation error."""
        response = client.post(
            "/api/v1/horarios/parse-nl",
            json={"text": ""},
        )
        assert response.status_code == 422

    def test_parse_nl_missing_text_returns_422(self, client):
        """Missing text field should return 422 validation error."""
        response = client.post(
            "/api/v1/horarios/parse-nl",
            json={},
        )
        assert response.status_code == 422

    def test_parse_nl_llm_failure_returns_503(self, client):
        """LLM service failure should return 503."""
        from unittest.mock import MagicMock
        from domain.ports.outbound.llm_port import LLMPort
        from infrastructure.adapters.inbound.api.middleware import (
            LLMServiceException,
        )

        mock_adapter = MagicMock(spec=LLMPort)
        mock_adapter.generate.side_effect = LLMServiceException(
            "Gemini API error"
        )
        client.app.container.llm_adapter.override(mock_adapter)

        response = client.post(
            "/api/v1/horarios/parse-nl",
            json={"text": "futbol los lunes"},
        )
        assert response.status_code == 503
        data = response.json()
        assert "error" in data
        assert "message" in data

    def test_parse_nl_partial_info_returns_200(self, client):
        """Partial info returns 200 with missing_fields populated."""
        from unittest.mock import MagicMock
        from domain.ports.outbound.llm_port import LLMPort

        mock_adapter = MagicMock(spec=LLMPort)
        mock_adapter.generate.return_value = ParseNLResponse(
            name="Estudio",
            missing_fields=["schedule", "location"],
        )
        client.app.container.llm_adapter.override(mock_adapter)

        response = client.post(
            "/api/v1/horarios/parse-nl",
            json={"text": "estudio"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Estudio"
        assert "schedule" in data["missing_fields"]
