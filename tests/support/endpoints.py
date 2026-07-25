from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedEndpoint:
    host: str
    port: int
    path: str
    url_no_path: str
    url_with_path: str


def parse_mocker_endpoint(endpoint: str) -> ParsedEndpoint:
    m = re.match(r"opc\.tcp://([^:/]+):(\d+)(/.*)?$", endpoint)
    if not m:
        raise ValueError(f"cannot parse endpoint: {endpoint!r}")
    host = m.group(1)
    port = int(m.group(2))
    path = m.group(3) or ""
    return ParsedEndpoint(
        host=host,
        port=port,
        path=path,
        url_no_path=f"opc.tcp://{host}:{port}",
        url_with_path=f"opc.tcp://{host}:{port}{path}" if path else f"opc.tcp://{host}:{port}/ua_mocker/",
    )
