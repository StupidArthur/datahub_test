from __future__ import annotations

import os
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class Settings:
    base_url: str
    tenant_id: str
    user: str
    password: str
    token: str
    mocker_endpoint: str
    test_prefix: str


def _load_settings() -> Settings:
    return Settings(
        base_url=os.environ.get("DATAHUB_BASE_URL", ""),
        tenant_id=os.environ.get("DATAHUB_TENANT_ID", ""),
        user=os.environ.get("DATAHUB_USER", ""),
        password=os.environ.get("DATAHUB_PASSWORD", ""),
        token=os.environ.get("DATAHUB_TOKEN", ""),
        mocker_endpoint=os.environ.get("UA_MOCKER_ENDPOINT", ""),
        test_prefix=os.environ.get("DATAHUB_TEST_PREFIX", "pytest_native_"),
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = _load_settings()
    if not s.base_url:
        pytest.skip("DATAHUB_BASE_URL not set")
    return s


@pytest.fixture(scope="session")
def api(settings: Settings):
    from tpt_api.client import AlgAPI

    client = AlgAPI(base_url=settings.base_url, timeout=20.0)
    if settings.token:
        client.token = settings.token
        client.client.headers["Authorization"] = f"Bearer {settings.token}"
    else:
        if not settings.user or not settings.password:
            pytest.skip("DATAHUB_USER / DATAHUB_PASSWORD not set")
        client.login(settings.user, settings.password, settings.tenant_id)
    return client


@pytest.fixture(scope="session")
def mocker_endpoint(settings: Settings) -> str:
    if not settings.mocker_endpoint:
        pytest.skip("UA_MOCKER_ENDPOINT not set")
    return settings.mocker_endpoint
