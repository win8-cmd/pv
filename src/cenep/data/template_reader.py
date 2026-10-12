"""读取电费账单标准 Excel 模板，并做表头/列映射。

职责边界（规格书第 31 节第 1–7 步）：

1. 检查文件格式与模板版本；
2. 检查必需工作表与表头；
3. **默认排除** `使用说明`、`数据校验`、`样本参考_勿直接测算`；
4. 读取业务数据行（保留原始单元格值，不在此处做类型转换）；
5. 识别字段映射（允许列顺序变化、支持中文列名别名）。

本模块只负责"把表格读成结构化行"，**不做业务校验**——
校验由 :mod:`cenep.data.bill_validation` 负责，落库由阶段 4 负责。
这样"读表"与"判定"分离，便于分别测试。

设计要点：

- 缺失单元格返回 ``None``，**不补 0**（规格书第 30 节）；
- 未知列**保留**在原始行里并单独报告，不静默丢弃；
- 样本表与校验表即使有数据也**不进入业务行**。
"""

from __future__ import annotations

import hashlib
import zipfile
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from cenep.data.bill_template_spec import (
    BUSINESS_SHEETS,
    EXCLUDED_SHEETS,
    TEMPLATE_VERSION,
    column_by_name,
    columns_of,
)

__all__ = [
    "COLUMN_ALIASES",
    "TemplateReadError",
    "TemplateReadResult",
    "TemplateRow",
    "ColumnMapping",
    "build_column_mapping",
    "compute_file_hash",
    "map_header",
    "normalize_header",
    "read_template",
]


class TemplateReadError(Exception):
    """读取模板失败（结构性问题，无法继续导入）。"""

    def __init__(self, message: str, *, details: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.details: tuple[str, ...] = tuple(details)

    def format(self) -> str:
        if not self.details:
            return str(self)
        joined = "\n".join(f"  - {item}" for item in self.details)
        return f"{self}\n{joined}"


#: 中文列名别名表：``标准字段名 -> 可接受的其它写法``。
#: 用于容忍人工录入/外部整理时的常见叫法差异（规格书第 31 节第 6 步）。
COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    # 月度汇总
    "项目编号": ("项目编码", "项目ID", "project_id"),
    "用户名称": ("客户名称", "用电户名", "户名"),
    "户号": ("用户号", "用电户号"),
    "供电单位": ("供电公司", "供电局"),
    "用电地址": ("地址", "用电地点"),
    "用电类别": ("用电分类", "电价类别"),
    "电压等级": ("电压", "供电电压"),
    "市场化属性": ("市场属性", "购电方式"),
    "账期": ("账单月份", "用电月份", "月份", "账期月份"),
    "账期开始日期": ("开始日期", "账期起", "起始日期"),
    "账期结束日期": ("结束日期", "账期止", "终止日期"),
    "账单打印日期": ("打印日期", "出账日期"),
    "本期总电量_kWh": ("本期总电量", "总电量", "本期电量", "总用电量"),
    "账单本期电费_元": ("本期电费", "账单电费", "总电费", "本期总电费"),
    "增值税专票金额_元": ("增值税专用发票金额", "专票金额", "发票金额"),
    "账单展示平均电价_元每kWh": ("平均电价", "账单平均电价", "展示平均电价"),
    "工商业电费_元": ("工商业电费",),
    "市场化购电电费_元": ("市场化购电电费", "购电电费"),
    "上网环节线损费用_元": ("上网环节线损费用", "线损费用", "上网环节线损费"),
    "输配电费_元": ("输配电费", "输配电价电费"),
    "系统运行费_元": ("系统运行费", "系统运行费用"),
    "政府性基金及附加_元": ("政府性基金及附加", "政府基金及附加", "政府性基金"),
    "功率因数调整电费_元": ("功率因数调整电费", "力调电费", "力率调整电费"),
    "需量电费_元": ("需量电费", "基本电费需量", "需量电费金额"),
    "市场化运营费合计_元": ("市场化运营费合计", "市场运营费", "市场运营费用"),
    "基本电费_元": ("基本电费",),
    "合同最大需量": ("合同需量", "合同最大需量值"),
    "合同最大需量单位": ("合同需量单位",),
    "实际最大需量": ("实际需量", "最大需量", "实际最大需量值"),
    "实际最大需量单位": ("实际需量单位", "最大需量单位"),
    "需量计费方式": ("需量方式", "计费方式"),
    "功率因数": ("功率因数实际值", "实际功率因数"),
    "来源文件": ("数据来源文件", "来源文件名", "源文件"),
    "来源页码": ("页码", "来源页"),
    "复核状态": ("复核", "审核状态", "数据复核状态"),
    "备注": ("注释", "说明"),
    # 分时电量电价
    "计量口径/计量点编号": ("计量口径", "计量点编号", "口径", "计量点"),
    "电量类型": ("电量口径", "电量种类"),
    "时段名称": ("时段", "分时段", "时段类别"),
    "时段开始": ("开始时间", "时段起"),
    "时段结束": ("结束时间", "时段止"),
    "电量_kWh": ("电量", "分时电量"),
    "购电电价_元每kWh": ("购电电价", "电价", "分时电价"),
    "电量电费_元": ("电量电费", "电费"),
    "电价类型/来源": ("电价类型", "电价来源"),
    # 费用明细
    "费用大类": ("费用分类", "费用类别"),
    "费用项目名称": ("费用项目", "费用名称", "项目名称"),
    "计费数量": ("数量", "计费量"),
    "计费数量单位": ("数量单位",),
    "单价_元每单位": ("单价",),
    "金额_元": ("金额", "费用金额"),
    "是否包含在其他费用中": ("是否已包含在其他费用中", "包含在其他费用中"),
    "被包含于/关联费用": ("被包含于", "关联费用"),
    "光伏测算可避免性": ("可避免性", "光伏可避免性"),
    "是否纳入基准电费": ("纳入基准电费", "是否计入基准"),
    # 计量点
    "计量点编号": ("计量点代码", "表位编号"),
    "计量点名称/位置": ("计量点名称", "计量点位置"),
    "计量点类型": ("表类型", "计量类型"),
    "主/分表关系": ("主分表关系", "表关系"),
    "倍率/定比": ("倍率", "定比", "综合倍率"),
    "是否已计入首页总电量": ("已计入首页总电量", "是否计入总电量"),
    "是否允许纳入汇总": ("允许纳入汇总", "是否允许汇总"),
}

#: 归一化时删除的字符（单位、括号、空白等），用于宽松匹配
_STRIP_PATTERN = re.compile(r"[\s（）()\[\]【】、,，.。:：;；/\\_\-%％]+")

#: 归一化时删除的单位后缀
_UNIT_SUFFIXES: tuple[str, ...] = (
    "元每kwh",
    "元每千瓦时",
    "元/kwh",
    "千瓦时",
    "kwh",
    "kva",
    "kw",
    "元",
    "台",
    "月",
)


def normalize_header(header: Any) -> str:
    """归一化表头文本，用于宽松匹配。

    处理：去空白与常见分隔符、统一大小写、去单位后缀。

    例：``"本期总电量_kWh"`` → ``"本期总电量"``；
    ``"账单本期电费_元"`` → ``"账单本期电费"``。
    """
    if header is None:
        return ""
    text = str(header).strip().lower()
    text = _STRIP_PATTERN.sub("", text)
    for suffix in _UNIT_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text


@dataclass(frozen=True)
class ColumnMapping:
    """某一工作表的表头映射结果。"""

    sheet_name: str
    #: 标准字段名 → 该表在第几列（0 基）
    indexes: Mapping[str, int] = field(default_factory=dict)
    #: 标准字段名 → 实际表头原文
    headers: Mapping[str, str] = field(default_factory=dict)
    #: 无法识别的列：``(列下标, 表头原文)``
    unknown_columns: tuple[tuple[int, str], ...] = ()
    #: 缺失的必需字段（标准字段名）
    missing_required: tuple[str, ...] = ()

    def index_of(self, standard_name: str) -> int | None:
        """返回标准字段所在列下标；未映射时 ``None``。"""
        return self.indexes.get(standard_name)


def map_header(sheet_name: str, header: Any) -> str | None:
    """把单个表头映射为标准字段名。

    Returns:
        标准字段名；无法识别时 ``None``。
    """
    if header is None or not str(header).strip():
        return None
    raw = str(header).strip()
    for column in columns_of(sheet_name):
        if raw == column.name:
            return column.name
    normalized = normalize_header(raw)
    if not normalized:
        return None
    for column in columns_of(sheet_name):
        if normalize_header(column.name) == normalized:
            return column.name
    for standard_name, aliases in COLUMN_ALIASES.items():
        try:
            column_by_name(sheet_name, standard_name)
        except KeyError:
            continue  # 该别名属于别的工作表
        for alias in aliases:
            if normalize_header(alias) == normalized:
                return standard_name
    return None


def build_column_mapping(sheet_name: str, header_row: Sequence[Any]) -> ColumnMapping:
    """根据实际表头行构建列映射。

    允许列顺序变化；未知列保留在 :attr:`ColumnMapping.unknown_columns`；
    重复映射同一标准字段时**保留第一次出现的列**并记录为未知列。
    """
    indexes: dict[str, int] = {}
    headers: dict[str, str] = {}
    unknown: list[tuple[int, str]] = []

    for index, header in enumerate(header_row):
        standard = map_header(sheet_name, header)
        if standard is None:
            if header is not None and str(header).strip():
                unknown.append((index, str(header).strip()))
            continue
        if standard in indexes:
            unknown.append((index, str(header).strip()))
            continue
        indexes[standard] = index
        headers[standard] = str(header).strip()

    missing = tuple(
        column.name
        for column in columns_of(sheet_name)
        if column.required and column.name not in indexes
    )

    return ColumnMapping(
        sheet_name=sheet_name,
        indexes=indexes,
        headers=headers,
        unknown_columns=tuple(unknown),
        missing_required=missing,
    )


@dataclass(frozen=True)
class TemplateRow:
    """模板中的一行原始数据。"""

    sheet_name: str
    row_number: int
    """Excel 行号（含表头，从 1 开始），便于错误定位。"""
    cells: Mapping[str, Any]
    """标准字段名 → 原始单元格值（**未做类型转换**）。"""

    def raw(self, standard_name: str) -> Any:
        """取原始值；未提供或空单元格返回 ``None``（不补 0）。"""
        return self.cells.get(standard_name)

    def text(self, standard_name: str) -> str | None:
        """取去空白后的文本；空的返回 ``None``。"""
        value = self.cells.get(standard_name)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def decimal(self, standard_name: str) -> Decimal | None:
        """取十进制数值。

        Raises:
            ValueError: 值存在但无法解析为数值。
        """
        value = self.cells.get(standard_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, bool):
            raise ValueError(f"{standard_name} 的值不是有效数值：{value!r}")
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        text = str(value).strip().replace(",", "")
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{standard_name} 的值无法解析为数值：{value!r}") from exc

    def date(self, standard_name: str) -> date | None:
        """取日期值。

        支持 Excel 日期单元格与 ``YYYY-MM-DD`` / ``YYYY/MM/DD`` 文本。

        Raises:
            ValueError: 值存在但无法解析为日期。
        """
        value = self.cells.get(standard_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"{standard_name} 的值无法解析为日期：{value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "row_number": self.row_number,
            "cells": {
                key: (value.isoformat() if isinstance(value, (date, datetime)) else str(value))
                for key, value in self.cells.items()
            },
        }


@dataclass
class TemplateReadResult:
    """一次模板读取的完整结果。"""

    file_name: str
    file_hash: str
    sheet_names: tuple[str, ...]
    mappings: Mapping[str, ColumnMapping]
    rows: Mapping[str, tuple[TemplateRow, ...]]
    template_version: str | None = None
    warnings: tuple[str, ...] = ()

    def business_rows(self, sheet_name: str) -> tuple[TemplateRow, ...]:
        """取某业务表的数据行。"""
        return self.rows.get(sheet_name, ())

    @property
    def total_business_rows(self) -> int:
        return sum(len(rows) for rows in self.rows.values())

    @property
    def all_rows(self) -> tuple[TemplateRow, ...]:
        collected: list[TemplateRow] = []
        for sheet in BUSINESS_SHEETS:
            collected.extend(self.business_rows(sheet))
        return tuple(collected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "file_hash": self.file_hash,
            "template_version": self.template_version,
            "sheet_names": list(self.sheet_names),
            "warnings": list(self.warnings),
            "row_counts": {name: len(rows) for name, rows in self.rows.items()},
            "unknown_columns": {
                name: [header for _index, header in mapping.unknown_columns]
                for name, mapping in self.mappings.items()
            },
            "missing_required": {
                name: list(mapping.missing_required) for name, mapping in self.mappings.items()
            },
        }


def compute_file_hash(path: str | Path) -> str:
    """计算文件 SHA-256，用于重复文件识别（规格书第 32 节）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cell_values(row: Sequence[Any], mapping: ColumnMapping) -> dict[str, Any]:
    """按映射从一行中取出标准字段的原始值。

    空单元格（``None`` 或纯空白字符串）**不出现在结果里**，
    以保证"未提供"与"明确为 0"区分开。
    """
    cells: dict[str, Any] = {}
    for standard_name, index in mapping.indexes.items():
        if index >= len(row):
            continue
        value = row[index]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cells[standard_name] = value
    return cells


def _read_sheet_rows(
    worksheet,
    mapping: ColumnMapping,
    *,
    max_rows: int | None = None,
) -> tuple[TemplateRow, ...]:
    """读取某业务表的数据行（跳过完全空行）。"""
    rows: list[TemplateRow] = []
    for offset, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if max_rows is not None and len(rows) >= max_rows:
            break
        if row is None:
            continue
        if all(value is None or (isinstance(value, str) and not value.strip()) for value in row):
            continue
        cells = _cell_values(row, mapping)
        rows.append(TemplateRow(sheet_name=mapping.sheet_name, row_number=offset, cells=cells))
    return tuple(rows)


def read_template(
    path: str | Path,
    *,
    required_sheets: Iterable[str] | None = None,
    max_rows_per_sheet: int | None = None,
) -> TemplateReadResult:
    """读取模板文件并构建列映射与数据行。

    Args:
        path: Excel 文件路径。
        required_sheets: 必需存在的工作表；默认要求全部业务表。
        max_rows_per_sheet: 每张表最多读取的行数（防御性限制）。

    Returns:
        :class:`TemplateReadResult`。

    Raises:
        TemplateReadError: 文件不存在、不是有效工作簿、
            缺少必需工作表，或业务表缺少必需字段。
    """
    target = Path(path)
    if not target.exists():
        raise TemplateReadError(f"文件不存在：{target}")
    if not target.is_file():
        raise TemplateReadError(f"不是普通文件：{target}")
    if target.stat().st_size == 0:
        raise TemplateReadError(f"文件为空：{target.name}")

    try:
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
    except ImportError as exc:  # pragma: no cover - 依赖缺失属于环境问题
        raise TemplateReadError("缺少 openpyxl，无法读取 Excel 文件") from exc

    try:
        workbook = load_workbook(target, data_only=True, read_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise TemplateReadError(f"无法读取工作簿（文件可能已损坏）：{exc}") from exc

    try:
        sheet_names = tuple(workbook.sheetnames)
        expected = tuple(required_sheets) if required_sheets is not None else BUSINESS_SHEETS
        missing_sheets = [name for name in expected if name not in sheet_names]
        if missing_sheets:
            raise TemplateReadError(
                "缺少必需工作表", details=[f"缺少：{name}" for name in missing_sheets]
            )

        warnings: list[str] = []
        for name in EXCLUDED_SHEETS:
            if name in sheet_names:
                warnings.append(f"已按规则排除工作表：{name}")

        mappings: dict[str, ColumnMapping] = {}
        rows: dict[str, tuple[TemplateRow, ...]] = {}
        structural_problems: list[str] = []

        for name in expected:
            worksheet = workbook[name]
            header_row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
            mapping = build_column_mapping(name, tuple(header_row))
            mappings[name] = mapping
            if mapping.missing_required:
                structural_problems.append(
                    f"{name} 缺少必需字段：{'、'.join(mapping.missing_required)}"
                )
            rows[name] = _read_sheet_rows(worksheet, mapping, max_rows=max_rows_per_sheet)

        if structural_problems:
            raise TemplateReadError("模板表头不完整", details=structural_problems)

        # 模板版本：从 `使用说明` 中解析（存在时）
        version: str | None = None
        if "使用说明" in sheet_names:
            version = _detect_template_version(workbook["使用说明"])
        if version is None:
            warnings.append("未在使用说明中识别到模板版本号，按当前版本处理")
        elif version != TEMPLATE_VERSION:
            warnings.append(
                f"模板版本为 {version}，当前程序支持的版本为 {TEMPLATE_VERSION}；"
                "如结构不兼容将无法完整导入"
            )
    finally:
        workbook.close()

    return TemplateReadResult(
        file_name=target.name,
        file_hash=compute_file_hash(target),
        sheet_names=sheet_names,
        mappings=mappings,
        rows=rows,
        template_version=version,
        warnings=tuple(warnings),
    )


#: 在 `使用说明` 中匹配版本号，例如 "模板版本 1.0"
_VERSION_PATTERN = re.compile(r"版本\s*([0-9]+(?:\.[0-9]+)*)")


def _detect_template_version(worksheet) -> str | None:
    """在 `使用说明` 中解析模板版本号。"""
    for row in worksheet.iter_rows(values_only=True):
        for value in row:
            if value is None:
                continue
            match = _VERSION_PATTERN.search(str(value))
            if match:
                return match.group(1)
        # 只扫描前若干行即可
        if worksheet.min_row is not None and row is None:
            break
    return None
