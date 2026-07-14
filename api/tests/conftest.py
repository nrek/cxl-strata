from __future__ import annotations

import os

# Tests must not inherit production `.env` identity/auth settings. These values
# are read once when app.core.config is imported below.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["STRATA_API_KEYS"] = "strata_dev_example"
os.environ["BOOTSTRAP_ORG_SLUG"] = "bootstrap-org"
os.environ["BOOTSTRAP_ORG_NAME"] = "Bootstrap Organization"
os.environ["API_KEY_PEPPER"] = "test-pepper"
os.environ["STRATA_ENV"] = "test"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
