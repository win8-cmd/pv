"""应用服务层。

负责组织业务流程：串接领域校验、领域计算与基础设施持久化。
本层不包含计算公式，也不包含界面代码。

**本模块同时是界面层访问导入/报告相关类型的唯一入口**：
界面层不得直接导入 ``cenep.data``（由分层守卫强制），
所需的枚举、异常与视图对象在此转出。
"""

from __future__ import annotations

from cenep.application.bill_service import (
    BillService,
    BillSummary,
    ManualBillInput,
)
from cenep.application.project_service import ProjectService
from cenep.application.report_files import (
    default_report_file_name,
    default_template_directory,
    default_template_file_name,
    write_report_file,
    write_template_file,
)

# 界面层所需的导入相关类型：在此转出，避免界面层直接依赖 data 层
from cenep.data.bill_import_service import (
    DuplicateDecision,
    ImportApplyResult,
    ImportDecision,
    ImportPreview,
    RecordCounts,
)
from cenep.data.template_reader import TemplateReadError

__all__ = [
    "BillService",
    "BillSummary",
    "DuplicateDecision",
    "ImportApplyResult",
    "ImportDecision",
    "ImportPreview",
    "ManualBillInput",
    "ProjectService",
    "RecordCounts",
    "TemplateReadError",
    "default_report_file_name",
    "default_template_directory",
    "default_template_file_name",
    "write_report_file",
    "write_template_file",
]
