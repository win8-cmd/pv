"""输入校验单元测试。

覆盖：长度一致性、非数值、NaN、无穷、负数、非序列、时间粒度、
空数组的合法性，以及项目字段校验。
"""

from __future__ import annotations

import math

import pytest

from cenep.domain.exceptions import ValidationError
from cenep.domain.models import Project, ProjectType
from cenep.domain.validation import (
    ISSUE_INFINITE,
    ISSUE_INTERVAL_INVALID,
    ISSUE_LENGTH_MISMATCH,
    ISSUE_NAN,
    ISSUE_NEGATIVE,
    ISSUE_NOT_A_NUMBER,
    ISSUE_NOT_SEQUENCE,
    Severity,
    check_energy_series,
    classify_energy_series,
    require_valid_energy_series,
    require_valid_project,
    validate_project,
)


class TestEnergySeriesValidation:
    def test_valid_series_passes(self) -> None:
        result = check_energy_series([3, 8, 2], [5, 4, 2])
        assert result.is_valid
        assert result.status == "valid"
        assert result.errors == []

    def test_empty_series_is_valid_input(self) -> None:
        """空数组是合法输入（由计算层给出全零结果与未定义比例）。"""
        result = check_energy_series([], [])
        assert result.is_valid
        assert result.status == "valid"

    def test_all_zero_is_valid(self) -> None:
        assert check_energy_series([0, 0, 0], [0, 0, 0]).is_valid

    @pytest.mark.parametrize(
        "load,pv,expected_code",
        [
            ([1, 2, 3], [1, 2], ISSUE_LENGTH_MISMATCH),
            ([1], [1, 2, 3], ISSUE_LENGTH_MISMATCH),
            ([], [1], ISSUE_LENGTH_MISMATCH),
        ],
    )
    def test_length_mismatch(self, load: list[float], pv: list[float], expected_code: str) -> None:
        result = check_energy_series(load, pv)
        assert not result.is_valid
        assert expected_code in result.error_codes()

    @pytest.mark.parametrize("bad_value", [None, "5", object(), [1], {"x": 1}, True])
    def test_non_numeric_element(self, bad_value: object) -> None:
        result = check_energy_series([1, bad_value, 3], [1, 2, 3])  # type: ignore[list-item]
        assert not result.is_valid
        assert ISSUE_NOT_A_NUMBER in result.error_codes()

    def test_nan_element(self) -> None:
        result = check_energy_series([1, math.nan], [2, 3])
        assert not result.is_valid
        assert ISSUE_NAN in result.error_codes()

    @pytest.mark.parametrize("bad_value", [math.inf, -math.inf])
    def test_infinite_element(self, bad_value: float) -> None:
        result = check_energy_series([1.0, bad_value], [2.0, 3.0])
        assert not result.is_valid
        assert ISSUE_INFINITE in result.error_codes()

    def test_negative_element(self) -> None:
        result = check_energy_series([1, -2], [2, 3])
        assert not result.is_valid
        assert ISSUE_NEGATIVE in result.error_codes()

    def test_negative_pv_element(self) -> None:
        result = check_energy_series([1, 2], [3, -1])
        assert not result.is_valid
        assert ISSUE_NEGATIVE in result.error_codes()

    @pytest.mark.parametrize("bad_series", ["1,2,3", b"123", 123, None])
    def test_not_a_sequence(self, bad_series: object) -> None:
        result = check_energy_series(bad_series, [1, 2, 3])  # type: ignore[arg-type]
        assert not result.is_valid
        assert ISSUE_NOT_SEQUENCE in result.error_codes()

    @pytest.mark.parametrize("bad_interval", [0, -5, 1.5, "60", True])
    def test_invalid_interval(self, bad_interval: object) -> None:
        result = check_energy_series([1], [1], interval_minutes=bad_interval)  # type: ignore[arg-type]
        assert not result.is_valid
        assert ISSUE_INTERVAL_INVALID in result.error_codes()

    def test_valid_interval(self) -> None:
        assert check_energy_series([1], [1], interval_minutes=15).is_valid

    def test_errors_are_collected_not_truncated(self) -> None:
        """多个问题必须全部报告，不能只报第一个后停止。"""
        result = check_energy_series([1, -2, math.nan], [1, 2])
        codes = set(result.error_codes())
        assert ISSUE_LENGTH_MISMATCH in codes
        assert ISSUE_NEGATIVE in codes
        assert ISSUE_NAN in codes

    def test_issue_severity_defaults_to_error(self) -> None:
        issue = check_energy_series([1], [1, 2]).errors[0]
        assert issue.severity is Severity.ERROR

    def test_issue_to_dict_is_serializable(self) -> None:
        issue = check_energy_series([1], [1, 2]).errors[0]
        payload = issue.to_dict()
        assert payload["issue_code"] == ISSUE_LENGTH_MISMATCH
        assert payload["severity"] == "error"
        assert isinstance(payload["message"], str)


class TestRequireValidEnergySeries:
    def test_returns_result_when_valid(self) -> None:
        assert require_valid_energy_series([1], [1]).is_valid

    def test_raises_validation_error_when_invalid(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            require_valid_energy_series([1, 2, 3], [1, 2])
        assert ISSUE_LENGTH_MISMATCH in excinfo.value.issue_codes()
        assert "length_mismatch" in str(excinfo.value)
        assert excinfo.value.format_issues()

    def test_formatted_issues_use_plain_severity_names(self) -> None:
        """面向用户的文本不得出现枚举类名（如 ``Severity.ERROR``）。"""
        with pytest.raises(ValidationError) as excinfo:
            require_valid_energy_series([1, 2, 3], [1, 2])
        formatted = excinfo.value.format_issues()
        assert "[error]" in formatted
        assert "Severity." not in formatted

    def test_validation_error_carries_all_issues(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            require_valid_energy_series([-1, math.nan], [1, 2])
        assert len(excinfo.value.issues) >= 2

    def test_input_data_is_not_modified(self) -> None:
        """校验必须只读：不得就地修改、补齐或丢弃用户数据。"""
        load = [3, -8, 2]
        pv = [5, 4, 2]
        load_copy = list(load)
        pv_copy = list(pv)
        with pytest.raises(ValidationError):
            require_valid_energy_series(load, pv)
        assert load == load_copy
        assert pv == pv_copy


class TestClassifyEnergySeries:
    def test_empty_series_note(self) -> None:
        notes = classify_energy_series([], [])
        assert [note.issue_code for note in notes] == ["empty_series"]
        assert notes[0].severity is Severity.WARNING

    def test_all_zero_note(self) -> None:
        codes = [note.issue_code for note in classify_energy_series([0, 0], [0, 0])]
        assert "all_zero_energy" in codes

    def test_no_pv_note(self) -> None:
        codes = [note.issue_code for note in classify_energy_series([1, 2], [0, 0])]
        assert "no_pv_energy" in codes
        assert "all_zero_energy" not in codes

    def test_no_load_note(self) -> None:
        codes = [note.issue_code for note in classify_energy_series([0, 0], [1, 2])]
        assert codes == ["no_load_energy"]

    def test_normal_case_has_no_notes(self) -> None:
        assert classify_energy_series([3, 8, 2], [5, 4, 2]) == []


class TestProjectValidation:
    def test_valid_project(self) -> None:
        assert validate_project(Project(name="合法项目")).is_valid

    def test_blank_name_rejected(self) -> None:
        result = validate_project(Project(name="   "))
        assert not result.is_valid
        assert "project_name_required" in result.error_codes()

    def test_empty_name_rejected(self) -> None:
        assert not validate_project(Project(name="")).is_valid

    def test_name_too_long_rejected(self) -> None:
        result = validate_project(Project(name="x" * 201))
        assert "project_name_too_long" in result.error_codes()

    def test_name_at_limit_accepted(self) -> None:
        assert validate_project(Project(name="x" * 200)).is_valid

    def test_invalid_project_type_rejected(self) -> None:
        project = Project(name="项目")
        project.project_type = "not-a-type"  # type: ignore[assignment]
        result = validate_project(project)
        assert "project_type_invalid" in result.error_codes()

    def test_invalid_project_id_rejected(self) -> None:
        project = Project(name="项目")
        project.project_id = "too-short"
        result = validate_project(project)
        assert "project_id_invalid" in result.error_codes()

    def test_invalid_timestamp_rejected(self) -> None:
        project = Project(name="项目")
        project.created_at = "2026/02/01 10:00"
        result = validate_project(project)
        assert "created_at_invalid" in result.error_codes()

    def test_require_valid_project_raises(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            require_valid_project(Project(name="  "))
        assert "project_name_required" in excinfo.value.issue_codes()

    @pytest.mark.parametrize("project_type", list(ProjectType))
    def test_all_project_types_valid(self, project_type: ProjectType) -> None:
        assert validate_project(Project(name="项目", project_type=project_type)).is_valid
