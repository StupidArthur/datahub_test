"""fixtures/history.py:历史数据造数工厂(plan.md 5.7 + history-data-fixtures.md)。

按 fixture 文档实现 A/B/C 等数据集;造数后查询核验,失败返回 setup failure。
"""
from __future__ import annotations

import time
from tpt_api.datahub import (
    import_tag_value,
    get_history_value,
)

from ua_test_harness.assertions import AssertFail
from ua_test_harness.context import RunContext


class HistoryFixtureFactory:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        from ua_test_harness.clients.tpt_client import get_api
        self.api = get_api(ctx)

    # ---- 数据集 -----------------------------------------------------------
    def create_acquisition_dataset(self, tag_name: str, count: int = 30, interval_sec: int = 1) -> dict:
        """方式 A:真实采集造数。create_tag → asyncua 写源值 → 等待采集 → 核验。

        注:本工厂方法只负责造数;真实采集由 DataHub 完成,本方法只 import 一批
        同时间戳的点供后续 history 查询核验使用。
        """
        now_ms = int(time.time() * 1000)
        items = [
            {"tagName": tag_name, "tagValue": float(i), "tagTime": now_ms - (count - i) * interval_sec * 1000}
            for i in range(count)
        ]
        import_tag_value(self.api, items)
        return {"count": count, "tagName": tag_name}

    def create_import_dataset(self, tag_name: str, count: int = 50) -> dict:
        """方式 B:importTagValue 直接导入。"""
        now_ms = int(time.time() * 1000)
        items = [
            {"tagName": tag_name, "tagValue": float(i), "tagTime": now_ms - (count - i) * 60 * 1000}
            for i in range(count)
        ]
        import_tag_value(self.api, items)
        time.sleep(3)  # 等 TPT 处理导入
        return {"count": count, "tagName": tag_name}

    def create_write_dataset(self, tag_name: str, count: int = 5) -> dict:
        """方式 C:实时写库产生少量历史点。"""
        from tpt_api.datahub import write_tag_values

        for i in range(count):
            write_tag_values(self.api, {tag_name: float(i)})
            time.sleep(0.2)
        return {"count": count, "tagName": tag_name}

    # ---- 核验 ------------------------------------------------------------
    def verify_history(self, tag_name: str, min_count: int, begin_ms: int | None = None, end_ms: int | None = None) -> int:
        """查询最近窗口的历史点,要求 >= min_count。"""
        if begin_ms is None:
            begin_ms = int(time.time() * 1000) - 24 * 3600 * 1000
        if end_ms is None:
            end_ms = int(time.time() * 1000) + 60 * 1000
        from datetime import datetime
        beg_str = datetime.fromtimestamp(begin_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        end_str = datetime.fromtimestamp(end_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        raw = get_history_value(
            self.api,
            tag_names=[tag_name],
            beg_time=beg_str,
            end_time=end_str,
            page=1,
            page_size=max(1000, min_count * 2),
        )
        # 返回结构: {tagName: {list: [...], total, ...}}
        if isinstance(raw, dict):
            entry = raw.get(tag_name) or {}
            if isinstance(entry, dict):
                pts = entry.get("list") or []
            else:
                pts = []
        elif isinstance(raw, list):
            pts = raw
        else:
            pts = (raw or {}).get("records") or []
        if len(pts) < min_count:
            raise AssertFail(
                f"[history:{tag_name}] expected>={min_count}, actual={len(pts)} (window=({begin_ms},{end_ms}))"
            )
        return len(pts)