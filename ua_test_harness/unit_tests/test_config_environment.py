from __future__ import annotations

from ua_test_harness.config import RunConfig


def test_subject_fields_fall_back_to_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATAHUB_BASE_URL", "http://example.invalid/")
    monkeypatch.setenv("DATAHUB_USER", "automation-user")
    monkeypatch.setenv("DATAHUB_PASSWORD", "secret-from-environment")
    monkeypatch.setenv("DATAHUB_TENANT_ID", "tenant-a")

    cfg = RunConfig.from_json('{"subject": {"password": ""}}')

    assert cfg.subject.base_url == "http://example.invalid/"
    assert cfg.subject.username == "automation-user"
    assert cfg.subject.password == "secret-from-environment"
    assert cfg.subject.tenant_id == "tenant-a"


def test_explicit_subject_fields_override_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATAHUB_PASSWORD", "environment-secret")

    cfg = RunConfig.from_json(
        '{"subject": {"baseUrl": "http://subject/", "username": "user", "password": "explicit"}}'
    )

    assert cfg.subject.base_url == "http://subject/"
    assert cfg.subject.username == "user"
    assert cfg.subject.password == "explicit"
