"""基础设施层。

负责 SQLite 持久化、后续的电费账单文件读取与报告导出。
本层可以把底层驱动异常包装为领域异常，但**不得**决定业务计算规则。
"""

from __future__ import annotations

__all__: list[str] = []
