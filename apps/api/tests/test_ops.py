"""Liveness, readiness, version and metrics — the endpoints Kubernetes and
Prometheus depend on."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app


def test_healthz_is_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "detail": None}


def test_healthz_never_touches_the_database() -> None:
    """Liveness must answer even when every database call would explode."""

    def exploding_session() -> Iterator[object]:
        raise AssertionError("/healthz must not request a database session")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = exploding_session
    try:
        with TestClient(app) as isolated:
            response = isolated.get("/healthz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_503_when_database_unreachable(db_session) -> None:
    class BrokenSession:
        def execute(self, *args: object, **kwargs: object) -> None:
            raise OperationalError("SELECT 1", None, Exception("connection refused"))

    def broken() -> Iterator[BrokenSession]:
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken
    try:
        with TestClient(app) as isolated:
            response = isolated.get("/readyz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_version_reports_build_identity(client: TestClient) -> None:
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "service": "api",
        "git_sha": "abc1234deadbeef",
        "pr_number": "4242",
        "app_env": "test",
    }


@pytest.mark.parametrize(
    "metric",
    ["http_requests_total", "http_request_duration_seconds", "api_build_info"],
)
def test_metrics_are_collected(client: TestClient, metric: str) -> None:
    """The instrumentator still records everything the dashboard queries.

    Read from the registry rather than over HTTP: the metrics endpoint is no
    longer mounted on the application, and the separate server it now runs on
    is not started under test (metrics_port is 0 there).
    """
    client.get("/version")  # generate at least one observation
    body = generate_latest(REGISTRY).decode()
    assert metric in body


def test_metrics_are_not_served_on_the_public_port(client: TestClient) -> None:
    """Regression test for a real finding.

    The Ingress routes `/` to the application port, so anything mounted there
    is reachable at the preview URL. /metrics used to be, publishing internal
    request rates, handler paths and latencies to anyone with the link. It now
    lives on its own port that only Prometheus reaches, via the Service.
    """
    assert client.get("/metrics").status_code == 404
