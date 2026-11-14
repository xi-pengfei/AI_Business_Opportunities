import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scout import api, service
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
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("DISPLAY_TOKEN", "test-display")
    monkeypatch.setenv("ALLOW_DEMO", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    settings.cache_clear()
    yield sessions
    engine.dispose()
    settings.cache_clear()


@pytest.fixture
def client(database):
    with TestClient(api.app, headers={"Authorization": "Bearer test-admin"}) as c:
        yield c
