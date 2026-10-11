"""账单字段解析（纯计算层）。

**本包是纯业务规则**：输入页文本，输出结构化字段与证据。
不得导入 ``pypdf``、``PySide6``、``sqlite3``、``pandas`` ——
由 ``tests/unit/test_layering.py`` 自动检查。

设计依据：``docs/phase2/P0_2_FIELD_EVIDENCE_MODEL.md``
与 ``docs/phase2/P0_2_REGRESSION_BASELINE.md``。
"""

from __future__ import annotations

from cenep.calculations.bill_parsing.parser import (
    PARSING_VERSION,
    parse_bill_fields,
)

__all__ = ["PARSING_VERSION", "parse_bill_fields"]
