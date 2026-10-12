"""电费账单领域模型测试（规格书第 29、30 节）。

重点验证规格书强制的数据规则：

- 金额与电量必须精确（``Decimal``），**不得使用 `float`**；
- **空值（``None``）与零值（``Decimal(0)``）严格区分**，不得自动补零；
- 负费用合法且必须保留负号（如功率因数调整电费）；
- 总电量不得为负；
- 需量单位必须显式区分 ``kW`` 与 ``kVA``；
- 费用包含关系可追溯，**已包含在其他费用中的项不得重复计入基准**；
- 计量点未核实关系时不得自动汇总；
- 分时项未提供的时段留空，不得补 0；
- 未确认的账单不得进入正式测算；样本数据不得确认。
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from cenep.domain.bill_models import (
    AVOIDABLE_FEE_KINDS,
    Avoidability,
    BaselineInclusion,
    BillConfirmationState,
    BillFeeItem,
    BillImportBatch,
    BillMeterPoint,
    BillTimeOfUseItem,
    BillValidationIssue,
    ElectricityBill,
    FeeCategory,
    ImportOutcome,
    IncludedInOtherFee,
    MeterPointType,
    MeteringBasis,
    ReviewStatus,
    TimeOfUsePeriod,
    ValidationResultState,
    ValidationSeverityLevel,
    YesNoUnknown,
    to_decimal,
)

#: 2025-09 冻结基线（规格书第 28 节）
SEP_ENERGY = "8780498"
SEP_TOTAL = "6699241.94"
SEP_VAT = "6534168.58"
SEP_PF = "-9206.37"


def _bill(**kwargs) -> ElectricityBill:
    base = dict(
        project_id="proj-1",
        billing_period="2025-09",
        period_start=date(2025, 9, 1),
        period_end=date(2025, 9, 30),
        total_energy_kwh=SEP_ENERGY,
        total_amount_yuan=SEP_TOTAL,
    )
    base.update(kwargs)
    return ElectricityBill(**base)


# ---------------------------------------------------------------------------
# 30.1 精确数值：Decimal 且拒绝 float
# ---------------------------------------------------------------------------


class TestPreciseNumbers:
    def test_money_and_energy_are_decimal(self) -> None:
        bill = _bill(vat_invoice_amount_yuan=SEP_VAT, power_factor_adjustment_fee_yuan=SEP_PF)
        assert isinstance(bill.total_energy_kwh, Decimal)
        assert isinstance(bill.total_amount_yuan, Decimal)
        assert isinstance(bill.vat_invoice_amount_yuan, Decimal)
        assert isinstance(bill.power_factor_adjustment_fee_yuan, Decimal)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"total_energy_kwh": 1.5},
            {"total_amount_yuan": 1.5},
            {"vat_invoice_amount_yuan": 1.5},
            {"power_factor_adjustment_fee_yuan": 1.5},
            {"actual_demand": 1.5},
            {"power_factor": 0.99},
        ],
    )
    def test_float_is_rejected(self, kwargs: dict) -> None:
        with pytest.raises(TypeError, match="float"):
            _bill(**kwargs)

    def test_to_decimal_rejects_float(self) -> None:
        with pytest.raises(TypeError, match="float"):
            to_decimal(0.1)

    def test_to_decimal_accepts_int_and_string(self) -> None:
        assert to_decimal(5) == Decimal("5")
        assert to_decimal("6.5") == Decimal("6.5")
        assert to_decimal(None) is None

    def test_to_decimal_rejects_unparsable_string(self) -> None:
        with pytest.raises(ValueError, match="无法解析"):
            to_decimal("abc")

    def test_to_decimal_rejects_bool(self) -> None:
        with pytest.raises(TypeError, match="布尔值"):
            to_decimal(True)

    def test_decimal_precision_avoids_float_error(self) -> None:
        """十进制运算不得出现浮点误差。"""
        first = BillFeeItem(fee_name="A", amount_yuan="0.1")
        second = BillFeeItem(fee_name="B", amount_yuan="0.2")
        assert first.amount_yuan + second.amount_yuan == Decimal("0.3")


# ---------------------------------------------------------------------------
# 30.2 空值与零值
# ---------------------------------------------------------------------------


class TestNullVersusZero:
    def test_missing_value_is_none(self) -> None:
        bill = ElectricityBill(project_id="p", billing_period="2025-09")
        assert bill.total_energy_kwh is None
        assert bill.total_amount_yuan is None
        assert bill.vat_invoice_amount_yuan is None

    def test_missing_is_not_zero(self) -> None:
        bill = ElectricityBill()
        assert bill.total_energy_kwh != Decimal(0)
        assert bill.total_amount_yuan is not Decimal(0)

    def test_explicit_zero_is_preserved(self) -> None:
        bill = _bill(system_operation_fee_yuan="0")
        assert bill.system_operation_fee_yuan == Decimal(0)
        assert bill.system_operation_fee_yuan is not None

    def test_zero_and_none_are_distinguishable(self) -> None:
        with_zero = _bill(demand_charge_yuan="0")
        without = _bill()
        assert with_zero.demand_charge_yuan == Decimal(0)
        assert without.demand_charge_yuan is None
        assert with_zero.demand_charge_yuan != without.demand_charge_yuan

    def test_tou_missing_energy_is_none_not_zero(self) -> None:
        item = BillTimeOfUseItem(metering_basis_id="MP1", period_name=TimeOfUsePeriod.FLAT)
        assert item.energy_kwh is None
        assert item.is_energy_missing is True
        assert item.energy_kwh != Decimal(0)

    def test_tou_explicit_zero_energy_is_allowed(self) -> None:
        item = BillTimeOfUseItem(
            metering_basis_id="MP1", period_name=TimeOfUsePeriod.FLAT, energy_kwh="0"
        )
        assert item.energy_kwh == Decimal(0)
        assert item.is_energy_missing is False


# ---------------------------------------------------------------------------
# 30.3 负费用与下限约束
# ---------------------------------------------------------------------------


class TestSignsAndBounds:
    def test_negative_fee_keeps_sign(self) -> None:
        bill = _bill(power_factor_adjustment_fee_yuan=SEP_PF)
        assert bill.power_factor_adjustment_fee_yuan == Decimal("-9206.37")
        assert bill.power_factor_adjustment_fee_yuan < 0

    def test_negative_fee_item_keeps_sign(self) -> None:
        item = BillFeeItem(fee_name="市场化运营费", amount_yuan="-141770.00")
        assert item.amount_yuan == Decimal("-141770.00")
        assert item.amount_yuan < 0

    def test_total_energy_must_not_be_negative(self) -> None:
        with pytest.raises(ValueError, match="本期总电量"):
            _bill(total_energy_kwh="-1")

    def test_total_energy_zero_is_allowed(self) -> None:
        assert _bill(total_energy_kwh="0").total_energy_kwh == Decimal(0)

    def test_demand_must_not_be_negative(self) -> None:
        with pytest.raises(ValueError, match="实际最大需量"):
            _bill(actual_demand="-5")

    def test_average_price_must_not_be_negative(self) -> None:
        with pytest.raises(ValueError, match="平均电价"):
            _bill(displayed_average_price="-0.1")

    def test_tou_energy_and_price_must_not_be_negative(self) -> None:
        with pytest.raises(ValueError, match="时段电量"):
            BillTimeOfUseItem(metering_basis_id="MP", energy_kwh="-1")
        with pytest.raises(ValueError, match="购电电价"):
            BillTimeOfUseItem(metering_basis_id="MP", price_yuan_per_kwh="-0.1")

    def test_meter_point_energy_must_not_be_negative(self) -> None:
        with pytest.raises(ValueError, match="计量点电量"):
            BillMeterPoint(point_code="M1", energy_kwh="-1")

    def test_meter_point_ratio_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="倍率"):
            BillMeterPoint(point_code="M1", ratio="0")


# ---------------------------------------------------------------------------
# 30.4 单位与账期
# ---------------------------------------------------------------------------


class TestUnitsAndPeriod:
    @pytest.mark.parametrize("unit", ["kW", "kVA"])
    def test_demand_unit_accepts_kw_and_kva(self, unit: str) -> None:
        bill = _bill(actual_demand_unit=unit)
        assert bill.actual_demand_unit == unit

    @pytest.mark.parametrize("unit", ["MW", "kwh", "千伏安", ""])
    def test_demand_unit_rejects_other_values(self, unit: str) -> None:
        with pytest.raises(ValueError, match="kW 或 kVA"):
            _bill(actual_demand_unit=unit)

    def test_kw_and_kva_are_not_interchangeable(self) -> None:
        """kW 与 kVA 必须是不同取值，不能被归一化。"""
        kw = _bill(actual_demand_unit="kW")
        kva = _bill(actual_demand_unit="kVA")
        assert kw.actual_demand_unit != kva.actual_demand_unit

    def test_period_end_before_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="不得早于"):
            _bill(period_start=date(2025, 9, 30), period_end=date(2025, 9, 1))

    def test_billing_days_inclusive(self) -> None:
        assert _bill().billing_days == 30

    def test_billing_days_none_when_incomplete(self) -> None:
        bill = ElectricityBill(project_id="p", period_start=date(2025, 9, 1))
        assert bill.billing_days is None

    def test_tou_segment_end_before_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="时段结束"):
            BillTimeOfUseItem(
                metering_basis_id="MP",
                segment_start=time(9, 0),
                segment_end=time(8, 0),
            )


# ---------------------------------------------------------------------------
# 30.5 确认闸门
# ---------------------------------------------------------------------------


class TestConfirmationGate:
    def test_new_bill_requires_manual_review(self) -> None:
        bill = _bill()
        assert bill.confirmation is BillConfirmationState.PENDING
        assert bill.needs_manual_review is True
        assert bill.is_usable_for_calculation is False

    def test_confirmed_bill_is_usable(self) -> None:
        confirmed = _bill().confirm()
        assert confirmed.confirmation is BillConfirmationState.CONFIRMED
        assert confirmed.needs_manual_review is False
        assert confirmed.is_usable_for_calculation is True

    def test_confirm_does_not_mutate_original(self) -> None:
        bill = _bill()
        bill.confirm()
        assert bill.confirmation is BillConfirmationState.PENDING

    def test_confirm_marks_review_status(self) -> None:
        assert _bill().confirm().review_status is ReviewStatus.REVIEWED

    def test_sample_bill_cannot_be_confirmed(self) -> None:
        with pytest.raises(ValueError, match="样本数据"):
            _bill(is_sample=True).confirm()

    def test_sample_bill_is_never_usable_even_if_forced(self) -> None:
        bill = _bill(is_sample=True, confirmation=BillConfirmationState.CONFIRMED)
        assert bill.is_usable_for_calculation is False

    def test_default_review_status_is_pending(self) -> None:
        assert _bill().review_status is ReviewStatus.PENDING


# ---------------------------------------------------------------------------
# 30.6 费用包含关系（防止重复汇总）
# ---------------------------------------------------------------------------


class TestFeeInclusion:
    def test_item_included_in_other_does_not_count_toward_baseline(self) -> None:
        item = BillFeeItem(
            fee_name="市场化运营费",
            amount_yuan="-141770.00",
            included_in_other=IncludedInOtherFee.YES,
            included_in_fee_name="市场化购电电费",
            baseline_inclusion=BaselineInclusion.YES,
        )
        assert item.counts_toward_baseline is False

    def test_item_not_included_counts_toward_baseline(self) -> None:
        item = BillFeeItem(
            fee_name="输配电费",
            amount_yuan="2000662.04",
            included_in_other=IncludedInOtherFee.NO,
            baseline_inclusion=BaselineInclusion.YES,
        )
        assert item.counts_toward_baseline is True

    def test_unverified_inclusion_does_not_count(self) -> None:
        item = BillFeeItem(fee_name="待核实项", amount_yuan="1", baseline_inclusion=BaselineInclusion.YES)
        assert item.included_in_other is IncludedInOtherFee.TO_VERIFY
        assert item.counts_toward_baseline is False

    def test_included_requires_target_fee_name(self) -> None:
        with pytest.raises(ValueError, match="被包含于"):
            BillFeeItem(
                fee_name="市场化运营费",
                amount_yuan="1",
                included_in_other=IncludedInOtherFee.YES,
            )

    def test_excluded_from_baseline_does_not_count(self) -> None:
        item = BillFeeItem(
            fee_name="某费用",
            amount_yuan="1",
            included_in_other=IncludedInOtherFee.NO,
            baseline_inclusion=BaselineInclusion.NO,
        )
        assert item.counts_toward_baseline is False

    def test_demand_fee_is_flagged_as_independent_mechanism(self) -> None:
        """需量类费用具有独立计费机制，必须可被识别（规格书第 37 节）。"""
        item = BillFeeItem(
            fee_name="需量电费",
            amount_yuan="1202916.00",
            fee_category=FeeCategory.DEMAND,
        )
        assert item.is_demand_type is True
        assert FeeCategory.DEMAND in AVOIDABLE_FEE_KINDS

    def test_avoidability_defaults_to_to_verify(self) -> None:
        item = BillFeeItem(fee_name="某费用", amount_yuan="1")
        assert item.avoidability is Avoidability.TO_VERIFY

    def test_avoidability_is_a_marker_not_a_rule(self) -> None:
        """可避免性标记不得单独决定是否计入基准。"""
        item = BillFeeItem(
            fee_name="某费用",
            amount_yuan="1",
            avoidability=Avoidability.AVOIDABLE,
            included_in_other=IncludedInOtherFee.NO,
            baseline_inclusion=BaselineInclusion.NO,
        )
        assert item.counts_toward_baseline is False

    def test_enum_type_guards(self) -> None:
        with pytest.raises(TypeError, match="IncludedInOtherFee"):
            BillFeeItem(fee_name="x", amount_yuan="1", included_in_other="是")
        with pytest.raises(TypeError, match="Avoidability"):
            BillFeeItem(fee_name="x", amount_yuan="1", avoidability="可避免")
        with pytest.raises(TypeError, match="BaselineInclusion"):
            BillFeeItem(fee_name="x", amount_yuan="1", baseline_inclusion="是")


# ---------------------------------------------------------------------------
# 30.7 计量点汇总规则
# ---------------------------------------------------------------------------


class TestMeterPointRollup:
    def test_point_already_in_total_cannot_join_rollup(self) -> None:
        point = BillMeterPoint(
            point_code="M1",
            energy_kwh="8516838",
            included_in_total=YesNoUnknown.YES,
            allowed_in_rollup=YesNoUnknown.YES,
        )
        assert point.can_join_rollup is False

    def test_point_not_in_total_but_allowed_can_join(self) -> None:
        point = BillMeterPoint(
            point_code="M2",
            energy_kwh="1000",
            included_in_total=YesNoUnknown.NO,
            allowed_in_rollup=YesNoUnknown.YES,
        )
        assert point.can_join_rollup is True

    def test_unverified_point_cannot_join_rollup(self) -> None:
        point = BillMeterPoint(point_code="M3", energy_kwh="1000")
        assert point.included_in_total is YesNoUnknown.TO_VERIFY
        assert point.allowed_in_rollup is YesNoUnknown.TO_VERIFY
        assert point.can_join_rollup is False

    def test_point_not_allowed_cannot_join_even_if_not_in_total(self) -> None:
        point = BillMeterPoint(
            point_code="M4",
            energy_kwh="1000",
            included_in_total=YesNoUnknown.NO,
            allowed_in_rollup=YesNoUnknown.NO,
        )
        assert point.can_join_rollup is False

    def test_point_type_enum_available(self) -> None:
        point = BillMeterPoint(point_code="M1", point_type=MeterPointType.MAIN)
        assert point.point_type is MeterPointType.MAIN
        assert MeterPointType.SUB.value == "分表"

    def test_enum_type_guards(self) -> None:
        with pytest.raises(TypeError, match="YesNoUnknown"):
            BillMeterPoint(point_code="M1", included_in_total="是")


# ---------------------------------------------------------------------------
# 30.8 分时口径区分
# ---------------------------------------------------------------------------


class TestTimeOfUseBasis:
    def test_basis_defaults_to_purchase(self) -> None:
        item = BillTimeOfUseItem(metering_basis_id="MP1")
        assert item.basis is MeteringBasis.PURCHASE

    def test_export_and_purchase_basis_are_distinct(self) -> None:
        """购电与上网口径必须区分，不得混为一体。"""
        purchase = BillTimeOfUseItem(metering_basis_id="MP1", basis=MeteringBasis.PURCHASE)
        export = BillTimeOfUseItem(metering_basis_id="MP1", basis=MeteringBasis.EXPORT)
        assert purchase.basis is not export.basis

    def test_basis_type_guard(self) -> None:
        with pytest.raises(TypeError, match="MeteringBasis"):
            BillTimeOfUseItem(metering_basis_id="MP1", basis="购电")

    @pytest.mark.parametrize(
        "period_name",
        [
            TimeOfUsePeriod.SHARP_PEAK,
            TimeOfUsePeriod.PEAK,
            TimeOfUsePeriod.FLAT,
            TimeOfUsePeriod.VALLEY,
            TimeOfUsePeriod.OTHER,
        ],
    )
    def test_all_period_names_available(self, period_name: TimeOfUsePeriod) -> None:
        item = BillTimeOfUseItem(metering_basis_id="MP1", period_name=period_name)
        assert item.period_name is period_name

    def test_price_is_not_copied_to_other_periods(self) -> None:
        """未提供电价的时段必须保持为空，不得继承其他时段电价。"""
        with_price = BillTimeOfUseItem(
            metering_basis_id="MP1",
            period_name=TimeOfUsePeriod.SHARP_PEAK,
            price_yuan_per_kwh="0.9",
        )
        without_price = BillTimeOfUseItem(
            metering_basis_id="MP1", period_name=TimeOfUsePeriod.VALLEY
        )
        assert with_price.price_yuan_per_kwh == Decimal("0.9")
        assert without_price.price_yuan_per_kwh is None


# ---------------------------------------------------------------------------
# 30.9 校验问题与导入批次
# ---------------------------------------------------------------------------


class TestValidationIssueAndBatch:
    def test_blocking_failed_issue_is_blocking(self) -> None:
        issue = BillValidationIssue(
            check_code="V02",
            check_item="总电量有效性",
            severity=ValidationSeverityLevel.BLOCKING,
            result=ValidationResultState.FAIL,
            detail="总电量缺失",
            sheet_name="月度汇总",
            row_number=2,
            column_name="本期总电量_kWh",
        )
        assert issue.is_blocking is True
        assert issue.sheet_name == "月度汇总"
        assert issue.row_number == 2
        assert issue.column_name == "本期总电量_kWh"

    def test_warning_failed_issue_is_not_blocking(self) -> None:
        issue = BillValidationIssue(
            check_code="V07",
            check_item="费用勾稽",
            severity=ValidationSeverityLevel.WARNING,
            result=ValidationResultState.FAIL,
        )
        assert issue.is_blocking is False

    def test_pending_issue_is_not_blocking(self) -> None:
        issue = BillValidationIssue(
            check_code="V01",
            check_item="账期完整性",
            severity=ValidationSeverityLevel.BLOCKING,
            result=ValidationResultState.PENDING,
        )
        assert issue.is_blocking is False

    def test_issue_defaults_to_pending(self) -> None:
        assert BillValidationIssue().result is ValidationResultState.PENDING

    def test_row_number_must_start_from_one(self) -> None:
        with pytest.raises(ValueError, match="行号"):
            BillValidationIssue(check_code="V01", row_number=0)

    def test_issue_enum_guards(self) -> None:
        with pytest.raises(TypeError, match="ValidationSeverityLevel"):
            BillValidationIssue(severity="阻断")
        with pytest.raises(TypeError, match="ValidationResultState"):
            BillValidationIssue(result="通过")

    def test_import_batch_counts(self) -> None:
        batch = BillImportBatch(
            project_id="p",
            file_name="bills.xlsx",
            template_version="1.0",
            total_records=10,
            valid_records=7,
            warning_records=2,
            invalid_records=1,
            outcome=ImportOutcome.PARTIAL,
        )
        assert batch.total_records == 10
        assert batch.has_invalid_records is True
        assert batch.outcome is ImportOutcome.PARTIAL

    def test_import_batch_rejects_negative_counts(self) -> None:
        with pytest.raises(ValueError, match="invalid_records"):
            BillImportBatch(file_name="x", invalid_records=-1)

    def test_import_batch_outcome_guard(self) -> None:
        with pytest.raises(TypeError, match="ImportOutcome"):
            BillImportBatch(file_name="x", outcome="成功")

    def test_import_batch_records_file_hash_for_duplicate_detection(self) -> None:
        batch = BillImportBatch(file_name="bills.xlsx", file_hash="a" * 64)
        assert batch.file_hash == "a" * 64


# ---------------------------------------------------------------------------
# 30.10 序列化与来源追踪
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_bill_to_dict_exposes_gate_flags(self) -> None:
        payload = _bill().to_dict()
        assert payload["confirmation"] == "待确认"
        assert payload["is_confirmed"] is False
        assert payload["needs_manual_review"] is True
        assert payload["is_usable_for_calculation"] is False

    def test_bill_to_dict_keeps_none_distinct_from_zero(self) -> None:
        payload = _bill(demand_charge_yuan="0").to_dict()
        assert payload["demand_charge_yuan"] == "0"
        missing = _bill().to_dict()
        assert missing["demand_charge_yuan"] is None

    def test_bill_to_dict_serialises_dates(self) -> None:
        payload = _bill().to_dict()
        assert payload["period_start"] == "2025-09-01"
        assert payload["period_end"] == "2025-09-30"

    def test_source_traceability_fields_exist(self) -> None:
        bill = _bill(source_file="bill.pdf", source_page="1")
        payload = bill.to_dict()
        assert payload["source_file"] == "bill.pdf"
        assert payload["source_page"] == "1"

    def test_fee_item_to_dict_includes_inclusion_flags(self) -> None:
        payload = BillFeeItem(
            fee_name="市场化运营费",
            amount_yuan="-141770.00",
            included_in_other=IncludedInOtherFee.YES,
            included_in_fee_name="市场化购电电费",
        ).to_dict()
        assert payload["included_in_other"] == "是"
        assert payload["included_in_fee_name"] == "市场化购电电费"
        assert payload["counts_toward_baseline"] is False

    def test_tou_to_dict_marks_missing_energy(self) -> None:
        payload = BillTimeOfUseItem(metering_basis_id="MP1").to_dict()
        assert payload["energy_kwh"] is None
        assert payload["is_energy_missing"] is True

    def test_meter_point_to_dict_includes_rollup_flag(self) -> None:
        payload = BillMeterPoint(
            point_code="M1",
            included_in_total=YesNoUnknown.YES,
            allowed_in_rollup=YesNoUnknown.YES,
        ).to_dict()
        assert payload["can_join_rollup"] is False
