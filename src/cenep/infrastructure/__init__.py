"""基础设施层。

负责 SQLite 持久化、账单表读取与（后续的）报告导出。
本层可以把底层驱动异常包装为领域异常，但**不得**决定业务计算规则。
"""

from __future__ import annotations

from cenep.infrastructure.bill_repository import (
    BillRecordRepository,
    SqliteBillRepository,
)
from cenep.infrastructure.database import (
    BUSINESS_TABLES,
    MIGRATIONS,
    SCHEMA_STATEMENTS,
    SCHEMA_VERSION,
    Database,
    ProjectRepository,
    translate_integrity_error,
)
from cenep.infrastructure.schema_v2 import BUSINESS_TABLES_V2, SCHEMA_STATEMENTS_V2

__all__ = [
    "BUSINESS_TABLES",
    "BUSINESS_TABLES_V2",
    "MIGRATIONS",
    "SCHEMA_STATEMENTS",
    "SCHEMA_STATEMENTS_V2",
    "SCHEMA_VERSION",
    "BillRecordRepository",
    "Database",
    "ProjectRepository",
    "SqliteBillRepository",
    "translate_integrity_error",
]
