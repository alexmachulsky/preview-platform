"""Widget creation and listing."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_widget_returns_201_and_persists(client: TestClient) -> None:
    response = client.post("/api/widgets", json={"name": "Test Widget", "color": "#ff00aa"})
    assert response.status_code == 201

    created = response.json()
    assert created["id"] > 0
    assert created["name"] == "Test Widget"
    assert created["color"] == "#ff00aa"
    assert created["created_at"]

    listed = client.get("/api/widgets")
    assert listed.status_code == 200
    assert any(widget["id"] == created["id"] for widget in listed.json())


def test_list_widgets_is_ordered_by_id(client: TestClient) -> None:
    for index in range(3):
        assert (
            client.post(
                "/api/widgets", json={"name": f"Ordered {index}", "color": "#123456"}
            ).status_code
            == 201
        )

    ids = [widget["id"] for widget in client.get("/api/widgets").json()]
    assert ids == sorted(ids)


def test_create_widget_rejects_empty_name(client: TestClient) -> None:
    response = client.post("/api/widgets", json={"name": "", "color": "#fff"})
    assert response.status_code == 422
