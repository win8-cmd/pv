"""账单应用服务（规格书第 33 节：人工录入与编辑）。

职责边界：

- **做**：组织账单用例流程（导入 → 预览 → 确认 → 落库；人工录入 → 校验 →
  保存 → 读取），装配 `data` / `infrastructure` 依赖，给出粒度合适的用例方法，
  并保证"未确认不得用于正式测算"这一闸门在服务层即可判定。
- **不做**：不写 SQL（交给 :class:`SqliteBillRepository`）、
  不实现 Excel 读写细节（交给 `cenep.data`）、不碰 Qt 控件。

界面层只允许调用本服务，不得直接访问仓储或数据库。

**人工录入与 Excel 导入共用同一套领域模型与校验**：人工录入的账单同样要过
:func:`cenep.data.bill_validation.validate_bill_data`，因此两条入口的数据质量
口径完全一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from cenep.data.bill_import_service import (
    BillImportService,
    DuplicateDecision,
    ImportApplyResult,
    ImportDecision,
    ImportPreview,
)
from cenep.data.bill_validation import ValidationReport, validate_bill_data
from cenep.data.template_reader import TemplateReadError
from cenep.domain.bill_models import (
    BillFeeItem,
    BillImportBatch,
    BillMeterPoint,
    BillTimeOfUseItem,
    ElectricityBill,
    ReviewStatus,
    to_decimal,
)
from cenep.domain.exceptions import ValidationError
from cenep.infrastructure.bill_repository import SqliteBillRepository
from cenep.infrastructure.database import Database

__all__ = [
    "BillService",
    "BillSummary",
    "ManualBillInput",
]


# ---------------------------------------------------------------------------
# 人工录入输入
# ---------------------------------------------------------------------------


@dataclass
class ManualBillInput:
    """人工录入一张账单的输入。

    全部数值字段都是"未提供的字符串/``None``"——**空字符串与 ``None`` 都表示未提供**，
    由服务层转换为 ``Decimal``；**绝不把空值当成 0**。

    这样可以同时服务于界面表单（全是文本）与程序化调用。
    """

    billing_period: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    account_number: str | None = None
    customer_name: str | None = None
    supply_company: str | None = None
    supply_address: str | None = None
    electricity_category: str | None = None
    voltage_level: str | None = None
    total_energy_kwh: str | None = None
    total_amount_yuan: str | None = None
    vat_invoice_amount_yuan: str | None = None
    displayed_average_price: str | None = None
    industrial_commercial_fee_yuan: str | None = None
    power_factor_adjustment_fee_yuan: str | None = None
    demand_charge_yuan: str | None = None
    contract_demand: str | None = None
    contract_demand_unit: str | None = None
    actual_demand: str | None = None
    actual_demand_unit: str | None = None
    demand_billing_mode: str | None = None
    source_file: str | None = None
    source_page: str | None = None
    review_status: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items()}


#: 人工录入中属于 ``Decimal`` 的字段
_MANUAL_DECIMAL_FIELDS: tuple[str, ...] = (
    "total_energy_kwh",
    "total_amount_yuan",
    "vat_invoice_amount_yuan",
    "displayed_average_price",
    "industrial_commercial_fee_yuan",
    "power_factor_adjustment_fee_yuan",
    "demand_charge_yuan",
    "contract_demand",
    "actual_demand",
)

#: 人工录入中属于日期的字段
_MANUAL_DATE_FIELDS: tuple[str, ...] = ("period_start", "period_end")


def _text(value: str | None) -> str | None:
    """空字符串 → ``None``（未提供），其余去空白。"""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _decimal_input(value: str | None, field_name: str) -> Decimal | None:
    """把录入文本转为 ``Decimal``；空值保持 ``None``（不补 0）。

    Raises:
        ValidationError: 文本非空但无法解析为数值。
    """
    text = _text(value)
    if text is None:
        return None
    try:
        return to_decimal(text)
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            f"{field_name} 不是有效数值：{value!r}",
            issues=(),
        ) from exc


def _date_input(value: str | None, field_name: str):
    from datetime import date, datetime

    text = _text(value)
    if text is None:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValidationError(f"{field_name} 不是有效日期（应为 YYYY-MM-DD）：{value!r}")


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


@dataclass
class BillSummary:
    """账单汇总视图（供界面展示，不含业务公式）。"""

    project_id: str
    bill_count: int = 0
    confirmed_count: int = 0
    pending_review_count: int = 0
    pending_confirmation_count: int = 0
    periods: tuple[str, ...] = ()
    total_energy_kwh: Decimal | None = None
    total_amount_yuan: Decimal | None = None

    @property
    def all_confirmed(self) -> bool:
        return self.bill_count > 0 and self.confirmed_count == self.bill_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "bill_count": self.bill_count,
            "confirmed_count": self.confirmed_count,
            "pending_review_count": self.pending_review_count,
            "pending_confirmation_count": self.pending_confirmation_count,
            "periods": list(self.periods),
            "total_energy_kwh": (
                str(self.total_energy_kwh) if self.total_energy_kwh is not None else None
            ),
            "total_amount_yuan": (
                str(self.total_amount_yuan) if self.total_amount_yuan is not None else None
            ),
            "all_confirmed": self.all_confirmed,
        }


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


class BillService:
    """账单相关用例的应用服务。

    Args:
        database: 数据库对象；不传则使用默认路径。
        auto_initialize: 为 ``True`` 时在首次操作前自动建表（幂等）。
    """

    def __init__(
        self,
        database: Database | None = None,
        *,
        auto_initialize: bool = True,
    ) -> None:
        if database is None:
            from cenep import config

            database = Database(config.ensure_parent_dir(config.resolve_database_path()))
        self._db = database
        self._repository = SqliteBillRepository(database)
        self._import_service = BillImportService(self._repository)
        self._initialized = False
        if auto_initialize:
            self.initialize()

    # -- 生命周期 -------------------------------------------------------
    @property
    def database(self) -> Database:
        return self._db

    @property
    def repository(self) -> SqliteBillRepository:
        return self._repository

    def initialize(self) -> None:
        """建库建表（幂等）。"""
        self._db.initialize_schema()
        self._initialized = True

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._db.exists():
            self._db.initialize_schema()
        self._initialized = True

    # -- Excel 导入 -----------------------------------------------------
    def preview_import(
        self,
        path: str | Path,
        *,
        project_id: str,
        price_unit_is_per_mwh: bool = False,
    ) -> ImportPreview:
        """生成导入预览（**只读，不写入**）。

        Raises:
            TemplateReadError: 文件结构性问题。
        """
        self.ensure_initialized()
        return self._import_service.preview(
            path, project_id=project_id, price_unit_is_per_mwh=price_unit_is_per_mwh
        )

    def apply_import(
        self,
        preview: ImportPreview,
        *,
        decision: ImportDecision,
        duplicate_decision: DuplicateDecision | None = None,
        imported_by: str | None = None,
        user_decision_note: str | None = None,
    ) -> ImportApplyResult:
        """按用户决策落库。

        Raises:
            ValueError: 决策与预览状态不匹配（存在阻断却要求全部导入、
                存在重复却未给出处置方式）。
            PersistenceError: 数据库写入失败。
        """
        self.ensure_initialized()
        return self._import_service.apply(
            preview,
            decision=decision,
            duplicate_decision=duplicate_decision,
            imported_by=imported_by,
            user_decision_note=user_decision_note,
        )

    # -- 人工录入 -------------------------------------------------------
    def create_bill(
        self,
        project_id: str,
        payload: ManualBillInput | dict[str, Any],
        *,
        is_sample: bool = False,
    ) -> ElectricityBill:
        """人工录入一张账单并落库。

        Args:
            project_id: 目标项目主键。
            payload: :class:`ManualBillInput` 或同构字典。
            is_sample: 样本数据标记；样本**不得确认**，也不得用于正式测算。

        Raises:
            ValidationError: 字段格式非法，或违反账单数据约束。
            PersistenceError: 数据库写入失败（含业务键重复）。
        """
        self.ensure_initialized()
        if isinstance(payload, dict):
            payload = ManualBillInput(**payload)

        values = self._manual_values(project_id, payload, is_sample)
        bill_values: dict[str, Any] = {
            key: value for key, value in values.items() if key != "is_sample"
        }
        bill_values["is_sample"] = is_sample
        # 数值字段由领域模型从字符串归一为 Decimal；
        # 日期字段需转回 date 对象（_manual_values 为 SQL 写库产出了 ISO 字符串）。
        for name in _MANUAL_DECIMAL_FIELDS:
            text = values[name]
            bill_values[name] = None if text is None else to_decimal(text)
        for name in _MANUAL_DATE_FIELDS:
            text = values[name]
            bill_values[name] = (
                None if text is None else date.fromisoformat(text)
            )

        try:
            bill = ElectricityBill(**bill_values)
        except (ValueError, TypeError) as exc:
            raise ValidationError(f"账单数据不合法：{exc}", issues=()) from exc

        batch = BillImportBatch(
            project_id=project_id,
            file_name="（人工录入）",
            imported_by=None,
            total_records=1,
            valid_records=1,
            outcome=self._manual_outcome(),
            user_decision="人工录入",
        )
        self._repository.save_batch(batch, [bill], [], [], [])
        created = self._repository.get_bill(bill.bill_id)
        return created if created is not None else bill

    @staticmethod
    def _review_status(value: str | None | ReviewStatus) -> ReviewStatus:
        """把录入值解析为复核状态。

        同时接受 ``ReviewStatus`` 成员与中文文本；``None``/空 → 待复核。

        Note:
            ``ReviewStatus`` 是 ``str`` 的子类，因此**必须先判断是否为枚举成员**；
            否则 ``ReviewStatus(ReviewStatus.REVIEWED)`` 会抛
            "not a valid ReviewStatus"（实测踩坑）。
        """
        if isinstance(value, ReviewStatus):
            return value
        text = _text(value)
        if text is None:
            return ReviewStatus.PENDING
        try:
            return ReviewStatus(text)
        except ValueError as exc:
            allowed = "、".join(item.value for item in ReviewStatus)
            raise ValidationError(
                f"复核状态非法：{value!r}；允许值为 {allowed}。", issues=()
            ) from exc

    @staticmethod
    def _manual_outcome():
        from cenep.domain.bill_models import ImportOutcome

        return ImportOutcome.SUCCESS

    def update_bill(self, bill_id: str, payload: ManualBillInput | dict[str, Any]) -> ElectricityBill:
        """修改人工录入的账单。

        使用"整体替换"语义：未在 ``payload`` 中提供的字段会被清空为未提供。
        若只想改少数字段，请先用 :meth:`get_bill` 取出后构造完整输入。

        Raises:
            ValidationError: 账单不存在或数据非法。
        """
        self.ensure_initialized()
        existing = self._repository.get_bill(bill_id)
        if existing is None:
            raise ValidationError(f"账单不存在：{bill_id}", issues=())
        if isinstance(payload, dict):
            # 忽略调用方可能多传的只读字段，避免 TypeError
            allowed = set(ManualBillInput().__dict__)
            payload = ManualBillInput(
                **{key: value for key, value in payload.items() if key in allowed}
            )

        values = self._manual_values(existing.project_id, payload, existing.is_sample)
        # **就地更新**：不能用"先删后插"或"先插后删"，
        # 因为业务键唯一索引 (项目,户号,账期) 会让新行与旧行冲突（实测踩坑）。
        values["bill_id"] = bill_id
        # 更新后必须重新确认
        values["confirmation"] = "待确认"
        values.pop("is_sample", None)

        columns = [key for key in values if key != "bill_id"]
        assignments = ", ".join(f"{column} = ?" for column in columns)
        params = [
            values[column].value if isinstance(values[column], ReviewStatus) else values[column]
            for column in columns
        ]
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    f"UPDATE bill SET {assignments} WHERE bill_id = ?",
                    params + [bill_id],
                )
        except Exception as exc:  # sqlite3.IntegrityError 等
            from cenep.infrastructure.database import translate_integrity_error

            if isinstance(exc, __import__("sqlite3").IntegrityError):
                raise translate_integrity_error(exc, entity_id=bill_id) from exc
            raise

        updated = self._repository.get_bill(bill_id)
        if updated is None:  # pragma: no cover - 刚更新过，不应发生
            raise ValidationError(f"更新后无法读回账单：{bill_id}", issues=())
        return updated

    def _manual_values(
        self,
        project_id: str,
        payload: ManualBillInput,
        is_sample: bool,
    ) -> dict[str, Any]:
        """把人工录入输入规范化为数据库列值。"""
        values: dict[str, Any] = {
            "project_id": project_id,
            "billing_period": _text(payload.billing_period),
            "account_number": _text(payload.account_number),
            "customer_name": _text(payload.customer_name),
            "supply_company": _text(payload.supply_company),
            "supply_address": _text(payload.supply_address),
            "electricity_category": _text(payload.electricity_category),
            "voltage_level": _text(payload.voltage_level),
            "contract_demand_unit": _text(payload.contract_demand_unit),
            "actual_demand_unit": _text(payload.actual_demand_unit),
            "demand_billing_mode": _text(payload.demand_billing_mode),
            "source_file": _text(payload.source_file),
            "source_page": _text(payload.source_page),
            "note": _text(payload.note),
            "is_sample": 1 if is_sample else 0,
            # 保留枚举成员：领域模型要求 ReviewStatus，SQL 写入侧再取 .value
            "review_status": self._review_status(payload.review_status),
        }
        for name in _MANUAL_DECIMAL_FIELDS:
            value = _decimal_input(getattr(payload, name), name)
            values[name] = None if value is None else str(value)
        for name in _MANUAL_DATE_FIELDS:
            value = _date_input(getattr(payload, name), name)
            values[name] = None if value is None else value.isoformat()
        return values

    def _delete_bill_row(self, bill_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM bill WHERE bill_id = ?", (bill_id,))

    def copy_bill(
        self,
        source_bill_id: str,
        *,
        billing_period: str,
        period_start: str | None = None,
        period_end: str | None = None,
        total_energy_kwh: str | None = None,
        total_amount_yuan: str | None = None,
    ) -> ElectricityBill:
        """以既有账单为模板新建一张账单（规格书第 33 节"复制上月"）。

        典型用法：上月账单填完后，复制上月再改账期与金额。

        **复制规则（有意为之）**：

        - 复用来源账单的**静态信息**：户号、户名、供电单位、地址、用电类别、
          电压等级、需量单位、需量计费方式、来源文件/页码；
        - **必须显式给出新账期**；
        - **金额与电量默认清空为未提供**，除非显式传入 —— 避免把上月数值
          当作本月数值"顺手带过去"（这是最容易造成虚增数据的事故）；
        - 复核状态重置为**待复核**；确认状态重置为**待确认**。

        Raises:
            ValidationError: 来源账单不存在，或新数据非法。
        """
        self.ensure_initialized()
        source = self._repository.get_bill(source_bill_id)
        if source is None:
            raise ValidationError(f"来源账单不存在：{source_bill_id}", issues=())

        payload = ManualBillInput(
            billing_period=billing_period,
            period_start=period_start,
            period_end=period_end,
            account_number=source.account_number,
            customer_name=source.customer_name,
            supply_company=source.supply_company,
            supply_address=source.supply_address,
            electricity_category=source.electricity_category,
            voltage_level=source.voltage_level,
            # 金额与电量**不复制**，须显式传入
            total_energy_kwh=total_energy_kwh,
            total_amount_yuan=total_amount_yuan,
            demand_billing_mode=source.demand_billing_mode,
            contract_demand_unit=source.contract_demand_unit,
            actual_demand_unit=source.actual_demand_unit,
            source_file=source.source_file,
            source_page=source.source_page,
            review_status=ReviewStatus.PENDING.value,
        )
        return self.create_bill(source.project_id, payload, is_sample=source.is_sample)

    def list_bills_by_review_status(
        self, project_id: str, status: ReviewStatus | str
    ) -> list[ElectricityBill]:
        """按复核状态筛选账单（界面筛选用）。"""
        self.ensure_initialized()
        if isinstance(status, str):
            status = self._review_status(status)
        return [
            bill
            for bill in self.list_bills(project_id)
            if bill.review_status is status
        ]

    def delete_bill(self, bill_id: str, *, allow_confirmed: bool = False) -> None:
        """删除账单。

        Args:
            allow_confirmed: 是否允许删除**已确认**账单。默认禁止，
                避免误删已确认数据；调用方需显式传入 ``True``。

        Raises:
            ValidationError: 账单不存在，或已确认但未获授权删除。
        """
        self.ensure_initialized()
        bill = self._repository.get_bill(bill_id)
        if bill is None:
            raise ValidationError(f"账单不存在：{bill_id}", issues=())
        if bill.is_confirmed and not allow_confirmed:
            raise ValidationError(
                "该账单已确认，删除需显式授权（allow_confirmed=True）", issues=()
            )
        self._delete_bill_row(bill_id)

    # -- 查询 -----------------------------------------------------------
    def list_bills(
        self, project_id: str, *, billing_period: str | None = None
    ) -> list[ElectricityBill]:
        self.ensure_initialized()
        return self._repository.list_bills(project_id, billing_period=billing_period)

    def get_bill(self, bill_id: str) -> ElectricityBill | None:
        self.ensure_initialized()
        return self._repository.get_bill(bill_id)

    def list_tou_items(self, bill_id: str) -> list[BillTimeOfUseItem]:
        self.ensure_initialized()
        return self._repository.list_tou_items(bill_id)

    def list_fee_items(self, bill_id: str) -> list[BillFeeItem]:
        self.ensure_initialized()
        return self._repository.list_fee_items(bill_id)

    def list_meter_points(self, bill_id: str) -> list[BillMeterPoint]:
        self.ensure_initialized()
        return self._repository.list_meter_points(bill_id)

    def list_batches(self, project_id: str) -> list[BillImportBatch]:
        self.ensure_initialized()
        return self._repository.list_batches(project_id)

    def summarize(self, project_id: str) -> BillSummary:
        """汇总项目的账单情况（计数与合计，不做经济性推断）。"""
        bills = self.list_bills(project_id)
        total_energy: Decimal | None = None
        total_amount: Decimal | None = None
        for bill in bills:
            if bill.total_energy_kwh is not None:
                total_energy = (total_energy or Decimal(0)) + bill.total_energy_kwh
            if bill.total_amount_yuan is not None:
                total_amount = (total_amount or Decimal(0)) + bill.total_amount_yuan
        return BillSummary(
            project_id=project_id,
            bill_count=len(bills),
            confirmed_count=sum(1 for bill in bills if bill.is_confirmed),
            pending_review_count=sum(
                1 for bill in bills if bill.review_status is not ReviewStatus.REVIEWED
            ),
            pending_confirmation_count=sum(1 for bill in bills if not bill.is_confirmed),
            periods=tuple(sorted({bill.billing_period for bill in bills if bill.billing_period})),
            total_energy_kwh=total_energy,
            total_amount_yuan=total_amount,
        )

    # -- 校验与确认 -----------------------------------------------------
    def validate_project_bills(self, project_id: str) -> ValidationReport:
        """对项目下**全部**账单重跑 13 类校验（只读）。"""
        self.ensure_initialized()
        bills = self.list_bills(project_id)
        tou: list[BillTimeOfUseItem] = []
        fees: list[BillFeeItem] = []
        points: list[BillMeterPoint] = []
        for bill in bills:
            tou.extend(self.list_tou_items(bill.bill_id))
            fees.extend(self.list_fee_items(bill.bill_id))
            points.extend(self.list_meter_points(bill.bill_id))
        return validate_bill_data(bills, tou_items=tou, fee_items=fees, meter_points=points)

    def confirm_bill(self, bill_id: str, *, confirmed_by: str | None = None) -> None:
        """人工确认账单。

        Raises:
            ValidationError: 账单不存在，或为样本数据（样本不得确认）。
        """
        self.ensure_initialized()
        try:
            self._repository.confirm_bill(bill_id, confirmed_by=confirmed_by)
        except ValueError as exc:
            raise ValidationError(str(exc), issues=()) from exc

    def set_review_status(self, bill_id: str, status: ReviewStatus | str) -> None:
        """更新复核状态。"""
        self.ensure_initialized()
        if isinstance(status, str):
            status = self._review_status(status)
        try:
            self._repository.update_review_status(bill_id, status)
        except ValueError as exc:
            raise ValidationError(str(exc), issues=()) from exc

    def usable_bills(self, project_id: str) -> list[ElectricityBill]:
        """返回**可用于正式测算**的账单。

        闸门规则（在领域层闸门之上再加一条）：

        1. 领域层 ``is_usable_for_calculation``：**已人工确认且非样本**；
        2. 追加：复核状态不是"存在疑问"。

        **为什么追加第 2 条**：领域层只检查"已确认 + 非样本"。
        但一张被明确标记为"存在疑问"的账单，说明已知数据有问题，
        即使被误确认也不应进入测算。反之，"待复核"只是"还没复核"，
        用户确认时即代表他已经人工核对过，因此**不**在本层拦截
        （否则会出现"必须先点复核才能确认、但复核又要先确认"的死循环）。

        这是"未确认不得用于正式测算"闸门的**唯一出口**，
        经济评价模块必须只接受本方法的返回值。
        """
        self.ensure_initialized()
        return [
            bill
            for bill in self.list_bills(project_id)
            if bill.is_usable_for_calculation
            and bill.review_status is not ReviewStatus.QUESTIONABLE
        ]

    def bills_with_unresolved_questions(self, project_id: str) -> list[ElectricityBill]:
        """返回复核状态为"存在疑问"的账单（阻断测算，需先解决）。"""
        self.ensure_initialized()
        return self.list_bills_by_review_status(project_id, ReviewStatus.QUESTIONABLE)
