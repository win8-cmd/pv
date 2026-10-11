"""PDF 页级文本提取（基础设施层）。

**本模块是唯一允许导入 ``pypdf`` 的地方。** 领域层与计算层不得依赖它，
该约束由 ``tests/unit/test_layering.py`` 自动检查。

职责范围（严格限定，不越界）：

- 读取 PDF 文件。
- 提取每一页的文本。
- 判断是否存在可用文本层。
- 计算文件内容的 SHA-256。
- 把解析异常转换为明确状态。

**不负责**：识别电费账单字段、费用归类、金额计算、数据库写入、界面展示。

设计要点：

1. 原始文件**只读**，不修改、不移动、不删除。
2. 不使用临时文件，因此不存在临时文件清理问题（任务书 4.5 第 11 项）。
3. 失败**不抛异常给调用方**，而是返回 ``status=FAILED`` 的结果对象，
   使界面层可以稳定展示失败原因而不崩溃。
4. 只有"参数非法"这类编程错误才抛 :class:`PdfExtractionError`。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from cenep.domain.pdf_extraction import (
    MIN_MEANINGFUL_CHARS,
    PdfExtractionResult,
    PdfExtractionStatus,
    PdfPage,
    normalize_page_text,
)

__all__ = [
    "HASH_CHUNK_SIZE",
    "PARSER_NAME",
    "PdfExtractionError",
    "compute_file_hash",
    "extract_pdf",
    "parser_version",
]

#: 解析器名称，写入结果用于追溯。
PARSER_NAME = "pypdf"

#: 计算哈希时的分块大小（64 KiB），避免把大文件整体读入内存。
HASH_CHUNK_SIZE = 64 * 1024

#: 机器可读的错误代码
ERROR_CODE_NOT_FOUND = "file_not_found"
ERROR_CODE_NOT_A_FILE = "not_a_regular_file"
ERROR_CODE_EMPTY_FILE = "empty_file"
ERROR_CODE_NOT_PDF = "not_a_pdf"
ERROR_CODE_CORRUPT = "corrupt_pdf"
ERROR_CODE_UNEXPECTED = "unexpected_error"


class PdfExtractionError(Exception):
    """调用方传入了非法参数（编程错误），而非 PDF 本身有问题。

    PDF 内容层面的问题一律通过返回 ``status=FAILED`` 的结果对象表达，
    不通过异常。
    """

    code = "pdf_extraction_invalid_argument"


def parser_version() -> str:
    """返回实际使用的 pypdf 版本；导入失败时返回空字符串。

    以**实际安装版本**为准，不硬编码，避免版本号与真实行为不一致。
    """
    try:
        import pypdf  # noqa: PLC0415 - 延迟导入，便于本模块在无 pypdf 时也能被导入检查

        return str(getattr(pypdf, "__version__", "") or "")
    except Exception:  # pragma: no cover - 仅在依赖缺失时触发
        return ""


def compute_file_hash(path: str | Path) -> str:
    """计算文件内容的 SHA-256（小写十六进制）。

    Args:
        path: 文件路径。

    Returns:
        64 位小写十六进制字符串。

    Raises:
        PdfExtractionError: 路径不是已存在的普通文件。
        OSError: 读取失败（由调用方 :func:`extract_pdf` 统一转换）。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise PdfExtractionError(f"文件不存在：{file_path}")
    if not file_path.is_file():
        raise PdfExtractionError(f"不是普通文件：{file_path}")

    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _failure(
    *,
    file_hash: str,
    file_name: str,
    file_size_bytes: int,
    error_code: str,
    message: str,
) -> PdfExtractionResult:
    """构造失败结果。页数为 0、无文本层、无页面。"""
    return PdfExtractionResult(
        file_hash=file_hash,
        file_name=file_name,
        file_size_bytes=file_size_bytes,
        page_count=0,
        status=PdfExtractionStatus.FAILED,
        text_layer_available=False,
        pages=(),
        parser_name=PARSER_NAME,
        parser_version=parser_version(),
        errors=(message,),
        error_code=error_code,
    )


def extract_pdf(path: str | Path) -> PdfExtractionResult:
    """提取 PDF 的页级文本。

    Args:
        path: PDF 文件路径。

    Returns:
        :class:`~cenep.domain.pdf_extraction.PdfExtractionResult`：

        - ``SUCCESS``：至少一页存在可用文本层；
        - ``NEEDS_OCR``：文件可正常打开，但整篇没有可用文本（疑似扫描件）；
        - ``FAILED``：文件缺失、为空、非 PDF 或损坏。

    Raises:
        PdfExtractionError: ``path`` 为空或类型非法（编程错误）。
    """
    if path is None:
        raise PdfExtractionError("路径不能为 None")
    file_path = Path(path)

    # 文件名只保留名称部分，避免把本地目录结构写进数据与日志
    file_name = file_path.name

    # --- 1) 前置校验与哈希 -------------------------------------------------
    try:
        if not file_path.exists():
            return _failure(
                file_hash="",
                file_name=file_name,
                file_size_bytes=0,
                error_code=ERROR_CODE_NOT_FOUND,
                message=f"文件不存在：{file_name}",
            )
        if not file_path.is_file():
            return _failure(
                file_hash="",
                file_name=file_name,
                file_size_bytes=0,
                error_code=ERROR_CODE_NOT_A_FILE,
                message=f"不是普通文件：{file_name}",
            )
        file_size = file_path.stat().st_size
        file_hash = compute_file_hash(file_path)
    except OSError as exc:
        return _failure(
            file_hash="",
            file_name=file_name,
            file_size_bytes=0,
            error_code=ERROR_CODE_UNEXPECTED,
            message=f"读取文件失败：{exc}",
        )

    if file_size == 0:
        # 空文件：内容哈希是空串的 SHA-256，仍如实返回，便于识别重复空文件
        return _failure(
            file_hash=file_hash,
            file_name=file_name,
            file_size_bytes=0,
            error_code=ERROR_CODE_EMPTY_FILE,
            message="文件为空（0 字节），不是有效的 PDF。",
        )

    # --- 2) 解析 PDF -------------------------------------------------------
    try:
        from pypdf import PdfReader  # noqa: PLC0415 - 延迟导入
        from pypdf.errors import PdfReadError  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 依赖缺失时
        return _failure(
            file_hash=file_hash,
            file_name=file_name,
            file_size_bytes=file_size,
            error_code=ERROR_CODE_UNEXPECTED,
            message=f"PDF 解析库不可用：{exc}。请安装依赖：pip install -e \".[dev]\"",
        )

    try:
        reader = PdfReader(str(file_path))
        if reader.is_encrypted:
            # 加密 PDF 未提供口令：明确失败，不尝试猜测口令
            try:
                opened = reader.decrypt("")
            except Exception:
                opened = 0
            if not opened:
                return _failure(
                    file_hash=file_hash,
                    file_name=file_name,
                    file_size_bytes=file_size,
                    error_code=ERROR_CODE_CORRUPT,
                    message="PDF 已加密且无法用空口令打开，请先解除加密。",
                )
        page_count = len(reader.pages)
    except PdfReadError as exc:
        # pypdf 对"不是 PDF"与"结构损坏"都抛 PdfReadError，按内容区分
        marker = "not a pdf" in str(exc).lower() or "eof marker" in str(exc).lower()
        return _failure(
            file_hash=file_hash,
            file_name=file_name,
            file_size_bytes=file_size,
            error_code=ERROR_CODE_NOT_PDF if marker else ERROR_CODE_CORRUPT,
            message=f"PDF 解析失败：{exc}",
        )
    except Exception as exc:  # noqa: BLE001 - 任何解析库异常都必须转为明确状态
        return _failure(
            file_hash=file_hash,
            file_name=file_name,
            file_size_bytes=file_size,
            error_code=ERROR_CODE_CORRUPT,
            message=f"PDF 解析出现未预期错误：{type(exc).__name__}: {exc}",
        )

    # --- 3) 逐页提取 -------------------------------------------------------
    pages: list[PdfPage] = []
    errors: list[str] = []
    for index in range(page_count):
        page_number = index + 1
        try:
            raw = reader.pages[index].extract_text()
            text = normalize_page_text(raw)
        except Exception as exc:  # noqa: BLE001 - 单页失败不应导致整篇失败
            # 单页提取失败：该页留空并记录，其余页继续，且整篇状态降级为需复核
            text = ""
            errors.append(f"第 {page_number} 页文本提取失败：{type(exc).__name__}: {exc}")
        pages.append(PdfPage(page_number=page_number, text=text, char_count=len(text)))

    meaningful_total = sum(len(page.text.strip()) for page in pages)
    text_layer_available = meaningful_total >= MIN_MEANINGFUL_CHARS

    if text_layer_available and not errors:
        status = PdfExtractionStatus.SUCCESS
    elif text_layer_available and errors:
        # 有文本但存在单页失败：能给出文本层，但不能声称完全成功
        status = PdfExtractionStatus.NEEDS_OCR
    else:
        status = PdfExtractionStatus.NEEDS_OCR

    if not pages and page_count == 0:
        return _failure(
            file_hash=file_hash,
            file_name=file_name,
            file_size_bytes=file_size,
            error_code=ERROR_CODE_CORRUPT,
            message="PDF 不含任何页面。",
        )

    error_code: str | None = None
    if status is PdfExtractionStatus.NEEDS_OCR and not errors:
        error_code = "no_text_layer"
    elif errors:
        error_code = "page_extraction_failed"

    return PdfExtractionResult(
        file_hash=file_hash,
        file_name=file_name,
        file_size_bytes=file_size,
        page_count=page_count,
        status=status,
        text_layer_available=text_layer_available and status is PdfExtractionStatus.SUCCESS,
        pages=tuple(pages),
        parser_name=PARSER_NAME,
        parser_version=parser_version(),
        errors=tuple(errors),
        error_code=error_code,
    )


def summarize(result: PdfExtractionResult) -> dict[str, Any]:
    """返回便于日志/界面展示的摘要（不含完整页文本）。

    完整文本属原始证据，不应写入常规日志。
    """
    return {
        "file_name": result.file_name,
        "status": result.status.value,
        "page_count": result.page_count,
        "text_layer_available": result.text_layer_available,
        "total_char_count": result.total_char_count,
        "error_code": result.error_code,
        "errors": list(result.errors),
    }
