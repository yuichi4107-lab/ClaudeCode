"""Tests for DEMO_MODE helper and settings."""

import asyncio
import importlib

import pytest


def test_settings_default_demo_mode_false(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    from app import config
    importlib.reload(config)
    assert config.settings.demo_mode is False


def test_settings_demo_mode_true_from_env(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    assert config.settings.demo_mode is True


def test_guest_user_has_full_access(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.core.demo import GUEST_USER
    assert GUEST_USER.has_full_access is True
    assert GUEST_USER.is_admin is False
    assert GUEST_USER.email == "guest@demo.ynfactory.online"


def test_get_current_user_returns_guest_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.auth import dependencies
    importlib.reload(dependencies)

    class _FakeRequest:
        session: dict = {}

    user = asyncio.run(dependencies.get_current_user(_FakeRequest(), db=None))
    assert user is not None
    assert user.email == "guest@demo.ynfactory.online"


def test_require_login_returns_guest_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.auth import dependencies
    importlib.reload(dependencies)

    user = asyncio.run(dependencies.require_login(user=None))
    assert user is not None
    assert user.email == "guest@demo.ynfactory.online"


def test_billing_router_returns_404_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.billing import router as billing_router_mod
    importlib.reload(billing_router_mod)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(billing_router_mod.router)
    client = TestClient(app)
    res = client.post("/billing/webhook")
    assert res.status_code == 404


def test_database_url_forced_to_inmemory_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pw@host/db")
    from app import config
    importlib.reload(config)
    from app import database
    importlib.reload(database)
    assert "sqlite" in database.effective_database_url()
    assert ":memory:" in database.effective_database_url()
