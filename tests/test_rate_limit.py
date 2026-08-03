"""Tests for the per-IP rate limiter on the LLM-backed endpoints.

The limiter is mounted directly on a bare app here rather than through
create_app(), so these tests do not depend on the DI container or on any
provider credentials.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.adapters.inbound.api.rate_limit import RateLimitMiddleware


def build_app(requests_per_minute: int = 3) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=requests_per_minute,
    )

    @app.post("/api/v1/horarios/parse-nl-conversation")
    def limited():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/horarios/generar")
    def solver():
        return {"ok": True}

    return app


@pytest.fixture
def client():
    with TestClient(build_app()) as c:
        yield c


class TestRateLimit:
    def test_allows_requests_under_the_limit(self, client):
        for _ in range(3):
            assert client.post("/api/v1/horarios/parse-nl-conversation").status_code == 200

    def test_blocks_once_the_limit_is_exceeded(self, client):
        for _ in range(3):
            client.post("/api/v1/horarios/parse-nl-conversation")

        response = client.post("/api/v1/horarios/parse-nl-conversation")

        assert response.status_code == 429
        assert response.json()["error"] == "RateLimitExceeded"
        assert int(response.headers["Retry-After"]) > 0

    def test_health_is_never_limited(self, client):
        # The warm-up ping and the uptime cron must always get through.
        for _ in range(10):
            assert client.get("/health").status_code == 200

    def test_solver_endpoint_is_not_limited(self, client):
        # Only the endpoints that spend provider quota are throttled.
        for _ in range(10):
            assert client.post("/api/v1/horarios/generar").status_code == 200

    def test_limit_is_tracked_per_ip(self, client):
        for _ in range(3):
            client.post("/api/v1/horarios/parse-nl-conversation")

        other_ip = client.post(
            "/api/v1/horarios/parse-nl-conversation",
            headers={"X-Forwarded-For": "203.0.113.9"},
        )

        assert other_ip.status_code == 200

    def test_zero_disables_the_limiter(self):
        with TestClient(build_app(requests_per_minute=0)) as c:
            for _ in range(10):
                assert c.post("/api/v1/horarios/parse-nl-conversation").status_code == 200
