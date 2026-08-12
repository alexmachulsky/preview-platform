"""FastAPI application for the Preview Platform demo workload.

Contract with the rest of the platform:

* listens on ``0.0.0.0:8000``
* ``/healthz`` is the liveness probe and never touches the database
* ``/readyz`` is the readiness probe and does exactly one ``SELECT 1``
* ``/metrics`` is served on a *separate* port (``METRICS_PORT``, default 9000)
  and never on the public application port, because the Ingress routes ``/``
  there. Metric names are the instrumentator's defaults
  (``http_requests_total``, ``http_request_duration_seconds``)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import Gauge, start_http_server
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.logging_config import configure_logging
from app.models import Job, Widget
from app.schemas import (
    HealthOut,
    JobCounts,
    JobCreate,
    JobListOut,
    JobOut,
    VersionOut,
    WidgetCreate,
    WidgetOut,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
LANDING_PAGE_ITEMS = 6

logger = logging.getLogger("app.api")

BUILD_INFO = Gauge(
    "api_build_info",
    "Build and environment identity of the running API, always 1.",
    ["git_sha", "pr_number", "app_env"],
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        service="api",
        git_sha=settings.git_sha,
        pr_number=settings.pr_number,
        app_env=settings.app_env,
    )
    BUILD_INFO.labels(
        git_sha=settings.git_sha,
        pr_number=settings.pr_number,
        app_env=settings.app_env,
    ).set(1)
    if settings.metrics_port:
        # Daemon thread; dies with the process. Started here rather than at
        # import time so the test suite, which imports this module, does not
        # bind a port.
        start_http_server(settings.metrics_port)
        logger.info(
            "metrics server listening",
            extra={"event": "startup", "port": settings.metrics_port},
        )

    logger.info("api starting", extra={"event": "startup"})
    yield
    logger.info("api stopping", extra={"event": "shutdown"})


app = FastAPI(
    title="Preview Platform API",
    description="Demo workload for ephemeral per-pull-request environments.",
    version="0.1.0",
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Default metric set on purpose: the Grafana dashboard queries
# http_requests_total and http_request_duration_seconds by name.
# `.instrument(app)` without `.expose(app)`. Exposing would mount /metrics on
# the application port, and the Ingress routes `/` there — publishing internal
# request rates, handler paths and latencies to anyone who can reach the
# preview URL. The metrics server below binds a separate port instead, which
# Prometheus reaches through the Service; scrapes never traverse the Ingress.
Instrumentator(
    should_group_status_codes=True,
    excluded_handlers=["/metrics", "/healthz"],
).instrument(app)


def _job_counts(session: Session) -> JobCounts:
    rows = session.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    known = {name: count for name, count in rows if name in JobCounts.model_fields}
    return JobCounts(**known)


# ── Operational endpoints ────────────────────────────────────────────────────


@app.get("/healthz", response_model=HealthOut, tags=["ops"])
def healthz() -> HealthOut:
    """Liveness. Deliberately dependency-free: a slow database must not
    convince the kubelet to restart a perfectly healthy process."""
    return HealthOut(status="ok")


@app.get("/readyz", response_model=HealthOut, tags=["ops"])
def readyz(session: Session = Depends(get_session)) -> Response:
    """Readiness — 200 once the database answers, 503 while it does not."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("readiness check failed", extra={"event": "readyz", "error": str(exc)})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=HealthOut(status="unavailable", detail="database unreachable").model_dump(),
        )
    return JSONResponse(content=HealthOut(status="ok", detail="database reachable").model_dump())


@app.get("/version", response_model=VersionOut, tags=["ops"])
def version(settings: Settings = Depends(get_settings)) -> VersionOut:
    """What is actually running here."""
    return VersionOut(
        service="api",
        git_sha=settings.git_sha,
        pr_number=settings.pr_number,
        app_env=settings.app_env,
    )


# ── Widgets ──────────────────────────────────────────────────────────────────


@app.get("/api/widgets", response_model=list[WidgetOut], tags=["widgets"])
def list_widgets(session: Session = Depends(get_session)) -> list[Widget]:
    return list(session.execute(select(Widget).order_by(Widget.id)).scalars().all())


@app.post(
    "/api/widgets",
    response_model=WidgetOut,
    status_code=status.HTTP_201_CREATED,
    tags=["widgets"],
)
def create_widget(body: WidgetCreate, session: Session = Depends(get_session)) -> Widget:
    widget = Widget(name=body.name, color=body.color)
    session.add(widget)
    session.commit()
    session.refresh(widget)
    logger.info(
        "widget created",
        extra={"event": "widget.created", "widget_id": widget.id, "name": widget.name},
    )
    return widget


# ── Jobs ─────────────────────────────────────────────────────────────────────


@app.get("/api/jobs", response_model=JobListOut, tags=["jobs"])
def list_jobs(session: Session = Depends(get_session)) -> JobListOut:
    jobs = session.execute(select(Job).order_by(Job.id)).scalars().all()
    return JobListOut(
        jobs=[JobOut.model_validate(job) for job in jobs],
        counts=_job_counts(session),
    )


@app.post(
    "/api/jobs",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
    tags=["jobs"],
)
def create_job(body: JobCreate, session: Session = Depends(get_session)) -> Job:
    job = Job(payload=body.payload, status="pending", attempts=0)
    session.add(job)
    session.commit()
    session.refresh(job)
    logger.info("job enqueued", extra={"event": "job.enqueued", "job_id": job.id})
    return job


# ── Landing page ─────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """The page a reviewer lands on from the PR comment.

    It must answer "which preview am I looking at, and is it alive?" in under
    a second, so it degrades to a still-useful page when the database is down
    rather than returning a 500.
    """
    widgets: list[Widget] = []
    jobs: list[Job] = []
    counts = JobCounts()
    widget_count = 0
    db_online = True

    try:
        widget_count = session.scalar(select(func.count()).select_from(Widget)) or 0
        widgets = list(
            session.execute(select(Widget).order_by(Widget.id.desc()).limit(LANDING_PAGE_ITEMS))
            .scalars()
            .all()
        )
        jobs = list(
            session.execute(select(Job).order_by(Job.id.desc()).limit(LANDING_PAGE_ITEMS))
            .scalars()
            .all()
        )
        counts = _job_counts(session)
    except SQLAlchemyError as exc:
        db_online = False
        logger.warning(
            "landing page rendered without database",
            extra={"event": "index.degraded", "error": str(exc)},
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "settings": settings,
            "hue": settings.hue,
            "short_sha": settings.short_sha,
            "db_online": db_online,
            "widget_count": widget_count,
            "widgets": widgets,
            "jobs": jobs,
            "counts": counts,
            "job_total": counts.total,
        },
    )
