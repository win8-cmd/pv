"""输入校验规则。

本模块只做"数据是否可用"的判断，不做任何业务修正。
禁止静默替换、截断、填 0 或丢弃非法数据。

校验结果有两种表现形式：

1. 结构化结果 :class:`ValidationResult`（``check_energy_series``）——
   调用方希望自己决定如何处理问题时使用。
2. 异常 :class:`~cenep.domain.exceptions.ValidationError`
   （``require_valid_energy_series``）—— 调用方希望"不合法就中断"时使用。

二者基于同一套规则实现，不会出现判定不一致。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from cenep.domain.exceptions import ValidationError, summarize_issues


class Severity(str, Enum):
    """校验问题严重程度。"""

    ERROR = "error"
    """数据不可用于计算。"""

    WARNING = "warning"
    """数据可用，但存在需要用户确认的疑点。"""

    INFO = "info"
    """提示性信息，不影响计算。"""


#: 校验问题的稳定代码。测试与界面按代码判断，不依赖中文文案。
ISSUE_LENGTH_MISMATCH = "length_mismatch"
ISSUE_NOT_A_NUMBER = "not_a_number"
ISSUE_NAN = "nan_value"
ISSUE_INFINITE = "infinite_value"
ISSUE_NEGATIVE = "negative_value"
ISSUE_NOT_SEQUENCE = "not_a_sequence"
ISSUE_INTERVAL_INVALID = "interval_minutes_invalid"
ISSUE_EMPTY_SERIES = "empty_series"
ISSUE_ALL_ZERO = "all_zero_energy"
ISSUE_NO_PV = "no_pv_energy"
ISSUE_NO_LOAD = "no_load_energy"


@dataclass(frozen=True)
class ValidationIssue:
    """一条结构化校验问题。

    Attributes:
        issue_code: 稳定代码，见模块级 ``ISSUE_*`` 常量。
        field_name: 出问题的字段或数据列，例如 ``"load"`` / ``"pv[3]"``。
        message: 面向用户的中文说明。
        severity: 严重程度。
        value: 触发问题的原始值（便于界面回显定位），可能为 ``None``。
    """

    issue_code: str
    field_name: str
    message: str
    severity: Severity = Severity.ERROR
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典（用于 input_snapshot 与审计留痕）。"""
        return {
            "issue_code": self.issue_code,
            "field_name": self.field_name,
            "message": self.message,
            "severity": self.severity.value if isinstance(self.severity, Severity) else str(self.severity),
            "value": None if self.value is None else str(self.value),
        }


@dataclass
class ValidationResult:
    """一组校验问题的集合。"""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """是否存在 ``ERROR`` 级问题。"""
        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity is Severity.WARNING]

    @property
    def status(self) -> str:
        """总体状态：``valid`` / ``valid_with_warnings`` / ``invalid``。"""
        if not self.is_valid:
            return "invalid"
        return "valid_with_warnings" if self.warnings else "valid"

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def extend(self, issues: Sequence[ValidationIssue]) -> None:
        self.issues.extend(issues)

    def error_codes(self) -> tuple[str, ...]:
        return tuple(issue.issue_code for issue in self.errors)

    def __bool__(self) -> bool:  # pragma: no cover - 语义糖
        return self.is_valid


def _check_series(
    values: Sequence[float],
    field_name: str,
    result: ValidationResult,
) -> None:
    """校验单个电量序列的元素合法性（非序列、非数值、NaN、无穷、负数）。"""
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        result.add(
            ValidationIssue(
                issue_code=ISSUE_NOT_SEQUENCE,
                field_name=field_name,
                message=f"{field_name} 必须是数值序列（list/tuple/Sequence），实际为 {type(values).__name__}。",
                value=values,
            )
        )
        return

    for index, value in enumerate(values):
        item_field = f"{field_name}[{index}]"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            result.add(
                ValidationIssue(
                    issue_code=ISSUE_NOT_A_NUMBER,
                    field_name=item_field,
                    message=f"{item_field} 不是数值：{value!r}（电量必须为数值，禁止用文本替代）。",
                    value=value,
                )
            )
            continue
        if math.isnan(value):
            result.add(
                ValidationIssue(
                    issue_code=ISSUE_NAN,
                    field_name=item_field,
                    message=f"{item_field} 为 NaN，无法参与电量计算。",
                    value=value,
                )
            )
            continue
        if math.isinf(value):
            result.add(
                ValidationIssue(
                    issue_code=ISSUE_INFINITE,
                    field_name=item_field,
                    message=f"{item_field} 为无穷值，无法参与电量计算。",
                    value=value,
                )
            )
            continue
        if value < 0:
            result.add(
                ValidationIssue(
                    issue_code=ISSUE_NEGATIVE,
                    field_name=item_field,
                    message=(
                        f"{item_field} 为负数（{value}）。时段电量不允许为负；"
                        "若为反向潮流数据，应在数据源阶段拆分方向后重新导入。"
                    ),
                    value=value,
                )
            )


def check_energy_series(
    load: Sequence[float],
    pv: Sequence[float],
    *,
    interval_minutes: int | None = None,
) -> ValidationResult:
    """校验一组用于消纳计算的时段电量序列。

    校验规则（与 ``docs/CALCULATION_SPEC.md`` 第 3 节一一对应）：

    1. ``load`` 与 ``pv`` 必须都是数值序列。
    2. 两者长度必须一致。
    3. 元素必须为数值，不允许 ``bool``、字符串或 ``None`` 冒充数值。
    4. 不允许 ``NaN``。
    5. 不允许 ``inf`` / ``-inf``。
    6. 不允许负数。
    7. ``interval_minutes`` 若给出，必须为正整数。

    空数组不算错误：它是合法输入，由计算层给出全零结果与未定义比例。

    Returns:
        :class:`ValidationResult`；``is_valid`` 为 ``False`` 表示不可计算。
    """
    result = ValidationResult()

    _check_series(load, "load", result)
    _check_series(pv, "pv", result)

    load_is_seq = isinstance(load, Sequence) and not isinstance(load, (str, bytes))
    pv_is_seq = isinstance(pv, Sequence) and not isinstance(pv, (str, bytes))
    if load_is_seq and pv_is_seq and len(load) != len(pv):
        result.add(
            ValidationIssue(
                issue_code=ISSUE_LENGTH_MISMATCH,
                field_name="load/pv",
                message=(
                    f"负荷与光伏序列长度不一致：load={len(load)}，pv={len(pv)}。"
                    "消纳计算要求两个序列在相同时段上一一对应，禁止自行截断或补齐。"
                ),
                value={"load": len(load), "pv": len(pv)},
            )
        )

    if interval_minutes is not None:
        if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int) or interval_minutes <= 0:
            result.add(
                ValidationIssue(
                    issue_code=ISSUE_INTERVAL_INVALID,
                    field_name="interval_minutes",
                    message=(
                        f"时间粒度必须为正整数分钟，实际为 {interval_minutes!r}。"
                        "时间粒度是单位一致性的声明值，不会由程序自动推断。"
                    ),
                    value=interval_minutes,
                )
            )

    return result


def require_valid_energy_series(
    load: Sequence[float],
    pv: Sequence[float],
    *,
    interval_minutes: int | None = None,
) -> ValidationResult:
    """校验电量序列，不合法直接抛 :class:`ValidationError`。

    与 :func:`check_energy_series` 使用完全相同的规则；本函数只负责把
    ``ERROR`` 级问题转为异常，**不会修改任何输入数据**。
    """
    result = check_energy_series(load, pv, interval_minutes=interval_minutes)
    if not result.is_valid:
        raise ValidationError(
            f"输入电量数据未通过校验：{summarize_issues(result.errors)}",
            issues=result.errors,
        )
    return result


PROJECT_NAME_MAX_LENGTH = 200
"""项目名称最大长度（与 DATA_MODEL.md 中 ``varchar(200)`` 语义一致）。"""


def validate_project(project: "Any") -> ValidationResult:
    """校验 :class:`cenep.domain.models.Project` 的字段合法性。

    规则：

    1. ``name`` 必填且去除首尾空白后非空。
    2. ``name`` 长度不超过 :data:`PROJECT_NAME_MAX_LENGTH`。
    3. ``project_type`` 必须是 :class:`~cenep.domain.models.ProjectType` 之一。
    4. ``created_at`` / ``updated_at`` 必须是可解析的 ISO 8601 时间戳。
    5. ``project_id`` 必须是 32 位十六进制 UUID 字符串。

    本函数不修改传入对象。
    """
    # 延迟导入以避免运行期循环依赖
    from cenep.domain.models import ProjectType, is_valid_iso_timestamp

    result = ValidationResult()

    project_id = getattr(project, "project_id", "")
    if not isinstance(project_id, str) or len(project_id) != 32 or not all(
        char in "0123456789abcdef" for char in project_id.lower()
    ):
        result.add(
            ValidationIssue(
                issue_code="project_id_invalid",
                field_name="project_id",
                message=f"project_id 必须是 32 位十六进制 UUID 字符串，实际为 {project_id!r}。",
                value=project_id,
            )
        )

    name = getattr(project, "name", None)
    if not isinstance(name, str) or not name.strip():
        result.add(
            ValidationIssue(
                issue_code="project_name_required",
                field_name="name",
                message="项目名称必填且不能为空白字符。",
                value=name,
            )
        )
    elif len(name.strip()) > PROJECT_NAME_MAX_LENGTH:
        result.add(
            ValidationIssue(
                issue_code="project_name_too_long",
                field_name="name",
                message=f"项目名称长度 {len(name.strip())} 超过上限 {PROJECT_NAME_MAX_LENGTH}。",
                value=name,
            )
        )

    project_type = getattr(project, "project_type", None)
    if not isinstance(project_type, ProjectType):
        try:
            ProjectType(project_type)
        except (ValueError, TypeError):
            result.add(
                ValidationIssue(
                    issue_code="project_type_invalid",
                    field_name="project_type",
                    message=(
                        f"项目类型非法：{project_type!r}；"
                        f"允许值为 {[item.value for item in ProjectType]}。"
                    ),
                    value=project_type,
                )
            )

    for field_name in ("created_at", "updated_at"):
        value = getattr(project, field_name, None)
        if not is_valid_iso_timestamp(value):
            result.add(
                ValidationIssue(
                    issue_code=f"{field_name}_invalid",
                    field_name=field_name,
                    message=f"{field_name} 必须是 ISO 8601 时间戳，实际为 {value!r}。",
                    value=value,
                )
            )

    return result


def require_valid_project(project: "Any") -> ValidationResult:
    """校验项目字段，不合法抛 :class:`ValidationError`。"""
    result = validate_project(project)
    if not result.is_valid:
        raise ValidationError(
            f"项目数据未通过校验：{summarize_issues(result.errors)}",
            issues=result.errors,
        )
    return result


def classify_energy_series(load: Sequence[float], pv: Sequence[float]) -> list[ValidationIssue]:
    """对**合法**序列做业务提示（全零、无光伏、无负荷）。

    这些提示不影响计算执行，用于界面提醒与报告脚注。
    """
    notes: list[ValidationIssue] = []
    total_load = float(sum(load))
    total_pv = float(sum(pv))

    if not load and not pv:
        notes.append(
            ValidationIssue(
                issue_code=ISSUE_EMPTY_SERIES,
                field_name="load/pv",
                message="输入为空数组：全部电量计为 0 kWh，比例类指标未定义。",
                severity=Severity.WARNING,
            )
        )
        return notes

    if total_load == 0.0 and total_pv == 0.0:
        notes.append(
            ValidationIssue(
                issue_code=ISSUE_ALL_ZERO,
                field_name="load/pv",
                message="全部时段负荷与光伏电量均为 0 kWh：电量为 0，比例类指标未定义。",
                severity=Severity.WARNING,
            )
        )
    if total_pv == 0.0 and load:
        notes.append(
            ValidationIssue(
                issue_code=ISSUE_NO_PV,
                field_name="pv",
                message="光伏发电量合计为 0 kWh：自用率与余电比例未定义。",
                severity=Severity.WARNING,
            )
        )
    if total_load == 0.0 and pv:
        notes.append(
            ValidationIssue(
                issue_code=ISSUE_NO_LOAD,
                field_name="load",
                message="用电量合计为 0 kWh：负荷覆盖率未定义。",
                severity=Severity.WARNING,
            )
        )
    return notes


__all__ = [
    "ISSUE_ALL_ZERO",
    "ISSUE_EMPTY_SERIES",
    "ISSUE_INTERVAL_INVALID",
    "ISSUE_LENGTH_MISMATCH",
    "ISSUE_NAN",
    "ISSUE_NEGATIVE",
    "ISSUE_NOT_A_NUMBER",
    "ISSUE_NOT_SEQUENCE",
    "ISSUE_NO_LOAD",
    "ISSUE_NO_PV",
    "PROJECT_NAME_MAX_LENGTH",
    "Severity",
    "ValidationIssue",
    "ValidationResult",
    "check_energy_series",
    "classify_energy_series",
    "require_valid_energy_series",
    "require_valid_project",
    "validate_project",
]
