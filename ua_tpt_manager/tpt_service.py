"""封装 tpt_api:登录 / 数据源 / 位号 / 历史值。

供后台 worker(长任务)和监控轮询(短任务)共用同一个 AlgAPI 长驻 client。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from tpt_api import AlgAPI
from tpt_api import datahub

from app_config import TptEnv


class TptService:
    def __init__(self, env: TptEnv):
        self.env = env
        self.api: AlgAPI | None = None
        self.logged_in = False
        self._ds_cache: list[dict] | None = None

    # ---- 登录 ----
    def login(self) -> None:
        api = AlgAPI(self.env.base_url, timeout=60.0)
        api.login(self.env.username, self.env.password, self.env.tenant_id)
        self.api = api
        self.logged_in = True
        self._ds_cache = None

    def logout(self) -> None:
        if self.api:
            try:
                self.api.client.close()
            except Exception:
                pass
        self.api = None
        self.logged_in = False
        self._ds_cache = None

    def _ensure(self) -> None:
        if not self.api or not self.logged_in:
            raise RuntimeError("未登录 TPT")

    # ---- 数据源(ds-info)----
    def list_ds(self, refresh: bool = False) -> list[dict]:
        self._ensure()
        if self._ds_cache is None or refresh:
            self._ds_cache = datahub.get_all_ds_info(self.api)
        return self._ds_cache

    def find_ds_by_url(self, url: str) -> dict | None:
        target = (url or "").rstrip("/")
        for r in self.list_ds():
            if (r.get("dsTarUrl") or "").rstrip("/") == target:
                return r
        return None

    def add_ds(self, name: str, url: str) -> dict:
        """新增 OPC UA 数据源(ds_type=1 REAL_TIME_DB, ds_sub_type=4 OPC_UA_SERVER)。"""
        self._ensure()
        rec = datahub.add_ds_info(self.api, ds_name=name, ds_tar_url=url)
        self._ds_cache = None
        return rec

    def get_ds_alive(self, url: str) -> bool | None:
        r = self.find_ds_by_url(url)
        return None if r is None else bool(r.get("alive"))

    # ---- 位号(tag-info)----
    def list_tags(self, refresh: bool = False) -> list[dict]:
        self._ensure()
        if refresh or not self.api.tags:
            datahub.get_all_tags_all_types(self.api)
        return self.api.tags

    def list_tags_under(self, ds_id: int) -> list[dict]:
        return [t for t in self.list_tags() if t.get("dsId") == ds_id]

    def find_tag_by_name(self, name: str) -> dict | None:
        return self.api.name_map.get(name) if self.api else None

    def add_tag(self, tag_name: str, tag_base_name: str, data_type: int, ds_id: int) -> dict:
        self._ensure()
        return datahub.add_tag(
            self.api,
            tag_name=tag_name,
            tag_base_name=tag_base_name,
            data_type=data_type,
            ds_id=ds_id,
        )

    # ---- 历史值 / 跟手度 ----
    def get_latest_point(self, tag_name: str) -> dict | None:
        """取该位号最近一个历史点(查最近 120s,page_size=1,按 appTime 倒序)。"""
        self._ensure()
        now = datetime.now()
        beg = (now - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        end = now.strftime("%Y-%m-%d %H:%M:%S")
        resp = datahub.get_history_value(
            self.api,
            tag_names=[tag_name],
            beg_time=beg,
            end_time=end,
            page=1,
            page_size=1,
            sort="-appTime",
        )
        info = resp.get(tag_name) or {}
        lst = info.get("list") or []
        return lst[0] if lst else None

    def latency_seconds(self, tag_name: str) -> float | None:
        """跟手度(系统响应时间)= now - 最新点 appTime(秒)。无数据返回 None。"""
        pt = self.get_latest_point(tag_name)
        if not pt:
            return None
        ts = pt.get("appTime") or pt.get("tagTime")
        if not ts:
            return None
        try:
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return (datetime.now() - t).total_seconds()

    def heartbeat_value(self, tag_name: str) -> Any | None:
        pt = self.get_latest_point(tag_name)
        return None if pt is None else pt.get("tagValue")

    def heartbeat_freshness(self, tag_name: str) -> dict:
        """一次查询返回心跳位号跟手度信息:{value, app_time, latency}。

        latency = now - appTime(秒);无数据时各字段为 None。
        """
        pt = self.get_latest_point(tag_name)
        if not pt:
            return {"value": None, "app_time": None, "latency": None}
        ts = pt.get("appTime") or pt.get("tagTime")
        latency: float | None = None
        if ts:
            try:
                t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                latency = (datetime.now() - t).total_seconds()
            except ValueError:
                latency = None
        return {"value": pt.get("tagValue"), "app_time": ts, "latency": latency}
