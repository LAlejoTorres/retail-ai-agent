"""Shared fixtures: seed a fresh SQLite store before the tool tests run."""
from __future__ import annotations

import pytest

from app.data.seed import seed


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    seed()
    yield
