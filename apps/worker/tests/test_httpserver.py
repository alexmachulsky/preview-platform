"""The worker's metrics/health endpoint — no database involved."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from worker.httpserver import start_metrics_server
from worker.metrics import BUILD_INFO

TIMEOUT = 5


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    # Port 0 lets the OS pick a free port, so the suite never collides with a
    # worker already running on 9000.
    server = start_metrics_server(port=0, host="127.0.0.1")
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_healthz_returns_ok(base_url: str) -> None:
    status, body = _get(f"{base_url}/healthz")
    assert status == 200
    assert json.loads(body) == {"status": "ok", "service": "worker"}


def test_metrics_exposes_the_contract_metric_names(base_url: str) -> None:
    BUILD_INFO.labels(git_sha="abc1234", pr_number="4242", app_env="test").set(1)

    status, body = _get(f"{base_url}/metrics")
    assert status == 200

    for metric in (
        "worker_jobs_processed_total",
        "worker_jobs_failed_total",
        "worker_poll_iterations_total",
        "worker_build_info",
    ):
        assert metric in body

    assert 'worker_build_info{app_env="test",git_sha="abc1234",pr_number="4242"} 1.0' in body


def test_unknown_path_is_404(base_url: str) -> None:
    status, body = _get(f"{base_url}/nope")
    assert status == 404
    assert json.loads(body) == {"status": "not_found"}
