from __future__ import annotations

import os
import time
from dataclasses import dataclass

import pytest

from tests.support.infra_retry import is_infra_noise


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


def _login_with_retry(client, settings: Settings) -> None:
    deadline = time.monotonic() + 120.0
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.login(settings.user, settings.password, settings.tenant_id)
            return
        except Exception as exc:  # noqa: BLE001 - retried only for infra noise
            last = exc
            if not is_infra_noise(exc):
                raise
            time.sleep(8.0)
    raise RuntimeError(f"login failed after retrying infra noise: {last!r}")


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
        _login_with_retry(client, settings)
    yield client
    client.client.close()


@pytest.fixture(scope="session")
def mocker_endpoint(settings: Settings) -> str:
    if not settings.mocker_endpoint:
        pytest.skip("UA_MOCKER_ENDPOINT not set")
    return settings.mocker_endpoint
