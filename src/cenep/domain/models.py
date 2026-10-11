"""领域数据模型。

本模块定义 CENEP 全部实体，与 ``docs/DATA_MODEL.md` 一一对应。
第一阶段：

- :class:`Project` 具备完整 SQLite 读写能力（见 :mod:`cenep.infrastructure.database`）。
- 其余实体在本阶段只定义字段、类型、可空性与约束，作为后续阶段的冻结契约。

约定：

- 主键统一为 UUID4 字符串（``str``），不使用自增整数，
  以便未来多库合并、导入导出时不发生主键冲突。
- 时间戳统一为 UTC 的 ISO 8601 字符串（``YYYY-MM-DDTHH:MM:SSZ``），
  精确到秒，便于 SQLite 文本比较与排序。
- 电量统一单位 kWh；金额统一单位元；容量单位为 kWp。
- "时段电量"与"瞬时功率"是不同物理量，字段名必须以 ``energy_kwh`` /
  ``power_kw`` 显式区分，禁止混用。
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """返回当前 UTC 时间，格式 ``YYYY-MM-DDTHH:MM:SSZ``（精确到秒）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """生成新的实体主键（UUID4 十六进制字符串）。"""
    return uuid.uuid4().hex


def is_valid_iso_timestamp(value: str) -> bool:
    """校验字符串是否为可解析的 ISO 8601 时间戳。"""
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# 枚举（取值与 docs/DATA_MODEL.md、DATA_MODEL.md 中的 CHECK 约束保持一致）
# ---------------------------------------------------------------------------


class ProjectType(str, Enum):
    """项目类型。"""

    INDUSTRIAL_COMMERCIAL = "industrial_commercial"
    """工商业分布式光伏（第一阶段主要场景）。"""

    UTILITY_SCALE = "utility_scale"
    """集中式地面电站（后续阶段）。"""

    OTHER = "other"
    """其他。"""


class DocumentType(str, Enum):
    """文件类型。"""

    ELECTRICITY_BILL = "electricity_bill"
    """电费账单（PDF/图片/Excel）。"""

    LOAD_PROFILE = "load_profile"
    """负荷曲线数据文件。"""

    TARIFF_DOCUMENT = "tariff_document"
    """电价政策或电价表文件。"""

    OTHER = "other"
    """其他附件。"""


class ProcessingStatus(str, Enum):
    """文件处理状态。"""

    PENDING = "pending"
    """已登记，尚未处理。"""

    PARSED = "parsed"
    """已成功解析。"""

    FAILED = "failed"
    """解析失败。"""

    MANUAL_REVIEW = "manual_review"
    """解析结果存疑，需人工复核。"""


class ValidationStatus(str, Enum):
    """数据校验状态。用于电费账单与负荷数据。"""

    UNVALIDATED = "unvalidated"
    """尚未校验。默认值；不允许把未校验数据当作已核实数据使用。"""

    VALID = "valid"
    """通过校验。"""

    INVALID = "invalid"
    """未通过校验，不可用于计算。"""

    WARNING = "warning"
    """可用但存在疑点。"""


class SourceType(str, Enum):
    """负荷数据来源类型。"""

    METER_INTERVAL = "meter_interval"
    """电表分时计量数据（真实数据）。"""

    BILL_ALLOCATED = "bill_allocated"
    """由月度账单按典型曲线分摊得到的估算数据。"""

    SYNTHETIC = "synthetic"
    """模拟/假设生成的数据。"""

    MANUAL = "manual"
    """人工录入。"""


class TariffType(str, Enum):
    """电价类型。"""

    TOU_INDUSTRIAL = "tou_industrial"
    """工商业分时电价。"""

    FLAT = "flat"
    """单一制电价。"""

    DEMAND = "demand"
    """两部制（含基本电费/需量电费）。"""

    MARKET = "market"
    """市场化交易电价。"""

    OTHER = "other"
    """其他。"""


class EntityStatus(str, Enum):
    """实体生命周期状态。电价方案与光伏方案共用。"""

    DRAFT = "draft"
    """草稿，未定稿。"""

    ACTIVE = "active"
    """启用中。"""

    ARCHIVED = "archived"
    """已归档，只读保留。"""


class ValidationIssueSeverity(str, Enum):
    """校验问题严重程度（持久化视图）。

    与 :class:`cenep.domain.validation.Severity` 取值一致，
    用于 :class:`ResultRecord` / ``validation_issue`` 表的落库表达。
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CalculationStatus(str, Enum):
    """计算运行记录状态。"""

    PENDING = "pending"
    """已创建，尚未执行。"""

    RUNNING = "running"
    """执行中。"""

    SUCCEEDED = "succeeded"
    """成功完成。"""

    FAILED = "failed"
    """执行失败。"""


class MetricName(str, Enum):
    """计算结果指标名。

    取值与 :class:`cenep.calculations.self_consumption.SelfConsumptionResult`
    输出的字段名一致，保证结果可追溯。
    """

    TOTAL_LOAD_KWH = "total_load_kwh"
    TOTAL_PV_KWH = "total_pv_kwh"
    TOTAL_SELF_CONSUMPTION_KWH = "total_self_consumption_kwh"
    TOTAL_EXPORT_KWH = "total_export_kwh"
    TOTAL_GRID_IMPORT_KWH = "total_grid_import_kwh"
    SELF_CONSUMPTION_RATE = "self_consumption_rate"
    LOAD_COVERAGE_RATE = "load_coverage_rate"
    EXPORT_RATE = "export_rate"


class ReportType(str, Enum):
    """报告类型。"""

    FEASIBILITY = "feasibility"
    """可行性研究报告。"""

    COMPARISON = "comparison"
    """方案对比报告。"""

    DATA_QUALITY = "data_quality"
    """数据质量报告。"""

    OTHER = "other"
    """其他。"""


class CalculationType(str, Enum):
    """计算类型。"""

    SELF_CONSUMPTION = "self_consumption"
    """光伏消纳计算。"""


#: 假设备注版本号。任何影响计算结果的口径变化都必须提升该版本号，
#: 并同步更新 docs/CALCULATION_SPEC.md。
ASSUMPTIONS_VERSION = "2026.02-stage1"
"""当前计算假设版本。"""

CALCULATION_ENGINE_VERSION = "0.1.0"
"""消纳计算引擎版本，写入 CalculationRun.calculation_version 以支持追溯。"""


# ---------------------------------------------------------------------------
# 实体
# ---------------------------------------------------------------------------


@dataclass
class Project:
    """项目 —— 全部业务数据的隔离边界。

    不同 ``project_id`` 之间的数据必须互相隔离，任何跨项目聚合都是错误行为。
    """

    project_id: str = field(default_factory=new_id)
    """主键，UUID4 十六进制字符串。"""

    name: str = ""
    """项目名称，必填，非空。"""

    location: str | None = None
    """项目地址（省/市/区），可空。"""

    customer_name: str | None = None
    """业主或客户名称，可空。"""

    project_type: ProjectType = ProjectType.INDUSTRIAL_COMMERCIAL
    """项目类型，默认工商业分布式。"""

    created_at: str = field(default_factory=utc_now_iso)
    """创建时间（UTC ISO 8601，秒精度）。"""

    updated_at: str = field(default_factory=utc_now_iso)
    """最后更新时间（UTC ISO 8601，秒精度）。"""

    description: str | None = None
    """项目说明，可空。"""

    def to_dict(self) -> dict[str, Any]:
        """转为字典；枚举转为字符串值，便于 JSON 序列化与落库。"""
        data = asdict(self)
        data["project_type"] = self.project_type.value if isinstance(self.project_type, ProjectType) else str(self.project_type)
        return data

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Project":
        """从 SQLite 行字典构造实例。"""
        project_type = row.get("project_type") or ProjectType.INDUSTRIAL_COMMERCIAL.value
        return cls(
            project_id=row["project_id"],
            name=row["name"],
            location=row.get("location"),
            customer_name=row.get("customer_name"),
            project_type=ProjectType(project_type),
            created_at=row.get("created_at") or utc_now_iso(),
            updated_at=row.get("updated_at") or utc_now_iso(),
            description=row.get("description"),
        )


@dataclass
class Document:
    """文件 —— 原始文件的路径与元数据分开管理。"""

    document_id: str = field(default_factory=new_id)
    project_id: str = ""
    filename: str = ""
    """原始文件名（仅名称，不含目录，避免泄露本地路径）。"""

    document_type: DocumentType = DocumentType.OTHER
    file_path: str | None = None
    """本地文件路径。属元数据层，与解析结果表分离。"""

    imported_at: str = field(default_factory=utc_now_iso)
    processing_status: ProcessingStatus = ProcessingStatus.PENDING


@dataclass
class BillRecord:
    """电费账单记录（月度）。"""

    bill_id: str = field(default_factory=new_id)
    project_id: str = ""
    billing_period_start: str | None = None
    """账期起（``YYYY-MM-DD``）。"""

    billing_period_end: str | None = None
    """账期止（``YYYY-MM-DD``）。"""

    total_energy_kwh: float | None = None
    """账期总用电量。缺失时为 ``None``，**禁止填 0 或估算值冒充实测值**。"""

    total_amount_yuan: float | None = None
    """账期总电费（元）。缺失时为 ``None``。"""

    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
    source_document_id: str | None = None


@dataclass
class LoadProfile:
    """负荷曲线 —— 时段电量数据。

    ``energy_kwh`` 是**时段电量**（kWh），不是瞬时功率（kW）。
    两者换算关系为 ``energy_kwh = power_kw × interval_minutes / 60``，
    禁止直接把功率数值写入本字段。
    """

    profile_id: str = field(default_factory=new_id)
    project_id: str = ""
    timestamp: str = ""
    """时段起点（UTC ISO 8601）。"""

    energy_kwh: float = 0.0
    """该时段电量（kWh）。"""

    interval_minutes: int = 60
    """时段长度（分钟），正整数。"""

    source_type: SourceType = SourceType.MANUAL


@dataclass
class TariffModel:
    """电价方案。

    正式电价数据必须记录来源（``source_reference``）与生效日期，
    未核实数据不得标记为已核实正式电价（见 CALCULATION_SPEC.md 第 4.9 条）。
    """

    tariff_id: str = field(default_factory=new_id)
    name: str = ""
    region: str | None = None
    effective_from: str | None = None
    """生效日期（``YYYY-MM-DD``）。"""

    effective_to: str | None = None
    """失效日期，``None`` 表示仍然有效。"""

    tariff_type: TariffType = TariffType.TOU_INDUSTRIAL
    source_reference: str | None = None
    """来源说明（文件名/文号/URL）。为空表示来源未核实。"""

    status: EntityStatus = EntityStatus.DRAFT


@dataclass
class PVModel:
    """光伏方案。"""

    pv_model_id: str = field(default_factory=new_id)
    project_id: str = ""
    installed_capacity_kwp: float = 0.0
    annual_generation_kwh: float | None = None
    """年发电量。第一阶段不做发电量模拟，缺失时为 ``None``。"""

    generation_profile_reference: str | None = None
    """发电量曲线来源引用（文件 ID 或口径说明）。"""

    assumptions_version: str = ASSUMPTIONS_VERSION


@dataclass
class Scenario:
    """测算方案 —— 把光伏方案与电价方案组合成一次可计算的输入集合。"""

    scenario_id: str = field(default_factory=new_id)
    project_id: str = ""
    name: str = ""
    pv_model_id: str | None = None
    tariff_id: str | None = None
    assumptions: str | None = None
    """方案假设说明（JSON 文本或备注）。"""

    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class CalculationRun:
    """计算运行记录 —— 结果可追溯的关键。

    ``input_snapshot`` 保存本次计算实际使用的输入摘要，
    ``calculation_version`` 保存引擎版本，二者共同保证结果可复现。
    """

    calculation_run_id: str = field(default_factory=new_id)
    scenario_id: str | None = None
    calculation_type: CalculationType = CalculationType.SELF_CONSUMPTION
    calculation_version: str = CALCULATION_ENGINE_VERSION
    input_snapshot: str | None = None
    """输入快照（JSON 文本）。"""

    status: CalculationStatus = CalculationStatus.PENDING
    started_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None


@dataclass
class ResultRecord:
    """计算结果 —— 一条记录一个指标。"""

    result_id: str = field(default_factory=new_id)
    calculation_run_id: str = ""
    metric_name: str = ""
    value: float | None = None
    """指标数值。未定义（如零分母）时为 ``None``，不写 0 冒充。"""

    unit: str | None = None
    period: str | None = None
    status: str = "ok"
    """``ok`` 或 ``undefined``。"""


@dataclass
class ValidationIssueRecord:
    """校验问题持久化记录。

    与 :class:`cenep.domain.validation.ValidationIssue` 字段对齐，
    但额外携带关联对象信息以便落库。
    """

    issue_id: str = field(default_factory=new_id)
    project_id: str | None = None
    related_object_type: str | None = None
    related_object_id: str | None = None
    field_name: str = ""
    issue_code: str = ""
    severity: ValidationIssueSeverity = ValidationIssueSeverity.ERROR
    message: str = ""


@dataclass
class Report:
    """报告输出记录。"""

    report_id: str = field(default_factory=new_id)
    project_id: str = ""
    scenario_id: str | None = None
    report_type: ReportType = ReportType.OTHER
    file_path: str | None = None
    generated_at: str | None = None
    status: str = "pending"


__all__ = [
    "ASSUMPTIONS_VERSION",
    "CALCULATION_ENGINE_VERSION",
    "BillRecord",
    "CalculationRun",
    "CalculationStatus",
    "CalculationType",
    "Document",
    "DocumentType",
    "EntityStatus",
    "LoadProfile",
    "MetricName",
    "PVModel",
    "ProcessingStatus",
    "Project",
    "ProjectType",
    "Report",
    "ReportType",
    "ResultRecord",
    "Scenario",
    "SourceType",
    "TariffModel",
    "TariffType",
    "ValidationIssueRecord",
    "ValidationIssueSeverity",
    "ValidationStatus",
    "is_valid_iso_timestamp",
    "new_id",
    "utc_now_iso",
]
