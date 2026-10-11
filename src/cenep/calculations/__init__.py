"""纯计算模块层。

本层只允许依赖 Python 标准库与 :mod:`cenep.domain`：**不得**导入 PySide6、
sqlite3、pandas、PDF 解析库或任何 ``cenep.ui`` / ``cenep.infrastructure`` 模块。
该约束由 ``tests/unit/test_layering.py`` 自动检查。
"""

from __future__ import annotations

__all__: list[str] = []
