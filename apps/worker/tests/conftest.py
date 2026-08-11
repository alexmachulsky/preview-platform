"""Test fixtures for the worker service.

``SELECT ... FOR UPDATE SKIP LOCKED`` has no meaningful SQLite equivalent, so
the suite runs against a real Postgres. Override the target with
``TEST_DATABASE_URL``; if nothing is listening, the database-backed tests are
skipped with a clear reason after a 3 second connect timeout — never a hang.

The target is its *own* database, ``preview_test``, never the application's
``preview``. ``create_all`` below writes no ``alembic_version`` row, so a
suite run against the application database leaves tables that the api's
``alembic upgrade head`` still expects to create, and the ``migrate`` service
in docker compose then fails with ``DuplicateTable``. The test database is
created on demand from the server's ``postgres`` maintenance database, so a
bare ``docker compose up -d postgres && pytest`` works with no setup step.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from worker.models import Base

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://preview:preview@localhost:5432/preview_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
#: Database used to connect when the test database may not exist yet.
MAINTENANCE_DATABASE = "postgres"
CONNECT_TIMEOUT_SECONDS = 3

TEST_URL = make_url(TEST_DATABASE_URL)
MAINTENANCE_URL = TEST_URL.set(database=MAINTENANCE_DATABASE)

#: Fixtures that imply "this test needs a live database".
DATABASE_FIXTURES = frozenset({"engine", "db_session", "session_factory"})


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
    engine = _make_engine()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def connection(engine) -> Iterator[object]:
    """An outer transaction that is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture()
def session_factory(connection) -> sessionmaker[Session]:
    """A factory the worker code can use as if it owned the database.

    Sessions join the outer transaction as savepoints, so ``process_batch``
    commits for real and the test still leaves no trace behind.
    """
    return sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest.fixture()
def db_session(session_factory) -> Iterator[Session]:
    """A session for arranging fixtures and asserting on results."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
