"""excel → ua_player CSV 转换(注入心跳列)。

ua_player CSV 格式(见 ua_player/data_loader.py):
- 首列 = 时间戳(--interval 模式下忽略解析,任意值即可)
- 其余列 = 节点名(可带 [bool]/[w] 后缀),节点名即 UA 节点 id(ns=1,容器 MYDATA,无 count 展开)
- 用 --interval 1 启动 → 每秒播一行,心跳列 0~99 循环即秒级自增

首列若可被 supcon_io.parse_time 解析则视为时间戳列(不计入位号);否则全部列均为数据列,
首列用占位行号。若 excel 已含心跳列则不重复注入。
"""
from __future__ import annotations

import csv
from pathlib import Path

from supcon_io import parse_time, read


def _analyze(excel_path: str):
    table = read(excel_path, excel_numeric_handling="allow")
    headers = list(table.title or [])
    rows = table.data or []
    first_is_ts = bool(
        rows and headers and parse_time(rows[0][0] if rows[0] else None) is not None
    )
    return headers, rows, first_is_ts


def excel_tag_columns(excel_path: str, heartbeat_tag: str) -> list[str]:
    """excel 中可作为位号的列名(排除时间戳列与已有的心跳列)。"""
    headers, _rows, first_is_ts = _analyze(excel_path)
    start = 1 if first_is_ts else 0
    return [h for h in headers[start:] if (h or "").strip() != heartbeat_tag]


def convert(excel_path: str, heartbeat_tag: str, out_csv_path: str | Path) -> Path:
    """把 excel 转成 ua_player 兼容 CSV,自动注入心跳列(0~99 循环)。"""
    headers, rows, first_is_ts = _analyze(excel_path)
    start = 1 if first_is_ts else 0
    tag_idx = list(range(start, len(headers)))
    tag_names = [headers[i] for i in tag_idx]
    has_hb = any((h or "").strip() == heartbeat_tag for h in tag_names)
    inject_hb = not has_hb
    ts_header = headers[0] if first_is_ts else "time"

    out_csv_path = Path(out_csv_path)
    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        out_header = [ts_header] + tag_names + ([heartbeat_tag] if inject_hb else [])
        w.writerow(out_header)
        for ri, row in enumerate(rows):
            ts_val = row[0] if (first_is_ts and len(row) > 0) else ri
            vals = []
            for i in tag_idx:
                v = row[i] if i < len(row) else ""
                vals.append("" if v is None else str(v))
            if inject_hb:
                vals.append(str(ri % 100))
            w.writerow([ts_val] + vals)
    return out_csv_path
