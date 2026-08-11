"""The landing page — the demo surface a reviewer actually looks at."""

from __future__ import annotations

from itertools import pairwise

from fastapi.testclient import TestClient

from app.config import Settings


def test_index_renders_environment_identity(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    html = response.text
    assert "PR #4242" in html
    assert "abc1234" in html  # short sha, not the full one
    assert "<b>test</b>" in html  # app env chip
    assert f"--hue: {Settings(pr_number='4242').hue}" in html


def test_index_has_no_external_assets(client: TestClient) -> None:
    """The cluster has no egress guarantees: nothing may be fetched remotely."""
    html = client.get("/").text
    assert 'src="http' not in html
    assert 'href="http' not in html
    assert "//cdn" not in html


def test_index_shows_live_counts(client: TestClient) -> None:
    client.post("/api/widgets", json={"name": "Rendered Widget", "color": "#00ffcc"})
    client.post("/api/jobs", json={"payload": "rendered job"})

    html = client.get("/").text
    assert "Rendered Widget" in html
    assert "rendered job" in html


def _hue_distance(left: int, right: int) -> int:
    """Shortest distance between two hues on the colour wheel."""
    delta = abs(left - right) % 360
    return min(delta, 360 - delta)


def test_hue_is_deterministic() -> None:
    assert Settings(pr_number="42").hue == Settings(pr_number="42").hue
    assert 0 <= Settings(pr_number="42").hue < 360
    assert 0 <= Settings(pr_number="local").hue < 360


def test_consecutive_pull_requests_get_obviously_different_hues() -> None:
    """Neighbouring previews are the ones a reviewer sees side by side."""
    hues = [Settings(pr_number=str(number)).hue for number in range(1, 25)]

    for left, right in pairwise(hues):
        assert _hue_distance(left, right) >= 60, f"{left}° and {right}° are too close"

    assert len(set(hues)) == len(hues)
