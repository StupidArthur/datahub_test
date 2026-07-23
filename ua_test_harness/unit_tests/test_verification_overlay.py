"""verification overlay merge 单测。"""
from __future__ import annotations

from pathlib import Path

from ua_test_harness.case_inventory import (
    build_inventory,
    verification_overlay_from_run,
)


def test_verification_overlay_from_run_maps_pass_and_fail(tmp_path: Path) -> None:
    overlay = verification_overlay_from_run(
        [
            {"caseId": "UA-2-1-017", "status": "PASS", "reportPath": "/a/report.json"},
            {"caseId": "UA-2-1-019", "status": "FAIL", "reportPath": "/b/report.json"},
            {"caseId": "UA-2-1-099", "status": "TIMEOUT"},
        ]
    )
    assert overlay["UA-2-1-017"]["status"] == "VERIFIED"
    assert overlay["UA-2-1-019"]["status"] == "VERIFIED_FAIL"
    assert overlay["UA-2-1-099"]["status"] == "VERIFIED_BLOCKED"


def test_build_inventory_merges_verification_overlay(tmp_path: Path) -> None:
    doc = tmp_path / "ua_test_harness" / "test_cases" / "UA-1-1.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        """# UA-1-1 连接建立
| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |
|---|---|---|---|---|---|
| UA-1-1-01 | A | P | S | E | V |
""",
        encoding="utf-8",
    )
    report = build_inventory(
        tmp_path,
        implemented={"UA-1-1-01": {"filePath": "t.py", "lineno": 1}},
        expected_total=1,
        verification_overlay={"UA-1-1-01": {"status": "VERIFIED", "verifiedAt": "t0"}},
    )
    assert report["cases"][0]["verificationStatus"] == "VERIFIED"
    assert report["summary"]["verified"] == 1


def test_cli_overlay_preserves_verification_records(tmp_path: Path) -> None:
    """CLI --verification-overlay 必须保留旧 inventory 中的验证记录。"""
    import json

    from ua_test_harness.case_inventory import main as inventory_main

    # 构造临时仓库
    doc = tmp_path / "ua_test_harness" / "test_cases" / "UA-1-1.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "# UA-1-1 连接建立\n"
        "\n"
        "| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |\n"
        "|---|---|---|---|---|---|\n"
        "| UA-1-1-01 | A | P | S | E | V |\n",
        encoding="utf-8",
    )

    # 构造旧 inventory（包含验证记录）
    old_inventory = tmp_path / "old-inventory.json"
    old_inventory.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "UA-1-1-01",
                        "verificationStatus": "VERIFIED",
                        "verifiedAt": "2026-07-15T04:35:03Z",
                        "runReportPath": "output/old/report.json",
                        "runStatus": "PASS",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "output-inventory.json"
    rc = inventory_main(
        [
            "--repo-root", str(tmp_path),
            "--output", str(output_path),
            "--expected-total", "1",
            "--strict-structure",
            "--verification-overlay", str(old_inventory),
        ]
    )
    assert rc == 0

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["verified"] == 1
    assert report["summary"]["notVerified"] == 0

    case_row = report["cases"][0]
    assert case_row["verificationStatus"] == "VERIFIED"
    assert case_row["verifiedAt"] == "2026-07-15T04:35:03Z"
    assert case_row["runReportPath"] == "output/old/report.json"
    assert case_row["runStatus"] == "PASS"
    assert case_row["docPath"] == "ua_test_harness/test_cases/UA-1-1.md"
