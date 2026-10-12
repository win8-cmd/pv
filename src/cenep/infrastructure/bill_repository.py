"""账单六类实体的 SQLite 持久化。

实现 :class:`cenep.data.bill_import_service.BillRepository` 协议，
并提供账单查询与状态更新。

设计要点（规格书第 30 节）：

- **金额与电量存 ``TEXT`` 十进制字符串**：写入时用 ``Decimal`` 的 ``str()``，
  读取时用 ``to_decimal()`` 还原为 ``Decimal``，**全程不经过 float**，
  从而避免第一阶段 ``REAL`` 列的十进制精度问题；
- **``None`` ↔ ``NULL`` 一一对应**：未提供的值写入 ``NULL`` 并读回 ``None``，
  **绝不写 0**；显式 ``Decimal(0)`` 存为 ``'0'`` 并读回 ``Decimal(0)``；
- **负值合法**：金额列允许负值（功率因数调整电费等）；
- 批次与其明细在**同一事务**内写入，任一失败则整体回滚；
- 全部 SQL 使用参数化占位符。

本模块只被应用层使用；界面层不得直接调用。
"""

from __future__ import annotations

import sqlite3

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from cenep.domain.bill_models import (
    Avoidability,
    BillConfirmationState,
    BaselineInclusion,
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
from cenep.domain.exceptions import PersistenceError
from cenep.infrastructure.database import Database

__all__ = ["BillRecordRepository", "SqliteBillRepository"]


# ---------------------------------------------------------------------------
# 值转换helper
# ---------------------------------------------------------------------------


def _to_text(value: Decimal | None) -> str | None:
    """``Decimal`` → 十进制字符串；``None`` → ``NULL``。"""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise TypeError(f"金额/电量必须为 Decimal，实际为 {type(value).__name__}")
    return str(value)


def _to_day(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _to_clock(value: time | None) -> str | None:
    return value.strftime("%H:%M:%S") if value is not None else None


def _enum(value: Any, default: Any = None) -> Any:
    """枚举 → 字符串（用于写库）。"""
    if value is None:
        return None
    return value.value if hasattr(value, "value") else value


def _dec(value: Any) -> Decimal | None:
    """库中的字符串/数值 → ``Decimal``；``None`` 保持 ``None``。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return to_decimal(value)


def _day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _clock(value: Any) -> time | None:
    if value is None or value == "":
        return None
    text = str(value)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"无法解析时间：{value!r}")


def _enum_from(enum_cls: Any, value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return enum_cls(value)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 仓储
# ---------------------------------------------------------------------------

_BILL_COLUMNS: tuple[str, ...] = (
    "bill_id", "project_id", "import_batch_id",
    "account_number", "customer_name", "supply_company", "supply_address",
    "electricity_category", "voltage_level", "market_attribute",
    "billing_period", "period_start", "period_end", "printed_on",
    "total_energy_kwh", "total_amount_yuan", "vat_invoice_amount_yuan",
    "displayed_average_price",
    "industrial_commercial_fee_yuan", "market_purchase_fee_yuan",
    "grid_loss_fee_yuan", "transmission_distribution_fee_yuan",
    "system_operation_fee_yuan", "government_fund_fee_yuan",
    "power_factor_adjustment_fee_yuan", "demand_charge_yuan",
    "market_operation_fee_yuan", "basic_charge_yuan",
    "contract_demand", "contract_demand_unit", "actual_demand",
    "actual_demand_unit", "demand_billing_mode", "power_factor",
    "source_file", "source_page", "review_status", "confirmation",
    "is_sample", "note",
)

#: 账单中属于 ``Decimal`` 的列（写入需转字符串，读取需转回 ``Decimal``）
_BILL_DECIMAL_FIELDS: tuple[str, ...] = (
    "total_energy_kwh", "total_amount_yuan", "vat_invoice_amount_yuan",
    "displayed_average_price",
    "industrial_commercial_fee_yuan", "market_purchase_fee_yuan",
    "grid_loss_fee_yuan", "transmission_distribution_fee_yuan",
    "system_operation_fee_yuan", "government_fund_fee_yuan",
    "power_factor_adjustment_fee_yuan", "demand_charge_yuan",
    "market_operation_fee_yuan", "basic_charge_yuan",
    "contract_demand", "actual_demand", "power_factor",
)

#: 账单中属于日期的列
_BILL_DATE_FIELDS: tuple[str, ...] = ("period_start", "period_end", "printed_on")


def _bill_row(bill: ElectricityBill) -> dict[str, Any]:
    """领域对象 → 数据库行。"""
    row: dict[str, Any] = {
        "bill_id": bill.bill_id,
        "project_id": bill.project_id,
        "import_batch_id": bill.import_batch_id,
        "account_number": bill.account_number,
        "customer_name": bill.customer_name,
        "supply_company": bill.supply_company,
        "supply_address": bill.supply_address,
        "electricity_category": bill.electricity_category,
        "voltage_level": bill.voltage_level,
        "market_attribute": bill.market_attribute,
        "billing_period": bill.billing_period,
        "printed_on": _to_day(bill.printed_on),
        "contract_demand_unit": bill.contract_demand_unit,
        "actual_demand_unit": bill.actual_demand_unit,
        "demand_billing_mode": bill.demand_billing_mode,
        "source_file": bill.source_file,
        "source_page": bill.source_page,
        "review_status": bill.review_status.value,
        "confirmation": bill.confirmation.value,
        "is_sample": 1 if bill.is_sample else 0,
        "note": bill.note,
    }
    for field in _BILL_DECIMAL_FIELDS:
        row[field] = _to_text(getattr(bill, field))
    for field in _BILL_DATE_FIELDS:
        row[field] = _to_day(getattr(bill, field))
    return row


def _bill_from_row(row: Mapping[str, Any]) -> ElectricityBill:
    """数据库行 → 领域对象。

    注意：``confirmation``（人工确认状态）必须一并读回，
    否则"已确认"的账单重开后会被误认为"待确认"，
    使未确认数据被当成已确认数据使用。
    """
    values: dict[str, Any] = {
        "bill_id": row["bill_id"],
        "project_id": row["project_id"],
        "import_batch_id": row["import_batch_id"],
        "account_number": row["account_number"],
        "customer_name": row["customer_name"],
        "supply_company": row["supply_company"],
        "supply_address": row["supply_address"],
        "electricity_category": row["electricity_category"],
        "voltage_level": row["voltage_level"],
        "market_attribute": row["market_attribute"],
        "billing_period": row["billing_period"],
        "contract_demand_unit": row["contract_demand_unit"],
        "actual_demand_unit": row["actual_demand_unit"],
        "demand_billing_mode": row["demand_billing_mode"],
        "source_file": row["source_file"],
        "source_page": row["source_page"],
        "review_status": _enum_from(ReviewStatus, row["review_status"], ReviewStatus.PENDING),
        "confirmation": _enum_from(
            BillConfirmationState, row["confirmation"], BillConfirmationState.PENDING
        ),
        "note": row["note"],
        "is_sample": bool(row["is_sample"]),
    }
    for field in _BILL_DECIMAL_FIELDS:
        values[field] = _dec(row[field])
    for field in _BILL_DATE_FIELDS:
        values[field] = _day(row[field])
    return ElectricityBill(**values)


class SqliteBillRepository:
    """基于 SQLite 的账单仓储（同时满足导入服务的 ``BillRepository`` 协议）。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------
    # 导入服务协议所需
    # ------------------------------------------------------------------
    def existing_file_hashes(self, project_id: str) -> set[str]:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT file_hash FROM bill_import_batch "
                "WHERE project_id = ? AND file_hash IS NOT NULL",
                (project_id,),
            ).fetchall()
        return {row["file_hash"] for row in rows}

    def existing_bill_keys(self, project_id: str) -> set[str]:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT project_id, IFNULL(account_number,'') AS acc, "
                "IFNULL(billing_period,'') AS period FROM bill WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        return {f"{row['project_id']}|{row['acc']}|{row['period']}" for row in rows}

    def save_batch(
        self,
        batch: BillImportBatch,
        bills: Sequence[ElectricityBill],
        tou_items: Sequence[BillTimeOfUseItem],
        fee_items: Sequence[BillFeeItem],
        meter_points: Sequence[BillMeterPoint],
        *,
        replace_bill_keys: Iterable[str] = (),
    ) -> None:
        """在**单个事务**内写入批次、账单与其全部明细。"""
        replace_set = set(replace_bill_keys)
        try:
            self._write_batch(
                batch, bills, tou_items, fee_items, meter_points, replace_set
            )
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(
                f"导入结果写入被数据库拒绝：{exc}",
                operation="save_batch",
            ) from exc

    def _write_batch(
        self,
        batch: BillImportBatch,
        bills: Sequence[ElectricityBill],
        tou_items: Sequence[BillTimeOfUseItem],
        fee_items: Sequence[BillFeeItem],
        meter_points: Sequence[BillMeterPoint],
        replace_set: set[str],
    ) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO bill_import_batch(batch_id, project_id, file_name, file_hash, "
                "template_version, imported_at, imported_by, total_records, valid_records, "
                "warning_records, invalid_records, skipped_records, outcome, user_decision, message) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    batch.batch_id,
                    batch.project_id,
                    batch.file_name,
                    batch.file_hash,
                    batch.template_version,
                    batch.imported_at,
                    batch.imported_by,
                    batch.total_records,
                    batch.valid_records,
                    batch.warning_records,
                    batch.invalid_records,
                    batch.skipped_records,
                    batch.outcome.value,
                    batch.user_decision,
                    batch.message,
                ),
            )

            if replace_set:
                for key in replace_set:
                    project_id, account, period = key.split("|", 2)
                    rows = conn.execute(
                        "SELECT bill_id FROM bill WHERE project_id = ? "
                        "AND IFNULL(account_number,'') = ? AND IFNULL(billing_period,'') = ?",
                        (project_id, account, period),
                    ).fetchall()
                    for row in rows:
                        # 明细表为 ON DELETE CASCADE，主表删除即级联清理
                        conn.execute("DELETE FROM bill WHERE bill_id = ?", (row["bill_id"],))

            for bill in bills:
                row = _bill_row(bill)
                row["import_batch_id"] = batch.batch_id
                columns = list(row)
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO bill({', '.join(columns)}) VALUES({placeholders})",
                    [row[column] for column in columns],
                )

            for item in tou_items:
                conn.execute(
                    "INSERT INTO bill_tou_item(tou_item_id, bill_id, project_id, billing_period, "
                    "metering_basis_id, basis, period_name, segment_start, segment_end, energy_kwh, "
                    "price_yuan_per_kwh, energy_amount_yuan, price_type_or_source, source_file, "
                    "source_page, review_status, note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        item.tou_item_id,
                        item.bill_id,
                        item.project_id,
                        item.billing_period,
                        item.metering_basis_id,
                        item.basis.value,
                        _enum(item.period_name),
                        _to_clock(item.segment_start),
                        _to_clock(item.segment_end),
                        _to_text(item.energy_kwh),
                        _to_text(item.price_yuan_per_kwh),
                        _to_text(item.energy_amount_yuan),
                        item.price_type_or_source,
                        item.source_file,
                        item.source_page,
                        item.review_status.value,
                        item.note,
                    ),
                )

            for fee in fee_items:
                conn.execute(
                    "INSERT INTO bill_fee_item(fee_item_id, bill_id, project_id, billing_period, "
                    "fee_category, fee_name, quantity, quantity_unit, unit_price, amount_yuan, "
                    "included_in_other, included_in_fee_name, avoidability, baseline_inclusion, "
                    "source_file, source_page, review_status, note) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fee.fee_item_id,
                        fee.bill_id,
                        fee.project_id,
                        fee.billing_period,
                        _enum(fee.fee_category),
                        fee.fee_name,
                        _to_text(fee.quantity),
                        fee.quantity_unit,
                        _to_text(fee.unit_price),
                        _to_text(fee.amount_yuan),
                        fee.included_in_other.value,
                        fee.included_in_fee_name,
                        fee.avoidability.value,
                        fee.baseline_inclusion.value,
                        fee.source_file,
                        fee.source_page,
                        fee.review_status.value,
                        fee.note,
                    ),
                )

            for point in meter_points:
                conn.execute(
                    "INSERT INTO bill_meter_point(meter_point_id, bill_id, project_id, billing_period, "
                    "point_code, point_name, point_type, main_sub_relation, ratio, energy_kwh, "
                    "included_in_total, allowed_in_rollup, source_file, source_page, review_status, note) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        point.meter_point_id,
                        point.bill_id,
                        point.project_id,
                        point.billing_period,
                        point.point_code,
                        point.point_name,
                        _enum(point.point_type),
                        point.main_sub_relation,
                        _to_text(point.ratio),
                        _to_text(point.energy_kwh),
                        point.included_in_total.value,
                        point.allowed_in_rollup.value,
                        point.source_file,
                        point.source_page,
                        point.review_status.value,
                        point.note,
                    ),
                )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_bills(
        self, project_id: str, *, billing_period: str | None = None
    ) -> list[ElectricityBill]:
        """按项目（可选账期）查询账单，按账期升序。"""
        sql = "SELECT * FROM bill WHERE project_id = ?"
        params: list[Any] = [project_id]
        if billing_period is not None:
            sql += " AND billing_period = ?"
            params.append(billing_period)
        sql += " ORDER BY IFNULL(billing_period,''), bill_id"
        with self.database.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_bill_from_row(row) for row in rows]

    def get_bill(self, bill_id: str) -> ElectricityBill | None:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM bill WHERE bill_id = ?", (bill_id,)).fetchone()
        return _bill_from_row(row) if row else None

    def list_tou_items(self, bill_id: str) -> list[BillTimeOfUseItem]:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bill_tou_item WHERE bill_id = ? ORDER BY rowid", (bill_id,)
            ).fetchall()
        return [
            BillTimeOfUseItem(
                tou_item_id=row["tou_item_id"],
                bill_id=row["bill_id"],
                project_id=row["project_id"],
                billing_period=row["billing_period"],
                metering_basis_id=row["metering_basis_id"],
                basis=_enum_from(MeteringBasis, row["basis"], MeteringBasis.PURCHASE),
                period_name=_enum_from(TimeOfUsePeriod, row["period_name"]),
                segment_start=_clock(row["segment_start"]),
                segment_end=_clock(row["segment_end"]),
                energy_kwh=_dec(row["energy_kwh"]),
                price_yuan_per_kwh=_dec(row["price_yuan_per_kwh"]),
                energy_amount_yuan=_dec(row["energy_amount_yuan"]),
                price_type_or_source=row["price_type_or_source"],
                source_file=row["source_file"],
                source_page=row["source_page"],
                review_status=_enum_from(ReviewStatus, row["review_status"], ReviewStatus.PENDING),
                note=row["note"],
            )
            for row in rows
        ]

    def list_fee_items(self, bill_id: str) -> list[BillFeeItem]:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bill_fee_item WHERE bill_id = ? ORDER BY rowid", (bill_id,)
            ).fetchall()
        return [
            BillFeeItem(
                fee_item_id=row["fee_item_id"],
                bill_id=row["bill_id"],
                project_id=row["project_id"],
                billing_period=row["billing_period"],
                fee_category=_enum_from(FeeCategory, row["fee_category"]),
                fee_name=row["fee_name"],
                quantity=_dec(row["quantity"]),
                quantity_unit=row["quantity_unit"],
                unit_price=_dec(row["unit_price"]),
                amount_yuan=_dec(row["amount_yuan"]),
                included_in_other=_enum_from(
                    IncludedInOtherFee, row["included_in_other"], IncludedInOtherFee.TO_VERIFY
                ),
                included_in_fee_name=row["included_in_fee_name"],
                avoidability=_enum_from(
                    Avoidability, row["avoidability"], Avoidability.TO_VERIFY
                ),
                baseline_inclusion=_enum_from(
                    BaselineInclusion, row["baseline_inclusion"], BaselineInclusion.TO_CONFIRM
                ),
                source_file=row["source_file"],
                source_page=row["source_page"],
                review_status=_enum_from(ReviewStatus, row["review_status"], ReviewStatus.PENDING),
                note=row["note"],
            )
            for row in rows
        ]

    def list_meter_points(self, bill_id: str) -> list[BillMeterPoint]:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bill_meter_point WHERE bill_id = ? ORDER BY rowid", (bill_id,)
            ).fetchall()
        return [
            BillMeterPoint(
                meter_point_id=row["meter_point_id"],
                bill_id=row["bill_id"],
                project_id=row["project_id"],
                billing_period=row["billing_period"],
                point_code=row["point_code"],
                point_name=row["point_name"],
                point_type=_enum_from(MeterPointType, row["point_type"]),
                main_sub_relation=row["main_sub_relation"],
                ratio=_dec(row["ratio"]),
                energy_kwh=_dec(row["energy_kwh"]),
                included_in_total=_enum_from(
                    YesNoUnknown, row["included_in_total"], YesNoUnknown.TO_VERIFY
                ),
                allowed_in_rollup=_enum_from(
                    YesNoUnknown, row["allowed_in_rollup"], YesNoUnknown.TO_VERIFY
                ),
                source_file=row["source_file"],
                source_page=row["source_page"],
                review_status=_enum_from(ReviewStatus, row["review_status"], ReviewStatus.PENDING),
                note=row["note"],
            )
            for row in rows
        ]

    def list_batches(self, project_id: str) -> list[BillImportBatch]:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM bill_import_batch WHERE project_id = ? ORDER BY imported_at, batch_id",
                (project_id,),
            ).fetchall()
        return [
            BillImportBatch(
                batch_id=row["batch_id"],
                project_id=row["project_id"],
                file_name=row["file_name"],
                file_hash=row["file_hash"],
                template_version=row["template_version"],
                imported_at=row["imported_at"],
                imported_by=row["imported_by"],
                total_records=row["total_records"],
                valid_records=row["valid_records"],
                warning_records=row["warning_records"],
                invalid_records=row["invalid_records"],
                skipped_records=row["skipped_records"],
                outcome=_enum_from(ImportOutcome, row["outcome"], ImportOutcome.SUCCESS),
                message=row["message"],
                user_decision=row["user_decision"],
            )
            for row in rows
        ]

    def count_bills(self, project_id: str) -> int:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM bill WHERE project_id = ?", (project_id,)
            ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # 状态更新与人工确认
    # ------------------------------------------------------------------
    def update_review_status(self, bill_id: str, status: ReviewStatus) -> None:
        self._require_bill(bill_id)
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE bill SET review_status = ? WHERE bill_id = ?",
                (status.value, bill_id),
            )

    def confirm_bill(self, bill_id: str, *, confirmed_by: str | None = None) -> None:
        """人工确认账单。

        Raises:
            ValueError: 账单不存在，或属于样本数据（**样本不得确认**）。
        """
        bill = self._require_bill(bill_id)
        if bill.is_sample:
            raise ValueError("样本数据不得确认，也不得用于正式测算")
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE bill SET confirmation = '已确认', confirmed_at = datetime('now'), "
                "confirmed_by = ? WHERE bill_id = ?",
                (confirmed_by, bill_id),
            )

    def _require_bill(self, bill_id: str) -> ElectricityBill:
        bill = self.get_bill(bill_id)
        if bill is None:
            raise ValueError(f"账单不存在：{bill_id}")
        return bill


#: 语义化别名（供阅读者明确实现是 SQLite 版）
BillRecordRepository = SqliteBillRepository
