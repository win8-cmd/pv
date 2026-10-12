"""数据层：Excel / CSV 读写、模板生成、列映射与数据质量检查。

**分层约定**（见 `docs/ARCHITECTURE.md` 依赖方向规则第 5 条）：

- 本层**只依赖 `domain`**，不得依赖 `ui`、`application`、`infrastructure`；
- Excel 读写库（`openpyxl`）**只允许出现在本层与 `infrastructure`**；
- 界面与应用代码通过本层处理表格，**不得直接操作 Excel**。

模块划分：

- :mod:`cenep.data.bill_template_spec`：模板结构规范（纯数据，无 Excel 依赖）；
- :mod:`cenep.data.template_writer`：生成标准模板文件；
- :mod:`cenep.data.template_reader`：（阶段 3）读取与列映射；
- :mod:`cenep.data.bill_validation`：（阶段 2）13 类数据校验。
"""

from __future__ import annotations

from cenep.data.bill_template_spec import (
    ALL_SHEETS,
    BUSINESS_SHEETS,
    EXCLUDED_SHEETS,
    SAMPLE_MARKER_TEXT,
    SAMPLE_TEMPLATE_ROWS,
    SHEET_DATA_VALIDATION,
    SHEET_FEE_ITEMS,
    SHEET_INSTRUCTIONS,
    SHEET_METER_POINTS,
    SHEET_MONTHLY_SUMMARY,
    SHEET_SAMPLE_REFERENCE,
    SHEET_TIME_OF_USE,
    TEMPLATE_NAME,
    TEMPLATE_VERSION,
    SheetSpec,
    get_sheet,
    headers_of,
)
from cenep.data.bill_validation import (
    CHECK_ITEMS,
    ValidationReport,
    validate_bill_data,
)

__all__ = [
    "ALL_SHEETS",
    "BUSINESS_SHEETS",
    "CHECK_ITEMS",
    "EXCLUDED_SHEETS",
    "SAMPLE_MARKER_TEXT",
    "SAMPLE_TEMPLATE_ROWS",
    "SHEET_DATA_VALIDATION",
    "SHEET_FEE_ITEMS",
    "SHEET_INSTRUCTIONS",
    "SHEET_METER_POINTS",
    "SHEET_MONTHLY_SUMMARY",
    "SHEET_SAMPLE_REFERENCE",
    "SHEET_TIME_OF_USE",
    "TEMPLATE_NAME",
    "TEMPLATE_VERSION",
    "SheetSpec",
    "ValidationReport",
    "get_sheet",
    "headers_of",
    "validate_bill_data",
]
