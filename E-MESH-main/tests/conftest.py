"""
Test configuration and shared fixtures for E-Mesh backend.

Strategy:
- Use a named temporary SQLite file per test (UUID-named)
- Both db_session and client connect to the SAME file
- Overrides get_db (the actual dependency used by routers)
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

# ── Path setup FIRST ──────────────────────────────────────────────────────────
_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from typing import AsyncGenerator  # noqa: E402

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.enums import UserRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402, F401 — register all models
from app.main import app as fastapi_app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.core import dependencies as _deps  # noqa: E402


def _make_test_engine_and_factory(db_path: str):
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(
        url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession,
        expire_on_commit=False, autoflush=False,
    )
    return engine, factory


@pytest_asyncio.fixture
async def test_db():
    """
    Create a named temp-file SQLite DB per test.
    Returns (engine, session_factory) sharing the same file connection.
    Cleans up after the test.
    """
    db_path = os.path.join(tempfile.gettempdir(), f"emesh_test_{uuid.uuid4().hex}.db")
    engine, factory = _make_test_engine_and_factory(db_path)

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine, factory

    # Dispose engine (close all connections) then delete DB file
    await engine.dispose()
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        # Also remove WAL and SHM files if they exist
        for ext in ("-wal", "-shm"):
            f = db_path + ext
            if os.path.exists(f):
                os.remove(f)
    except OSError:
        pass


@pytest_asyncio.fixture
async def db_session(test_db) -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for seeding test data — uses same file as client."""
    _, factory = test_db
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_db) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTPX test client with get_db overridden to use the shared test DB file.
    """
    _, factory = test_db

    async def _override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[_deps.get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()


# ── User factories ────────────────────────────────────────────────────────────

async def _make_user(
    session: AsyncSession,
    username: str,
    role: UserRole,
    password: str = "Test@1234",
) -> User:
    user = User(
        username=username,
        full_name=f"Test {username.replace('_', ' ').title()}",
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "test_admin", UserRole.ADMIN)


@pytest_asyncio.fixture
async def civilian_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "test_civilian", UserRole.CIVILIAN)


@pytest_asyncio.fixture
async def manager_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "test_manager", UserRole.INCIDENT_MANAGER)


@pytest_asyncio.fixture
async def responder_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "test_responder", UserRole.RESPONDER)


# ── Auth helpers ──────────────────────────────────────────────────────────────

async def get_token(ac: AsyncClient, username: str, password: str = "Test@1234") -> str:
    resp = await ac.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def admin_token(client: AsyncClient, admin_user: User) -> str:
    return await get_token(client, admin_user.username)


@pytest_asyncio.fixture
async def civilian_token(client: AsyncClient, civilian_user: User) -> str:
    return await get_token(client, civilian_user.username)


@pytest_asyncio.fixture
async def manager_token(client: AsyncClient, manager_user: User) -> str:
    return await get_token(client, manager_user.username)


@pytest_asyncio.fixture
async def responder_token(client: AsyncClient, responder_user: User) -> str:
    return await get_token(client, responder_user.username)
