"""账单数据校验（规格书第 27 节 13 类校验项）。

本模块对一批账单数据执行确定性检查，产出
:class:`cenep.domain.bill_models.BillValidationIssue` 清单。

设计原则（规格书第 35、36、37 节）：

- **只报告，不改数**：校验不得修改任何原始金额或电量；
- **口径一致才比较**：分时电量与总电量只在账期、计量口径、电量类型一致时比较；
- **缺失不等于 0**：未提供的时段视为"未知"，不得当成 0 来证明数据完整；
- **不擅自汇总**：未核实主分表关系或已计入首页总量的计量点不参与汇总；
- **不把分项简单相加**：只有"未包含在其他费用中"且"纳入基准电费"为是的费用项
  才参与基准合计。

校验结论以"问题清单"形式返回；调用方（阶段 3 导入器、阶段 4 界面）负责展示
并决定是否放行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence

from cenep.domain.bill_models import (
    ZERO,
    BillFeeItem,
    BillMeterPoint,
    BillTimeOfUseItem,
    BillValidationIssue,
    ElectricityBill,
    IncludedInOtherFee,
    MeteringBasis,
    ReviewStatus,
    ValidationResultState,
    ValidationSeverityLevel,
    YesNoUnknown,
)

__all__ = [
    "CHECK_ITEMS",
    "ValidationReport",
    "validate_bill_data",
]

#: 13 类校验项的编号与名称（与模板 `数据校验` 表一致）
CHECK_ITEMS: dict[str, str] = {
    "V01": "账期完整性",
    "V02": "总电量有效性",
    "V03": "账单金额有效性",
    "V04": "首页总量与分时电量口径冲突",
    "V05": "计量点是否重复计入",
    "V06": "费用是否重复计入",
    "V07": "费用分项与账单总金额勾稽",
    "V08": "分时电量与总量勾稽",
    "V09": "电价单位检查",
    "V10": "需量单位与计费方式检查",
    "V11": "关键字段复核状态",
    "V12": "来源文件与页码可追溯性",
    "V13": "是否具备光伏消纳测算所需数据",
}

#: `月度汇总` 表中属于"关键字段"的账单属性（规格书第 27 节 V11）
KEY_REVIEW_FIELDS: tuple[tuple[str, str], ...] = (
    ("total_energy_kwh", "本期总电量_kWh"),
    ("total_amount_yuan", "账单本期电费_元"),
    ("period_start", "账期开始日期"),
    ("period_end", "账期结束日期"),
)

#: 费用勾稽允许的容差（元）
RECONCILIATION_TOLERANCE_YUAN = Decimal("0.02")


@dataclass
class ValidationReport:
    """一次校验的完整结果。"""

    issues: tuple[BillValidationIssue, ...] = ()
    checked_bills: int = 0

    @property
    def blocking_issues(self) -> tuple[BillValidationIssue, ...]:
        """阻断级且未通过的问题。存在任一项则不得导入。"""
        return tuple(issue for issue in self.issues if issue.is_blocking)

    @property
    def has_blocking(self) -> bool:
        return bool(self.blocking_issues)

    @property
    def failed_issues(self) -> tuple[BillValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.result is ValidationResultState.FAIL)

    def issues_for_check(self, check_code: str) -> tuple[BillValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.check_code == check_code)

    def to_dict(self) -> dict[str, object]:
        return {
            "checked_bills": self.checked_bills,
            "issue_count": len(self.issues),
            "blocking_count": len(self.blocking_issues),
            "failed_count": len(self.failed_issues),
            "has_blocking": self.has_blocking,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _issue(
    code: str,
    severity: ValidationSeverityLevel,
    result: ValidationResultState,
    detail: str,
    *,
    sheet_name: str | None = None,
    row_number: int | None = None,
    column_name: str | None = None,
    bill: ElectricityBill | None = None,
) -> BillValidationIssue:
    # 展示友好：未通过的项至少按"警告"呈现，避免"严重程度=提示"与
    # "结果=不通过"并存造成误读；阻断级的判定保持不变。
    effective = severity
    if result is ValidationResultState.FAIL and severity is ValidationSeverityLevel.INFO:
        effective = ValidationSeverityLevel.WARNING
    return BillValidationIssue(
        check_code=code,
        check_item=CHECK_ITEMS[code],
        severity=effective,
        result=result,
        detail=detail,
        sheet_name=sheet_name,
        row_number=row_number,
        column_name=column_name,
        project_id=bill.project_id if bill else "",
    )


def _pass(
    code: str,
    detail: str = "检查通过",
    *,
    sheet_name: str | None = None,
    row_number: int | None = None,
    column_name: str | None = None,
    bill: ElectricityBill | None = None,
) -> BillValidationIssue:
    """产出一条"通过"记录。

    **必须带上工作表与行号**：界面需要逐项定位到模板行，
    通过项也要能显示"检查了哪一行"。
    """
    return _issue(
        code,
        ValidationSeverityLevel.INFO,
        ValidationResultState.PASS,
        detail,
        sheet_name=sheet_name,
        row_number=row_number,
        column_name=column_name,
        bill=bill,
    )


def _not_applicable(
    code: str,
    detail: str,
    *,
    sheet_name: str | None = None,
    row_number: int | None = None,
    bill: ElectricityBill | None = None,
) -> BillValidationIssue:
    """产出一条"不适用"记录（同样带定位信息）。"""
    return _issue(
        code,
        ValidationSeverityLevel.INFO,
        ValidationResultState.NOT_APPLICABLE,
        detail,
        sheet_name=sheet_name,
        row_number=row_number,
        bill=bill,
    )


# ---------------------------------------------------------------------------
# 单项校验
# ---------------------------------------------------------------------------


def _check_v01_period(bill: ElectricityBill, row: int | None) -> BillValidationIssue:
    if bill.period_start is None or bill.period_end is None:
        return _issue(
            "V01",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            "账期开始日期或结束日期缺失",
            sheet_name="月度汇总",
            row_number=row,
            column_name="账期开始日期/账期结束日期",
            bill=bill,
        )
    if bill.period_end < bill.period_start:
        return _issue(
            "V01",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            f"账期结束日期（{bill.period_end}）早于开始日期（{bill.period_start}）",
            sheet_name="月度汇总",
            row_number=row,
            column_name="账期结束日期",
            bill=bill,
        )
    return _pass(
        "V01",
        f"账期 {bill.period_start} ~ {bill.period_end}",
        sheet_name="月度汇总",
        row_number=row,
        bill=bill,
    )


def _check_v02_energy(bill: ElectricityBill, row: int | None) -> BillValidationIssue:
    if bill.total_energy_kwh is None:
        return _issue(
            "V02",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            "本期总电量缺失（缺失不得补 0）",
            sheet_name="月度汇总",
            row_number=row,
            column_name="本期总电量_kWh",
            bill=bill,
        )
    if bill.total_energy_kwh < ZERO:
        return _issue(
            "V02",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            f"本期总电量为负数：{bill.total_energy_kwh}",
            sheet_name="月度汇总",
            row_number=row,
            column_name="本期总电量_kWh",
            bill=bill,
        )
    return _pass(
        "V02",
        f"本期总电量 {bill.total_energy_kwh} kWh",
        sheet_name="月度汇总",
        row_number=row,
        column_name="本期总电量_kWh",
        bill=bill,
    )


def _check_v03_amount(bill: ElectricityBill, row: int | None) -> BillValidationIssue:
    if bill.total_amount_yuan is None:
        return _issue(
            "V03",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            "账单本期电费缺失（缺失不得补 0）",
            sheet_name="月度汇总",
            row_number=row,
            column_name="账单本期电费_元",
            bill=bill,
        )
    if bill.total_amount_yuan < ZERO:
        return _issue(
            "V03",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            f"账单本期电费为负数：{bill.total_amount_yuan}，请核实是否为退费或调整",
            sheet_name="月度汇总",
            row_number=row,
            column_name="账单本期电费_元",
            bill=bill,
        )
    return _pass(
        "V03",
        f"账单本期电费 {bill.total_amount_yuan} 元",
        sheet_name="月度汇总",
        row_number=row,
        column_name="账单本期电费_元",
        bill=bill,
    )


def _check_v04_basis_conflict(
    bill: ElectricityBill,
    tou_items: Sequence[BillTimeOfUseItem],
    row: int | None,
) -> BillValidationIssue:
    """首页总量与分时电量口径冲突检查。

    只在**存在多个计量口径**时才可能冲突：若多个口径的电量都被当作"总量"，
    说明填报口径不清。
    """
    basis_ids = {item.metering_basis_id for item in tou_items if item.metering_basis_id}
    if len(basis_ids) <= 1:
        return _not_applicable(
            "V04",
            "仅一个计量口径，无需检查口径冲突",
            sheet_name="月度汇总",
            row_number=row,
            bill=bill,
        )
    purchase_items = [item for item in tou_items if item.basis is MeteringBasis.PURCHASE]
    purchase_sum = sum(
        (item.energy_kwh for item in purchase_items if item.energy_kwh is not None),
        ZERO,
    )
    if bill.total_energy_kwh is None or purchase_sum == ZERO:
        return _not_applicable(
            "V04",
            "缺少可比对的电量数据",
            sheet_name="月度汇总",
            row_number=row,
            bill=bill,
        )
    difference = bill.total_energy_kwh - purchase_sum
    tolerance = max(
        RECONCILIATION_TOLERANCE_YUAN,
        (abs(bill.total_energy_kwh) * Decimal("0.0001")).quantize(Decimal("1")),
    )
    if abs(difference) > tolerance:
        return _issue(
            "V04",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            f"首页总电量 {bill.total_energy_kwh} 与同口径分时购电电量合计 "
            f"{purchase_sum} 存在差异 {difference}（多计量口径 {len(basis_ids)} 个）",
            sheet_name="月度汇总",
            row_number=row,
            column_name="本期总电量_kWh",
            bill=bill,
        )
    return _pass(
            "V04",
            "首页总量与分时电量口径一致",
            sheet_name="月度汇总",
            row_number=row,
            bill=bill,
        )


def _check_v05_meter_points(
    bill: ElectricityBill,
    meter_points: Sequence[BillMeterPoint],
    row: int | None,
) -> BillValidationIssue:
    if not meter_points:
        return _not_applicable(
            "V05",
            "未提供计量点数据",
            sheet_name="计量点",
            row_number=row,
            bill=bill,
        )
    unclear = [
        point
        for point in meter_points
        if point.included_in_total is YesNoUnknown.TO_VERIFY
        or point.allowed_in_rollup is YesNoUnknown.TO_VERIFY
    ]
    risky = [
        point
        for point in meter_points
        if point.included_in_total is YesNoUnknown.YES
        and point.allowed_in_rollup is YesNoUnknown.YES
    ]
    if risky:
        codes = "、".join(point.point_code for point in risky)
        return _issue(
            "V05",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            f"计量点 {codes} 同时标记为“已计入首页总电量”与“允许纳入汇总”，"
            "存在重复计入风险；不得自动汇总",
            sheet_name="计量点",
            row_number=row,
            column_name="是否已计入首页总电量/是否允许纳入汇总",
            bill=bill,
        )
    if unclear:
        codes = "、".join(point.point_code for point in unclear)
        return _issue(
            "V05",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            f"计量点 {codes} 的主分表关系/汇总标记未核实，不得自动汇总其电量",
            sheet_name="计量点",
            row_number=row,
            bill=bill,
        )
    return _pass(
            "V05",
            f"{len(meter_points)} 个计量点标记清晰",
            sheet_name="计量点",
            row_number=row,
            bill=bill,
        )


def _check_v06_fee_duplication(
    bill: ElectricityBill,
    fee_items: Sequence[BillFeeItem],
    row: int | None,
) -> BillValidationIssue:
    if not fee_items:
        return _not_applicable(
            "V06",
            "未提供费用明细",
            sheet_name="费用明细",
            row_number=row,
            bill=bill,
        )
    unverified = [
        item
        for item in fee_items
        if item.included_in_other is IncludedInOtherFee.TO_VERIFY
    ]
    if unverified:
        names = "、".join(item.fee_name for item in unverified)
        return _issue(
            "V06",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            f"费用项 {names} 的“是否包含在其他费用中”为待核实，"
            "存在重复汇总风险；核实前不得参与合计",
            sheet_name="费用明细",
            row_number=row,
            column_name="是否包含在其他费用中",
            bill=bill,
        )
    return _pass(
            "V06",
            f"{len(fee_items)} 个费用项的包含关系已核实",
            sheet_name="费用明细",
            row_number=row,
            bill=bill,
        )


def _check_v07_reconciliation(
    bill: ElectricityBill,
    fee_items: Sequence[BillFeeItem],
    row: int | None,
) -> BillValidationIssue:
    """费用分项与账单总金额勾稽。

    **只比较口径明确的费用项**：仅"未包含在其他费用中"且"纳入基准电费"为是的项
    参与合计；差异只报告，**不得修改原始金额**。
    """
    participants = [
        item
        for item in fee_items
        if item.counts_toward_baseline and item.amount_yuan is not None
    ]
    if not participants or bill.total_amount_yuan is None:
        return _not_applicable(
            "V07",
            "缺少可参与勾稽的费用项或账单总金额",
            sheet_name="费用明细",
            row_number=row,
            bill=bill,
        )
    subtotal = sum((item.amount_yuan for item in participants), ZERO)
    difference = subtotal - bill.total_amount_yuan
    if abs(difference) > RECONCILIATION_TOLERANCE_YUAN:
        names = "、".join(item.fee_name for item in participants)
        return _issue(
            "V07",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            f"参与勾稽的费用项合计 {subtotal} 与账单本期电费 "
            f"{bill.total_amount_yuan} 差异 {difference}"
            f"（容差 {RECONCILIATION_TOLERANCE_YUAN}）；参与项：{names}。"
            "已保留原始数据，未做任何修改",
            sheet_name="费用明细",
            row_number=row,
            bill=bill,
        )
    return _pass(
            "V07",
            f"费用合计 {subtotal} 与账单总金额一致（容差内）",
            sheet_name="费用明细",
            row_number=row,
            bill=bill,
        )


def _check_v08_tou_energy(
    bill: ElectricityBill,
    tou_items: Sequence[BillTimeOfUseItem],
    row: int | None,
) -> BillValidationIssue:
    """分时电量与总量勾稽。

    仅在账期、计量范围、电量类型均一致时比较；
    **未提供的时段视为未知，不得当成 0**。
    """
    if not tou_items:
        return _not_applicable(
            "V08",
            "未提供分时电量数据",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )
    if bill.total_energy_kwh is None:
        return _not_applicable(
            "V08",
            "缺少总电量，无法比对",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )

    basis_ids = {item.metering_basis_id for item in tou_items if item.metering_basis_id}
    if len(basis_ids) != 1:
        return _not_applicable(
            "V08",
            f"存在 {len(basis_ids)} 个计量口径，口径不一致，不进行求和比较",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )

    purchase_items = [item for item in tou_items if item.basis is MeteringBasis.PURCHASE]
    if not purchase_items:
        return _not_applicable(
            "V08",
            "无购电口径的分时电量",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )

    missing = [item for item in purchase_items if item.energy_kwh is None]
    if missing:
        periods = "、".join(
            item.period_name.value if item.period_name else "未命名时段" for item in missing
        )
        return _issue(
            "V08",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            f"以下时段未提供电量：{periods}；缺失时段视为未知，"
            "不得当作 0 用于证明分时数据完整",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )

    subtotal = sum((item.energy_kwh for item in purchase_items), ZERO)
    difference = bill.total_energy_kwh - subtotal
    tolerance = max(Decimal("1"), (abs(bill.total_energy_kwh) * Decimal("0.0001")).quantize(Decimal("1")))
    if abs(difference) > tolerance:
        return _issue(
            "V08",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            f"电量差 = 总电量 {bill.total_energy_kwh} − 同口径分时电量合计 "
            f"{subtotal} = {difference}（容差 {tolerance}）",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )
    return _pass(
            "V08",
            f"分时电量合计 {subtotal} 与总电量一致（容差内）",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )


def _check_v09_price_unit(
    tou_items: Sequence[BillTimeOfUseItem],
    row: int | None = None,
) -> BillValidationIssue:
    """电价单位检查：单价必须为元/kWh 量级。"""
    if not tou_items:
        return _not_applicable(
            "V09",
            "未提供电价数据",
            sheet_name="分时电量电价",
            row_number=row,
        )
    suspicious = [
        item
        for item in tou_items
        if item.price_yuan_per_kwh is not None and item.price_yuan_per_kwh > Decimal("10")
    ]
    if suspicious:
        periods = "、".join(
            f"{item.metering_basis_id or '未标口径'} "
            f"{item.price_yuan_per_kwh} {item.price_yuan_per_kwh and '元/kWh'}"
            for item in suspicious
        )
        return _issue(
            "V09",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            f"以下电价超出合理量级（疑似误填 元/MWh，需显式换算并记录原始单位）：{periods}",
            sheet_name="分时电量电价",
            column_name="购电电价_元每kWh",
        )
    return _pass(
        "V09",
        "电价量级正常",
        sheet_name="分时电量电价",
        row_number=row,
    )


def _check_v10_demand(
    bill: ElectricityBill,
    row: int | None,
) -> BillValidationIssue:
    """需量单位与计费方式检查。"""
    problems: list[str] = []
    if bill.actual_demand is not None and not bill.actual_demand_unit:
        problems.append("填写了实际最大需量但未填写单位")
    if bill.contract_demand is not None and not bill.contract_demand_unit:
        problems.append("填写了合同最大需量但未填写单位")
    if bill.demand_charge_yuan is not None and not bill.demand_billing_mode:
        problems.append("填写了需量电费但未填写需量计费方式")
    if problems:
        return _issue(
            "V10",
            ValidationSeverityLevel.BLOCKING,
            ValidationResultState.FAIL,
            "；".join(problems) + "。需量单位必须为 kW 或 kVA，两者不得混淆",
            sheet_name="月度汇总",
            row_number=row,
            bill=bill,
        )
    return _pass(
            "V10",
            "需量单位与计费方式检查通过",
            sheet_name="月度汇总",
            row_number=row,
            bill=bill,
        )


def _check_v11_review_status(
    bill: ElectricityBill,
    row: int | None,
) -> BillValidationIssue:
    """关键字段复核状态检查。"""
    missing_values = [
        label for attr, label in KEY_REVIEW_FIELDS if getattr(bill, attr) is None
    ]
    if missing_values:
        return _issue(
            "V11",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            f"以下关键字段空缺，无法复核：{'、'.join(missing_values)}",
            sheet_name="月度汇总",
            row_number=row,
            bill=bill,
        )
    if bill.review_status is ReviewStatus.PENDING:
        return _issue(
            "V11",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            "复核状态为“待复核”：未复核数据不得用于正式测算",
            sheet_name="月度汇总",
            row_number=row,
            column_name="复核状态",
            bill=bill,
        )
    if bill.review_status is ReviewStatus.QUESTIONABLE:
        return _issue(
            "V11",
            ValidationSeverityLevel.WARNING,
            ValidationResultState.FAIL,
            "复核状态为“存在疑问”：须解决后方可用于正式测算",
            sheet_name="月度汇总",
            row_number=row,
            column_name="复核状态",
            bill=bill,
        )
    return _pass(
            "V11",
            f"关键字段齐备，复核状态：{bill.review_status.value}",
            sheet_name="月度汇总",
            row_number=row,
            column_name="复核状态",
            bill=bill,
        )


def _check_v12_traceability(
    bill: ElectricityBill,
    row: int | None,
) -> BillValidationIssue:
    if not bill.source_file:
        return _issue(
            "V12",
            ValidationSeverityLevel.INFO,
            ValidationResultState.FAIL,
            "未填写来源文件，无法追溯",
            sheet_name="月度汇总",
            row_number=row,
            column_name="来源文件",
            bill=bill,
        )
    if not bill.source_page:
        return _issue(
            "V12",
            ValidationSeverityLevel.INFO,
            ValidationResultState.FAIL,
            f"来源文件为 {bill.source_file}，但未填写来源页码",
            sheet_name="月度汇总",
            row_number=row,
            column_name="来源页码",
            bill=bill,
        )
    return _pass(
            "V12",
            f"来源可追溯：{bill.source_file} 第 {bill.source_page} 页",
            sheet_name="月度汇总",
            row_number=row,
            column_name="来源文件",
            bill=bill,
        )


def _check_v13_pv_readiness(
    bill: ElectricityBill,
    tou_items: Sequence[BillTimeOfUseItem],
    row: int | None,
) -> BillValidationIssue:
    """是否具备光伏消纳测算所需数据。

    消纳测算需要**分时/逐时电量**；仅有月总量时不足。
    """
    if bill.total_energy_kwh is None:
        return _issue(
            "V13",
            ValidationSeverityLevel.INFO,
            ValidationResultState.FAIL,
            "缺少总电量，无法进行消纳测算",
            sheet_name="月度汇总",
            row_number=row,
            bill=bill,
        )
    timed_items = [item for item in tou_items if item.energy_kwh is not None]
    if not timed_items:
        return _issue(
            "V13",
            ValidationSeverityLevel.INFO,
            ValidationResultState.FAIL,
            "仅有月度总量、缺少分时电量：无法精确计算光伏自发自用率。"
            "如需估算，结果必须标注为估算值",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )
    return _pass(
            "V13",
            f"具备 {len(timed_items)} 条分时电量，可用于消纳测算",
            sheet_name="分时电量电价",
            row_number=row,
            bill=bill,
        )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


@dataclass
class _Bundle:
    """一批账单项及其从属数据。"""

    bill: ElectricityBill
    tou_items: tuple[BillTimeOfUseItem, ...] = ()
    fee_items: tuple[BillFeeItem, ...] = ()
    meter_points: tuple[BillMeterPoint, ...] = ()
    row_number: int | None = None


def validate_bill_data(
    bills: Sequence[ElectricityBill],
    *,
    tou_items: Iterable[BillTimeOfUseItem] = (),
    fee_items: Iterable[BillFeeItem] = (),
    meter_points: Iterable[BillMeterPoint] = (),
) -> ValidationReport:
    """对账单数据执行 13 类校验。

    Args:
        bills: 账单主记录序列。
        tou_items: 全部分时电量电价项（按 ``bill_id`` 归组）。
        fee_items: 全部费用明细项。
        meter_points: 全部计量点。

    Returns:
        :class:`ValidationReport`。**不修改任何输入数据。**

    Note:
        每个校验项至少产出一条记录（通过 / 不通过 / 不适用），
        便于界面逐项展示；数据为空时相关项标记为"不适用"而非"通过"。
    """
    tou_all = tuple(tou_items)
    fee_all = tuple(fee_items)
    meter_all = tuple(meter_points)

    by_bill_tou: dict[str, list[BillTimeOfUseItem]] = {}
    for item in tou_all:
        by_bill_tou.setdefault(item.bill_id, []).append(item)
    by_bill_fee: dict[str, list[BillFeeItem]] = {}
    for item in fee_all:
        by_bill_fee.setdefault(item.bill_id, []).append(item)
    by_bill_meter: dict[str, list[BillMeterPoint]] = {}
    for item in meter_all:
        by_bill_meter.setdefault(item.bill_id, []).append(item)

    issues: list[BillValidationIssue] = []

    if not bills:
        # 无数据时逐项标记"不适用"，避免"没有报错"被误读为"通过"
        for code in CHECK_ITEMS:
            issues.append(_not_applicable(code, "未提供账单数据"))
        return ValidationReport(issues=tuple(issues), checked_bills=0)

    for index, bill in enumerate(bills):
        row = index + 2  # 表头占第 1 行，数据从第 2 行开始
        bill_tou = tuple(by_bill_tou.get(bill.bill_id, ()))
        bill_fee = tuple(by_bill_fee.get(bill.bill_id, ()))
        bill_meter = tuple(by_bill_meter.get(bill.bill_id, ()))

        issues.append(_check_v01_period(bill, row))
        issues.append(_check_v02_energy(bill, row))
        issues.append(_check_v03_amount(bill, row))
        issues.append(_check_v04_basis_conflict(bill, bill_tou, row))
        issues.append(_check_v05_meter_points(bill, bill_meter, row))
        issues.append(_check_v06_fee_duplication(bill, bill_fee, row))
        issues.append(_check_v07_reconciliation(bill, bill_fee, row))
        issues.append(_check_v08_tou_energy(bill, bill_tou, row))
        issues.append(_check_v09_price_unit(bill_tou, row))
        issues.append(_check_v10_demand(bill, row))
        issues.append(_check_v11_review_status(bill, row))
        issues.append(_check_v12_traceability(bill, row))
        issues.append(_check_v13_pv_readiness(bill, bill_tou, row))

    return ValidationReport(issues=tuple(issues), checked_bills=len(bills))
