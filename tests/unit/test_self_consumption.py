"""光伏消纳计算单元测试。

包含：

- 任务书第 9.5 节标准验收案例的逐项数值断言；
- 两条能量守恒关系断言；
- 任务书第 9.6 节列出的全部边界情况；
- 非法输入的明确报错行为（不得静默修正）。
"""

from __future__ import annotations

import math

import pytest

from cenep.calculations.self_consumption import (
    CALCULATION_VERSION,
    STATUS_OK,
    STATUS_UNDEFINED_RATIO,
    SelfConsumptionResult,
    calculate_self_consumption,
    calculate_self_consumption_with_issues,
)
from cenep.domain.exceptions import ValidationError
from cenep.domain.validation import ISSUE_LENGTH_MISMATCH, ISSUE_NAN, ISSUE_NEGATIVE

# 任务书第 9.5 节标准验收案例
ACCEPTANCE_LOAD = [3, 8, 2]
ACCEPTANCE_PV = [5, 4, 2]


def test_acceptance_case_all_metrics() -> None:
    """标准验收案例：逐项核对任务书表格中的数值。"""
    result = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV, interval_minutes=60)

    assert result.total_load_kwh == pytest.approx(13.0)
    assert result.total_pv_kwh == pytest.approx(11.0)
    assert result.total_self_consumption_kwh == pytest.approx(9.0)
    assert result.total_export_kwh == pytest.approx(2.0)
    assert result.total_grid_import_kwh == pytest.approx(4.0)

    assert result.self_consumption_rate == pytest.approx(9 / 11)
    assert result.load_coverage_rate == pytest.approx(9 / 13)
    assert result.export_rate == pytest.approx(2 / 11)

    assert result.status == STATUS_OK
    assert result.periods == 3
    assert result.interval_minutes == 60
    assert result.energy_unit == "kWh"
    assert result.calculation_version == CALCULATION_VERSION


def test_acceptance_case_period_values() -> None:
    """逐时段公式复核：min / max 结果与手算一致。"""
    result = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV)
    # 时段 1: min(3,5)=3, max(5-3,0)=2, max(3-5,0)=0
    # 时段 2: min(8,4)=4, max(4-8,0)=0, max(8-4,0)=4
    # 时段 3: min(2,2)=2, max(2-2,0)=0, max(2-2,0)=0
    assert result.total_self_consumption_kwh == pytest.approx(3 + 4 + 2)
    assert result.total_export_kwh == pytest.approx(2 + 0 + 0)
    assert result.total_grid_import_kwh == pytest.approx(0 + 4 + 0)


def test_energy_conservation_relations() -> None:
    """任务书第 9.4 节两条守恒关系。"""
    result = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV)
    assert result.total_pv_kwh == pytest.approx(
        result.total_self_consumption_kwh + result.total_export_kwh
    )
    assert result.total_load_kwh == pytest.approx(
        result.total_self_consumption_kwh + result.total_grid_import_kwh
    )
    result.check_energy_balance()


@pytest.mark.parametrize(
    "load,pv",
    [
        ([0, 0, 0], [0, 0, 0]),
        ([1, 2, 3], [0, 0, 0]),
        ([0, 0, 0], [1, 2, 3]),
        ([5, 5, 5], [5, 5, 5]),
        ([9, 9, 9], [1, 2, 3]),
        ([1, 2, 3], [9, 9, 9]),
        ([0.5, 1.25, 3.75], [2.5, 0.25, 4.0]),
        ([1e-6, 2e-6], [3e-6, 1e-7]),
        ([1e6, 2e6], [1.5e6, 3e6]),
    ],
)
def test_conservation_holds_for_many_inputs(load: list[float], pv: list[float]) -> None:
    result = calculate_self_consumption(load, pv)
    result.check_energy_balance()
    assert result.total_pv_kwh == pytest.approx(
        result.total_self_consumption_kwh + result.total_export_kwh
    )
    assert result.total_load_kwh == pytest.approx(
        result.total_self_consumption_kwh + result.total_grid_import_kwh
    )


class TestBoundaryCases:
    def test_empty_arrays(self) -> None:
        """空数组：电量为 0，比例未定义。"""
        result = calculate_self_consumption([], [])
        assert result.total_load_kwh == 0.0
        assert result.total_pv_kwh == 0.0
        assert result.total_self_consumption_kwh == 0.0
        assert result.total_export_kwh == 0.0
        assert result.total_grid_import_kwh == 0.0
        assert result.self_consumption_rate is None
        assert result.load_coverage_rate is None
        assert result.export_rate is None
        assert result.status == STATUS_UNDEFINED_RATIO
        assert result.periods == 0

    def test_all_zero_energy(self) -> None:
        result = calculate_self_consumption([0, 0, 0], [0, 0, 0])
        assert result.total_load_kwh == 0.0
        assert result.total_pv_kwh == 0.0
        assert result.self_consumption_rate is None
        assert result.load_coverage_rate is None
        assert result.export_rate is None
        assert result.status == STATUS_UNDEFINED_RATIO

    def test_load_only_no_pv(self) -> None:
        """只有负荷、没有光伏：全部购电，比例未定义。"""
        result = calculate_self_consumption([3, 8, 2], [0, 0, 0])
        assert result.total_pv_kwh == 0.0
        assert result.total_self_consumption_kwh == 0.0
        assert result.total_export_kwh == 0.0
        assert result.total_grid_import_kwh == pytest.approx(13.0)
        assert result.self_consumption_rate is None
        assert result.load_coverage_rate == pytest.approx(0.0)
        assert result.export_rate is None
        assert result.status == STATUS_UNDEFINED_RATIO

    def test_pv_only_no_load(self) -> None:
        """只有光伏、没有负荷：全部上网，自用率为 0，负荷覆盖率未定义。"""
        result = calculate_self_consumption([0, 0, 0], [5, 4, 2])
        assert result.total_load_kwh == 0.0
        assert result.total_self_consumption_kwh == 0.0
        assert result.total_export_kwh == pytest.approx(11.0)
        assert result.total_grid_import_kwh == 0.0
        assert result.self_consumption_rate == pytest.approx(0.0)
        assert result.load_coverage_rate is None
        assert result.export_rate == pytest.approx(1.0)
        assert result.status == STATUS_UNDEFINED_RATIO

    def test_pv_equals_load_exactly(self) -> None:
        """光伏与负荷完全相等：自用率 100%，无上网无购电。"""
        result = calculate_self_consumption([4, 4, 4], [4, 4, 4])
        assert result.total_self_consumption_kwh == pytest.approx(12.0)
        assert result.total_export_kwh == 0.0
        assert result.total_grid_import_kwh == 0.0
        assert result.self_consumption_rate == pytest.approx(1.0)
        assert result.load_coverage_rate == pytest.approx(1.0)
        assert result.export_rate == pytest.approx(0.0)
        assert result.status == STATUS_OK

    def test_pv_always_less_than_load(self) -> None:
        result = calculate_self_consumption([10, 10, 10], [1, 2, 3])
        assert result.total_export_kwh == 0.0
        assert result.total_self_consumption_kwh == pytest.approx(6.0)
        assert result.total_grid_import_kwh == pytest.approx(24.0)
        assert result.self_consumption_rate == pytest.approx(1.0)
        assert result.export_rate == pytest.approx(0.0)
        assert result.load_coverage_rate == pytest.approx(6 / 30)

    def test_pv_always_greater_than_load(self) -> None:
        result = calculate_self_consumption([1, 2, 3], [10, 10, 10])
        assert result.total_self_consumption_kwh == pytest.approx(6.0)
        assert result.total_grid_import_kwh == 0.0
        assert result.total_export_kwh == pytest.approx(24.0)
        assert result.load_coverage_rate == pytest.approx(1.0)
        assert result.export_rate == pytest.approx(0.8)
        assert result.self_consumption_rate == pytest.approx(0.2)

    def test_single_period(self) -> None:
        result = calculate_self_consumption([1.0], [2.0])
        assert result.total_export_kwh == pytest.approx(1.0)
        assert result.self_consumption_rate == pytest.approx(0.5)

    def test_zero_load_in_some_periods_but_not_all(self) -> None:
        """部分时段零负荷：负荷覆盖率分母非零，仍是有效比值。"""
        result = calculate_self_consumption([0, 6], [3, 3])
        assert result.total_load_kwh == pytest.approx(6.0)
        assert result.total_self_consumption_kwh == pytest.approx(3.0)
        assert result.total_export_kwh == pytest.approx(3.0)
        assert result.load_coverage_rate == pytest.approx(0.5)
        assert result.self_consumption_rate == pytest.approx(0.5)
        assert result.status == STATUS_OK


class TestInvalidInputRaises:
    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            calculate_self_consumption([1, 2, 3], [1, 2])
        assert ISSUE_LENGTH_MISMATCH in excinfo.value.issue_codes()

    def test_negative_raises(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            calculate_self_consumption([1, -2], [1, 2])
        assert ISSUE_NEGATIVE in excinfo.value.issue_codes()

    def test_nan_raises(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            calculate_self_consumption([1, math.nan], [1, 2])
        assert ISSUE_NAN in excinfo.value.issue_codes()

    @pytest.mark.parametrize("bad", [math.inf, -math.inf])
    def test_infinite_raises(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            calculate_self_consumption([1, bad], [1, 2])

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValidationError):
            calculate_self_consumption([1, "2"], [1, 2])  # type: ignore[list-item]

    def test_invalid_interval_raises(self) -> None:
        with pytest.raises(ValidationError):
            calculate_self_consumption([1], [1], interval_minutes=0)

    def test_invalid_input_is_not_silently_corrected(self) -> None:
        """非法输入必须抛错，不得返回被"修正"过的结果。"""
        load = [3, 8, 2]
        pv = [5, 4, 2, 1]
        with pytest.raises(ValidationError):
            calculate_self_consumption(load, pv)
        assert load == [3, 8, 2]
        assert pv == [5, 4, 2, 1]


class TestResultStructure:
    def test_result_is_structured_dataclass(self) -> None:
        result = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV)
        assert isinstance(result, SelfConsumptionResult)

    def test_to_dict_contains_all_required_fields(self) -> None:
        result = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV)
        payload = result.to_dict()
        for key in (
            "total_load_kwh",
            "total_pv_kwh",
            "total_self_consumption_kwh",
            "total_export_kwh",
            "total_grid_import_kwh",
            "self_consumption_rate",
            "load_coverage_rate",
            "export_rate",
            "status",
        ):
            assert key in payload

    def test_undefined_ratios_stay_none_in_dict_not_zero(self) -> None:
        """未定义比例必须保持 None，禁止转换成 0。"""
        payload = calculate_self_consumption([0], [0]).to_dict()
        assert payload["self_consumption_rate"] is None
        assert payload["load_coverage_rate"] is None
        assert payload["export_rate"] is None

    def test_ratio_is_fraction_not_percentage(self) -> None:
        """比例内部使用 0~1 表示，界面展示时才转百分比。"""
        result = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV)
        assert 0.0 <= result.self_consumption_rate <= 1.0
        assert 0.0 <= result.export_rate <= 1.0
        assert result.load_coverage_rate <= 1.0

    def test_load_coverage_rate_never_exceeds_one(self) -> None:
        """负荷覆盖率 = 自用 / 用电，逐时段取小后求和，恒不超过 1。"""
        cases = (
            ([10], [100]),
            ([1, 2, 3], [100, 100, 100]),
            ([5, 0, 7], [1, 9, 100]),
            ([0.5, 0.25], [1000.0, 1000.0]),
        )
        for load, pv in cases:
            result = calculate_self_consumption(load, pv)
            assert result.load_coverage_rate is not None
            assert result.load_coverage_rate <= 1.0, (load, pv, result.load_coverage_rate)
            assert result.total_self_consumption_kwh <= result.total_load_kwh

    def test_ratios_stay_within_unit_interval(self) -> None:
        """三个比例指标都必须落在 0~1 区间内。"""
        result = calculate_self_consumption([1, 2, 3], [100, 100, 100])
        for ratio in (result.self_consumption_rate, result.load_coverage_rate, result.export_rate):
            assert ratio is not None
            assert 0.0 <= ratio <= 1.0

    def test_metric_rows_mark_undefined_status(self) -> None:
        rows = calculate_self_consumption([0], [0]).to_metric_rows()
        by_name = {row["metric_name"]: row for row in rows}
        assert by_name["total_load_kwh"]["value"] == 0.0
        assert by_name["total_load_kwh"]["status"] == "ok"
        assert by_name["self_consumption_rate"]["status"] == "undefined"
        assert by_name["self_consumption_rate"]["value"] is None

    def test_metric_rows_ok_for_defined_ratios(self) -> None:
        rows = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV).to_metric_rows()
        by_name = {row["metric_name"]: row for row in rows}
        assert by_name["self_consumption_rate"]["status"] == "ok"
        assert by_name["self_consumption_rate"]["value"] == pytest.approx(9 / 11)
        assert len(rows) == 8

    def test_input_fingerprint_is_stable_and_input_sensitive(self) -> None:
        first = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV)
        second = calculate_self_consumption(ACCEPTANCE_LOAD, ACCEPTANCE_PV)
        different = calculate_self_consumption([3, 8, 3], ACCEPTANCE_PV)
        assert first.input_fingerprint == second.input_fingerprint
        assert first.input_fingerprint != different.input_fingerprint

    def test_check_energy_balance_detects_violation(self) -> None:
        """守恒自检本身必须有效：人为构造违例时必须报错。"""
        broken = SelfConsumptionResult(
            total_load_kwh=10.0,
            total_pv_kwh=10.0,
            total_self_consumption_kwh=1.0,
            total_export_kwh=1.0,
            total_grid_import_kwh=1.0,
            self_consumption_rate=0.1,
            load_coverage_rate=0.1,
            export_rate=0.1,
            status=STATUS_OK,
        )
        with pytest.raises(AssertionError):
            broken.check_energy_balance()


class TestNonRaisingEntryPoint:
    def test_success_returns_result_and_notes(self) -> None:
        result, failure, warnings = calculate_self_consumption_with_issues(
            ACCEPTANCE_LOAD, ACCEPTANCE_PV
        )
        assert result is not None
        assert failure is None
        assert warnings == ()

    def test_failure_returns_issue_without_result(self) -> None:
        result, failure, warnings = calculate_self_consumption_with_issues([1, 2, 3], [1, 2])
        assert result is None
        assert failure is not None
        assert failure.issue_code == ISSUE_LENGTH_MISMATCH
        assert warnings == ()

    def test_warning_only_case_still_returns_result(self) -> None:
        result, failure, warnings = calculate_self_consumption_with_issues([0], [0])
        assert result is not None
        assert failure is None
        assert warnings
