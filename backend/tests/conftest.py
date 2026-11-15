import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scout import api, auth, service
from scout.config import settings
from scout.models import Base


@pytest.fixture
def database(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service, "Session", sessions)
    monkeypatch.setattr(api, "Session", sessions)
    monkeypatch.setattr(auth, "Session", sessions)
    monkeypatch.setenv("DISPLAY_TOKEN", "test-display")
    monkeypatch.setenv("ALLOW_DEMO", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    settings.cache_clear()
    yield sessions
    engine.dispose()
    settings.cache_clear()


@pytest.fixture
def client(database):
    """启动时种子管理员，用账号密码登录换成 JWT —— 与真实调用链一致。"""
    with TestClient(api.app) as c:
        result = c.post(
            "/api/v1/auth/login",
            json={"username": settings().admin_username, "password": settings().admin_password},
        )
        assert result.status_code == 200, result.text
        c.headers["Authorization"] = f"Bearer {result.json()['access_token']}"
        yield c
