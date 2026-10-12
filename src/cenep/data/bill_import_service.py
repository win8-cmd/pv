"""账单 Excel 导入服务（规格书第 31、32 节）。

职责：把"读表 → 转换 → 校验 → 重复识别 → 用户决策 → 保存"串成一条可测试的用例链。

**两阶段设计（关键）**：

1. :meth:`BillImportService.preview` —— **只读**。读取文件、转换、跑 13 类校验、
   识别重复，返回导入预览（有效/警告/无效记录数、错误明细、重复项）。
   此阶段**不写入任何数据**。
2. :meth:`BillImportService.apply` —— 依据用户在预览阶段做出的决策写入。
   用户可取消导入，或选择"仅导入有效记录"；重复记录可跳过 / 替换 / 保留。

**硬性约束**：

- **不得静默跳过错误行**：每条问题都带工作表、行号、字段与原因；
- **不得静默覆盖数据**：检测到重复必须交由用户决策；
- **样本表与校验表不参与导入**（由读取层保证）；
- **未提供的值保持 ``None``**，不补 0；
- 写入的账单初始为**待复核**，未确认前不得进入正式测算。

持久化通过 :class:`BillRepository` 协议注入：应用服务不写 SQL，
数据库实现（含 ``SCHEMA_VERSION = 2`` 迁移）在阶段 4 落地。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from cenep.data.bill_template_spec import (
    BUSINESS_SHEETS,
    SHEET_FEE_ITEMS,
    SHEET_METER_POINTS,
    SHEET_MONTHLY_SUMMARY,
    SHEET_TIME_OF_USE,
)
from cenep.data.bill_validation import CHECK_ITEMS, ValidationReport, validate_bill_data
from cenep.data.template_mapping import (
    ConversionIssue,
    ConversionResult,
    convert_fee_items,
    convert_meter_points,
    convert_monthly_summary,
    convert_time_of_use,
)
from cenep.data.template_reader import TemplateReadError, TemplateReadResult, read_template
from cenep.domain.bill_models import (
    BillFeeItem,
    BillImportBatch,
    BillMeterPoint,
    BillTimeOfUseItem,
    ElectricityBill,
    ImportOutcome,
    ReviewStatus,
)

__all__ = [
    "BillImportService",
    "BillRepository",
    "DuplicateCandidate",
    "ImportApplyResult",
    "ImportDecision",
    "ImportPreview",
    "InMemoryBillRepository",
    "RecordCounts",
]


class ImportDecision(str, Enum):
    """用户在预览阶段的选择。"""

    CANCEL = "取消导入"
    VALID_ONLY = "仅导入有效记录"
    IMPORT_ALL = "导入全部记录"


class DuplicateDecision(str, Enum):
    """重复账单的处理方式（规格书第 32 节）。"""

    SKIP = "跳过"
    REPLACE = "替换"
    KEEP = "保留"


@dataclass(frozen=True)
class DuplicateCandidate:
    """一条疑似重复记录。"""

    kind: str
    """重复类型：``文件`` / ``账单`` / ``计量口径``。"""
    key: str
    """用于比对的业务键。"""
    sheet_name: str
    row_number: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "sheet_name": self.sheet_name,
            "row_number": self.row_number,
            "message": self.message,
        }


@dataclass(frozen=True)
class RecordCounts:
    """导入预览的记录计数。"""

    total: int = 0
    valid: int = 0
    warning: int = 0
    invalid: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "valid": self.valid,
            "warning": self.warning,
            "invalid": self.invalid,
        }


@dataclass
class ImportPreview:
    """导入预览：**不包含任何写入**。"""

    file_name: str
    file_hash: str
    project_id: str
    template_version: str | None
    counts: RecordCounts
    conversion: ConversionResult
    validation: ValidationReport
    duplicates: tuple[DuplicateCandidate, ...] = ()
    warnings: tuple[str, ...] = ()
    row_sheet_names: tuple[str, ...] = ()

    @property
    def has_blocking_issues(self) -> bool:
        """是否存在阻断级问题（存在则不得导入）。"""
        return self.validation.has_blocking

    @property
    def has_duplicates(self) -> bool:
        return bool(self.duplicates)

    @property
    def blocking_issues(self):
        return self.validation.blocking_issues

    @property
    def issues_by_location(self) -> dict[tuple[str, int], list[str]]:
        """按 ``(工作表, 行号)`` 汇总问题，便于界面逐行展示。"""
        grouped: dict[tuple[str, int], list[str]] = {}
        for issue in self.conversion.issues:
            key = (issue.sheet_name, issue.row_number)
            grouped.setdefault(key, []).append(
                f"{issue.column_name}：{issue.message}"
            )
        for issue in self.validation.issues:
            if issue.result.value != "不通过":
                continue
            key = (issue.sheet_name or "", issue.row_number or 0)
            grouped.setdefault(key, []).append(
                f"{issue.check_code} {issue.check_item}：{issue.detail}"
            )
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "file_hash": self.file_hash,
            "project_id": self.project_id,
            "template_version": self.template_version,
            "counts": self.counts.to_dict(),
            "has_blocking_issues": self.has_blocking_issues,
            "has_duplicates": self.has_duplicates,
            "duplicates": [item.to_dict() for item in self.duplicates],
            "warnings": list(self.warnings),
            "conversion_issues": [item.to_dict() for item in self.conversion.issues],
            "validation": self.validation.to_dict(),
            "issue_locations": [
                {"sheet_name": sheet, "row_number": row, "messages": messages}
                for (sheet, row), messages in sorted(self.issues_by_location.items())
            ],
        }


@dataclass
class ImportApplyResult:
    """导入执行结果。"""

    batch: BillImportBatch
    preview: ImportPreview
    decision: ImportDecision
    duplicate_decision: DuplicateDecision | None = None
    imported_bills: tuple[ElectricityBill, ...] = ()
    imported_tou_items: tuple[BillTimeOfUseItem, ...] = ()
    imported_fee_items: tuple[BillFeeItem, ...] = ()
    imported_meter_points: tuple[BillMeterPoint, ...] = ()
    skipped_rows: tuple[tuple[str, int], ...] = ()
    replaced_bills: tuple[str, ...] = ()

    @property
    def imported_count(self) -> int:
        return len(self.imported_bills)

    def summary_lines(self) -> tuple[str, ...]:
        """可直接展示给用户的导入摘要。"""
        counts = self.preview.counts
        lines = [
            f"文件：{self.preview.file_name}",
            f"记录总数 {counts.total}：有效 {counts.valid}、警告 {counts.warning}、无效 {counts.invalid}",
            f"用户选择：{self.decision.value}",
            f"导入结果：{self.batch.outcome.value}，写入账单 {self.imported_count} 条",
            f"分时电量 {len(self.imported_tou_items)} 条、费用明细 {len(self.imported_fee_items)} 条、"
            f"计量点 {len(self.imported_meter_points)} 条",
        ]
        if self.duplicate_decision is not None:
            lines.append(f"重复处理：{self.duplicate_decision.value}")
        if self.skipped_rows:
            lines.append(f"跳过记录：{len(self.skipped_rows)} 条")
        if self.preview.warnings:
            lines.append("提示：" + "；".join(self.preview.warnings))
        return tuple(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch.to_dict(),
            "decision": self.decision.value,
            "duplicate_decision": (
                self.duplicate_decision.value if self.duplicate_decision else None
            ),
            "imported_count": self.imported_count,
            "skipped_rows": [list(item) for item in self.skipped_rows],
            "replaced_bills": list(self.replaced_bills),
            "summary": list(self.summary_lines()),
        }


class BillRepository(Protocol):
    """账单持久化协议。

    应用服务只依赖本协议，**不写 SQL**；SQLite 实现在阶段 4 提供
    （含 ``SCHEMA_VERSION = 2`` 迁移）。
    """

    def existing_file_hashes(self, project_id: str) -> set[str]:
        """返回该项目已导入过的文件摘要集合。"""
        ...

    def existing_bill_keys(self, project_id: str) -> set[str]:
        """返回该项目已有的账单业务键集合。"""
        ...

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
        """保存一个导入批次及其全部记录。"""
        ...


class InMemoryBillRepository:
    """内存实现：用于测试与离线预览，不落盘。"""

    def __init__(self) -> None:
        self.batches: list[BillImportBatch] = []
        self.bills: list[ElectricityBill] = []
        self.tou_items: list[BillTimeOfUseItem] = []
        self.fee_items: list[BillFeeItem] = []
        self.meter_points: list[BillMeterPoint] = []

    # -- 查询 -----------------------------------------------------------
    def existing_file_hashes(self, project_id: str) -> set[str]:
        return {
            batch.file_hash
            for batch in self.batches
            if batch.project_id == project_id and batch.file_hash
        }

    def existing_bill_keys(self, project_id: str) -> set[str]:
        return {
            bill_key(bill)
            for bill in self.bills
            if bill.project_id == project_id
        }

    # -- 写入 -----------------------------------------------------------
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
        replace_set = set(replace_bill_keys)
        if replace_set:
            self.bills = [
                bill
                for bill in self.bills
                if bill_key(bill) not in replace_set
            ]
        self.batches.append(batch)
        self.bills.extend(bills)
        self.tou_items.extend(tou_items)
        self.fee_items.extend(fee_items)
        self.meter_points.extend(meter_points)


def bill_key(bill: ElectricityBill) -> str:
    """账单业务键：项目 + 户号 + 账期（用于重复识别）。"""
    return "|".join(
        [
            bill.project_id or "",
            bill.account_number or "",
            bill.billing_period or "",
        ]
    )


def tou_key(item: BillTimeOfUseItem) -> str:
    """分时项业务键：项目 + 账期 + 计量口径 + 时段。"""
    period = item.period_name.value if item.period_name else ""
    return "|".join(
        [
            item.project_id or "",
            item.billing_period or "",
            item.metering_basis_id or "",
            item.basis.value,
            period,
            item.segment_start.isoformat() if item.segment_start else "",
        ]
    )


@dataclass
class _RowClassification:
    """逐行有效性判定结果。"""

    valid: set[tuple[str, int]] = field(default_factory=set)
    warning: set[tuple[str, int]] = field(default_factory=set)
    invalid: set[tuple[str, int]] = field(default_factory=set)


class BillImportService:
    """账单 Excel 导入用例。

    Args:
        repository: 持久化实现；默认使用内存实现（不落盘）。
    """

    def __init__(self, repository: BillRepository | None = None) -> None:
        self.repository: BillRepository = repository or InMemoryBillRepository()

    # ------------------------------------------------------------------
    # 预览（只读）
    # ------------------------------------------------------------------
    def preview(
        self,
        path: str | Path,
        *,
        project_id: str,
        price_unit_is_per_mwh: bool = False,
    ) -> ImportPreview:
        """读取文件并生成导入预览（**不写入任何数据**）。

        Args:
            path: Excel 文件路径。
            project_id: 目标项目主键。
            price_unit_is_per_mwh: 来源单价是否为元/MWh（需显式换算）。

        Raises:
            TemplateReadError: 文件结构性问题（缺表、缺必需字段、损坏等）。
        """
        read_result: TemplateReadResult = read_template(path)
        conversion = self._convert(read_result, project_id, price_unit_is_per_mwh)
        report = validate_bill_data(
            conversion.bills,
            tou_items=conversion.tou_items,
            fee_items=conversion.fee_items,
            meter_points=conversion.meter_points,
        )
        duplicates = self._detect_duplicates(read_result, conversion, project_id)
        counts = self._classify(conversion, report)

        return ImportPreview(
            file_name=read_result.file_name,
            file_hash=read_result.file_hash,
            project_id=project_id,
            template_version=read_result.template_version,
            counts=counts,
            conversion=conversion,
            validation=report,
            duplicates=duplicates,
            warnings=read_result.warnings,
            row_sheet_names=tuple(read_result.rows),
        )

    # ------------------------------------------------------------------
    # 应用（写入）
    # ------------------------------------------------------------------
    def apply(
        self,
        preview: ImportPreview,
        *,
        decision: ImportDecision,
        duplicate_decision: DuplicateDecision | None = None,
        imported_by: str | None = None,
        user_decision_note: str | None = None,
    ) -> ImportApplyResult:
        """依据用户决策执行导入。

        Args:
            preview: :meth:`preview` 的产出。
            decision: 取消 / 仅导入有效记录 / 导入全部记录。
            duplicate_decision: 检测到重复时的处理方式；存在重复时**必填**。
            imported_by: 操作人。
            user_decision_note: 追加说明。

        Raises:
            ValueError: 决策与预览状态不匹配（例如有阻断问题却要求全部导入、
                存在重复却未给出处理方式）。

        Note:
            取消导入时**不写入任何数据**，但仍返回结果对象并记录批次结果。
        """
        if decision is ImportDecision.CANCEL:
            return self._make_cancelled(preview, imported_by, user_decision_note)

        if preview.has_duplicates and duplicate_decision is None:
            raise ValueError("检测到疑似重复账单，必须明确选择：跳过 / 替换 / 保留")

        if decision is ImportDecision.IMPORT_ALL and preview.has_blocking_issues:
            raise ValueError(
                "存在阻断级校验问题，不得导入全部记录；"
                "请修正后重试，或选择“仅导入有效记录”"
            )

        classification = self._classify_rows(preview)
        skipped: set[tuple[str, int]] = set()

        if decision is ImportDecision.VALID_ONLY:
            skipped |= classification.warning
            skipped |= classification.invalid
        # IMPORT_ALL：仅跳过无效行（无效行无法构造出可用账单）
        skipped |= classification.invalid

        keep = self._filter_converted(preview, skipped)

        duplicate_keys = {
            item.key for item in preview.duplicates if item.kind == "账单"
        }
        duplicate_rows = {
            (item.sheet_name, item.row_number)
            for item in preview.duplicates
            if item.kind == "账单"
        }

        replace_keys: set[str] = set()
        if duplicate_decision is DuplicateDecision.SKIP:
            keep = self._drop_rows(keep, duplicate_rows)
            skipped |= duplicate_rows
        elif duplicate_decision is DuplicateDecision.REPLACE:
            replace_keys = set(duplicate_keys)
        # KEEP：不改动，按新记录写入

        batch = self._build_batch(
            preview,
            decision=decision,
            imported_by=imported_by,
            user_decision_note=user_decision_note,
            total=preview.counts.total,
            valid=preview.counts.valid,
            warning=preview.counts.warning,
            invalid=preview.counts.invalid,
            skipped=len(skipped),
            imported_bills=len(keep.bills),
            outcome=self._outcome(decision, preview),
        )

        self.repository.save_batch(
            batch,
            keep.bills,
            keep.tou_items,
            keep.fee_items,
            keep.meter_points,
            replace_bill_keys=replace_keys,
        )

        return ImportApplyResult(
            batch=batch,
            preview=preview,
            decision=decision,
            duplicate_decision=duplicate_decision,
            imported_bills=tuple(keep.bills),
            imported_tou_items=tuple(keep.tou_items),
            imported_fee_items=tuple(keep.fee_items),
            imported_meter_points=tuple(keep.meter_points),
            skipped_rows=tuple(sorted(skipped)),
            replaced_bills=tuple(sorted(replace_keys)),
        )

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _convert(
        self,
        read_result: TemplateReadResult,
        project_id: str,
        price_unit_is_per_mwh: bool,
    ) -> ConversionResult:
        """按工作表顺序把数据行转换为领域对象。"""
        conversion = convert_monthly_summary(
            read_result.business_rows(SHEET_MONTHLY_SUMMARY),
            project_id=project_id,
            price_unit_is_per_mwh=price_unit_is_per_mwh,
        )
        convert_time_of_use(
            read_result.business_rows(SHEET_TIME_OF_USE),
            project_id=project_id,
            result=conversion,
        )
        convert_fee_items(
            read_result.business_rows(SHEET_FEE_ITEMS),
            project_id=project_id,
            result=conversion,
        )
        convert_meter_points(
            read_result.business_rows(SHEET_METER_POINTS),
            project_id=project_id,
            result=conversion,
        )
        return conversion

    def _detect_duplicates(
        self,
        read_result: TemplateReadResult,
        conversion: ConversionResult,
        project_id: str,
    ) -> tuple[DuplicateCandidate, ...]:
        """识别重复：文件摘要、账单业务键、计量口径。"""
        found: list[DuplicateCandidate] = []

        existing_hashes = self.repository.existing_file_hashes(project_id)
        if read_result.file_hash in existing_hashes:
            found.append(
                DuplicateCandidate(
                    kind="文件",
                    key=read_result.file_hash[:16],
                    sheet_name=SHEET_MONTHLY_SUMMARY,
                    row_number=1,
                    message="该文件的摘要与已导入批次相同，可能重复导入同一文件",
                )
            )

        existing_keys = self.repository.existing_bill_keys(project_id)
        seen_in_file: set[str] = set()
        for index, bill in enumerate(conversion.bills):
            key = bill_key(bill)
            row_number = index + 2
            if key in existing_keys:
                found.append(
                    DuplicateCandidate(
                        kind="账单",
                        key=key,
                        sheet_name=SHEET_MONTHLY_SUMMARY,
                        row_number=row_number,
                        message=f"账单（户号 {bill.account_number or '未填'}、账期 {bill.billing_period or '未填'}）已存在",
                    )
                )
            if key in seen_in_file:
                found.append(
                    DuplicateCandidate(
                        kind="账单",
                        key=key,
                        sheet_name=SHEET_MONTHLY_SUMMARY,
                        row_number=row_number,
                        message="同一文件内出现重复账期，请确认是否有意为之",
                    )
                )
            seen_in_file.add(key)

        seen_tou: set[str] = set()
        for index, item in enumerate(conversion.tou_items):
            key = tou_key(item)
            if key in seen_tou:
                found.append(
                    DuplicateCandidate(
                        kind="计量口径",
                        key=key,
                        sheet_name=SHEET_TIME_OF_USE,
                        row_number=index + 2,
                        message="同一账期、计量口径与时段的电量重复出现",
                    )
                )
            seen_tou.add(key)

        return tuple(found)

    def _classify(self, conversion: ConversionResult, report: ValidationReport) -> RecordCounts:
        """统计有效 / 警告 / 无效记录数。"""
        total_rows = len(conversion.bills)
        problem_rows: set[int] = set()
        for issue in report.failed_issues:
            if issue.sheet_name == SHEET_MONTHLY_SUMMARY and issue.row_number:
                problem_rows.add(issue.row_number)

        invalid_rows = {
            row.row_number for row in conversion.issues if row.sheet_name == SHEET_MONTHLY_SUMMARY
        }
        blocking_rows = {
            issue.row_number
            for issue in report.blocking_issues
            if issue.sheet_name == SHEET_MONTHLY_SUMMARY and issue.row_number
        }
        invalid_rows |= blocking_rows
        warning_rows = problem_rows - invalid_rows

        total = max(total_rows, len(invalid_rows | warning_rows))
        valid = max(0, total - len(invalid_rows) - len(warning_rows))
        return RecordCounts(
            total=total,
            valid=valid,
            warning=len(warning_rows),
            invalid=len(invalid_rows),
        )

    def _classify_rows(self, preview: ImportPreview) -> _RowClassification:
        """按 ``(工作表, 行号)`` 判定每行的有效性。"""
        result = _RowClassification()
        for (sheet, row), messages in preview.issues_by_location.items():
            key = (sheet, row)
            if any("阻断" in message or "失败" in message for message in messages):
                result.invalid.add(key)
            else:
                result.warning.add(key)
        for issue in preview.conversion.issues:
            result.invalid.add((issue.sheet_name, issue.row_number))
        for issue in preview.validation.blocking_issues:
            result.invalid.add((issue.sheet_name or "", issue.row_number or 0))
        result.warning -= result.invalid
        return result

    def _filter_converted(
        self, preview: ImportPreview, skipped: set[tuple[str, int]]
    ) -> ConversionResult:
        """剔除被跳过行对应的账单主记录。

        其他三张表（分时、费用、计量点）按行号与账单主记录无一一对应关系，
        因此保持原样；其问题在预览阶段已逐条列出供人工处理。
        """
        skip_bill_rows = {row for sheet, row in skipped if sheet == SHEET_MONTHLY_SUMMARY}
        return ConversionResult(
            bills=[
                bill
                for index, bill in enumerate(preview.conversion.bills)
                if (index + 2) not in skip_bill_rows
            ],
            tou_items=list(preview.conversion.tou_items),
            fee_items=list(preview.conversion.fee_items),
            meter_points=list(preview.conversion.meter_points),
            issues=[],
        )

    def _drop_rows(
        self, conversion: ConversionResult, rows: set[tuple[str, int]]
    ) -> ConversionResult:
        """按 ``(工作表, 行号)`` 删除对应账单。"""
        drop_bills = {row for sheet, row in rows if sheet == SHEET_MONTHLY_SUMMARY}
        return ConversionResult(
            bills=[
                bill
                for index, bill in enumerate(conversion.bills)
                if (index + 2) not in drop_bills
            ],
            tou_items=list(conversion.tou_items),
            fee_items=list(conversion.fee_items),
            meter_points=list(conversion.meter_points),
            issues=[],
        )

    def _outcome(self, decision: ImportDecision, preview: ImportPreview) -> ImportOutcome:
        if preview.counts.invalid and decision is ImportDecision.VALID_ONLY:
            return ImportOutcome.PARTIAL
        return ImportOutcome.SUCCESS

    def _build_batch(
        self,
        preview: ImportPreview,
        *,
        decision: ImportDecision,
        imported_by: str | None,
        user_decision_note: str | None,
        total: int,
        valid: int,
        warning: int,
        invalid: int,
        skipped: int,
        imported_bills: int,
        outcome: ImportOutcome,
    ) -> BillImportBatch:
        return BillImportBatch(
            project_id=preview.project_id,
            file_name=preview.file_name,
            file_hash=preview.file_hash,
            template_version=preview.template_version,
            imported_by=imported_by,
            total_records=total,
            valid_records=imported_bills,
            warning_records=warning,
            invalid_records=invalid,
            skipped_records=skipped,
            outcome=outcome,
            message=user_decision_note,
            user_decision=decision.value,
        )

    def _make_cancelled(
        self,
        preview: ImportPreview,
        imported_by: str | None,
        note: str | None,
    ) -> ImportApplyResult:
        """取消导入：不写入任何数据。"""
        batch = self._build_batch(
            preview,
            decision=ImportDecision.CANCEL,
            imported_by=imported_by,
            user_decision_note=note,
            total=preview.counts.total,
            valid=0,
            warning=preview.counts.warning,
            invalid=preview.counts.invalid,
            skipped=preview.counts.total,
            imported_bills=0,
            outcome=ImportOutcome.REJECTED,
        )
        return ImportApplyResult(
            batch=batch,
            preview=preview,
            decision=ImportDecision.CANCEL,
            skipped_rows=tuple(sorted(preview.issues_by_location)),
        )


#: 校验项编号 → 名称（供界面按编号展示）
CHECK_ITEM_NAMES: dict[str, str] = dict(CHECK_ITEMS)

#: 业务工作表顺序（供界面与摘要展示）
BUSINESS_SHEET_ORDER: tuple[str, ...] = tuple(BUSINESS_SHEETS)

#: 导入后账单的初始复核状态
INITIAL_REVIEW_STATUS = ReviewStatus.PENDING
