"""Test fixtures for the api service.

The suite talks to a real Postgres — the queries under test (``SELECT 1``,
``now()`` defaults, the check constraint on ``jobs.status``) are only
meaningful against the real engine. Point it somewhere else with
``TEST_DATABASE_URL``.

It talks to its *own* database, ``preview_test``, never the application's
``preview``. The fixtures below build the schema with ``create_all``, which
writes no ``alembic_version`` row; against the application database that
leaves tables Alembic believes it still has to create, and the next
``alembic upgrade head`` — the ``migrate`` service in docker compose — dies
with ``DuplicateTable: relation "widgets" already exists``. A separate
database keeps the test run from ever touching the migration state.

The test database is created on demand from the server's ``postgres``
maintenance database, so a bare ``docker compose up -d postgres && pytest``
works with no setup step.

If no server answers, every test is skipped with a clear reason instead of
hanging on a TCP connect: the connection attempt has a hard 3 second timeout.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://preview:preview@localhost:5432/preview_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
#: Database used to connect when the test database may not exist yet.
MAINTENANCE_DATABASE = "postgres"
CONNECT_TIMEOUT_SECONDS = 3

# Must happen before `app.config` is imported anywhere, since the settings
# object is built from the environment and cached for the process.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("GIT_SHA", "abc1234deadbeef")
os.environ.setdefault("PR_NUMBER", "4242")
os.environ.setdefault("APP_ENV", "test")
# 0 disables the metrics server. Every test in this suite imports the app and
# runs its lifespan; binding a real port would make the suite fail whenever
# 9000 is busy, and would leave a listening socket behind.
os.environ.setdefault("METRICS_PORT", "0")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import URL, Engine, make_url  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

TEST_URL = make_url(TEST_DATABASE_URL)
MAINTENANCE_URL = TEST_URL.set(database=MAINTENANCE_DATABASE)


def _make_engine(url: URL | str = TEST_DATABASE_URL, **kwargs: object) -> Engine:
    return create_engine(
        url,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
        poolclass=None,
        future=True,
        **kwargs,
    )


def _connect_failure(url: URL) -> SQLAlchemyError | None:
    """Return the error from opening ``url``, or None when it answers."""
    engine = _make_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return exc
    finally:
        engine.dispose()
    return None


def _database_unavailable_reason() -> str | None:
    """Return a human-readable reason, or None when the server is usable.

    The probe targets the maintenance database first: the test database is
    allowed not to exist yet, since ``_ensure_test_database`` creates it. The
    test database itself is the fallback, for servers that keep ``postgres``
    off-limits but hand out the database we actually want.
    """
    failure = _connect_failure(MAINTENANCE_URL)
    if failure is None:
        return None
    failure = _connect_failure(TEST_URL) or failure
    if failure is None:
        return None
    return (
        f"no database server behind {TEST_DATABASE_URL} ({type(failure).__name__}). "
        "Start one with `docker compose up -d postgres`, or set TEST_DATABASE_URL."
    )


def _ensure_test_database() -> None:
    """Create the test database if the server does not have it yet.

    ``CREATE DATABASE`` cannot run inside a transaction block, hence
    AUTOCOMMIT. Failures are only fatal when the test database is still
    unreachable afterwards — a locked-down maintenance database, or another
    suite winning the same race, are both fine.
    """
    try:
        engine = _make_engine(MAINTENANCE_URL, isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as connection:
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": TEST_URL.database},
                ).scalar()
                if exists:
                    return
                quoted = engine.dialect.identifier_preparer.quote(str(TEST_URL.database))
                connection.execute(text(f"CREATE DATABASE {quoted}"))
        finally:
            engine.dispose()
    except SQLAlchemyError:
        if _connect_failure(TEST_URL) is not None:
            raise


_SKIP_REASON = _database_unavailable_reason()


#: Fixtures that imply "this test needs a live database".
DATABASE_FIXTURES = frozenset({"engine", "db_session", "client"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip only the tests that actually need Postgres, and say why."""
    if _SKIP_REASON is None:
        return
    marker = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if DATABASE_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(marker)


@pytest.fixture(scope="session")
def engine():
    if _SKIP_REASON is not None:  # pragma: no cover - defensive
        pytest.skip(_SKIP_REASON)
    _ensure_test_database()
    engine = _make_engine()
    # checkfirst so the api and worker suites can share one test database:
    # both declare ``jobs`` identically, and whoever runs second finds it.
    Base.metadata.create_all(engine, checkfirst=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    """A session whose writes are always rolled back.

    The session joins an outer connection-level transaction as a savepoint, so
    application code is free to call ``commit()`` while the test still leaves
    the database exactly as it found it.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """TestClient wired to the rolled-back session."""

    def override_get_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
