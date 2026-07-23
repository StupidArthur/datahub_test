"""OPC UA functional mock 的最小读写/变化/浏览自检。"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def probe(endpoint: str, namespace_index: int = 2, wait_sec: float = 1.2) -> dict[str, Any]:
    from asyncua import Client, ua

    started = time.monotonic()
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": _now(),
        "endpoint": endpoint,
        "namespaceIndex": namespace_index,
        "checks": [],
    }

    def add(name: str, ok: bool, **details: Any) -> None:
        result["checks"].append({"name": name, "ok": ok, **details})

    try:
        async with Client(url=endpoint, timeout=5.0) as client:
            objects = client.nodes.objects
            object_children = await objects.get_children()
            browsed = []
            mocker_node = None
            for child in object_children:
                browse_name = await child.read_browse_name()
                browsed.append(str(browse_name))
                if browse_name.Name == "mocker":
                    mocker_node = child
            add("browse_mocker_root", mocker_node is not None, objectChildren=browsed)

            if mocker_node is not None:
                children = await mocker_node.get_children()
                child_names = [str(await child.read_browse_name()) for child in children]
                add("browse_mocker_children", len(children) >= 1, count=len(children), children=child_names)

            static_node_id = f"ns={namespace_index};s=smoke_static_1"
            changing_node_id = f"ns={namespace_index};s=smoke_change_1"
            static_node = client.get_node(static_node_id)
            changing_node = client.get_node(changing_node_id)

            initial = await static_node.read_value()
            add("read_static", abs(float(initial) - 12.5) < 1e-9, nodeId=static_node_id, actual=initial, expected=12.5)

            target = 42.25
            await static_node.write_value(target, varianttype=ua.VariantType.Double)
            written = await static_node.read_value()
            add("write_readback", abs(float(written) - target) < 1e-9, nodeId=static_node_id, actual=written, expected=target)

            before = await changing_node.read_value()
            await asyncio.sleep(wait_sec)
            after = await changing_node.read_value()
            add("changing_value", before != after, nodeId=changing_node_id, before=before, after=after, waitSec=wait_sec)
    except Exception as exc:
        add("connect_or_protocol", False, error=f"{type(exc).__name__}: {exc}")

    result["elapsedMs"] = round((time.monotonic() - started) * 1000, 2)
    result["ok"] = bool(result["checks"]) and all(item["ok"] for item in result["checks"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="ua_test_harness.mock_probe")
    parser.add_argument("--endpoint", default="opc.tcp://127.0.0.1:18960/ua_mocker/")
    parser.add_argument("--namespace-index", type=int, default=2)
    parser.add_argument("--wait-sec", type=float, default=1.2)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    result = asyncio.run(probe(args.endpoint, args.namespace_index, args.wait_sec))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        path = Path(args.output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
