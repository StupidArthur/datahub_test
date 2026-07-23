"""ua_test_harness:UA 自动化测试执行器。

提供:
- 装饰器 + catalog 导出(catalog.py)
- 结构化事件协议(events.py)
- RunConfig 加载(config.py)
- RunContext/CaseContext(context.py)
- ResourceRegistry LIFO 清理(resources.py)
- 轮询等待(polling.py)
- 证据与指标(evidence.py / metrics.py)
- 报告生成(report.py)
- 客户端适配(tpt_client / opcua_client / mock_control)
- CLI(cli.py)
"""
from __future__ import annotations

__version__ = "0.1.0"