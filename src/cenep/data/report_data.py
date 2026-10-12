"""账单事实报告的数据组装（规格书第 34、41 节）。

**设计边界（重要）**：本模块只做**账单事实的整理与呈现**，
明确**不做**经济性结论——

- 不计算收益率、回收期、NPV/IRR；
- **不把账单平均电价当作光伏边际节省电价**（规格书第 5.3 节明令禁止）；
- 不推测光伏消纳率（缺少逐时负荷时，只能标注"数据不足"）。

报告中的数据分为三类，以便阅读者区分证据强度：

1. **原始事实**：账单原文录入的金额与电量；
2. **计算值**：由原始事实按明确公式得出（如电量差、合计）；
3. **缺失/待核实**：未提供的字段显式标注，**不补 0**。

本模块是纯数据装配，不导入任何 Excel 库；
生成 xlsx 由 :mod:`cenep.data.report_writer` 负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from cenep.data.bill_validation import CHECK_ITEMS, ValidationReport, validate_bill_data
from cenep.domain.bill_models import (
    BillFeeItem,
    BillMeterPoint,
    BillTimeOfUseItem,
    ElectricityBill,
    IncludedInOtherFee,
    ReviewStatus,
)

__all__ = [
    "ReportBundle",
    "MISSING_TEXT",
    "build_report_bundle",
    "format_decimal",
    "format_optional",
]

#: 未提供值的统一显示文本（**不显示 0**）
MISSING_TEXT = "未提供"

#: 报告标题与版本
REPORT_TITLE = "CENEP 电费账单数据质量与事实报告"
REPORT_VERSION = "1.0"


def format_optional(value: Decimal | None) -> str:
    """数值显示：``None`` → "未提供"，否则十进制字符串（不经过 float）。"""
    if value is None:
        return MISSING_TEXT
    if not isinstance(value, Decimal):
        raise TypeError(f"报告数值必须为 Decimal，实际为 {type(value).__name__}")
    return str(value)


def format_decimal(value: Decimal) -> str:
    """必定存在的数值。"""
    return str(value)


def _format_date(value: date | None) -> str:
    return value.isoformat() if value is not None else MISSING_TEXT


@dataclass(frozen=True)
class ReportBundle:
    """一份报告所需的全部数据（与具体文件格式无关）。"""

    project_id: str
    project_name: str
    generated_at: str
    bills: tuple[ElectricityBill, ...] = ()
    tou_items: tuple[BillTimeOfUseItem, ...] = ()
    fee_items: tuple[BillFeeItem, ...] = ()
    meter_points: tuple[BillMeterPoint, ...] = ()
    validation: ValidationReport | None = None
    notes: tuple[str, ...] = ()

    # -- 概览 -----------------------------------------------------------
    @property
    def bill_count(self) -> int:
        return len(self.bills)

    @property
    def confirmed_count(self) -> int:
        return sum(1 for bill in self.bills if bill.is_confirmed)

    @property
    def usable_count(self) -> int:
        return sum(1 for bill in self.bills if bill.is_usable_for_calculation)

    @property
    def periods(self) -> tuple[str, ...]:
        return tuple(sorted({bill.billing_period for bill in self.bills if bill.billing_period}))

    @property
    def total_energy_kwh(self) -> Decimal | None:
        values = [bill.total_energy_kwh for bill in self.bills if bill.total_energy_kwh is not None]
        return sum(values, Decimal(0)) if values else None

    @property
    def total_amount_yuan(self) -> Decimal | None:
        values = [
            bill.total_amount_yuan for bill in self.bills if bill.total_amount_yuan is not None
        ]
        return sum(values, Decimal(0)) if values else None

    @property
    def blocking_count(self) -> int:
        return len(self.validation.blocking_issues) if self.validation else 0

    @property
    def failed_check_count(self) -> int:
        return len(self.validation.failed_issues) if self.validation else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "generated_at": self.generated_at,
            "bill_count": self.bill_count,
            "confirmed_count": self.confirmed_count,
            "usable_count": self.usable_count,
            "periods": list(self.periods),
            "total_energy_kwh": format_optional(self.total_energy_kwh),
            "total_amount_yuan": format_optional(self.total_amount_yuan),
            "blocking_count": self.blocking_count,
            "failed_check_count": self.failed_check_count,
        }


#: 概览中"数据完整性"要回答的问题
DATA_COMPLETENESS_QUESTIONS: tuple[str, ...] = (
    "是否覆盖连续月份（账期无缺月）",
    "是否每张账单都已人工确认",
    "是否存在阻断级校验问题",
    "是否有分时电量（缺少则无法评估光伏消纳）",
    "是否记录了来源文件与页码（可追溯）",
)


def _completeness_findings(bundle: ReportBundle) -> list[tuple[str, str, str]]:
    """生成"数据完整性"判断表：``(检查问题, 结论, 说明)``。

    结论只有三种：**满足 / 不满足 / 待核实**，不做评分、不做经济推断。
    """
    findings: list[tuple[str, str, str]] = []

    # 1) 账期是否连续
    periods = list(bundle.periods)
    if len(periods) < 2:
        findings.append(
            ("是否覆盖连续月份（账期无缺月）", "待核实", f"当前仅有 {len(periods)} 个账期，不足以判断连续性")
        )
    else:
        gaps: list[str] = []
        for previous, current in zip(periods, periods[1:]):
            try:
                py, pm = (int(part) for part in previous.split("-"))
                cy, cm = (int(part) for part in current.split("-"))
            except (ValueError, AttributeError):
                gaps.append(f"{previous}→{current}")
                continue
            expected = py * 12 + pm + 1
            if cy * 12 + cm != expected:
                gaps.append(f"{previous}→{current}")
        if gaps:
            findings.append(
                ("是否覆盖连续月份（账期无缺月）", "不满足", f"存在缺月：{'、'.join(gaps)}")
            )
        else:
            findings.append(
                ("是否覆盖连续月份（账期无缺月）", "满足", f"{periods[0]} 至 {periods[-1]} 连续")
            )

    # 2) 是否全部已确认
    if bundle.bill_count == 0:
        findings.append(("是否每张账单都已人工确认", "待核实", "没有账单"))
    elif bundle.confirmed_count == bundle.bill_count:
        findings.append(
            ("是否每张账单都已人工确认", "满足", f"{bundle.confirmed_count}/{bundle.bill_count} 已确认")
        )
    else:
        findings.append(
            (
                "是否每张账单都已人工确认",
                "不满足",
                f"仅 {bundle.confirmed_count}/{bundle.bill_count} 已确认；"
                "未确认数据不得用于正式测算",
            )
        )

    # 3) 阻断级问题
    if bundle.validation is None:
        findings.append(("是否存在阻断级校验问题", "待核实", "未执行校验"))
    elif bundle.blocking_count:
        findings.append(
            ("是否存在阻断级校验问题", "不满足", f"存在 {bundle.blocking_count} 项阻断级问题")
        )
    else:
        findings.append(("是否存在阻断级校验问题", "满足", "无阻断级问题"))

    # 4) 分时电量
    timed = [item for item in bundle.tou_items if item.energy_kwh is not None]
    if not timed:
        findings.append(
            (
                "是否有分时电量（缺少则无法评估光伏消纳）",
                "不满足",
                "仅有月度总量；缺少分时电量时无法精确评估自发自用，"
                "如需估算必须标注为估算值",
            )
        )
    else:
        findings.append(
            ("是否有分时电量（缺少则无法评估光伏消纳）", "满足", f"共 {len(timed)} 条分时电量")
        )

    # 5) 可追溯性
    missing_source = [
        bill.billing_period or "（无账期）"
        for bill in bundle.bills
        if not bill.source_file or not bill.source_page
    ]
    if not bundle.bills:
        findings.append(("是否记录了来源文件与页码（可追溯）", "待核实", "没有账单"))
    elif missing_source:
        findings.append(
            (
                "是否记录了来源文件与页码（可追溯）",
                "不满足",
                f"以下账期缺少来源：{'、'.join(missing_source)}",
            )
        )
    else:
        findings.append(("是否记录了来源文件与页码（可追溯）", "满足", "全部账单均可追溯到来源文件与页码"))

    return findings


def build_report_bundle(
    *,
    project_id: str,
    project_name: str,
    bills: Sequence[ElectricityBill],
    tou_items: Sequence[BillTimeOfUseItem] = (),
    fee_items: Sequence[BillFeeItem] = (),
    meter_points: Sequence[BillMeterPoint] = (),
    generated_at: str | None = None,
) -> ReportBundle:
    """组装报告数据（含校验结果与固定说明）。

    Args:
        project_id / project_name: 项目标识与名称。
        bills: 账单主记录。
        tou_items / fee_items / meter_points: 从属明细。
        generated_at: 生成时间（ISO 8601）；默认为当前 UTC 时间。

    Returns:
        :class:`ReportBundle`。**不修改任何输入对象。**
    """
    bill_tuple = tuple(bills)
    tou_tuple = tuple(tou_items)
    fee_tuple = tuple(fee_items)
    meter_tuple = tuple(meter_points)

    report = validate_bill_data(
        bill_tuple,
        tou_items=tou_tuple,
        fee_items=fee_tuple,
        meter_points=meter_tuple,
    )

    notes: list[str] = [
        "本报告只呈现账单事实与数据质量，不包含收益率、回收期等经济性结论。",
        "账单展示平均电价仅为账单统计值，**不能作为光伏边际节省电价使用**。",
        "未提供的字段显示为“未提供”，系统不会把它当作 0。",
        "缺少分时/逐时电量时，无法精确评估光伏自发自用；如需估算必须标注为估算值。",
        "未人工确认的账单不得用于正式测算。",
        f"校验项定义：{'、'.join(f'{code} {name}' for code, name in CHECK_ITEMS.items())}。",
    ]

    return ReportBundle(
        project_id=project_id,
        project_name=project_name,
        generated_at=generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        bills=bill_tuple,
        tou_items=tou_tuple,
        fee_items=fee_tuple,
        meter_points=meter_tuple,
        validation=report,
        notes=tuple(notes),
    )


#: 报告用到的固定说明（供 writer 与界面共用）
REPORT_NOTES: tuple[str, ...] = (
    "本报告由 CENEP 生成，仅呈现账单事实与数据质量，不含经济性结论。",
    "未提供的字段显示为“未提供”，不视为 0。",
)

#: 账单事实表的列定义：``(标题, 取值)``
BILL_FACT_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("账期", lambda b: b.billing_period or MISSING_TEXT),
    ("账期开始", lambda b: _format_date(b.period_start)),
    ("账期结束", lambda b: _format_date(b.period_end)),
    ("户号", lambda b: b.account_number or MISSING_TEXT),
    ("用户名称", lambda b: b.customer_name or MISSING_TEXT),
    ("供电单位", lambda b: b.supply_company or MISSING_TEXT),
    ("本期总电量_kWh", lambda b: format_optional(b.total_energy_kwh)),
    ("账单本期电费_元", lambda b: format_optional(b.total_amount_yuan)),
    ("增值税专票金额_元", lambda b: format_optional(b.vat_invoice_amount_yuan)),
    ("账单展示平均电价_元每kWh", lambda b: format_optional(b.displayed_average_price)),
    ("工商业电费_元", lambda b: format_optional(b.industrial_commercial_fee_yuan)),
    ("功率因数调整电费_元", lambda b: format_optional(b.power_factor_adjustment_fee_yuan)),
    ("需量电费_元", lambda b: format_optional(b.demand_charge_yuan)),
    ("实际最大需量", lambda b: format_optional(b.actual_demand)),
    ("需量单位", lambda b: b.actual_demand_unit or MISSING_TEXT),
    ("复核状态", lambda b: b.review_status.value),
    ("确认状态", lambda b: b.confirmation.value),
    ("可用于正式测算", lambda b: "是" if b.is_usable_for_calculation else "否"),
    ("样本数据", lambda b: "是" if b.is_sample else "否"),
    ("来源文件", lambda b: b.source_file or MISSING_TEXT),
    ("来源页码", lambda b: b.source_page or MISSING_TEXT),
    ("备注", lambda b: b.note or ""),
)

#: 费用明细表的列定义
FEE_FACT_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("账期", lambda f: f.billing_period or MISSING_TEXT),
    ("费用大类", lambda f: f.fee_category.value if f.fee_category else MISSING_TEXT),
    ("费用项目名称", lambda f: f.fee_name or MISSING_TEXT),
    ("金额_元", lambda f: format_optional(f.amount_yuan)),
    ("是否包含在其他费用中", lambda f: f.included_in_other.value),
    ("被包含于/关联费用", lambda f: f.included_in_fee_name or ""),
    ("是否计入基准合计", lambda f: "是" if f.counts_toward_baseline else "否"),
    ("光伏测算可避免性", lambda f: f.avoidability.value),
    ("是否纳入基准电费", lambda f: f.baseline_inclusion.value),
)

#: 分时电量电价表的列定义
TOU_FACT_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("账期", lambda t: t.billing_period or MISSING_TEXT),
    ("计量口径/计量点编号", lambda t: t.metering_basis_id or MISSING_TEXT),
    ("电量类型", lambda t: t.basis.value),
    ("时段名称", lambda t: t.period_name.value if t.period_name else MISSING_TEXT),
    ("时段开始", lambda t: t.segment_start.strftime("%H:%M") if t.segment_start else MISSING_TEXT),
    ("时段结束", lambda t: t.segment_end.strftime("%H:%M") if t.segment_end else MISSING_TEXT),
    ("电量_kWh", lambda t: format_optional(t.energy_kwh)),
    ("购电电价_元每kWh", lambda t: format_optional(t.price_yuan_per_kwh)),
)

#: 计量点表的列定义
METER_FACT_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("账期", lambda m: m.billing_period or MISSING_TEXT),
    ("计量点编号", lambda m: m.point_code or MISSING_TEXT),
    ("计量点名称/位置", lambda m: m.point_name or ""),
    ("计量点类型", lambda m: m.point_type.value if m.point_type else MISSING_TEXT),
    ("电量_kWh", lambda m: format_optional(m.energy_kwh)),
    ("是否已计入首页总电量", lambda m: m.included_in_total.value),
    ("是否允许纳入汇总", lambda m: m.allowed_in_rollup.value),
    ("是否可参与汇总", lambda m: "是" if m.can_join_rollup else "否"),
)


def fee_baseline_subtotal(fee_items: Sequence[BillFeeItem]) -> Decimal | None:
    """计入基准合计的费用小计。

    只累加"未包含在其他费用中"且"纳入基准电费"为是、且有金额的项。
    无任何参与项时返回 ``None``（而不是 0），以免被误读为"合计为零"。
    """
    participants = [
        item for item in fee_items if item.counts_toward_baseline and item.amount_yuan is not None
    ]
    if not participants:
        return None
    return sum((item.amount_yuan for item in participants), Decimal(0))


def internal_fee_subtotal(fee_items: Sequence[BillFeeItem]) -> Decimal | None:
    """已包含在其他费用中的项之和（用于提示重复汇总风险）。"""
    internal = [
        item
        for item in fee_items
        if item.included_in_other is IncludedInOtherFee.YES and item.amount_yuan is not None
    ]
    if not internal:
        return None
    return sum((item.amount_yuan for item in internal), Decimal(0))


def completeness_findings(bundle: ReportBundle) -> list[tuple[str, str, str]]:
    """对外暴露"数据完整性"判断结果。"""
    return _completeness_findings(bundle)
