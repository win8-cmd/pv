"""账单数据校验测试（规格书第 27、40 节）。

覆盖规格书第 40 节"数据质量测试"要求的全部情形：

- 总量与分时口径一致时的差异检查；
- 不同计量口径不能直接求和；
- 主表与分表不得无依据重复汇总；
- 费用重复计入检查；
- 账单总额与分项勾稽差；
- 元/MWh 与元/kWh 的单位错误；
- kW 与 kVA 的需量单位混淆；
- 来源文件与页码缺失；
- 未复核关键字段的提示或阻断；
- 未知字段不自动填 0。

以及第 27 节 13 类校验项的存在性与"只报告、不改数"约束。
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from cenep.data.bill_validation import (
    CHECK_ITEMS,
    RECONCILIATION_TOLERANCE_YUAN,
    validate_bill_data,
)
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
    ValidationResultState,
    ValidationSeverityLevel,
    YesNoUnknown,
)


def _bill(**kwargs) -> ElectricityBill:
    base = dict(
        bill_id="B1",
        project_id="P1",
        billing_period="2025-09",
        period_start=date(2025, 9, 1),
        period_end=date(2025, 9, 30),
        total_energy_kwh="8780498",
        total_amount_yuan="6699241.94",
        source_file="2025-09账单.pdf",
        source_page="1",
        review_status=ReviewStatus.REVIEWED,
    )
    base.update(kwargs)
    return ElectricityBill(**base)


def _tou(**kwargs) -> BillTimeOfUseItem:
    base = dict(
        bill_id="B1",
        project_id="P1",
        billing_period="2025-09",
        metering_basis_id="MP1",
        basis=MeteringBasis.PURCHASE,
    )
    base.update(kwargs)
    return BillTimeOfUseItem(**base)


def _fee(**kwargs) -> BillFeeItem:
    base = dict(
        bill_id="B1",
        project_id="P1",
        billing_period="2025-09",
        fee_name="输配电费",
        amount_yuan="2000662.04",
        included_in_other=IncludedInOtherFee.NO,
        baseline_inclusion=BaselineInclusion.YES,
    )
    base.update(kwargs)
    return BillFeeItem(**base)


def _check(report, code: str):
    issues = report.issues_for_check(code)
    assert issues, f"缺少校验项 {code}"
    return issues[0]


# ---------------------------------------------------------------------------
# 校验项齐备性
# ---------------------------------------------------------------------------


class TestCheckItemsPresent:
    def test_thirteen_check_items_defined(self) -> None:
        assert len(CHECK_ITEMS) == 13
        assert set(CHECK_ITEMS) == {f"V{i:02d}" for i in range(1, 14)}

    def test_every_check_produces_a_record(self) -> None:
        report = validate_bill_data([_bill()])
        for code in CHECK_ITEMS:
            assert report.issues_for_check(code), f"{code} 未产出校验记录"

    def test_empty_input_marks_all_not_applicable(self) -> None:
        """无数据时不得静默"通过"，必须标记为不适用。"""
        report = validate_bill_data([])
        assert report.checked_bills == 0
        assert len(report.issues) == 13
        assert all(
            issue.result is ValidationResultState.NOT_APPLICABLE for issue in report.issues
        )
        assert report.has_blocking is False

    def test_issues_carry_sheet_and_row_for_location(self) -> None:
        report = validate_bill_data([_bill(total_energy_kwh=None)])
        issue = _check(report, "V02")
        assert issue.sheet_name == "月度汇总"
        assert issue.row_number == 2
        assert issue.column_name == "本期总电量_kWh"


# ---------------------------------------------------------------------------
# V01 账期 / V02 电量 / V03 金额
# ---------------------------------------------------------------------------


class TestPeriodEnergyAmount:
    def test_missing_period_is_blocking(self) -> None:
        report = validate_bill_data([_bill(period_start=None)])
        issue = _check(report, "V01")
        assert issue.result is ValidationResultState.FAIL
        assert issue.severity is ValidationSeverityLevel.BLOCKING
        assert report.has_blocking is True

    def test_valid_period_passes(self) -> None:
        assert _check(validate_bill_data([_bill()]), "V01").result is ValidationResultState.PASS

    def test_missing_total_energy_is_blocking(self) -> None:
        report = validate_bill_data([_bill(total_energy_kwh=None)])
        issue = _check(report, "V02")
        assert issue.is_blocking is True
        assert "缺失" in issue.detail

    def test_missing_total_amount_is_blocking(self) -> None:
        report = validate_bill_data([_bill(total_amount_yuan=None)])
        assert _check(report, "V03").is_blocking is True


# ---------------------------------------------------------------------------
# V04 口径冲突
# ---------------------------------------------------------------------------


class TestBasisConflict:
    def test_single_basis_is_not_applicable(self) -> None:
        report = validate_bill_data([_bill()], tou_items=[_tou(energy_kwh="100")])
        assert _check(report, "V04").result is ValidationResultState.NOT_APPLICABLE

    def test_multiple_bases_with_matching_total_pass(self) -> None:
        bill = _bill(total_energy_kwh="1000")
        items = [
            _tou(metering_basis_id="MP1", energy_kwh="1000"),
            _tou(metering_basis_id="MP2", energy_kwh="10", basis=MeteringBasis.EXPORT),
        ]
        report = validate_bill_data([bill], tou_items=items)
        assert _check(report, "V04").result is ValidationResultState.PASS

    def test_multiple_bases_with_mismatch_fail(self) -> None:
        bill = _bill(total_energy_kwh="1000")
        items = [
            _tou(metering_basis_id="MP1", energy_kwh="500"),
            _tou(metering_basis_id="MP2", energy_kwh="10", basis=MeteringBasis.EXPORT),
        ]
        report = validate_bill_data([bill], tou_items=items)
        issue = _check(report, "V04")
        assert issue.result is ValidationResultState.FAIL
        assert "口径" in issue.detail


# ---------------------------------------------------------------------------
# V05 计量点
# ---------------------------------------------------------------------------


class TestMeterPointChecks:
    def test_no_points_is_not_applicable(self) -> None:
        assert (
            _check(validate_bill_data([_bill()]), "V05").result
            is ValidationResultState.NOT_APPLICABLE
        )

    def test_double_counted_point_is_blocking(self) -> None:
        """同时"已计入首页总量"且"允许纳入汇总"必须阻断。"""
        point = BillMeterPoint(
            bill_id="B1",
            point_code="M1",
            energy_kwh="8516838",
            included_in_total=YesNoUnknown.YES,
            allowed_in_rollup=YesNoUnknown.YES,
        )
        report = validate_bill_data([_bill()], meter_points=[point])
        issue = _check(report, "V05")
        assert issue.is_blocking is True
        assert "重复计入" in issue.detail

    def test_unverified_point_is_warning_not_blocking(self) -> None:
        point = BillMeterPoint(bill_id="B1", point_code="M2", energy_kwh="1000")
        report = validate_bill_data([_bill()], meter_points=[point])
        issue = _check(report, "V05")
        assert issue.result is ValidationResultState.FAIL
        assert issue.is_blocking is False
        assert "未核实" in issue.detail

    def test_clear_point_passes(self) -> None:
        point = BillMeterPoint(
            bill_id="B1",
            point_code="M3",
            energy_kwh="1000",
            point_type=MeterPointType.SUB,
            included_in_total=YesNoUnknown.NO,
            allowed_in_rollup=YesNoUnknown.YES,
        )
        report = validate_bill_data([_bill()], meter_points=[point])
        assert _check(report, "V05").result is ValidationResultState.PASS


# ---------------------------------------------------------------------------
# V06 费用重复计入 / V07 勾稽
# ---------------------------------------------------------------------------


class TestFeeChecks:
    def test_unverified_inclusion_is_blocking(self) -> None:
        report = validate_bill_data([_bill()], fee_items=[_fee(included_in_other=IncludedInOtherFee.TO_VERIFY)])
        issue = _check(report, "V06")
        assert issue.is_blocking is True
        assert "重复汇总风险" in issue.detail

    def test_verified_inclusion_passes(self) -> None:
        assert (
            _check(validate_bill_data([_bill()], fee_items=[_fee()]), "V06").result
            is ValidationResultState.PASS
        )

    def test_reconciliation_match_passes(self) -> None:
        bill = _bill(total_amount_yuan="300.00")
        items = [_fee(fee_name="A", amount_yuan="100.00"), _fee(fee_name="B", amount_yuan="200.00")]
        report = validate_bill_data([bill], fee_items=items)
        assert _check(report, "V07").result is ValidationResultState.PASS

    def test_reconciliation_within_tolerance_passes(self) -> None:
        bill = _bill(total_amount_yuan="100.00")
        report = validate_bill_data(
            [bill], fee_items=[_fee(fee_name="A", amount_yuan=str(Decimal("100.00") + RECONCILIATION_TOLERANCE_YUAN))]
        )
        assert _check(report, "V07").result is ValidationResultState.PASS

    def test_reconciliation_beyond_tolerance_warns_without_modifying(self) -> None:
        """超差只告警，且**不得修改原始金额**。"""
        bill = _bill(total_amount_yuan="100.00")
        item = _fee(fee_name="A", amount_yuan="100.03")
        report = validate_bill_data([bill], fee_items=[item])
        issue = _check(report, "V07")
        assert issue.result is ValidationResultState.FAIL
        assert "未做任何修改" in issue.detail
        # 原始数据未被改动
        assert item.amount_yuan == Decimal("100.03")
        assert bill.total_amount_yuan == Decimal("100.00")

    def test_included_fee_excluded_from_reconciliation(self) -> None:
        """已包含在其他费用中的项不得参与勾稽合计（防止重复汇总）。"""
        bill = _bill(total_amount_yuan="100.00")
        items = [
            _fee(fee_name="市场化购电电费", amount_yuan="100.00"),
            _fee(
                fee_name="市场化运营费",
                amount_yuan="-141770.00",
                included_in_other=IncludedInOtherFee.YES,
                included_in_fee_name="市场化购电电费",
            ),
        ]
        report = validate_bill_data([bill], fee_items=items)
        assert _check(report, "V07").result is ValidationResultState.PASS

    def test_no_fee_items_is_not_applicable(self) -> None:
        report = validate_bill_data([_bill()])
        assert _check(report, "V07").result is ValidationResultState.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# V08 分时电量勾稽
# ---------------------------------------------------------------------------


class TestTouEnergyChecks:
    def test_matching_tou_passes(self) -> None:
        bill = _bill(total_energy_kwh="300")
        items = [
            _tou(period_name=TimeOfUsePeriod.SHARP_PEAK, energy_kwh="100"),
            _tou(period_name=TimeOfUsePeriod.FLAT, energy_kwh="200"),
        ]
        report = validate_bill_data([bill], tou_items=items)
        assert _check(report, "V08").result is ValidationResultState.PASS

    def test_different_bases_are_not_summed(self) -> None:
        """不同计量口径不得直接求和比较。"""
        bill = _bill(total_energy_kwh="1000")
        items = [
            _tou(metering_basis_id="MP1", energy_kwh="1000"),
            _tou(metering_basis_id="MP2", energy_kwh="500"),
        ]
        report = validate_bill_data([bill], tou_items=items)
        issue = _check(report, "V08")
        assert issue.result is ValidationResultState.NOT_APPLICABLE
        assert "口径不一致" in issue.detail

    def test_missing_period_is_unknown_not_zero(self) -> None:
        """未提供电量的时段视为未知，不得当作 0 来证明数据完整。"""
        bill = _bill(total_energy_kwh="100")
        items = [
            _tou(period_name=TimeOfUsePeriod.SHARP_PEAK, energy_kwh="100"),
            _tou(period_name=TimeOfUsePeriod.VALLEY, energy_kwh=None),
        ]
        report = validate_bill_data([bill], tou_items=items)
        issue = _check(report, "V08")
        assert issue.result is ValidationResultState.FAIL
        assert "视为未知" in issue.detail
        assert "不得当作 0" in issue.detail

    def test_tou_sum_mismatch_reports_difference(self) -> None:
        bill = _bill(total_energy_kwh="1000")
        items = [_tou(period_name=TimeOfUsePeriod.FLAT, energy_kwh="990")]
        report = validate_bill_data([bill], tou_items=items)
        issue = _check(report, "V08")
        assert issue.result is ValidationResultState.FAIL
        assert "电量差" in issue.detail


# ---------------------------------------------------------------------------
# V09 电价单位 / V10 需量单位
# ---------------------------------------------------------------------------


class TestUnitChecks:
    def test_price_in_mwh_magnitude_is_blocking(self) -> None:
        """把 元/MWh 当 元/kWh 填写时必须阻断。"""
        items = [_tou(price_yuan_per_kwh="762.97")]
        report = validate_bill_data([_bill()], tou_items=items)
        issue = _check(report, "V09")
        assert issue.is_blocking is True
        assert "元/MWh" in issue.detail

    def test_reasonable_price_passes(self) -> None:
        items = [_tou(price_yuan_per_kwh="0.76297")]
        report = validate_bill_data([_bill()], tou_items=items)
        assert _check(report, "V09").result is ValidationResultState.PASS

    def test_demand_without_unit_is_blocking(self) -> None:
        bill = _bill(actual_demand="30844", actual_demand_unit=None)
        report = validate_bill_data([bill])
        issue = _check(report, "V10")
        assert issue.is_blocking is True
        assert "未填写单位" in issue.detail

    def test_demand_charge_without_mode_is_blocking(self) -> None:
        bill = _bill(demand_charge_yuan="1202916", actual_demand_unit="kW")
        report = validate_bill_data([bill])
        assert _check(report, "V10").is_blocking is True

    def test_complete_demand_info_passes(self) -> None:
        bill = _bill(
            actual_demand="30844",
            actual_demand_unit="kW",
            contract_demand="30000",
            contract_demand_unit="kW",
            demand_charge_yuan="1202916",
            demand_billing_mode="按实际最大需量",
        )
        report = validate_bill_data([bill])
        assert _check(report, "V10").result is ValidationResultState.PASS


# ---------------------------------------------------------------------------
# V11 复核状态 / V12 可追溯性 / V13 消纳数据
# ---------------------------------------------------------------------------


class TestReviewTraceabilityReadiness:
    def test_pending_review_fails_with_warning(self) -> None:
        report = validate_bill_data([_bill(review_status=ReviewStatus.PENDING)])
        issue = _check(report, "V11")
        assert issue.result is ValidationResultState.FAIL
        assert issue.severity is ValidationSeverityLevel.WARNING
        assert "未复核数据不得用于正式测算" in issue.detail

    def test_questionable_review_fails(self) -> None:
        report = validate_bill_data([_bill(review_status=ReviewStatus.QUESTIONABLE)])
        assert _check(report, "V11").result is ValidationResultState.FAIL

    def test_reviewed_passes(self) -> None:
        report = validate_bill_data([_bill(review_status=ReviewStatus.REVIEWED)])
        assert _check(report, "V11").result is ValidationResultState.PASS

    def test_missing_source_file_fails(self) -> None:
        report = validate_bill_data([_bill(source_file=None)])
        issue = _check(report, "V12")
        assert issue.result is ValidationResultState.FAIL
        assert "来源文件" in issue.detail

    def test_missing_source_page_fails(self) -> None:
        report = validate_bill_data([_bill(source_page=None)])
        issue = _check(report, "V12")
        assert issue.result is ValidationResultState.FAIL
        assert "页码" in issue.detail

    def test_source_present_passes(self) -> None:
        report = validate_bill_data([_bill()])
        assert _check(report, "V12").result is ValidationResultState.PASS

    def test_monthly_only_cannot_compute_self_consumption(self) -> None:
        """仅有月度总量时，必须明确无法精确计算自用率。"""
        report = validate_bill_data([_bill()])
        issue = _check(report, "V13")
        assert issue.result is ValidationResultState.FAIL
        assert "无法精确计算" in issue.detail
        assert "标注为估算" in issue.detail

    def test_with_tou_energy_is_ready(self) -> None:
        items = [_tou(period_name=TimeOfUsePeriod.FLAT, energy_kwh="100")]
        report = validate_bill_data([_bill()], tou_items=items)
        assert _check(report, "V13").result is ValidationResultState.PASS


# ---------------------------------------------------------------------------
# 报告整体行为
# ---------------------------------------------------------------------------


class TestReportBehaviour:
    def test_report_groups_by_bill(self) -> None:
        bills = [
            _bill(bill_id="B1", billing_period="2025-09"),
            _bill(bill_id="B2", billing_period="2025-10"),
        ]
        report = validate_bill_data(bills)
        assert report.checked_bills == 2
        assert len(report.issues) == 26
        assert _check(report, "V01").row_number == 2
        assert report.issues_for_check("V01")[1].row_number == 3

    def test_blocking_issue_makes_report_blocking(self) -> None:
        report = validate_bill_data([_bill(total_energy_kwh=None)])
        assert report.has_blocking is True
        assert len(report.blocking_issues) >= 1

    def test_clean_bill_has_no_blocking_issues(self) -> None:
        report = validate_bill_data([_bill()])
        assert report.has_blocking is False

    def test_report_to_dict_is_serialisable(self) -> None:
        payload = validate_bill_data([_bill()]).to_dict()
        assert payload["checked_bills"] == 1
        assert payload["issue_count"] == 13
        assert isinstance(payload["issues"], list)
        assert "has_blocking" in payload

    def test_validation_does_not_modify_bill(self) -> None:
        """校验必须是只读的：不得修改任何输入对象。"""
        bill = _bill(total_amount_yuan="100.00")
        tou = _tou(energy_kwh="100", price_yuan_per_kwh="0.76297")
        fee = _fee(amount_yuan="100.03")
        before = (bill.total_amount_yuan, tou.energy_kwh, fee.amount_yuan)
        validate_bill_data([bill], tou_items=[tou], fee_items=[fee])
        after = (bill.total_amount_yuan, tou.energy_kwh, fee.amount_yuan)
        assert before == after

    def test_tou_items_grouped_by_bill_id(self) -> None:
        """分时项必须按 ``bill_id`` 归组，不得跨账单串用。"""
        bills = [_bill(bill_id="B1"), _bill(bill_id="B2", total_energy_kwh="100")]
        items = [
            _tou(
                bill_id="B1",
                period_name=TimeOfUsePeriod.FLAT,
                energy_kwh="8780498",  # 与 B1 的总电量一致
            )
        ]
        report = validate_bill_data(bills, tou_items=items)
        first = report.issues_for_check("V08")[0]
        second = report.issues_for_check("V08")[1]
        assert first.row_number == 2
        assert first.result is ValidationResultState.PASS
        assert second.row_number == 3
        assert second.result is ValidationResultState.NOT_APPLICABLE, "B2 无分时数据"

    def test_demand_fee_category_flag_survives_validation(self) -> None:
        """需量类费用应可被识别，供后续判断可避免性。"""
        item = _fee(
            fee_name="需量电费",
            fee_category=FeeCategory.DEMAND,
            amount_yuan="1202916",
        )
        assert item.is_demand_type is True
        assert item.avoidability is Avoidability.TO_VERIFY
