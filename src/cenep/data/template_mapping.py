"""把模板数据行映射为账单领域对象。

职责（规格书第 31 节第 5–6 步）：

- 从 :class:`cenep.data.template_reader.TemplateRow` 转换出
  :class:`cenep.domain.bill_models` 的六类实体；
- 转换过程中**只做类型与单位转换**，不做业务判定；
- 无法转换的值**记录为问题**并保持字段为空，**绝不猜测或补 0**。

设计要点：

- 金额与电量一律经 :func:`cenep.domain.bill_models.to_decimal` 转为 ``Decimal``，
  传入 ``float`` 会被拒绝；
- 空单元格 → ``None``（未提供），与明确填 0 严格区分；
- 枚举文本按模板下拉取值解析；取值不在允许范围时记录问题并置为默认/空；
- 每张表的数据行都用 **Excel 行号**记录，便于错误定位。

本模块不导入 Excel 库：输入已是读出的行对象。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Any, Mapping, Sequence

from cenep.data.bill_template_spec import (
    SHEET_FEE_ITEMS,
    SHEET_METER_POINTS,
    SHEET_MONTHLY_SUMMARY,
    SHEET_TIME_OF_USE,
)
from cenep.data.template_reader import TemplateRow
from cenep.domain.bill_models import (
    Avoidability,
    BaselineInclusion,
    BillFeeItem,
    BillMeterPoint,
    BillTimeOfUseItem,
    ElectricityBill,
    FeeCategory,
    IncludedInOtherFee,
    MeterPointType,
    MeteringBasis,
    ReviewStatus,
    TimeOfUsePeriod,
    YesNoUnknown,
)

__all__ = [
    "ConversionIssue",
    "ConversionResult",
    "PERIOD_PATTERN",
    "convert_fee_items",
    "convert_meter_points",
    "convert_monthly_summary",
    "convert_time_of_use",
]

#: 账期格式 ``YYYY-MM``
PERIOD_PATTERN = re.compile(r"^(\d{4})-(\d{1,2})$")

#: 时间格式（``HH:MM`` / ``HH:MM:SS``）
_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


@dataclass(frozen=True)
class ConversionIssue:
    """一条转换问题（用于导入预览与错误定位）。"""

    sheet_name: str
    row_number: int
    column_name: str
    message: str
    raw_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "row_number": self.row_number,
            "column_name": self.column_name,
            "message": self.message,
            "raw_value": None if self.raw_value is None else str(self.raw_value),
        }


@dataclass
class ConversionResult:
    """一次转换的产出。"""

    bills: list[ElectricityBill] = field(default_factory=list)
    tou_items: list[BillTimeOfUseItem] = field(default_factory=list)
    fee_items: list[BillFeeItem] = field(default_factory=list)
    meter_points: list[BillMeterPoint] = field(default_factory=list)
    issues: list[ConversionIssue] = field(default_factory=list)

    def add_issue(
        self,
        row: TemplateRow,
        column_name: str,
        message: str,
        raw_value: Any = None,
    ) -> None:
        self.issues.append(
            ConversionIssue(
                sheet_name=row.sheet_name,
                row_number=row.row_number,
                column_name=column_name,
                message=message,
                raw_value=raw_value,
            )
        )

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    @property
    def rows_with_issues(self) -> tuple[tuple[str, int], ...]:
        """出现问题的 ``(工作表, 行号)`` 去重列表。"""
        seen: list[tuple[str, int]] = []
        for issue in self.issues:
            key = (issue.sheet_name, issue.row_number)
            if key not in seen:
                seen.append(key)
        return tuple(seen)


def _parse_period(text: str | None) -> str | None:
    """校验 ``YYYY-MM`` 账期格式；不合法返回 ``None``。"""
    if not text:
        return None
    match = PERIOD_PATTERN.match(text.strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def _parse_time(text: str | None) -> time | None:
    """解析 ``HH:MM`` / ``HH:MM:SS``；不合法返回 ``None``。"""
    if not text:
        return None
    match = _TIME_PATTERN.match(text.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return time(hour, minute, second)


def _enum_or_none(enum_cls, text: str | None, result: ConversionResult, row: TemplateRow, column: str):
    """把文本解析为枚举；空值返回 ``None``，非法值记录问题并返回 ``None``。"""
    if not text:
        return None
    try:
        return enum_cls(text.strip())
    except ValueError:
        allowed = "、".join(item.value for item in enum_cls)
        result.add_issue(row, column, f"取值不在允许范围（应为：{allowed}）", text)
        return None


def _decimal_or_issue(
    row: TemplateRow,
    column: str,
    result: ConversionResult,
    *,
    required: bool = False,
) -> Decimal | None:
    """读取十进制字段；失败时记录问题并返回 ``None``。

    **空值不视为错误**（除非 ``required``），且**不补 0**。
    """
    raw = row.raw(column)
    if raw is None:
        if required:
            result.add_issue(row, column, "必填字段缺失（未提供，不得补 0）")
        return None
    try:
        return row.decimal(column)
    except ValueError as exc:
        result.add_issue(row, column, f"数值无法解析：{exc}", raw)
        return None


def _date_or_issue(
    row: TemplateRow,
    column: str,
    result: ConversionResult,
    *,
    required: bool = False,
) -> date | None:
    """读取日期字段；失败时记录问题并返回 ``None``。"""
    raw = row.raw(column)
    if raw is None:
        if required:
            result.add_issue(row, column, "必填日期缺失")
        return None
    try:
        return row.date(column)
    except ValueError as exc:
        result.add_issue(row, column, f"日期无法解析：{exc}", raw)
        return None


# ---------------------------------------------------------------------------
# 月度汇总 → ElectricityBill
# ---------------------------------------------------------------------------


def convert_monthly_summary(
    rows: Sequence[TemplateRow],
    *,
    project_id: str,
    result: ConversionResult | None = None,
    price_unit_is_per_mwh: bool = False,
) -> ConversionResult:
    """把 `月度汇总` 行转换为 :class:`ElectricityBill`。

    Args:
        rows: 已读出的数据行。
        project_id: 目标项目主键。
        result: 复用已有转换结果（便于把多张表的产出汇总到一处）。
        price_unit_is_per_mwh: 若来源单价实为 **元/MWh**，置 ``True`` 以显式换算为
            元/kWh 并保留原始单位记录（规格书第 30 节第 6 条）。
            默认 ``False``（即视为元/kWh）。
    """
    result = result if result is not None else ConversionResult()

    for row in rows:
        account = row.text("户号")
        period_raw = row.text("账期")
        period = _parse_period(period_raw)
        if period is None:
            for column, message in (
                ("账期", "账期缺失，不得作为账单导入"),
                ("账期", "账期格式应为 YYYY-MM"),
            ):
                if (row.raw("账期") is None and "缺失" in message) or (
                    row.raw("账期") is not None and "格式" in message
                ):
                    result.add_issue(row, column, message, row.raw("账期"))
                    break

        price = _decimal_or_issue(row, "账单展示平均电价_元每kWh", result)
        note_suffix = ""
        if price is not None and price_unit_is_per_mwh:
            # 显式换算：元/MWh ÷ 1000 = 元/kWh，并在备注中留痕
            price = price / Decimal("1000")
            note_suffix = "［原始单位为元/MWh，已按 1/1000 换算为元/kWh］"

        note = row.text("备注")
        if note_suffix:
            note = f"{note or ''}{note_suffix}".strip() or note_suffix

        try:
            bill = ElectricityBill(
                project_id=project_id,
                customer_name=row.text("用户名称"),
                account_number=account,
                supply_company=row.text("供电单位"),
                supply_address=row.text("用电地址"),
                electricity_category=row.text("用电类别"),
                voltage_level=row.text("电压等级"),
                market_attribute=row.text("市场化属性"),
                billing_period=period,
                period_start=_date_or_issue(row, "账期开始日期", result, required=True),
                period_end=_date_or_issue(row, "账期结束日期", result, required=True),
                printed_on=_date_or_issue(row, "账单打印日期", result),
                total_energy_kwh=_decimal_or_issue(row, "本期总电量_kWh", result, required=True),
                total_amount_yuan=_decimal_or_issue(row, "账单本期电费_元", result, required=True),
                vat_invoice_amount_yuan=_decimal_or_issue(row, "增值税专票金额_元", result),
                displayed_average_price=price,
                industrial_commercial_fee_yuan=_decimal_or_issue(row, "工商业电费_元", result),
                market_purchase_fee_yuan=_decimal_or_issue(row, "市场化购电电费_元", result),
                grid_loss_fee_yuan=_decimal_or_issue(row, "上网环节线损费用_元", result),
                transmission_distribution_fee_yuan=_decimal_or_issue(row, "输配电费_元", result),
                system_operation_fee_yuan=_decimal_or_issue(row, "系统运行费_元", result),
                government_fund_fee_yuan=_decimal_or_issue(row, "政府性基金及附加_元", result),
                power_factor_adjustment_fee_yuan=_decimal_or_issue(
                    row, "功率因数调整电费_元", result
                ),
                demand_charge_yuan=_decimal_or_issue(row, "需量电费_元", result),
                market_operation_fee_yuan=_decimal_or_issue(row, "市场化运营费合计_元", result),
                basic_charge_yuan=_decimal_or_issue(row, "基本电费_元", result),
                contract_demand=_decimal_or_issue(row, "合同最大需量", result),
                contract_demand_unit=row.text("合同最大需量单位"),
                actual_demand=_decimal_or_issue(row, "实际最大需量", result),
                actual_demand_unit=row.text("实际最大需量单位"),
                demand_billing_mode=row.text("需量计费方式"),
                power_factor=_decimal_or_issue(row, "功率因数", result),
                source_file=row.text("来源文件"),
                source_page=row.text("来源页码"),
                review_status=(
                    _enum_or_none(ReviewStatus, row.text("复核状态"), result, row, "复核状态")
                    or ReviewStatus.PENDING
                ),
                note=note,
            )
        except (ValueError, TypeError) as exc:
            # 领域模型的一致性约束（负电量、账期倒置、非法单位、float 等）
            # 在此转为**可定位的导入问题**，并**丢弃该行**，
            # 使整份文件仍可预览与部分导入，而不是让整个导入崩溃。
            result.add_issue(
                row,
                "整行",
                f"该行不满足账单数据约束，已跳过：{exc}",
                row.raw("本期总电量_kWh"),
            )
            continue

        result.bills.append(bill)

    return result


# ---------------------------------------------------------------------------
# 分时电量电价 → BillTimeOfUseItem
# ---------------------------------------------------------------------------


def convert_time_of_use(
    rows: Sequence[TemplateRow],
    *,
    project_id: str,
    result: ConversionResult | None = None,
) -> ConversionResult:
    """把 `分时电量电价` 行转换为 :class:`BillTimeOfUseItem`。"""
    result = result if result is not None else ConversionResult()

    for row in rows:
        basis_text = row.text("电量类型")
        basis = _enum_or_none(MeteringBasis, basis_text, result, row, "电量类型")
        if basis_text and basis is None:
            basis = MeteringBasis.PURCHASE  # 明确回退，避免 None 影响后续判断

        result.tou_items.append(
            BillTimeOfUseItem(
                project_id=project_id,
                billing_period=_parse_period(row.text("账期")),
                metering_basis_id=row.text("计量口径/计量点编号"),
                basis=basis or MeteringBasis.PURCHASE,
                period_name=_enum_or_none(
                    TimeOfUsePeriod, row.text("时段名称"), result, row, "时段名称"
                ),
                segment_start=_parse_time(row.text("时段开始")),
                segment_end=_parse_time(row.text("时段结束")),
                energy_kwh=_decimal_or_issue(row, "电量_kWh", result),
                price_yuan_per_kwh=_decimal_or_issue(row, "购电电价_元每kWh", result),
                energy_amount_yuan=_decimal_or_issue(row, "电量电费_元", result),
                price_type_or_source=row.text("电价类型/来源"),
                source_file=row.text("来源文件"),
                source_page=row.text("来源页码"),
                review_status=(
                    _enum_or_none(ReviewStatus, row.text("复核状态"), result, row, "复核状态")
                    or ReviewStatus.PENDING
                ),
                note=row.text("备注"),
            )
        )

    return result


# ---------------------------------------------------------------------------
# 费用明细 → BillFeeItem
# ---------------------------------------------------------------------------


def convert_fee_items(
    rows: Sequence[TemplateRow],
    *,
    project_id: str,
    result: ConversionResult | None = None,
) -> ConversionResult:
    """把 `费用明细` 行转换为 :class:`BillFeeItem`。"""
    result = result if result is not None else ConversionResult()

    for row in rows:
        included = _enum_or_none(
            IncludedInOtherFee, row.text("是否包含在其他费用中"), result, row, "是否包含在其他费用中"
        )
        included_target = row.text("被包含于/关联费用")
        # "包含在其他费用中"为是但未填目标 → 领域模型会抛错，这里记录问题并降级为待核实
        if included is IncludedInOtherFee.YES and not included_target:
            result.add_issue(
                row,
                "被包含于/关联费用",
                "标记为已包含在其他费用中，但未填写被包含于哪一项",
                row.raw("被包含于/关联费用"),
            )
            included = IncludedInOtherFee.TO_VERIFY

        result.fee_items.append(
            BillFeeItem(
                project_id=project_id,
                billing_period=_parse_period(row.text("账期")),
                fee_category=_enum_or_none(
                    FeeCategory, row.text("费用大类"), result, row, "费用大类"
                ),
                fee_name=row.text("费用项目名称") or "",
                quantity=_decimal_or_issue(row, "计费数量", result),
                quantity_unit=row.text("计费数量单位"),
                unit_price=_decimal_or_issue(row, "单价_元每单位", result),
                amount_yuan=_decimal_or_issue(row, "金额_元", result, required=True),
                included_in_other=included or IncludedInOtherFee.TO_VERIFY,
                included_in_fee_name=included_target,
                avoidability=(
                    _enum_or_none(
                        Avoidability, row.text("光伏测算可避免性"), result, row, "光伏测算可避免性"
                    )
                    or Avoidability.TO_VERIFY
                ),
                baseline_inclusion=(
                    _enum_or_none(
                        BaselineInclusion, row.text("是否纳入基准电费"), result, row, "是否纳入基准电费"
                    )
                    or BaselineInclusion.TO_CONFIRM
                ),
                source_file=row.text("来源文件"),
                source_page=row.text("来源页码"),
                review_status=(
                    _enum_or_none(ReviewStatus, row.text("复核状态"), result, row, "复核状态")
                    or ReviewStatus.PENDING
                ),
                note=row.text("备注"),
            )
        )

    return result


# ---------------------------------------------------------------------------
# 计量点 → BillMeterPoint
# ---------------------------------------------------------------------------


def convert_meter_points(
    rows: Sequence[TemplateRow],
    *,
    project_id: str,
    result: ConversionResult | None = None,
) -> ConversionResult:
    """把 `计量点` 行转换为 :class:`BillMeterPoint`。"""
    result = result if result is not None else ConversionResult()

    for row in rows:
        result.meter_points.append(
            BillMeterPoint(
                project_id=project_id,
                billing_period=_parse_period(row.text("账期")),
                point_code=row.text("计量点编号") or "",
                point_name=row.text("计量点名称/位置"),
                point_type=_enum_or_none(
                    MeterPointType, row.text("计量点类型"), result, row, "计量点类型"
                ),
                main_sub_relation=row.text("主/分表关系"),
                ratio=_decimal_or_issue(row, "倍率/定比", result),
                energy_kwh=_decimal_or_issue(row, "电量_kWh", result),
                included_in_total=(
                    _enum_or_none(
                        YesNoUnknown, row.text("是否已计入首页总电量"), result, row, "是否已计入首页总电量"
                    )
                    or YesNoUnknown.TO_VERIFY
                ),
                allowed_in_rollup=(
                    _enum_or_none(
                        YesNoUnknown, row.text("是否允许纳入汇总"), result, row, "是否允许纳入汇总"
                    )
                    or YesNoUnknown.TO_VERIFY
                ),
                source_file=row.text("来源文件"),
                source_page=row.text("来源页码"),
                review_status=(
                    _enum_or_none(ReviewStatus, row.text("复核状态"), result, row, "复核状态")
                    or ReviewStatus.PENDING
                ),
                note=row.text("备注"),
            )
        )

    return result


#: 工作表 → 转换函数
CONVERTERS: Mapping[str, Any] = {
    SHEET_MONTHLY_SUMMARY: convert_monthly_summary,
    SHEET_TIME_OF_USE: convert_time_of_use,
    SHEET_FEE_ITEMS: convert_fee_items,
    SHEET_METER_POINTS: convert_meter_points,
}
