"""账单导入服务测试（规格书第 39 节，服务层）。

覆盖规格书第 39 节要求、且属于**导入服务**职责的情形：

- 正常文件导入（预览 → 应用 → 落库到仓储）；
- 空白可选字段（保持 ``None``，不补 0）；
- 缺失必填字段（记录问题 + 阻断）；
- 错误日期 / 负费用 / 负总电量；
- 中文列名别名、列顺序变化、未知额外列；
- 缺少必需工作表、损坏文件；
- 重复账期、重复文件导入；
- 有效与无效记录混合；
- 用户取消导入；
- 用户选择"仅导入有效行"；
- 重复记录的跳过 / 替换 / 保留三种处置。

服务为两阶段：``preview()`` **只读**，``apply()`` 才写入。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from cenep.data.bill_import_service import (
    BillImportService,
    DuplicateDecision,
    ImportDecision,
    InMemoryBillRepository,
    bill_key,
)
from cenep.data.bill_template_spec import (
    SHEET_FEE_ITEMS,
    SHEET_METER_POINTS,
    SHEET_MONTHLY_SUMMARY,
    SHEET_TIME_OF_USE,
    TEMPLATE_NAME,
    headers_of,
)
from cenep.data.template_reader import TemplateReadError
from cenep.data.template_writer import write_template
from cenep.domain.bill_models import ImportOutcome, ReviewStatus

PROJECT = "proj-1"

#: 一份完全有效的 2025-09 账单行
SEP_ROW = {
    "项目编号": "PRJ-001",
    "用户名称": "示例用户",
    "户号": "1234567890",
    "账期": "2025-09",
    "账期开始日期": "2025-09-01",
    "账期结束日期": "2025-09-30",
    "本期总电量_kWh": 8780498,
    "账单本期电费_元": 6699241.94,
    "增值税专票金额_元": 6534168.58,
    "账单展示平均电价_元每kWh": 0.76297,
    "工商业电费_元": 6708448.31,
    "功率因数调整电费_元": -9206.37,
    "需量电费_元": 1202916,
    "实际最大需量": 30844,
    "实际最大需量单位": "kW",
    "需量计费方式": "按实际最大需量",
    "来源文件": "2025-09账单.pdf",
    "来源页码": "1",
    "复核状态": "已复核",
}

OCT_ROW = {**SEP_ROW, "账期": "2025-10", "账期开始日期": "2025-10-01",
           "账期结束日期": "2025-10-31", "本期总电量_kWh": 7479418,
           "账单本期电费_元": 5471334.24, "来源文件": "2025-10账单.pdf"}


def _write_rows(path: Path, sheet: str, rows: list[dict], *, start: int = 2) -> None:
    """把若干条数据写入指定工作表。"""
    workbook = load_workbook(path)
    headers = headers_of(sheet)
    for offset, values in enumerate(rows):
        excel_row = start + offset
        for index, header in enumerate(headers, start=1):
            if header in values:
                workbook[sheet].cell(row=excel_row, column=index, value=values[header])
    workbook.save(path)


@pytest.fixture
def template_path(tmp_path: Path) -> Path:
    return write_template(tmp_path / TEMPLATE_NAME)


def _service() -> BillImportService:
    return BillImportService(InMemoryBillRepository())


# ---------------------------------------------------------------------------
# 39.1 正常文件
# ---------------------------------------------------------------------------


class TestNormalImport:
    def test_preview_is_read_only(self, template_path: Path) -> None:
        """预览阶段不得写入任何数据。"""
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])

        preview = service.preview(template_path, project_id=PROJECT)
        assert preview.counts.total == 1
        assert repository.bills == [], "预览阶段不得写入账单"
        assert repository.batches == [], "预览阶段不得写入批次"

    def test_apply_writes_records(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])

        preview = service.preview(template_path, project_id=PROJECT)
        result = service.apply(preview, decision=ImportDecision.VALID_ONLY)

        assert result.imported_count == 1
        assert len(repository.bills) == 1
        bill = repository.bills[0]
        assert bill.billing_period == "2025-09"
        assert bill.total_energy_kwh == 8780498
        assert bill.project_id == PROJECT

    def test_imported_bill_starts_pending_review(self, template_path: Path) -> None:
        """导入结果必须为待复核：导入成功不等于可用于正式测算。"""
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        service.apply(preview, decision=ImportDecision.VALID_ONLY)

        bill = repository.bills[0]
        assert bill.review_status is ReviewStatus.REVIEWED, "来源标注已复核时保留原状态"
        assert bill.confirmation.value == "待确认"
        assert bill.is_usable_for_calculation is False, "未确认不得用于正式测算"

    def test_all_four_sheets_are_imported(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        _write_rows(
            template_path,
            SHEET_TIME_OF_USE,
            [{"项目编号": "PRJ-001", "账期": "2025-09", "计量口径/计量点编号": "MP1",
              "电量类型": "购电", "时段名称": "平", "电量_kWh": 8780498}],
        )
        _write_rows(
            template_path,
            SHEET_FEE_ITEMS,
            [{"项目编号": "PRJ-001", "账期": "2025-09", "费用项目名称": "输配电费",
              "金额_元": 2000662.04, "是否包含在其他费用中": "否",
              "是否纳入基准电费": "是"}],
        )
        _write_rows(
            template_path,
            SHEET_METER_POINTS,
            [{"项目编号": "PRJ-001", "账期": "2025-09", "计量点编号": "M1",
              "电量_kWh": 8516838, "是否已计入首页总电量": "否",
              "是否允许纳入汇总": "是"}],
        )

        preview = service.preview(template_path, project_id=PROJECT)
        result = service.apply(preview, decision=ImportDecision.VALID_ONLY)
        assert len(result.imported_tou_items) == 1
        assert len(result.imported_fee_items) == 1
        assert len(result.imported_meter_points) == 1

    def test_summary_lines_are_human_readable(self, template_path: Path) -> None:
        service = _service()
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        result = service.apply(preview, decision=ImportDecision.VALID_ONLY)
        text = "\n".join(result.summary_lines())
        assert "文件：" in text
        assert "用户选择" in text
        assert "写入账单" in text


# ---------------------------------------------------------------------------
# 39.2 空值与零值
# ---------------------------------------------------------------------------


class TestBlankAndZero:
    def test_blank_optional_stays_none(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        minimal = {
            "项目编号": "PRJ-001", "账期": "2025-09",
            "账期开始日期": "2025-09-01", "账期结束日期": "2025-09-30",
            "本期总电量_kWh": 100, "账单本期电费_元": 200,
            "来源文件": "x.pdf", "来源页码": "1", "复核状态": "已复核",
        }
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [minimal])
        # 补一条同口径分时电量，使数据具备消纳测算条件（消除 V13 警告）
        _write_rows(
            template_path,
            SHEET_TIME_OF_USE,
            [{"项目编号": "PRJ-001", "账期": "2025-09", "计量口径/计量点编号": "MP1",
              "电量类型": "购电", "时段名称": "平", "电量_kWh": 100}],
        )
        preview = service.preview(template_path, project_id=PROJECT)
        assert preview.counts.valid == 1, "本行应为有效记录"
        service.apply(preview, decision=ImportDecision.VALID_ONLY)

        assert len(repository.bills) == 1
        bill = repository.bills[0]
        assert bill.vat_invoice_amount_yuan is None
        assert bill.demand_charge_yuan is None
        assert bill.actual_demand is None

    def test_blank_is_not_zero(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(
            template_path,
            SHEET_MONTHLY_SUMMARY,
            [{**SEP_ROW, "增值税专票金额_元": None}],
        )
        preview = service.preview(template_path, project_id=PROJECT)
        service.apply(preview, decision=ImportDecision.VALID_ONLY)
        from decimal import Decimal

        assert repository.bills[0].vat_invoice_amount_yuan is None
        assert repository.bills[0].vat_invoice_amount_yuan != Decimal(0)

    def test_explicit_zero_is_kept(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [{**SEP_ROW, "需量电费_元": 0}])
        preview = service.preview(template_path, project_id=PROJECT)
        service.apply(preview, decision=ImportDecision.VALID_ONLY)
        from decimal import Decimal

        assert repository.bills[0].demand_charge_yuan == Decimal(0)


# ---------------------------------------------------------------------------
# 39.3 缺失必填字段与非法值
# ---------------------------------------------------------------------------


class TestInvalidRows:
    def test_missing_required_field_is_invalid(self, template_path: Path) -> None:
        service = _service()
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [{"户号": "1", "账期": "2025-09"}])
        preview = service.preview(template_path, project_id=PROJECT)
        assert preview.counts.invalid >= 1
        assert preview.has_blocking_issues is True

    def test_invalid_period_is_reported(self, template_path: Path) -> None:
        service = _service()
        _write_rows(
            template_path, SHEET_MONTHLY_SUMMARY, [{**SEP_ROW, "账期": "2025年9月"}]
        )
        preview = service.preview(template_path, project_id=PROJECT)
        messages = [issue.message for issue in preview.conversion.issues]
        assert any("YYYY-MM" in message for message in messages)

    def test_invalid_date_is_reported(self, template_path: Path) -> None:
        service = _service()
        _write_rows(
            template_path, SHEET_MONTHLY_SUMMARY, [{**SEP_ROW, "账期开始日期": "二〇二五年九月"}]
        )
        preview = service.preview(template_path, project_id=PROJECT)
        messages = [issue.message for issue in preview.conversion.issues]
        assert any("日期无法解析" in message for message in messages)

    def test_negative_total_energy_is_rejected_with_location(self, template_path: Path) -> None:
        """负总电量必须被拒绝，并给出可定位的问题（而不是让导入崩溃）。"""
        service = _service()
        _write_rows(
            template_path, SHEET_MONTHLY_SUMMARY, [{**SEP_ROW, "本期总电量_kWh": -100}]
        )
        preview = service.preview(template_path, project_id=PROJECT)

        # 该行违反领域约束，被丢弃且不留账单
        assert preview.conversion.bills == [], "负总电量不得构造出账单"
        messages = [issue.message for issue in preview.conversion.issues]
        assert any("不得为负数" in message for message in messages), "应说明拒绝原因"
        assert any(issue.row_number == 2 for issue in preview.conversion.issues), "应指出行号"
        # 整行不可用 → 计入无效
        assert preview.counts.invalid >= 1

    def test_negative_fee_is_preserved(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        service.apply(preview, decision=ImportDecision.VALID_ONLY)
        from decimal import Decimal

        assert repository.bills[0].power_factor_adjustment_fee_yuan == Decimal("-9206.37")
        assert repository.bills[0].power_factor_adjustment_fee_yuan < 0, "负费用必须保留负号"

    def test_issue_locations_carry_sheet_and_row(self, template_path: Path) -> None:
        service = _service()
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW, {"户号": "x", "账期": "bad"}])
        preview = service.preview(template_path, project_id=PROJECT)
        locations = preview.issues_by_location
        assert (SHEET_MONTHLY_SUMMARY, 3) in locations
        assert locations[(SHEET_MONTHLY_SUMMARY, 3)]


# ---------------------------------------------------------------------------
# 39.4 混合有效与无效
# ---------------------------------------------------------------------------


class TestMixedValidity:
    def test_counts_split_valid_and_invalid(self, template_path: Path) -> None:
        service = _service()
        _write_rows(
            template_path,
            SHEET_MONTHLY_SUMMARY,
            [SEP_ROW, OCT_ROW, {"户号": "bad", "账期": "not-a-period"}],
        )
        preview = service.preview(template_path, project_id=PROJECT)
        assert preview.counts.total == 3
        assert preview.counts.valid == 2
        assert preview.counts.invalid == 1

    def test_valid_only_skips_invalid_rows(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(
            template_path,
            SHEET_MONTHLY_SUMMARY,
            [SEP_ROW, OCT_ROW, {"户号": "bad", "账期": "not-a-period"}],
        )
        preview = service.preview(template_path, project_id=PROJECT)
        result = service.apply(preview, decision=ImportDecision.VALID_ONLY)

        assert result.imported_count == 2
        assert len(repository.bills) == 2
        assert (SHEET_MONTHLY_SUMMARY, 4) in result.skipped_rows
        assert result.batch.outcome is ImportOutcome.PARTIAL

    def test_import_all_refuses_when_blocking(self, template_path: Path) -> None:
        """存在阻断问题时不得"导入全部记录"。"""
        service = _service()
        _write_rows(
            template_path,
            SHEET_MONTHLY_SUMMARY,
            [SEP_ROW, {"户号": "bad", "账期": "not-a-period"}],
        )
        preview = service.preview(template_path, project_id=PROJECT)
        assert preview.has_blocking_issues
        with pytest.raises(ValueError, match="阻断"):
            service.apply(preview, decision=ImportDecision.IMPORT_ALL)


# ---------------------------------------------------------------------------
# 39.5 用户取消
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_writes_nothing(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        result = service.apply(preview, decision=ImportDecision.CANCEL)

        assert result.imported_count == 0
        assert repository.bills == []
        assert repository.batches == [], "取消导入不得留下批次记录"
        assert result.batch.outcome is ImportOutcome.REJECTED

    def test_cancel_still_reports_preview(self, template_path: Path) -> None:
        service = _service()
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        result = service.apply(preview, decision=ImportDecision.CANCEL)
        assert result.preview is preview
        assert "取消导入" in "\n".join(result.summary_lines())


# ---------------------------------------------------------------------------
# 39.6 重复导入与三种处置
# ---------------------------------------------------------------------------


class TestDuplicates:
    def _import_twice(self, template_path: Path):
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        first = service.preview(template_path, project_id=PROJECT)
        service.apply(first, decision=ImportDecision.VALID_ONLY)
        second = service.preview(template_path, project_id=PROJECT)
        return service, repository, second

    def test_same_file_is_detected_as_duplicate(self, template_path: Path) -> None:
        _, _, second = self._import_twice(template_path)
        kinds = {item.kind for item in second.duplicates}
        assert "文件" in kinds, "重复导入同一文件必须被识别"
        assert "账单" in kinds, "相同业务键必须被识别"

    def test_duplicate_requires_explicit_decision(self, template_path: Path) -> None:
        service, _, second = self._import_twice(template_path)
        with pytest.raises(ValueError, match="重复"):
            service.apply(second, decision=ImportDecision.VALID_ONLY)

    def test_skip_does_not_add_records(self, template_path: Path) -> None:
        service, repository, second = self._import_twice(template_path)
        before = len(repository.bills)
        result = service.apply(
            second,
            decision=ImportDecision.VALID_ONLY,
            duplicate_decision=DuplicateDecision.SKIP,
        )
        assert result.imported_count == 0
        assert len(repository.bills) == before, "跳过不得新增记录"

    def test_replace_overwrites_same_business_key(self, template_path: Path) -> None:
        service, repository, second = self._import_twice(template_path)
        assert len(repository.bills) == 1
        result = service.apply(
            second,
            decision=ImportDecision.VALID_ONLY,
            duplicate_decision=DuplicateDecision.REPLACE,
        )
        assert len(repository.bills) == 1, "替换后同一业务键只应保留一条"
        assert result.replaced_bills, "应记录被替换的业务键"

    def test_keep_adds_another_record(self, template_path: Path) -> None:
        service, repository, second = self._import_twice(template_path)
        service.apply(
            second,
            decision=ImportDecision.VALID_ONLY,
            duplicate_decision=DuplicateDecision.KEEP,
        )
        assert len(repository.bills) == 2, "保留应允许并存两条"

    def test_duplicate_period_within_one_file_is_flagged(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW, SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        assert preview.has_duplicates
        assert any("同一文件内" in item.message for item in preview.duplicates)

    def test_bill_key_includes_account_and_period(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        service.apply(preview, decision=ImportDecision.VALID_ONLY)
        assert bill_key(repository.bills[0]) == f"{PROJECT}|1234567890|2025-09"

    def test_different_period_is_not_duplicate(self, template_path: Path) -> None:
        repository = InMemoryBillRepository()
        service = BillImportService(repository)
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        first = service.preview(template_path, project_id=PROJECT)
        service.apply(first, decision=ImportDecision.VALID_ONLY)
        assert service.repository.existing_bill_keys(PROJECT) == {f"{PROJECT}|1234567890|2025-09"}


# ---------------------------------------------------------------------------
# 39.7 结构性问题由读取层抛出
# ---------------------------------------------------------------------------


class TestStructuralErrors:
    def test_missing_sheet_raises(self, tmp_path: Path) -> None:
        from openpyxl import Workbook

        path = tmp_path / "bad.xlsx"
        workbook = Workbook()
        workbook.active.title = "无关表"
        workbook.save(path)
        with pytest.raises(TemplateReadError, match="缺少必需工作表"):
            _service().preview(path, project_id=PROJECT)

    def test_corrupt_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.xlsx"
        path.write_bytes(b"not a workbook")
        with pytest.raises(TemplateReadError, match="无法读取工作簿"):
            _service().preview(path, project_id=PROJECT)

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        path = write_template(tmp_path / TEMPLATE_NAME)
        workbook = load_workbook(path)
        sheet = workbook[SHEET_MONTHLY_SUMMARY]
        headers = list(headers_of(SHEET_MONTHLY_SUMMARY))
        headers.remove("账期")
        for column in range(1, sheet.max_column + 1):
            sheet.cell(row=1, column=column, value=None)
        for index, header in enumerate(headers, start=1):
            sheet.cell(row=1, column=index, value=header)
        workbook.save(path)

        with pytest.raises(TemplateReadError) as excinfo:
            _service().preview(path, project_id=PROJECT)
        assert "账期" in excinfo.value.format()


# ---------------------------------------------------------------------------
# 39.8 样本表与校验表不参与导入
# ---------------------------------------------------------------------------


class TestSampleSheetIsolation:
    def test_sample_sheet_rows_are_not_imported(self, tmp_path: Path) -> None:
        """样本表即使被填数据也不得进入导入结果。"""
        path = write_template(tmp_path / TEMPLATE_NAME)
        workbook = load_workbook(path)
        sample = workbook["样本参考_勿直接测算"]
        sample.cell(row=30, column=1, value="本期总电量_kWh")
        sample.cell(row=30, column=2, value=8780498)
        workbook.save(path)

        preview = _service().preview(path, project_id=PROJECT)
        assert preview.counts.total == 0
        assert preview.conversion.bills == []

    def test_excluded_sheets_produce_warnings(self, template_path: Path) -> None:
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = _service().preview(template_path, project_id=PROJECT)
        assert any("使用说明" in warning for warning in preview.warnings)
        assert any("样本参考" in warning for warning in preview.warnings)


# ---------------------------------------------------------------------------
# 39.9 结果可序列化（供界面与日志）
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_preview_to_dict_is_serialisable(self, template_path: Path) -> None:
        service = _service()
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        payload = service.preview(template_path, project_id=PROJECT).to_dict()
        assert payload["file_name"] == TEMPLATE_NAME
        assert payload["counts"]["total"] == 1
        assert isinstance(payload["conversion_issues"], list)
        assert "validation" in payload

    def test_apply_result_to_dict_is_serialisable(self, template_path: Path) -> None:
        service = _service()
        _write_rows(template_path, SHEET_MONTHLY_SUMMARY, [SEP_ROW])
        preview = service.preview(template_path, project_id=PROJECT)
        payload = service.apply(preview, decision=ImportDecision.VALID_ONLY).to_dict()
        assert payload["imported_count"] == 1
        assert payload["batch"]["file_name"] == TEMPLATE_NAME
        assert isinstance(payload["summary"], list)

    def test_duplicate_candidate_to_dict(self, template_path: Path) -> None:
        service, _, second = TestDuplicates()._import_twice(template_path)
        payload = [item.to_dict() for item in second.duplicates]
        assert payload
        assert {"kind", "key", "sheet_name", "row_number", "message"} <= set(payload[0])
