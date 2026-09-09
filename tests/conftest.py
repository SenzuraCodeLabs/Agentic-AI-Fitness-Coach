"""Shared test fixtures.

Test settings are forced here rather than read from the developer's ``.env`` so
the suite is deterministic on any machine and in CI, and so a test run can
never touch the real database or spend real API credit.
"""

from __future__ import annotations

import os

import pytest

# Set before any application import: pydantic-settings reads the environment at
# class instantiation, and importing a service module can trigger that.
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-not-a-real-key")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "fitcoach_test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-value-long-enough")
os.environ.setdefault("AGENT_SHARED_SECRET", "test-agent-secret-value-long-enough")
os.environ.setdefault("ENVIRONMENT", "test")

from shared.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Keep the settings singleton from leaking overrides between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def agent_secret() -> str:
    return get_settings().agent_shared_secret.get_secret_value()
