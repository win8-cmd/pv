"""电费账单的完整领域模型（V2.1 阶段 2）。

对应规格书第 29 节建议模型的六类实体：

- :class:`ElectricityBill`：月度账单主记录；
- :class:`BillFeeItem`：费用明细（含包含关系与可避免性标记）；
- :class:`BillTimeOfUseItem`：分时/逐小时电量与电价；
- :class:`BillMeterPoint`：计量点（含主分表关系与是否计入首页总量）；
- :class:`BillImportBatch`：导入批次（文件名、时间、记录数、结果）；
- :class:`BillValidationIssue`：数据校验问题（严重程度、表/行/字段、处理状态）。

**数值类型约定（本模块的核心设计决策）**

金额与电量一律使用 :class:`decimal.Decimal`：

- 规格书第 30 节要求精确数值与"空值 / 零值"严格区分；
- 第一阶段 `BillRecord` 的金额列为 SQLite ``REAL``（浮点），
  实测已确认与 `Decimal` 不一致，落库前必须解决（基线风险 R5）；
- 使用 `Decimal` 可避免 ``0.1 + 0.2 != 0.3`` 类误差影响费用勾稽。

**空值语义**

- 未提供 → ``None``（**不得填 0**）；
- 明确为零 → :data:`ZERO` / `Decimal("0")`；
- 二者在测算中的含义完全不同，本模型不作任何自动补零。

**分层**

本模块为纯领域代码：不导入 ``openpyxl``、``sqlite3``、``PySide6``、``pandas``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from cenep.domain.models import new_id, utc_now_iso

__all__ = [
    "AVOIDABLE_FEE_KINDS",
    "ZERO",
    "Avoidability",
    "BaselineInclusion",
    "BillConfirmationState",
    "BillFeeItem",
    "BillImportBatch",
    "BillMeterPoint",
    "BillTimeOfUseItem",
    "ElectricityBill",
    "FeeCategory",
    "ImportOutcome",
    "IncludedInOtherFee",
    "MeterPointType",
    "MeteringBasis",
    "ReviewStatus",
    "TimeOfUsePeriod",
    "ValidationResultState",
    "ValidationSeverityLevel",
    "YesNoUnknown",
    "to_decimal",
]

#: 明确的零值。与 ``None``（未提供）语义不同，不可互换。
ZERO = Decimal("0")


class ReviewStatus(str, Enum):
    """数据复核状态（规格书第 23.5 节）。"""

    PENDING = "待复核"
    REVIEWED = "已复核"
    QUESTIONABLE = "存在疑问"
    NOT_APPLICABLE = "不适用"


class MeteringBasis(str, Enum):
    """电量类型（规格书第 24 节）。"""

    PURCHASE = "购电"
    EXPORT = "上网"
    OTHER = "其他"


class TimeOfUsePeriod(str, Enum):
    """时段名称（规格书第 24 节）。"""

    SHARP_PEAK = "尖峰"
    PEAK = "高峰"
    FLAT = "平"
    VALLEY = "低谷"
    OTHER = "其他"


class FeeCategory(str, Enum):
    """费用大类（规格书第 25 节）。"""

    ENERGY = "电量电费"
    TRANSMISSION = "输配电费"
    SYSTEM = "系统运行费"
    GOVERNMENT = "政府性基金及附加"
    ADJUSTMENT = "调整类费用"
    DEMAND = "需量/基本电费"
    MARKET = "市场化运营费"
    OTHER = "其他"


class IncludedInOtherFee(str, Enum):
    """费用是否已包含在其他费用中（规格书第 25 节）。"""

    YES = "是"
    NO = "否"
    TO_VERIFY = "待核实"


class Avoidability(str, Enum):
    """光伏测算可避免性（规格书第 25 节）。

    **仅作数据管理与分析提示**，不得在缺乏明确业务规则时直接决定最终收益。
    """

    AVOIDABLE = "可避免"
    PARTIALLY_AVOIDABLE = "部分可避免"
    UNAVOIDABLE = "不可避免"
    TO_VERIFY = "待核实"


class BaselineInclusion(str, Enum):
    """是否纳入基准电费（规格书第 25 节）。"""

    YES = "是"
    NO = "否"
    TO_CONFIRM = "待确认"


class MeterPointType(str, Enum):
    """计量点类型（规格书第 26 节）。"""

    MAIN = "主表"
    SUB = "分表"
    CHECK = "考核表"
    OTHER = "其他"


class YesNoUnknown(str, Enum):
    """通用三态。"""

    YES = "是"
    NO = "否"
    TO_VERIFY = "待核实"


class ValidationSeverityLevel(str, Enum):
    """校验问题严重程度（规格书第 27 节）。"""

    BLOCKING = "阻断"
    WARNING = "警告"
    INFO = "提示"


class ValidationResultState(str, Enum):
    """校验结果（规格书第 27 节）。"""

    PASS = "通过"
    FAIL = "不通过"
    PENDING = "待检查"
    NOT_APPLICABLE = "不适用"


class ImportOutcome(str, Enum):
    """导入批次结果（规格书第 29.5、31 节）。"""

    SUCCESS = "全部导入"
    PARTIAL = "部分导入"
    REJECTED = "已取消"
    FAILED = "导入失败"


class BillConfirmationState(str, Enum):
    """账单确认状态。

    与 P0-2 的 :class:`cenep.domain.bill_fields.ConfirmationStatus` 语义一致：
    **解析/导入成功不等于可用于正式测算**，必须经人工确认。
    """

    PENDING = "待确认"
    CONFIRMED = "已确认"
    REJECTED = "已驳回"


#: 具有独立计费机制、**不得默认按光伏发电量同比例节省**的费用类别
#: （规格书第 37 节）。
AVOIDABLE_FEE_KINDS: tuple[FeeCategory, ...] = (
    FeeCategory.DEMAND,
)


def to_decimal(value: Decimal | int | str | None) -> Decimal | None:
    """把入参转换为 :class:`Decimal`。

    **显式拒绝 `float`**：金额与电量使用 `float` 会引入二进制浮点误差，
    破坏费用勾稽与"空值 / 零值"的精确区分。

    Args:
        value: ``Decimal`` / ``int`` / 十进制字符串 / ``None``。

    Returns:
        转换结果；``None`` 原样返回。

    Raises:
        TypeError: 传入 ``float``。
        ValueError: 传入无法解析的字符串。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("布尔值不是合法的数值输入")
    if isinstance(value, float):
        raise TypeError(
            "金额与电量不得使用 float（会引入浮点误差）；"
            "请使用 Decimal、int 或十进制字符串。"
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"无法解析为数值：{value!r}") from exc
    raise TypeError(f"不支持的数值类型：{type(value).__name__}")


def _check_non_negative(value: Decimal | None, label: str) -> None:
    if value is not None and value < ZERO:
        raise ValueError(f"{label}不得为负数，实际为 {value}")


def _check_segment(start: time | None, end: time | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError(f"时段结束（{end}）不得早于开始（{start}）")


@dataclass
class ElectricityBill:
    """月度账单主记录（规格书第 29.1 节）。

    必须**分别保存**账单总金额、工商业电费与发票金额——
    三者口径不同，不得为了让总额相等而互相覆盖或修改。
    """

    bill_id: str = field(default_factory=new_id)
    project_id: str = ""

    # --- 基本信息 -------------------------------------------------------
    customer_name: str | None = None
    """用户名称。"""

    account_number: str | None = None
    """户号。"""

    supply_company: str | None = None
    """供电单位。"""

    supply_address: str | None = None
    """用电地址。**含客户信息，不得提交到公开仓库。**"""

    electricity_category: str | None = None
    """用电类别，如"大工业用电"。"""

    voltage_level: str | None = None
    """电压等级，如"交流110kV"。"""

    market_attribute: str | None = None
    """市场化属性，如"市场化直购客户"。"""

    # --- 账期 -----------------------------------------------------------
    billing_period: str | None = None
    """账期，``YYYY-MM``。"""

    period_start: date | None = None
    period_end: date | None = None
    printed_on: date | None = None
    """账单打印日期。"""

    # --- 总量与金额 -----------------------------------------------------
    total_energy_kwh: Decimal | None = None
    """本期总电量（kWh）。权威字段，**不得由计量点或分时电量求和推导**。非负。"""

    total_amount_yuan: Decimal | None = None
    """账单本期电费（元）。"""

    vat_invoice_amount_yuan: Decimal | None = None
    """增值税专票金额（元）。与总金额口径不同。"""

    displayed_average_price: Decimal | None = None
    """账单展示平均电价（元/kWh）。**仅为统计值，不是光伏边际节省电价**。"""

    # --- 主要费用 -------------------------------------------------------
    industrial_commercial_fee_yuan: Decimal | None = None
    """工商业电费（元）。与总金额口径不同。"""

    market_purchase_fee_yuan: Decimal | None = None
    """(1) 市场化购电电费。"""

    grid_loss_fee_yuan: Decimal | None = None
    """(2) 上网环节线损费用。"""

    transmission_distribution_fee_yuan: Decimal | None = None
    """(3) 输配电费。"""

    system_operation_fee_yuan: Decimal | None = None
    """(4) 系统运行费。"""

    government_fund_fee_yuan: Decimal | None = None
    """(5) 政府性基金及附加。"""

    power_factor_adjustment_fee_yuan: Decimal | None = None
    """功率因数调整电费（元）。**可为负数，必须保留负号**。"""

    demand_charge_yuan: Decimal | None = None
    """需量电费（元）。独立计费机制。"""

    market_operation_fee_yuan: Decimal | None = None
    """市场化运营费合计（元）。可能已包含在其他费用中，核实后方可参与合计。"""

    basic_charge_yuan: Decimal | None = None
    """基本电费（元）。"""

    # --- 需量 -----------------------------------------------------------
    contract_demand: Decimal | None = None
    contract_demand_unit: str | None = None
    """需量单位，``kW`` 或 ``kVA``。**必须显式区分**。"""

    actual_demand: Decimal | None = None
    actual_demand_unit: str | None = None

    demand_billing_mode: str | None = None
    power_factor: Decimal | None = None

    # --- 来源与状态 -----------------------------------------------------
    source_file: str | None = None
    source_page: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    note: str | None = None

    confirmation: BillConfirmationState = BillConfirmationState.PENDING
    """确认状态。**未确认不得进入正式测算。**"""

    import_batch_id: str | None = None
    """来源导入批次；人工录入时为空。"""

    is_sample: bool = False
    """是否为模板样本数据。**样本数据不得作为生产项目账单。**"""

    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not isinstance(self.review_status, ReviewStatus):
            raise TypeError("review_status 必须是 ReviewStatus")
        if not isinstance(self.confirmation, BillConfirmationState):
            raise TypeError("confirmation 必须是 BillConfirmationState")

        # 通过 to_decimal 归一化，顺带拒绝 float
        for attr in (
            "total_energy_kwh",
            "total_amount_yuan",
            "vat_invoice_amount_yuan",
            "displayed_average_price",
            "industrial_commercial_fee_yuan",
            "market_purchase_fee_yuan",
            "grid_loss_fee_yuan",
            "transmission_distribution_fee_yuan",
            "system_operation_fee_yuan",
            "government_fund_fee_yuan",
            "power_factor_adjustment_fee_yuan",
            "demand_charge_yuan",
            "market_operation_fee_yuan",
            "basic_charge_yuan",
            "contract_demand",
            "actual_demand",
            "power_factor",
        ):
            setattr(self, attr, to_decimal(getattr(self, attr)))

        # 总电量必须非负（规格书第 30 节第 4 条）
        _check_non_negative(self.total_energy_kwh, "本期总电量")
        _check_non_negative(self.contract_demand, "合同最大需量")
        _check_non_negative(self.actual_demand, "实际最大需量")

        if self.displayed_average_price is not None:
            _check_non_negative(self.displayed_average_price, "账单展示平均电价")

        # 账期顺序（规格书第 27 节 V01）
        if self.period_start is not None and self.period_end is not None:
            if self.period_end < self.period_start:
                raise ValueError(
                    f"账期结束日（{self.period_end}）不得早于开始日（{self.period_start}）"
                )

        for unit_attr in ("contract_demand_unit", "actual_demand_unit"):
            unit = getattr(self, unit_attr)
            if unit is not None and unit not in ("kW", "kVA"):
                raise ValueError(f"{unit_attr} 只能是 kW 或 kVA，实际为 {unit!r}")

    # -- 便捷属性 -------------------------------------------------------
    @property
    def is_confirmed(self) -> bool:
        return self.confirmation is BillConfirmationState.CONFIRMED

    @property
    def needs_manual_review(self) -> bool:
        """是否需要人工复核。**未确认一律需要复核。**"""
        return not self.is_confirmed

    @property
    def is_usable_for_calculation(self) -> bool:
        """是否可用于正式测算：必须已确认，且不是样本数据。"""
        return self.is_confirmed and not self.is_sample

    @property
    def billing_days(self) -> int | None:
        """账期天数（含首尾）；首尾缺一时返回 ``None``。"""
        if self.period_start is None or self.period_end is None:
            return None
        return (self.period_end - self.period_start).days + 1

    def confirm(
        self,
        *,
        confirmed_at: datetime | None = None,
    ) -> ElectricityBill:
        """标记为已确认（返回副本，不修改原对象）。"""
        if self.is_sample:
            raise ValueError("样本数据不得确认，也不得作为生产项目账单使用")
        return _replace_bill(
            self,
            confirmation=BillConfirmationState.CONFIRMED,
            review_status=ReviewStatus.REVIEWED,
            updated_at=(confirmed_at.isoformat() if confirmed_at else utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        def num(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        def day(value: date | None) -> str | None:
            return None if value is None else value.isoformat()

        return {
            "bill_id": self.bill_id,
            "project_id": self.project_id,
            "customer_name": self.customer_name,
            "account_number": self.account_number,
            "billing_period": self.billing_period,
            "period_start": day(self.period_start),
            "period_end": day(self.period_end),
            "total_energy_kwh": num(self.total_energy_kwh),
            "total_amount_yuan": num(self.total_amount_yuan),
            "vat_invoice_amount_yuan": num(self.vat_invoice_amount_yuan),
            "displayed_average_price": num(self.displayed_average_price),
            "industrial_commercial_fee_yuan": num(self.industrial_commercial_fee_yuan),
            "power_factor_adjustment_fee_yuan": num(self.power_factor_adjustment_fee_yuan),
            "demand_charge_yuan": num(self.demand_charge_yuan),
            "actual_demand": num(self.actual_demand),
            "actual_demand_unit": self.actual_demand_unit,
            "review_status": self.review_status.value,
            "confirmation": self.confirmation.value,
            "is_sample": self.is_sample,
            "is_confirmed": self.is_confirmed,
            "needs_manual_review": self.needs_manual_review,
            "is_usable_for_calculation": self.is_usable_for_calculation,
            "source_file": self.source_file,
            "source_page": self.source_page,
            "note": self.note,
            "import_batch_id": self.import_batch_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _replace_bill(bill: ElectricityBill, **changes: Any) -> ElectricityBill:
    """返回替换了部分字段的账单副本（保持 `__post_init__` 校验）。"""
    from dataclasses import replace as _dc_replace

    return _dc_replace(bill, **changes)


@dataclass
class BillFeeItem:
    """账单费用明细（规格书第 29.2、25 节）。"""

    fee_item_id: str = field(default_factory=new_id)
    bill_id: str = ""
    project_id: str = ""
    billing_period: str | None = None
    fee_category: FeeCategory | None = None
    fee_name: str = ""

    quantity: Decimal | None = None
    quantity_unit: str | None = None
    unit_price: Decimal | None = None
    """单价（元/单位）。"""

    amount_yuan: Decimal | None = None
    """金额（元）。**可为负数**。"""

    included_in_other: IncludedInOtherFee = IncludedInOtherFee.TO_VERIFY
    included_in_fee_name: str | None = None
    """被包含于哪一项（当 ``included_in_other`` 为"是"时填写）。"""

    avoidability: Avoidability = Avoidability.TO_VERIFY
    """光伏测算可避免性。**仅作管理标记。**"""

    baseline_inclusion: BaselineInclusion = BaselineInclusion.TO_CONFIRM

    source_file: str | None = None
    source_page: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    note: str | None = None

    def __post_init__(self) -> None:
        for attr in ("quantity", "unit_price", "amount_yuan"):
            setattr(self, attr, to_decimal(getattr(self, attr)))
        if not isinstance(self.included_in_other, IncludedInOtherFee):
            raise TypeError("included_in_other 必须是 IncludedInOtherFee")
        if not isinstance(self.avoidability, Avoidability):
            raise TypeError("avoidability 必须是 Avoidability")
        if not isinstance(self.baseline_inclusion, BaselineInclusion):
            raise TypeError("baseline_inclusion 必须是 BaselineInclusion")
        if (
            self.included_in_other is IncludedInOtherFee.YES
            and not (self.included_in_fee_name or "").strip()
        ):
            raise ValueError('当"是否包含在其他费用中"为"是"时，必须填写被包含于哪一项')

    @property
    def counts_toward_baseline(self) -> bool:
        """是否可参与基准电费合计。

        **只有明确"未包含在其他费用中"且"纳入基准电费"为"是"时才计入**——
        这是防止重复汇总的关键（规格书第 25、35 节）。
        """
        return (
            self.included_in_other is IncludedInOtherFee.NO
            and self.baseline_inclusion is BaselineInclusion.YES
        )

    @property
    def is_demand_type(self) -> bool:
        """是否属于独立计费机制的费用（不得按电量同比例节省）。"""
        return self.fee_category in AVOIDABLE_FEE_KINDS

    def to_dict(self) -> dict[str, Any]:
        def num(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "fee_item_id": self.fee_item_id,
            "bill_id": self.bill_id,
            "fee_category": self.fee_category.value if self.fee_category else None,
            "fee_name": self.fee_name,
            "quantity": num(self.quantity),
            "quantity_unit": self.quantity_unit,
            "unit_price": num(self.unit_price),
            "amount_yuan": num(self.amount_yuan),
            "included_in_other": self.included_in_other.value,
            "included_in_fee_name": self.included_in_fee_name,
            "avoidability": self.avoidability.value,
            "baseline_inclusion": self.baseline_inclusion.value,
            "counts_toward_baseline": self.counts_toward_baseline,
            "is_demand_type": self.is_demand_type,
            "source_file": self.source_file,
            "source_page": self.source_page,
            "review_status": self.review_status.value,
            "note": self.note,
        }


@dataclass
class BillTimeOfUseItem:
    """分时或逐小时的电量与电价（规格书第 29.3、24 节）。

    **未提供的时段必须留空（``None``），不得补 0**——
    缺失与"确为零"在分时电量勾稽中的含义完全不同。
    """

    tou_item_id: str = field(default_factory=new_id)
    bill_id: str = ""
    project_id: str = ""
    billing_period: str | None = None

    metering_basis_id: str | None = None
    """计量口径 / 计量点编号。**不同口径不得直接求和**。"""

    basis: MeteringBasis = MeteringBasis.PURCHASE
    period_name: TimeOfUsePeriod | None = None
    segment_start: time | None = None
    segment_end: time | None = None

    energy_kwh: Decimal | None = None
    """该时段电量（kWh）。缺失为 ``None``。"""

    price_yuan_per_kwh: Decimal | None = None
    """购电电价（元/kWh）。未提供的时段留空，不得复制其他时段电价。"""

    energy_amount_yuan: Decimal | None = None
    price_type_or_source: str | None = None

    source_file: str | None = None
    source_page: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    note: str | None = None

    def __post_init__(self) -> None:
        for attr in ("energy_kwh", "price_yuan_per_kwh", "energy_amount_yuan"):
            setattr(self, attr, to_decimal(getattr(self, attr)))
        _check_non_negative(self.energy_kwh, "时段电量")
        _check_non_negative(self.price_yuan_per_kwh, "购电电价")
        if not isinstance(self.basis, MeteringBasis):
            raise TypeError("basis 必须是 MeteringBasis")
        _check_segment(self.segment_start, self.segment_end)

    @property
    def is_energy_missing(self) -> bool:
        """电量是否缺失。**缺失不等于 0**。"""
        return self.energy_kwh is None

    def to_dict(self) -> dict[str, Any]:
        def num(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "tou_item_id": self.tou_item_id,
            "bill_id": self.bill_id,
            "billing_period": self.billing_period,
            "metering_basis_id": self.metering_basis_id,
            "basis": self.basis.value,
            "period_name": self.period_name.value if self.period_name else None,
            "segment_start": self.segment_start.isoformat() if self.segment_start else None,
            "segment_end": self.segment_end.isoformat() if self.segment_end else None,
            "energy_kwh": num(self.energy_kwh),
            "price_yuan_per_kwh": num(self.price_yuan_per_kwh),
            "energy_amount_yuan": num(self.energy_amount_yuan),
            "price_type_or_source": self.price_type_or_source,
            "is_energy_missing": self.is_energy_missing,
            "source_file": self.source_file,
            "source_page": self.source_page,
            "review_status": self.review_status.value,
            "note": self.note,
        }


@dataclass
class BillMeterPoint:
    """计量点（规格书第 29.4、26 节）。"""

    meter_point_id: str = field(default_factory=new_id)
    bill_id: str = ""
    project_id: str = ""
    billing_period: str | None = None

    point_code: str = ""
    point_name: str | None = None
    point_type: MeterPointType | None = None
    main_sub_relation: str | None = None
    ratio: Decimal | None = None
    """倍率 / 定比。"""

    energy_kwh: Decimal | None = None

    included_in_total: YesNoUnknown = YesNoUnknown.TO_VERIFY
    """是否已计入首页总电量。"""

    allowed_in_rollup: YesNoUnknown = YesNoUnknown.TO_VERIFY
    """是否允许纳入汇总。**未核实主分表关系时不得自动汇总**。"""

    source_file: str | None = None
    source_page: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    note: str | None = None

    def __post_init__(self) -> None:
        self.ratio = to_decimal(self.ratio)
        self.energy_kwh = to_decimal(self.energy_kwh)
        _check_non_negative(self.energy_kwh, "计量点电量")
        if self.ratio is not None and self.ratio <= ZERO:
            raise ValueError(f"倍率/定比必须为正数，实际为 {self.ratio}")
        if not isinstance(self.included_in_total, YesNoUnknown):
            raise TypeError("included_in_total 必须是 YesNoUnknown")
        if not isinstance(self.allowed_in_rollup, YesNoUnknown):
            raise TypeError("allowed_in_rollup 必须是 YesNoUnknown")

    @property
    def can_join_rollup(self) -> bool:
        """能否参与电量汇总。

        必须同时满足：允许纳入汇总、且未计入首页总电量
        （否则会与首页总量重复计算，规格书第 26 节）。
        """
        return (
            self.allowed_in_rollup is YesNoUnknown.YES
            and self.included_in_total is YesNoUnknown.NO
        )

    def to_dict(self) -> dict[str, Any]:
        def num(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "meter_point_id": self.meter_point_id,
            "bill_id": self.bill_id,
            "billing_period": self.billing_period,
            "point_code": self.point_code,
            "point_name": self.point_name,
            "point_type": self.point_type.value if self.point_type else None,
            "main_sub_relation": self.main_sub_relation,
            "ratio": num(self.ratio),
            "energy_kwh": num(self.energy_kwh),
            "included_in_total": self.included_in_total.value,
            "allowed_in_rollup": self.allowed_in_rollup.value,
            "can_join_rollup": self.can_join_rollup,
            "source_file": self.source_file,
            "source_page": self.source_page,
            "review_status": self.review_status.value,
            "note": self.note,
        }


@dataclass
class BillValidationIssue:
    """数据校验问题（规格书第 29.6、27 节）。"""

    issue_id: str = field(default_factory=new_id)
    batch_id: str | None = None
    project_id: str = ""

    check_code: str = ""
    """校验编号，如 ``V01``。"""

    check_item: str = ""
    severity: ValidationSeverityLevel = ValidationSeverityLevel.WARNING
    result: ValidationResultState = ValidationResultState.PENDING
    detail: str = ""
    """差异值 / 异常说明。"""

    sheet_name: str | None = None
    row_number: int | None = None
    column_name: str | None = None

    handler: str | None = None
    handled_on: date | None = None
    handle_status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.severity, ValidationSeverityLevel):
            raise TypeError("severity 必须是 ValidationSeverityLevel")
        if not isinstance(self.result, ValidationResultState):
            raise TypeError("result 必须是 ValidationResultState")
        if self.row_number is not None and self.row_number < 1:
            raise ValueError("行号必须从 1 开始")

    @property
    def is_blocking(self) -> bool:
        """是否为阻断级且未通过——导入器据此拦截。"""
        return (
            self.severity is ValidationSeverityLevel.BLOCKING
            and self.result is ValidationResultState.FAIL
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "batch_id": self.batch_id,
            "check_code": self.check_code,
            "check_item": self.check_item,
            "severity": self.severity.value,
            "result": self.result.value,
            "detail": self.detail,
            "sheet_name": self.sheet_name,
            "row_number": self.row_number,
            "column_name": self.column_name,
            "handle_status": self.handle_status,
            "handler": self.handler,
            "handled_on": self.handled_on.isoformat() if self.handled_on else None,
            "is_blocking": self.is_blocking,
        }


@dataclass
class BillImportBatch:
    """导入批次（规格书第 29.5、31 节）。"""

    batch_id: str = field(default_factory=new_id)
    project_id: str = ""
    file_name: str = ""
    file_hash: str | None = None
    """文件摘要，用于重复文件识别。"""

    template_version: str | None = None
    imported_at: str = field(default_factory=utc_now_iso)
    imported_by: str | None = None

    total_records: int = 0
    valid_records: int = 0
    warning_records: int = 0
    invalid_records: int = 0
    skipped_records: int = 0

    outcome: ImportOutcome = ImportOutcome.SUCCESS
    message: str | None = None
    user_decision: str | None = None
    """用户对重复账单的处理选择：跳过 / 替换 / 保留。"""

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ImportOutcome):
            raise TypeError("outcome 必须是 ImportOutcome")
        for attr in (
            "total_records",
            "valid_records",
            "warning_records",
            "invalid_records",
            "skipped_records",
        ):
            value = getattr(self, attr)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{attr} 必须是非负整数，实际为 {value!r}")

    @property
    def has_invalid_records(self) -> bool:
        return self.invalid_records > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "project_id": self.project_id,
            "file_name": self.file_name,
            "file_hash": self.file_hash,
            "template_version": self.template_version,
            "imported_at": self.imported_at,
            "imported_by": self.imported_by,
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "warning_records": self.warning_records,
            "invalid_records": self.invalid_records,
            "skipped_records": self.skipped_records,
            "outcome": self.outcome.value,
            "message": self.message,
            "user_decision": self.user_decision,
        }
