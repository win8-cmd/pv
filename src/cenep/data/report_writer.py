"""把账单事实报告写成 Excel 工作簿（规格书第 41 节"报告接入"）。

**设计边界**：本模块只负责把 :class:`cenep.data.report_data.ReportBundle`
渲染成 xlsx —— **不做任何业务计算，也不产生经济性结论**。
所有数值都已由 ``report_data`` 以 ``Decimal`` 准备好，
本模块只做格式化与排版，**不碰浮点**。

工作簿结构（6 张工作表）：

1. `报告说明`   —— 报告边界、禁止事项、数据分类约定
2. `数据概览`   —— 项目、账期范围、合计、确认情况、校验结论、费用口径
3. `数据完整性` —— 逐项"满足/不满足/待核实"判断（不做评分）
4. `账单事实`   —— 逐张账单的原始字段
5. `费用明细`   —— 费用项与是否计入基准合计
6. `分时与计量点` —— 分时电量电价、计量点与 13 类校验明细

约定：金额/电量以**文本**写入（保留十进制精度，避免浮点误差）；
未提供的字段写"未提供"而不是 0；表头加粗并冻结首行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from cenep.data import report_data as rd

__all__ = [
    "REPORT_FILE_SUFFIX",
    "REPORT_SHEET_NAMES",
    "build_report_workbook",
    "default_report_name",
    "write_report",
]

#: 报告文件扩展名
REPORT_FILE_SUFFIX = ".xlsx"

#: 工作表名称（顺序即写入顺序）
REPORT_SHEET_NAMES: tuple[str, ...] = (
    "报告说明",
    "数据概览",
    "数据完整性",
    "账单事实",
    "费用明细",
    "分时与计量点",
)

_HEADER_FILL = PatternFill("solid", start_color="FFD9E1F2")
_BOLD = Font(bold=True)


def default_report_name(project_name: str, *, generated_on: str | None = None) -> str:
    """生成默认报告文件名（去掉不安全的路径字符）。"""
    safe = "".join(ch for ch in project_name if ch not in '\\/:*?"<>|').strip() or "项目"
    suffix = f"_{generated_on}" if generated_on else ""
    return f"CENEP_账单事实报告_{safe}{suffix}{REPORT_FILE_SUFFIX}"


def _write_header(sheet, headers: Sequence[str], *, freeze: bool = True) -> int:
    """写一行加粗表头，返回该行行号。"""
    sheet.append(list(headers))
    row = sheet.max_row
    for cell in sheet[row]:
        cell.font = _BOLD
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    if freeze and sheet.freeze_panes is None:
        sheet.freeze_panes = "A2"
    return row


def _autosize(sheet, *, min_width: int = 10, max_width: int = 34) -> None:
    """按内容估算列宽（中文按两个字符宽计）。"""
    for index, column_cells in enumerate(sheet.iter_cols(), start=1):
        longest = 0
        for cell in column_cells:
            if cell.value is None:
                continue
            text = str(cell.value)
            width = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
            longest = max(longest, width)
        sheet.column_dimensions[get_column_letter(index)].width = max(
            min_width, min(max_width, longest + 2)
        )


def _section_title(sheet, text: str) -> int:
    """写一个加粗小节标题，返回其行号。"""
    sheet.append([text])
    row = sheet.max_row
    sheet.cell(row=row, column=1).font = _BOLD
    return row


def _write_notes_sheet(sheet, bundle: rd.ReportBundle) -> None:
    """`报告说明`：报告边界、禁止事项与数据分类约定。"""
    sheet.append([rd.REPORT_TITLE])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append([])

    _write_header(sheet, ("报告基本信息", "内容"), freeze=False)
    info: tuple[tuple[str, str], ...] = (
        ("项目名称", bundle.project_name),
        ("项目编号", bundle.project_id),
        ("生成时间", bundle.generated_at),
        ("报告版本", rd.REPORT_VERSION),
        ("账单数量", str(bundle.bill_count)),
        (
            "账期范围",
            f"{bundle.periods[0]} ~ {bundle.periods[-1]}"
            if bundle.periods
            else rd.MISSING_TEXT,
        ),
        ("已人工确认", f"{bundle.confirmed_count} / {bundle.bill_count}"),
        ("可用于正式测算", f"{bundle.usable_count} / {bundle.bill_count}"),
    )
    for label, value in info:
        sheet.append([label, value])

    sheet.append([])
    _section_title(sheet, "本报告的边界（必读）")
    for note in bundle.notes:
        sheet.append([note])

    sheet.append([])
    _section_title(sheet, "数据分类约定")
    for label, detail in (
        ("原始事实", "账单原文录入的金额与电量，未做任何换算或修正"),
        ("计算值", "由原始事实按明确公式得出（如合计、电量差），报告中已注明口径"),
        ("缺失/待核实", f"未提供的字段统一显示为“{rd.MISSING_TEXT}”，系统不会当作 0"),
    ):
        sheet.append([label, detail])
    _autosize(sheet, max_width=100)


def _write_overview_sheet(sheet, bundle: rd.ReportBundle) -> None:
    """`数据概览`：合计、确认情况、校验结论与费用口径。"""
    _write_header(sheet, ("指标", "值", "说明"))
    rows: tuple[tuple[str, str, str], ...] = (
        ("账单数量", str(bundle.bill_count), "已录入的账单张数"),
        (
            "账期",
            "、".join(bundle.periods) if bundle.periods else rd.MISSING_TEXT,
            "按时间升序",
        ),
        (
            "合计总电量_kWh",
            rd.format_optional(bundle.total_energy_kwh),
            "各账单本期总电量之和；缺失的账单不参与求和",
        ),
        (
            "合计电费_元",
            rd.format_optional(bundle.total_amount_yuan),
            "各账单本期电费之和；缺失的账单不参与求和",
        ),
        (
            "已确认账单",
            f"{bundle.confirmed_count} / {bundle.bill_count}",
            "未确认不得用于正式测算",
        ),
        (
            "可用于正式测算",
            f"{bundle.usable_count} / {bundle.bill_count}",
            "已确认、非样本且无未决疑问",
        ),
        ("阻断级校验问题", str(bundle.blocking_count), "大于 0 时不得测算"),
        ("未通过的校验项", str(bundle.failed_check_count), "含警告级"),
    )
    for row in rows:
        sheet.append(list(row))

    sheet.append([])
    _section_title(sheet, "费用口径")
    _write_header(sheet, ("指标", "值", "说明"), freeze=False)
    fee_rows: tuple[tuple[str, str, str], ...] = (
        (
            "计入基准合计的费用小计_元",
            rd.format_optional(rd.fee_baseline_subtotal(bundle.fee_items)),
            "仅“未包含在其他费用中”且“纳入基准电费=是”的项；无参与项时显示未提供",
        ),
        (
            "已包含在其他费用中的合计_元",
            rd.format_optional(rd.internal_fee_subtotal(bundle.fee_items)),
            "这些项不得再次计入合计，否则会重复汇总",
        ),
    )
    for row in fee_rows:
        sheet.append(list(row))
    _autosize(sheet, max_width=60)


def _write_completeness_sheet(sheet, bundle: rd.ReportBundle) -> None:
    """`数据完整性`：逐项判断，不做评分、不做经济推断。"""
    _write_header(sheet, ("检查问题", "结论", "说明"))
    for question, verdict, detail in rd.completeness_findings(bundle):
        sheet.append([question, verdict, detail])
    _autosize(sheet, max_width=70)


def _write_table(sheet, columns: Sequence[tuple[str, Any]], items: Sequence[Any]) -> None:
    """按列定义写一张事实表。"""
    _write_header(sheet, [title for title, _ in columns])
    for item in items:
        sheet.append([str(getter(item)) for _title, getter in columns])
    _autosize(sheet)


def _write_validation_rows(sheet, bundle: rd.ReportBundle) -> None:
    """写 13 类校验明细。"""
    _write_header(
        sheet,
        ("校验项", "名称", "严重程度", "结果", "工作表", "行号", "字段", "说明"),
        freeze=False,
    )
    if bundle.validation is None:  # pragma: no cover - 组装时总会带上
        sheet.append([rd.MISSING_TEXT] * 8)
        return
    for issue in bundle.validation.issues:
        sheet.append(
            [
                issue.check_code,
                issue.check_item,
                issue.severity.value,
                issue.result.value,
                issue.sheet_name or "",
                "" if issue.row_number is None else str(issue.row_number),
                issue.column_name or "",
                issue.detail,
            ]
        )


def build_report_workbook(bundle: rd.ReportBundle) -> Workbook:
    """构建报告工作簿对象（未保存）。"""
    workbook = Workbook()
    workbook.active.title = REPORT_SHEET_NAMES[0]
    sheets = {
        name: workbook.active if index == 0 else workbook.create_sheet(name)
        for index, name in enumerate(REPORT_SHEET_NAMES)
    }

    _write_notes_sheet(sheets["报告说明"], bundle)
    _write_overview_sheet(sheets["数据概览"], bundle)
    _write_completeness_sheet(sheets["数据完整性"], bundle)
    _write_table(sheets["账单事实"], rd.BILL_FACT_COLUMNS, bundle.bills)
    _write_table(sheets["费用明细"], rd.FEE_FACT_COLUMNS, bundle.fee_items)

    # 第 6 张表依次放：分时电量电价、计量点、校验明细
    sheet = sheets["分时与计量点"]
    _write_table(sheet, rd.TOU_FACT_COLUMNS, bundle.tou_items)
    sheet.append([])
    _section_title(sheet, "计量点")
    _write_header(sheet, [title for title, _ in rd.METER_FACT_COLUMNS], freeze=False)
    for item in bundle.meter_points:
        sheet.append([str(getter(item)) for _title, getter in rd.METER_FACT_COLUMNS])
    sheet.append([])
    _section_title(sheet, "校验明细（13 类）")
    _write_validation_rows(sheet, bundle)
    _autosize(sheet, max_width=60)

    return workbook


def write_report(bundle: rd.ReportBundle, path: str | Path) -> Path:
    """把报告写入文件并返回实际路径。

    Args:
        bundle: :func:`cenep.data.report_data.build_report_bundle` 的产出。
        path: 目标路径；扩展名不是 ``.xlsx`` 时会自动修正；父目录自动创建。

    Returns:
        实际写入的路径。

    Raises:
        OSError: 写入失败。
        TypeError: 数值字段不是 ``Decimal``（防止浮点混入报告）。
    """
    target = Path(path)
    if target.suffix.lower() != REPORT_FILE_SUFFIX:
        target = target.with_suffix(REPORT_FILE_SUFFIX)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    workbook = build_report_workbook(bundle)
    try:
        workbook.save(target)
    finally:
        workbook.close()
    return target
