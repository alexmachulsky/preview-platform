"""Liveness, readiness, version and metrics — the endpoints Kubernetes and
Prometheus depend on."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
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
def test_metrics_exposes_expected_names(client: TestClient, metric: str) -> None:
    client.get("/version")  # generate at least one observation
    body = client.get("/metrics").text
    assert metric in body
