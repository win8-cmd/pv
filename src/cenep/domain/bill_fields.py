"""电费账单字段与证据的领域模型（P0-2）。

本模块是**纯 Python**：不导入 ``pypdf``、``PySide6``、``sqlite3`` 或任何 IO 库。
解析规则在 :mod:`cenep.calculations.bill_parsing` 中实现，
结果被映射为本模块定义的结构化数据。

核心设计目标（与 ``docs/phase2/P0_2_FIELD_EVIDENCE_MODEL.md`` 一致）：

1. **缺失保持缺失**：``value is None``，绝不用 0 填充。
2. **冲突不静默取一个**：多个不同候选值 → ``needs_review``，``value`` 保持 ``None``。
3. **可追溯**：每个字段都带来源页码、原文片段与规则标识。
4. **金额精确**：金额与电量一律 ``Decimal``，禁止 ``float``。
5. **单位不混用**：``元/kWh``（单价）、``元``（金额）、``kWh``（电量）严格区分。
6. **解析成功不等于账单有效**：``parsed`` 仅表示识别成功，
   能否用于测算由 :attr:`BillFieldSet.is_usable_for_calculation` 统一判定。

这些约束在 ``__post_init__`` 中强制，把语义固化在类型层面，
而不是只靠调用方自觉——与 P0-1 中 ``PdfExtractionResult`` 的做法一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from cenep.domain.pdf_extraction import PdfExtractionStatus
from cenep.domain.validation import Severity, ValidationIssue

__all__ = [
    "PENDING_CONFIRMATION",
    "UNIT_DATE",
    "UNIT_KWH",
    "UNIT_RATIO",
    "UNIT_YUAN",
    "UNIT_YUAN_PER_KWH",
    "BillConfirmation",
    "BillField",
    "BillFieldSet",
    "ConfirmationStatus",
    "FieldEvidence",
    "FieldName",
    "FieldStatus",
    "ReconciliationResult",
    "RECONCILIATION_TOLERANCE_YUAN",
]

#: 单位常量（集中定义，避免各处拼写不一致）
UNIT_KWH = "kWh"
UNIT_YUAN = "元"
UNIT_YUAN_PER_KWH = "元/kWh"
UNIT_RATIO = "ratio"
UNIT_DATE = "date"

#: 费用勾稽的默认容差（任务书 6.4）。
RECONCILIATION_TOLERANCE_YUAN = Decimal("0.02")


def _to_decimal(value: Decimal | int | str | None) -> Decimal | None:
    """把入参转换为 ``Decimal``；``None`` 原样返回。

    **显式拒绝 ``float``**：金额与电量用 ``float`` 会引入二进制浮点误差，
    是财务数据处理中必须避免的做法。
    """
    if value is None:
        return None
    if isinstance(value, float):
        raise TypeError(
            "金额与电量不得使用 float（会引入浮点误差）；"
            "请使用 Decimal、int 或十进制字符串。"
        )
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


class FieldStatus(str, Enum):
    """单个字段的识别状态。"""

    PARSED = "parsed"
    """唯一候选且格式合法。**注意：这不等于可用于测算。**"""

    NEEDS_REVIEW = "needs_review"
    """多个不同候选值，或单位不明 —— 必须人工复核。"""

    MISSING = "missing"
    """未找到该字段。``value`` 必须为 ``None``，绝不补 0。"""

    INVALID = "invalid"
    """找到了但在语义上不合法（如结束日早于开始日）。"""


class ConfirmationStatus(str, Enum):
    """账单的人工确认状态。

    **解析成功不等于可以进入正式测算。** 三个阶段必须显式区分：

    1. :attr:`PENDING` —— 解析完成、结果可供复核（**尚不可用于正式测算**）；
    2. :attr:`CONFIRMED` —— 已由人工确认（此时才可能进入正式测算）；
    3. :attr:`REJECTED` —— 人工复核后判定不可用。

    禁止调用方凭"解析成功"就跳过确认环节。
    """

    PENDING = "pending"
    """解析完成，等待人工复核。"""

    CONFIRMED = "confirmed"
    """已人工确认。"""

    REJECTED = "rejected"
    """人工复核后驳回。"""


class FieldName(str, Enum):
    """首批字段的标准标识符。

    与 ``docs/phase2/P0_2_REGRESSION_BASELINE.md`` 逐字一致；
    跨文档与代码的唯一契约，不得随意改名。
    """

    BILLING_PERIOD_START = "billing_period_start"
    BILLING_PERIOD_END = "billing_period_end"
    TOTAL_CONSUMPTION = "total_consumption"
    BILL_TOTAL_AMOUNT = "bill_total_amount"
    VAT_INVOICE_AMOUNT = "vat_invoice_amount"
    DISPLAYED_AVERAGE_PRICE = "displayed_average_price"
    INDUSTRIAL_COMMERCIAL_FEE = "industrial_commercial_fee"
    MARKET_PURCHASE_FEE = "market_purchase_fee"
    GRID_LOSS_FEE = "grid_loss_fee"
    TRANSMISSION_DISTRIBUTION_FEE = "transmission_distribution_fee"
    SYSTEM_OPERATION_FEE = "system_operation_fee"
    GOVERNMENT_FUND_FEE = "government_fund_fee"
    POWER_FACTOR_ADJUSTMENT_FEE = "power_factor_adjustment_fee"
    DEMAND_CHARGE = "demand_charge"


#: "五项之和"的参与字段（顺序即账单原文的 (1)~(5) 顺序）
FIVE_ITEM_FIELDS: tuple[FieldName, ...] = (
    FieldName.MARKET_PURCHASE_FEE,
    FieldName.GRID_LOSS_FEE,
    FieldName.TRANSMISSION_DISTRIBUTION_FEE,
    FieldName.SYSTEM_OPERATION_FEE,
    FieldName.GOVERNMENT_FUND_FEE,
)

#: 首批必需字段（缺任一则字段集不可用于测算）
REQUIRED_FIELDS: tuple[FieldName, ...] = (
    FieldName.BILLING_PERIOD_START,
    FieldName.BILLING_PERIOD_END,
    FieldName.TOTAL_CONSUMPTION,
    FieldName.BILL_TOTAL_AMOUNT,
    FieldName.VAT_INVOICE_AMOUNT,
    FieldName.DISPLAYED_AVERAGE_PRICE,
    FieldName.INDUSTRIAL_COMMERCIAL_FEE,
)

#: 字段的标准单位
FIELD_UNITS: Mapping[FieldName, str] = {
    FieldName.BILLING_PERIOD_START: UNIT_DATE,
    FieldName.BILLING_PERIOD_END: UNIT_DATE,
    FieldName.TOTAL_CONSUMPTION: UNIT_KWH,
    FieldName.BILL_TOTAL_AMOUNT: UNIT_YUAN,
    FieldName.VAT_INVOICE_AMOUNT: UNIT_YUAN,
    FieldName.DISPLAYED_AVERAGE_PRICE: UNIT_YUAN_PER_KWH,
    FieldName.INDUSTRIAL_COMMERCIAL_FEE: UNIT_YUAN,
    FieldName.MARKET_PURCHASE_FEE: UNIT_YUAN,
    FieldName.GRID_LOSS_FEE: UNIT_YUAN,
    FieldName.TRANSMISSION_DISTRIBUTION_FEE: UNIT_YUAN,
    FieldName.SYSTEM_OPERATION_FEE: UNIT_YUAN,
    FieldName.GOVERNMENT_FUND_FEE: UNIT_YUAN,
    FieldName.POWER_FACTOR_ADJUSTMENT_FEE: UNIT_YUAN,
    FieldName.DEMAND_CHARGE: UNIT_YUAN,
}


@dataclass(frozen=True)
class FieldEvidence:
    """单个字段的一条来源证据。

    ``source_text`` 必须保留**原文**（含原始空格与换行），
    不得存入规范化后的文本——规范化只用于匹配，证据用于审计。
    """

    page_number: int
    source_text: str
    raw_value: str
    label: str
    rule_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.page_number, int) or self.page_number < 1:
            raise ValueError(f"页码必须是从 1 开始的整数，实际为 {self.page_number!r}")
        if not self.source_text.strip():
            raise ValueError("source_text（原文片段）不能为空——证据必须可追溯")
        if not self.rule_id.strip():
            raise ValueError("rule_id（规则标识）不能为空——结果必须可追溯到规则")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "source_text": self.source_text,
            "raw_value": self.raw_value,
            "label": self.label,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True)
class BillField:
    """一个字段的完整识别结果。

    Attributes:
        name: 标准字段名（:class:`FieldName` 的取值）。
        unit: 单位；单位不明时为 ``None``。
        status: 识别状态。
        value: 唯一确定时的标准化值；否则 ``None``。
            日期字段为 :class:`datetime.date`，其余为 ``Decimal``。
        raw_value: 原文数值字面量（如 ``"6,708,448.31"``）。
        evidences: 全部来源证据，至少一条（``missing`` 除外）。
        candidates: 全部**不同**的候选值（用于冲突展示与人工复核）。
        issues: 该字段相关问题。
        parser_version: 产出该结果的解析规则版本。
        requires_manual_confirmation: 是否必须人工确认。
    """

    name: str
    status: FieldStatus
    unit: str | None = None
    value: Decimal | date | None = None
    raw_value: str | None = None
    evidences: tuple[FieldEvidence, ...] = ()
    candidates: tuple[Decimal, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    parser_version: str = ""
    requires_manual_confirmation: bool = False

    def __post_init__(self) -> None:
        self._validate_name()
        self._validate_value_type()
        self._validate_status_consistency()

    # -- 校验 -----------------------------------------------------------
    def _validate_name(self) -> None:
        valid = {item.value for item in FieldName}
        if self.name not in valid:
            raise ValueError(
                f"未知字段名 {self.name!r}；必须是 FieldName 中的取值之一"
                "（字段名是跨文档与代码的契约，不得使用近似名称）"
            )

    def _validate_value_type(self) -> None:
        if self.value is None:
            return
        if isinstance(self.value, float):
            raise TypeError("字段值不得为 float；金额与电量必须使用 Decimal")
        expected_is_date = self.name in (
            FieldName.BILLING_PERIOD_START.value,
            FieldName.BILLING_PERIOD_END.value,
        )
        if expected_is_date:
            if not isinstance(self.value, date):
                raise TypeError(f"{self.name} 的值必须是 datetime.date，实际为 {type(self.value).__name__}")
        elif not isinstance(self.value, Decimal):
            raise TypeError(f"{self.name} 的值必须是 Decimal，实际为 {type(self.value).__name__}")

    def _validate_status_consistency(self) -> None:
        distinct = set(self.candidates)

        if self.status is FieldStatus.PARSED:
            if self.value is None:
                raise ValueError("状态为 parsed 时 value 不得为 None")
            if len(distinct) > 1:
                raise ValueError(
                    "状态为 parsed 时不得存在多个不同候选值；"
                    "多候选必须置为 needs_review（禁止静默择一）"
                )
            if not self.evidences:
                raise ValueError("状态为 parsed 时必须至少有一条来源证据")

        if self.status is FieldStatus.NEEDS_REVIEW:
            if self.value is not None:
                raise ValueError(
                    "状态为 needs_review 时 value 必须为 None（不选任何一个候选值）"
                )
            if not self.requires_manual_confirmation:
                raise ValueError("状态为 needs_review 时必须要求人工确认")

        if self.status is FieldStatus.MISSING:
            if self.value is not None:
                raise ValueError("状态为 missing 时 value 必须为 None（禁止补 0）")
            if self.evidences:
                raise ValueError("状态为 missing 时不应有来源证据")
            if not self.requires_manual_confirmation:
                raise ValueError("状态为 missing 时必须要求人工确认")

        if self.status is FieldStatus.INVALID:
            if self.value is not None:
                raise ValueError("状态为 invalid 时 value 必须为 None")
            if not self.requires_manual_confirmation:
                raise ValueError("状态为 invalid 时必须要求人工确认")

        # 缺失值一律要求人工确认，防止"没有值"被当成"值为 0"继续流转
        if self.value is None and not self.requires_manual_confirmation:
            raise ValueError(
                "value 为 None 时必须要求人工确认（缺失不得被当作 0 继续流转）"
            )

        # 金额类字段不得出现 float（类型层面再兜一层）
        if self.unit in (UNIT_YUAN, UNIT_YUAN_PER_KWH, UNIT_KWH) and isinstance(self.value, float):
            raise TypeError(f"{self.name} 为数值类字段，值不得为 float")

    # -- 便捷属性 -------------------------------------------------------
    @property
    def is_parsed(self) -> bool:
        return self.status is FieldStatus.PARSED

    @property
    def is_missing(self) -> bool:
        return self.status is FieldStatus.MISSING

    @property
    def has_conflict(self) -> bool:
        """是否存在多个不同候选值。"""
        return len(set(self.candidates)) > 1

    @property
    def is_resolved(self) -> bool:
        """是否已唯一确定且无需人工确认。"""
        return self.status is FieldStatus.PARSED and not self.requires_manual_confirmation

    def evidence_pages(self) -> tuple[int, ...]:
        """全部证据所在页码（去重、升序）。"""
        return tuple(sorted({e.page_number for e in self.evidences}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "status": self.status.value,
            "value": None if self.value is None else str(self.value),
            "raw_value": self.raw_value,
            "candidates": [str(c) for c in self.candidates],
            "evidences": [e.to_dict() for e in self.evidences],
            "issues": [i.to_dict() for i in self.issues],
            "parser_version": self.parser_version,
            "requires_manual_confirmation": self.requires_manual_confirmation,
        }


@dataclass(frozen=True)
class ReconciliationResult:
    """费用勾稽结果。

    超差时**只记录**，绝不修改任何字段的 ``value``。
    """

    relation: str
    expected: Decimal
    actual: Decimal
    participating_fields: tuple[str, ...]
    tolerance: Decimal = RECONCILIATION_TOLERANCE_YUAN

    def __post_init__(self) -> None:
        for label, value in (("expected", self.expected), ("actual", self.actual), ("tolerance", self.tolerance)):
            if isinstance(value, float):
                raise TypeError(f"{label} 不得为 float；金额必须使用 Decimal")
            if not isinstance(value, Decimal):
                raise TypeError(f"{label} 必须是 Decimal，实际为 {type(value).__name__}")
        if self.tolerance < 0:
            raise ValueError("容差不能为负")
        if not self.participating_fields:
            raise ValueError("必须记录参与勾稽的字段名，以便界面展示与追溯")

    @property
    def difference(self) -> Decimal:
        """差额（``expected - actual``，保留正负号）。"""
        return self.expected - self.actual

    @property
    def absolute_difference(self) -> Decimal:
        return abs(self.difference)

    @property
    def is_within_tolerance(self) -> bool:
        """差额绝对值是否不超过容差（含边界）。"""
        return self.absolute_difference <= self.tolerance

    def to_issue(self) -> ValidationIssue | None:
        """超差时返回一条 ``WARNING`` 级问题；未超差返回 ``None``。"""
        if self.is_within_tolerance:
            return None
        return ValidationIssue(
            issue_code="reconciliation_mismatch",
            field_name=self.relation,
            message=(
                f"费用勾稽超差：计算值 {self.expected}，账单标注值 {self.actual}，"
                f"差额 {self.difference}，容差 {self.tolerance}。"
                f"参与字段：{', '.join(self.participating_fields)}。"
                "已保留原始数据，请人工复核。"
            ),
            severity=Severity.WARNING,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "difference": str(self.difference),
            "tolerance": str(self.tolerance),
            "is_within_tolerance": self.is_within_tolerance,
            "participating_fields": list(self.participating_fields),
        }


@dataclass(frozen=True)
class BillConfirmation:
    """一次账单确认记录。

    这是"解析完成"与"可进入正式测算"之间的**唯一闸门**：
    未经确认，任何解析结果都不得用于正式经济性测算（任务书要求）。
    """

    status: ConfirmationStatus = ConfirmationStatus.PENDING
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ConfirmationStatus):
            raise TypeError(
                f"status 必须是 ConfirmationStatus，实际为 {type(self.status).__name__}"
            )
        if self.status is ConfirmationStatus.CONFIRMED:
            if not (self.confirmed_by or "").strip():
                raise ValueError("状态为 confirmed 时必须记录确认人（confirmed_by）")
            if self.confirmed_at is None:
                raise ValueError("状态为 confirmed 时必须记录确认时间（confirmed_at）")
        if self.status is ConfirmationStatus.PENDING and (
            self.confirmed_by or self.confirmed_at
        ):
            raise ValueError("状态为 pending 时不得携带确认人与确认时间")

    @property
    def is_confirmed(self) -> bool:
        return self.status is ConfirmationStatus.CONFIRMED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": None if self.confirmed_at is None else self.confirmed_at.isoformat(),
            "note": self.note,
        }


#: 未经确认的默认确认记录
PENDING_CONFIRMATION = BillConfirmation()


@dataclass(frozen=True)
class BillFieldSet:
    """一次解析的完整结果。

    ``extraction_status`` 来自 P0-1：**提取不完整时，无论字段识别得多完整，
    都不得判定为可用于测算**。
    """

    fields: Mapping[str, BillField]
    parser_version: str
    page_count: int
    extraction_status: PdfExtractionStatus
    issues: tuple[ValidationIssue, ...] = ()
    reconciliations: tuple[ReconciliationResult, ...] = ()
    confirmation: BillConfirmation = PENDING_CONFIRMATION

    def __post_init__(self) -> None:
        if self.page_count < 0:
            raise ValueError("页数不能为负")
        if not isinstance(self.extraction_status, PdfExtractionStatus):
            raise TypeError(
                f"extraction_status 必须是 PdfExtractionStatus，实际为 "
                f"{type(self.extraction_status).__name__}"
            )
        if not isinstance(self.confirmation, BillConfirmation):
            raise TypeError(
                f"confirmation 必须是 BillConfirmation，实际为 "
                f"{type(self.confirmation).__name__}"
            )
        for key, item in self.fields.items():
            if key != item.name:
                raise ValueError(f"fields 的键 {key!r} 与字段名 {item.name!r} 不一致")

    # -- 取字段 ---------------------------------------------------------
    def get(self, name: str | FieldName) -> BillField | None:
        """按字段名取字段；不存在返回 ``None``。"""
        key = name.value if isinstance(name, FieldName) else name
        return self.fields.get(key)

    def require(self, name: str | FieldName) -> BillField:
        """按字段名取字段；不存在抛 :class:`KeyError`。"""
        field_obj = self.get(name)
        if field_obj is None:
            raise KeyError(f"字段集缺少字段：{name}")
        return field_obj

    def amount(self, name: str | FieldName) -> Decimal | None:
        """取数值型字段的值（缺失或未定时返回 ``None``）。"""
        field_obj = self.get(name)
        if field_obj is None:
            return None
        value = field_obj.value
        return value if isinstance(value, Decimal) else None

    @property
    def billing_days(self) -> int | None:
        """账期天数（含首尾）。

        Returns:
            天数；账期首尾任一未确定时返回 ``None``（**不返回 0 或 30 之类的默认值**）。
        """
        start = self.get(FieldName.BILLING_PERIOD_START)
        end = self.get(FieldName.BILLING_PERIOD_END)
        if start is None or end is None:
            return None
        if not isinstance(start.value, date) or not isinstance(end.value, date):
            return None
        return (end.value - start.value).days + 1

    # -- 状态判定 -------------------------------------------------------
    @property
    def is_parsed_and_ready_for_review(self) -> bool:
        """解析层面是否已完成、结果是否可供人工复核。

        **这不等于可以进入正式测算**——还需人工确认（见
        :attr:`is_usable_for_calculation`）。

        条件：提取完整 + 必需字段全部 parsed + 无冲突/待复核字段 + 勾稽在容差内。
        """
        if not self.is_complete_extraction:
            return False
        if not self.all_required_fields_parsed:
            return False
        if self.fields_requiring_review:
            return False
        return not self.has_reconciliation_mismatch

    @property
    def is_confirmed(self) -> bool:
        """是否已由人工确认。"""
        return self.confirmation.is_confirmed

    @property
    def needs_manual_review(self) -> bool:
        """是否需要人工复核（含"已解析待确认"与"存在问题"两种情形）。"""
        return not self.is_confirmed

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        """当前**阻塞进入正式测算**的原因清单（便于界面与接口直接展示）。"""
        reasons: list[str] = []
        if not self.is_complete_extraction:
            reasons.append(
                f"PDF 提取不完整（状态 {self.extraction_status.value}），不得进入正式测算"
            )
        missing = self.missing_fields
        if missing:
            reasons.append(f"存在缺失字段：{', '.join(missing)}")
        conflicted = self.conflicted_fields
        if conflicted:
            reasons.append(f"存在冲突字段（未自动择一）：{', '.join(conflicted)}")
        review = tuple(
            name for name in self.fields_requiring_review if name not in set(conflicted) | set(missing)
        )
        if review:
            reasons.append(f"以下字段需人工复核：{', '.join(review)}")
        if self.has_reconciliation_mismatch:
            mismatched = [
                rel.relation for rel in self.reconciliations if not rel.is_within_tolerance
            ]
            reasons.append(f"费用勾稽超差：{', '.join(mismatched)}")
        if self.confirmation.status is ConfirmationStatus.REJECTED:
            reasons.append("人工复核已驳回")
        elif self.confirmation.status is ConfirmationStatus.PENDING:
            reasons.append("尚未完成人工确认")
        return tuple(reasons)

    # -- 确认闸门 -------------------------------------------------------
    def can_confirm(self) -> tuple[bool, tuple[str, ...]]:
        """判断当前结果是否**允许被确认**。

        Returns:
            ``(是否允许, 阻塞原因)``。只有解析完整、无缺失/冲突/超差时才允许确认。
        """
        allowed = self.is_parsed_and_ready_for_review
        reasons = tuple(
            reason
            for reason in self.blocking_reasons
            if "尚未完成人工确认" not in reason
        )
        return allowed, reasons

    def confirm(
        self,
        *,
        confirmed_by: str,
        note: str | None = None,
        confirmed_at: datetime | None = None,
    ) -> BillFieldSet:
        """人工确认该结果，返回**新的**字段集。

        这是进入正式测算的必经步骤：未经确认的结果
        :attr:`is_usable_for_calculation` 恒为 ``False``。

        Args:
            confirmed_by: 确认人（必填，不得为空白）。
            note: 复核备注。
            confirmed_at: 确认时间；``None`` 时取当前 UTC 时间。

        Raises:
            ValueError: 未提供确认人，或存在阻塞问题（缺失/冲突/勾稽超差/
                提取不完整）时不允许确认——确认不能绕过复核。
        """
        if not (confirmed_by or "").strip():
            raise ValueError("必须提供确认人（confirmed_by），不得为空白")
        allowed, reasons = self.can_confirm()
        if not allowed:
            raise ValueError(
                "当前结果不允许确认，存在阻塞问题：" + "；".join(reasons)
            )
        return replace(
            self,
            confirmation=BillConfirmation(
                status=ConfirmationStatus.CONFIRMED,
                confirmed_by=confirmed_by.strip(),
                confirmed_at=confirmed_at or datetime.now(timezone.utc),
                note=note,
            ),
        )

    def reject(
        self,
        *,
        rejected_by: str,
        reason: str,
        rejected_at: datetime | None = None,
    ) -> BillFieldSet:
        """人工复核后驳回该结果，返回**新的**字段集。"""
        if not (rejected_by or "").strip():
            raise ValueError("必须提供复核人（rejected_by），不得为空白")
        if not (reason or "").strip():
            raise ValueError("必须提供驳回原因（reason），不得为空白")
        return replace(
            self,
            confirmation=BillConfirmation(
                status=ConfirmationStatus.REJECTED,
                confirmed_by=rejected_by.strip(),
                confirmed_at=rejected_at or datetime.now(timezone.utc),
                note=reason.strip(),
            ),
        )

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.fields.items() if v.is_missing))

    @property
    def conflicted_fields(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.fields.items() if v.has_conflict))

    @property
    def fields_requiring_review(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.fields.items() if v.requires_manual_confirmation))

    @property
    def has_reconciliation_mismatch(self) -> bool:
        return any(not r.is_within_tolerance for r in self.reconciliations)

    @property
    def is_complete_extraction(self) -> bool:
        """P0-1 的提取是否完整（只有 ``success`` 视为完整）。"""
        return self.extraction_status is PdfExtractionStatus.SUCCESS

    @property
    def all_required_fields_parsed(self) -> bool:
        for name in REQUIRED_FIELDS:
            field_obj = self.get(name)
            if field_obj is None or not field_obj.is_parsed:
                return False
        return True

    @property
    def is_usable_for_calculation(self) -> bool:
        """是否可用于**正式经济性测算**。

        必须**同时**满足：

        1. P0-1 提取状态为 ``SUCCESS``（部分提取/需 OCR/失败一律不可用）；
        2. 必需字段全部 ``parsed``；
        3. 没有任何字段要求人工确认（无缺失、无冲突）；
        4. 勾稽全部在容差内；
        5. **已由人工确认**（:class:`ConfirmationStatus.CONFIRMED`）。

        Important:
            第 5 条是本项目的一条硬性闸门：**解析成功不等于账单有效**，
            调用方不得仅凭解析成功就进入正式测算。
            没有第 5 条时本属性恒为 ``False``。
        """
        return self.is_parsed_and_ready_for_review and self.is_confirmed

    def to_dict(self) -> dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "page_count": self.page_count,
            "extraction_status": self.extraction_status.value,
            "is_complete_extraction": self.is_complete_extraction,
            "is_parsed_and_ready_for_review": self.is_parsed_and_ready_for_review,
            "is_confirmed": self.is_confirmed,
            "needs_manual_review": self.needs_manual_review,
            "is_usable_for_calculation": self.is_usable_for_calculation,
            "blocking_reasons": list(self.blocking_reasons),
            "confirmation": self.confirmation.to_dict(),
            "missing_fields": list(self.missing_fields),
            "conflicted_fields": list(self.conflicted_fields),
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "reconciliations": [r.to_dict() for r in self.reconciliations],
            "issues": [i.to_dict() for i in self.issues],
        }
