"""光伏自发自用 / 余电上网 / 电网购电的消纳计算。

本模块是第一阶段唯一的业务计算实现，也是后续经济评价的输入基础。
计算规则完全依据 ``docs/CALCULATION_SPEC.md``（版本 ``2026.02-stage1``）。

设计约束：

1. 纯函数：输入为两个数值序列，输出为结构化结果对象，
   不读取界面控件、不访问数据库、不写文件。
2. 非法输入**抛异常**（:class:`~cenep.domain.exceptions.ValidationError`），
   不做静默修正（不截断、不补齐、不把负数取绝对值、不把 NaN 当 0）。
3. 零分母时比例类指标返回 ``None``（未定义），而不是 0 或 0.0，
   以便界面展示"未定义"并避免被误当作"真实为 0"。

逐时段公式::

    self_consumption_t = min(load_t, pv_t)
    export_t           = max(pv_t - load_t, 0)
    grid_import_t      = max(load_t - pv_t, 0)

能量守恒关系（测试中按浮点近似比较）::

    total_pv   == total_self_consumption + total_export
    total_load == total_self_consumption + total_grid_import
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from cenep.domain.exceptions import ValidationError
from cenep.domain.validation import (
    ValidationIssue,
    classify_energy_series,
    require_valid_energy_series,
)

#: 消纳计算规则版本号。任何公式或口径变更都必须提升此版本，
#: 并同步更新 docs/CALCULATION_SPEC.md。
CALCULATION_VERSION = "0.1.0"

#: 电子电量容差。用于能量守恒自检，避免浮点误差造成假失败。
ENERGY_TOLERANCE_KWH = 1e-9

STATUS_OK = "ok"
"""计算正常完成。"""

STATUS_UNDEFINED_RATIO = "undefined_ratio"
"""电量已算出，但至少一个比例类指标因零分母而未定义。"""


@dataclass(frozen=True)
class SelfConsumptionResult:
    """消纳计算结果（结构化数据，不是格式化文本）。

    Attributes:
        total_load_kwh: 时段用电量合计（kWh）。
        total_pv_kwh: 时段光伏发电量合计（kWh）。
        total_self_consumption_kwh: 光伏自用电量合计（kWh）。
        total_export_kwh: 余电上网电量合计（kWh）。
        total_grid_import_kwh: 电网购电量合计（kWh）。
        self_consumption_rate: 自用率 = 自用电量 / 光伏发电量，0~1 的比值；
            光伏发电量为 0 时为 ``None``。
        load_coverage_rate: 负荷覆盖率 = 自用电量 / 用电量；
            用电量为 0 时为 ``None``。由于逐时段取小后求和，必有
            ``total_self_consumption <= total_load``，故该值处于 0~1 区间，
            不会超过 1。
        export_rate: 余电比例 = 余电上网电量 / 光伏发电量；
            光伏发电量为 0 时为 ``None``。
        status: ``ok`` 或 ``undefined_ratio``。
        interval_minutes: 调用方声明的时间粒度（分钟）；未声明为 ``None``。
        energy_unit: 电量单位，固定 ``"kWh"``。
        periods: 时段数。
        calculation_version: 计算规则版本，用于结果追溯。
        input_fingerprint: 输入数据的 SHA-256 指纹（前 16 位），
            用于结果与输入数据的对应追溯。
        notes: 业务提示（全零、无光伏、无负荷、空数组等），不影响数值。
    """

    total_load_kwh: float
    total_pv_kwh: float
    total_self_consumption_kwh: float
    total_export_kwh: float
    total_grid_import_kwh: float
    self_consumption_rate: float | None
    load_coverage_rate: float | None
    export_rate: float | None
    status: str
    interval_minutes: int | None = None
    energy_unit: str = "kWh"
    periods: int = 0
    calculation_version: str = CALCULATION_VERSION
    input_fingerprint: str = ""
    notes: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def has_undefined_ratios(self) -> bool:
        """是否存在未定义的比例指标。"""
        return (
            self.self_consumption_rate is None
            or self.load_coverage_rate is None
            or self.export_rate is None
        )

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典。

        ``None`` 保持为 ``None``（JSON ``null``），**不转换为 0**，
        以便下游区分"未定义"与"为零"。
        """
        data = asdict(self)
        data["notes"] = [note.to_dict() for note in self.notes]
        return data

    def to_metric_rows(self) -> list[dict[str, Any]]:
        """转为 ``ResultRecord`` 形态的指标行，便于落库。

        比例类指标为 ``None`` 时，``status`` 记为 ``undefined``，
        禁止把它们写成数值 0。
        """
        rows: list[dict[str, Any]] = []
        energy_metrics = (
            ("total_load_kwh", self.total_load_kwh),
            ("total_pv_kwh", self.total_pv_kwh),
            ("total_self_consumption_kwh", self.total_self_consumption_kwh),
            ("total_export_kwh", self.total_export_kwh),
            ("total_grid_import_kwh", self.total_grid_import_kwh),
        )
        for name, value in energy_metrics:
            rows.append({"metric_name": name, "value": value, "unit": "kWh", "status": "ok"})

        ratio_metrics = (
            ("self_consumption_rate", self.self_consumption_rate),
            ("load_coverage_rate", self.load_coverage_rate),
            ("export_rate", self.export_rate),
        )
        for name, ratio in ratio_metrics:
            rows.append(
                {
                    "metric_name": name,
                    "value": ratio,
                    "unit": "ratio",
                    "status": "ok" if ratio is not None else "undefined",
                }
            )
        return rows

    def check_energy_balance(self, tolerance: float = ENERGY_TOLERANCE_KWH) -> None:
        """自检两条能量守恒关系，不满足即抛 :class:`AssertionError`。

        生产代码不依赖断言，故此处显式抛异常；测试亦直接调用本方法。
        """
        pv_gap = abs(self.total_pv_kwh - (self.total_self_consumption_kwh + self.total_export_kwh))
        load_gap = abs(self.total_load_kwh - (self.total_self_consumption_kwh + self.total_grid_import_kwh))
        if pv_gap > tolerance or load_gap > tolerance:
            raise AssertionError(
                "能量守恒校验失败："
                f"|总光伏 - (自用 + 上网)| = {pv_gap:.12g}，"
                f"|总负荷 - (自用 + 购电)| = {load_gap:.12g}，容差 {tolerance:g} kWh。"
            )


def _fingerprint(load: Sequence[float], pv: Sequence[float], interval_minutes: int | None) -> str:
    """计算输入数据的稳定指纹（不参与业务判断，仅用于追溯）。"""
    digest = hashlib.sha256()
    digest.update(f"interval={interval_minutes};".encode())
    for name, series in (("load", load), ("pv", pv)):
        digest.update(f"{name}[{len(series)}]=".encode())
        for value in series:
            digest.update(f"{float(value)!r},".encode())
        digest.update(b";")
    return digest.hexdigest()[:16]


def calculate_self_consumption(
    load: Sequence[float],
    pv: Sequence[float],
    *,
    interval_minutes: int | None = None,
) -> SelfConsumptionResult:
    """计算光伏自发自用、余电上网与电网购电。

    Args:
        load: 每个时段的**用电量**（kWh），非负数值序列。
        pv: 相同时段、相同粒度的**光伏发电量**（kWh），非负数值序列。
        interval_minutes: 调用方声明的时段长度（分钟），可选。
            本函数不推断粒度、不做粒度换算；若两个序列粒度不同，
            必须由调用方先归一到同一粒度再调用。

    Returns:
        :class:`SelfConsumptionResult`。

    Raises:
        ValidationError: 输入不合法（长度不一致、负数、NaN、无穷、非数值、
            时间粒度非法）。异常对象携带结构化问题清单，原始数据未被修改。

    Note:
        空数组是合法输入：返回全 0 电量、三个比例指标均为 ``None``、
        ``status == "undefined_ratio"``。
    """
    result = require_valid_energy_series(load, pv, interval_minutes=interval_minutes)

    load_values = [float(value) for value in load]
    pv_values = [float(value) for value in pv]

    total_self_consumption = 0.0
    total_export = 0.0
    total_grid_import = 0.0

    for load_t, pv_t in zip(load_values, pv_values):
        total_self_consumption += min(load_t, pv_t)
        total_export += max(pv_t - load_t, 0.0)
        total_grid_import += max(load_t - pv_t, 0.0)

    total_load = math.fsum(load_values)
    total_pv = math.fsum(pv_values)

    self_consumption_rate = (total_self_consumption / total_pv) if total_pv > 0 else None
    load_coverage_rate = (total_self_consumption / total_load) if total_load > 0 else None
    export_rate = (total_export / total_pv) if total_pv > 0 else None

    notes = tuple(classify_energy_series(load_values, pv_values))
    undefined = (
        self_consumption_rate is None
        or load_coverage_rate is None
        or export_rate is None
    )

    computed = SelfConsumptionResult(
        total_load_kwh=total_load,
        total_pv_kwh=total_pv,
        total_self_consumption_kwh=total_self_consumption,
        total_export_kwh=total_export,
        total_grid_import_kwh=total_grid_import,
        self_consumption_rate=self_consumption_rate,
        load_coverage_rate=load_coverage_rate,
        export_rate=export_rate,
        status=STATUS_UNDEFINED_RATIO if undefined else STATUS_OK,
        interval_minutes=interval_minutes,
        energy_unit="kWh",
        periods=len(load_values),
        calculation_version=CALCULATION_VERSION,
        input_fingerprint=_fingerprint(load_values, pv_values, interval_minutes),
        notes=notes,
    )

    # 计算层内部自检：守恒关系必须成立，否则说明实现有缺陷而非用户数据问题。
    computed.check_energy_balance()
    return computed


def calculate_self_consumption_with_issues(
    load: Sequence[float],
    pv: Sequence[float],
    *,
    interval_minutes: int | None = None,
) -> tuple[SelfConsumptionResult | None, "ValidationIssue | None", tuple[ValidationIssue, ...]]:
    """非抛异常风格的调用入口，便于界面层做"校验 + 逐条提示"。

    Returns:
        ``(result, failure, warnings)``：

        - 成功：``failure`` 为 ``None``，``result`` 为计算结果。
        - 失败：``result`` 为 ``None``，``failure`` 为首条错误问题，
          ``warnings`` 为空元组。界面层可进一步捕获 ``ValidationError``
          获取全部问题。
    """
    try:
        result = calculate_self_consumption(load, pv, interval_minutes=interval_minutes)
    except ValidationError as exc:
        failure = exc.issues[0] if exc.issues else ValidationIssue(
            issue_code="validation_error",
            field_name="load/pv",
            message=str(exc),
        )
        return None, failure, ()
    return result, None, result.notes


__all__ = [
    "CALCULATION_VERSION",
    "ENERGY_TOLERANCE_KWH",
    "STATUS_OK",
    "STATUS_UNDEFINED_RATIO",
    "SelfConsumptionResult",
    "calculate_self_consumption",
    "calculate_self_consumption_with_issues",
]
