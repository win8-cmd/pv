"""生成电费账单标准 Excel 模板。

依据 `cenep.data.bill_template_spec` 的结构规范写出 `.xlsx` 文件。

模板特性（规格书第 19–21 节）：

- **不依赖 Excel 宏**（纯数据校验，不使用 VBA/宏）；
- 第一行固定为字段标题，业务表不合并表头，首行冻结并启用筛选；
- 枚举字段提供**下拉选项**（数据验证序列）；
- 关键字段通过单元格批注提供说明；
- 日期/金额等字段设置显示格式；
- `使用说明` 与 `数据校验` 预置内容；
- `样本参考_勿直接测算` 表带**显著警示**且导入器默认忽略。

本模块是唯一允许直接使用 `openpyxl` 的模板相关代码。
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from cenep.data.bill_template_spec import (
    ALL_SHEETS,
    SAMPLE_TEMPLATE_ROWS,
    SAMPLE_MARKER_TEXT,
    SHEET_DATA_VALIDATION,
    SHEET_INSTRUCTIONS,
    SHEET_SAMPLE_REFERENCE,
    TEMPLATE_NAME,
    TEMPLATE_VERSION,
    ColumnSpec,
    SheetSpec,
    get_sheet,
    instruction_rows,
    validation_check_items,
)

__all__ = [
    "TEMPLATE_NAME",
    "build_template",
    "default_template_path",
    "write_template",
]

#: 表头样式
_HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
_HEADER_FONT = Font(bold=True)
_REQUIRED_FONT = Font(bold=True, color="9C0006")
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_SAMPLE_FILL = PatternFill("solid", fgColor="FFF2CC")
_SAMPLE_FONT = Font(bold=True, color="9C5700")

#: 下拉选项最大长度（Excel 数据验证序列上限 255 字符）
_MAX_CHOICES_LENGTH = 255

#: 列宽上限与下限
_MIN_WIDTH = 10
_MAX_WIDTH = 34

#: 各工作表写入的数据行上限（数据验证与日期格式覆盖范围）
_MAX_DATA_ROWS = 200

#: 防御性上限：避免异常输入把模板撑成超大文件
_MAX_ROWS_HARD_LIMIT = 5000

def _write_header(sheet: Worksheet, spec: SheetSpec) -> None:
    """写首行字段标题，并按必填/说明设置样式与批注。"""
    for index, column in enumerate(spec.columns, start=1):
        cell = sheet.cell(row=1, column=index, value=column.header)
        cell.fill = _HEADER_FILL
        cell.font = _REQUIRED_FONT if column.required else _HEADER_FONT
        cell.border = _BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        note_parts = []
        if column.unit:
            note_parts.append(f"单位：{column.unit}")
        note_parts.append("必填" if column.required else "可选")
        if column.description:
            note_parts.append(column.description)
        if column.choices:
            note_parts.append("可选值：" + " / ".join(column.choices))
        comment = Comment("\n".join(note_parts), "CENEP")
        comment.width = 320
        comment.height = 150
        cell.comment = comment


def _apply_column_layout(sheet: Worksheet, spec: SheetSpec) -> None:
    """设置列宽、冻结首行、启用筛选。"""
    for index, column in enumerate(spec.columns, start=1):
        letter = get_column_letter(index)
        width = max(len(column.header) * 2 + 2, _MIN_WIDTH)
        sheet.column_dimensions[letter].width = min(width, _MAX_WIDTH)

    if spec.freeze_header:
        sheet.freeze_panes = "A2"
    if spec.enable_filter and spec.columns:
        last_letter = get_column_letter(len(spec.columns))
        sheet.auto_filter.ref = f"A1:{last_letter}1"


def _apply_data_validation(sheet: Worksheet, spec: SheetSpec) -> None:
    """为枚举字段添加下拉选项（数据验证序列）。"""
    for index, column in enumerate(spec.columns, start=1):
        if not column.choices:
            continue
        joined = ",".join(column.choices)
        if len(joined) > _MAX_CHOICES_LENGTH:  # pragma: no cover - 防御性分支
            joined = ",".join(column.choices)[:_MAX_CHOICES_LENGTH]
        validation = DataValidation(
            type="list",
            formula1=f'"{joined}"',
            allow_blank=True,
            showDropDown=False,  # 注意：openpyxl 中 False = 显示下拉箭头
        )
        validation.error = f"请从下拉列表中选择：{' / '.join(column.choices)}"
        validation.errorTitle = "取值不在允许范围内"
        validation.prompt = f"允许值：{' / '.join(column.choices)}"
        validation.promptTitle = column.name
        sheet.add_data_validation(validation)
        letter = get_column_letter(index)
        validation.add(f"{letter}2:{letter}{_MAX_DATA_ROWS}")


def _apply_number_formats(sheet: Worksheet, spec: SheetSpec) -> None:
    """为日期等字段设置**列级**显示格式。

    只设置列维度（``column_dimensions[...].number_format``），
    **不逐格写入**：openpyxl 中给空单元格设置格式会把它"创建"出来，
    使 ``max_row`` 变成格式化行数，破坏"业务表只有表头行"的语义，
    也会让导入器误判存在数据行（实测踩坑：max_row 变为 200）。
    """
    for index, column in enumerate(spec.columns, start=1):
        if not column.number_format:
            continue
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].number_format = column.number_format


def _write_instructions_sheet(sheet: Worksheet, spec: SheetSpec) -> None:
    """写 `使用说明`：标题行 + 预置说明 + 工作表用途汇总。"""
    _write_header(sheet, spec)
    row = 2

    for item in instruction_rows():
        sheet.cell(row=row, column=1, value=item.topic)
        sheet.cell(row=row, column=1).font = _HEADER_FONT
        sheet.cell(row=row, column=2, value=item.content)
        sheet.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="工作表清单")
    sheet.cell(row=row, column=1).font = _HEADER_FONT
    row += 1
    for index, item in enumerate(ALL_SHEETS, start=1):
        sheet.cell(row=row, column=1, value=f"{index}. {item.name}")
        detail = f"{item.purpose} 记录粒度：{item.granularity}"
        if item.note:
            detail = f"{detail} 注意：{item.note}"
        sheet.cell(row=row, column=2, value=detail)
        sheet.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1

    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 96


def _write_validation_sheet(sheet: Worksheet, spec: SheetSpec) -> None:
    """写 `数据校验`：预置 13 类校验项，结果默认为"待检查"。"""
    _write_header(sheet, spec)
    for offset, (code, item, rule, severity) in enumerate(validation_check_items()):
        row = 2 + offset
        sheet.cell(row=row, column=1, value=code)
        sheet.cell(row=row, column=2, value=item)
        sheet.cell(row=row, column=3, value=rule)
        sheet.cell(row=row, column=4, value=severity.value)
        sheet.cell(row=row, column=5, value="待检查")


def _write_sample_sheet(sheet: Worksheet, spec: SheetSpec) -> None:
    """写 `样本参考_勿直接测算`：显著警示 + 样本行。"""
    _write_header(sheet, spec)

    # 第 2 行放显著警示
    sheet.cell(row=2, column=1, value="⚠ 警告")
    sheet.cell(row=2, column=1).font = _SAMPLE_FONT
    sheet.cell(row=2, column=2, value=SAMPLE_MARKER_TEXT)
    sheet.cell(row=2, column=2).font = _SAMPLE_FONT
    sheet.cell(row=2, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    for column in range(1, len(spec.columns) + 1):
        sheet.cell(row=2, column=column).fill = _SAMPLE_FILL

    for offset, (field, sept, octo, unit, note) in enumerate(SAMPLE_TEMPLATE_ROWS):
        row = 4 + offset
        for column, value in enumerate((field, sept, octo, unit, note), start=1):
            cell = sheet.cell(row=row, column=column, value=value)
            cell.fill = _SAMPLE_FILL

    tail = 4 + len(SAMPLE_TEMPLATE_ROWS) + 1
    sheet.cell(
        row=tail,
        column=1,
        value="复核状态：上述数值一律为“待复核”，不得直接作为生产数据使用。",
    )
    sheet.cell(row=tail, column=1).font = _SAMPLE_FONT


def _write_business_sheet(sheet: Worksheet, spec: SheetSpec) -> None:
    """写业务表（月度汇总 / 分时电量电价 / 费用明细 / 计量点）。

    只写表头，**不预置任何数据行**——避免把示例当正式数据导入。
    """
    _write_header(sheet, spec)


def _create_sheet(workbook: Workbook, spec: SheetSpec, *, first: bool) -> Worksheet:
    sheet = workbook.active if first else workbook.create_sheet()
    sheet.title = spec.name

    if spec.name == SHEET_INSTRUCTIONS:
        _write_instructions_sheet(sheet, spec)
    elif spec.name == SHEET_DATA_VALIDATION:
        _write_validation_sheet(sheet, spec)
    elif spec.name == SHEET_SAMPLE_REFERENCE:
        _write_sample_sheet(sheet, spec)
    else:
        _write_business_sheet(sheet, spec)

    _apply_column_layout(sheet, spec)
    _apply_data_validation(sheet, spec)
    _apply_number_formats(sheet, spec)
    return sheet


def build_template() -> Workbook:
    """构建模板工作簿（不落盘）。

    Returns:
        `openpyxl.Workbook`，包含规格书第 20 节要求的 7 张工作表，
        顺序与名称稳定。
    """
    workbook = Workbook()
    for index, spec in enumerate(ALL_SHEETS):
        _create_sheet(workbook, spec, first=index == 0)
    workbook.properties.title = f"CENEP 工商业电费账单标准导入模板 V{TEMPLATE_VERSION}"
    workbook.properties.creator = "CENEP"
    workbook.properties.description = (
        "电费账单人工录入与导入标准模板。不依赖宏。"
        "样本参考表仅供字段对照，导入器默认忽略。"
    )
    return workbook


def write_template(path: str | Path) -> Path:
    """生成模板文件并写入 `path`。

    Args:
        path: 目标文件路径（父目录不存在时自动创建）。

    Returns:
        实际写入的绝对路径。
    """
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = build_template()
    workbook.save(target)
    return target


def default_template_path(directory: str | Path | None = None) -> Path:
    """返回模板的默认输出路径。

    Args:
        directory: 输出目录；``None`` 时使用当前工作目录。
    """
    base = Path(directory).expanduser().resolve() if directory is not None else Path.cwd()
    return base / TEMPLATE_NAME


def template_headers(sheet_name: str) -> tuple[str, ...]:
    """便捷入口：返回某表的字段标题（供测试与调用方核对）。"""
    return tuple(column.header for column in get_sheet(sheet_name).columns)


def display_name_for(column: ColumnSpec) -> str:
    """返回字段的显示名（含单位），用于说明与日志。"""
    if column.unit:
        return f"{column.name}（{column.unit}）"
    return column.name
