"""Job enqueueing — the producer half of the worker contract."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job


def test_enqueue_job_returns_201_pending(client: TestClient, db_session: Session) -> None:
    response = client.post("/api/jobs", json={"payload": "demo"})
    assert response.status_code == 201

    created = response.json()
    assert created["status"] == "pending"
    assert created["attempts"] == 0
    assert created["payload"] == "demo"

    stored = db_session.get(Job, created["id"])
    assert stored is not None
    assert stored.status == "pending"


def test_list_jobs_includes_status_counts(client: TestClient, db_session: Session) -> None:
    pending_id = client.post("/api/jobs", json={"payload": "still queued"}).json()["id"]
    done_id = client.post("/api/jobs", json={"payload": "already finished"}).json()["id"]

    finished = db_session.get(Job, done_id)
    assert finished is not None
    finished.status = "done"
    db_session.commit()

    body = client.get("/api/jobs").json()
    ids = {job["id"] for job in body["jobs"]}
    assert {pending_id, done_id} <= ids

    counts = body["counts"]
    assert counts["pending"] >= 1
    assert counts["done"] >= 1
    assert counts["failed"] >= 0
    assert sum(counts.values()) == len(db_session.execute(select(Job)).scalars().all())


def test_enqueue_rejects_empty_payload(client: TestClient) -> None:
    assert client.post("/api/jobs", json={"payload": ""}).status_code == 422
