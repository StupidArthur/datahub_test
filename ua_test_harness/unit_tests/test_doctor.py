from __future__ import annotations

from ua_test_harness.doctor import failures, url_target


def test_url_target() -> None:
    assert url_target("http://10.10.58.153:31501/") == ("10.10.58.153", 31501)
    assert url_target("https://example.test") == ("example.test", 443)
    assert url_target("") is None


def test_failures_happy_path() -> None:
    report = {
        "repository": {"found": True},
        "python": {"versionInfo": [3, 11, 9]},
        "imports": {
            "ua_test_harness": {"ok": True},
            "asyncua": {"ok": True},
            "yaml": {"ok": True},
        },
        "configuration": {"localIp": "10.30.70.77", "localIpDetected": True},
    }
    assert failures(report) == []
