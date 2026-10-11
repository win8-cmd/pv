"""PDF 提取的领域模型。

本模块是**纯 Python**：不导入 ``pypdf``、``PySide6``、``sqlite3`` 或任何 IO 库。
真正的 PDF 解析在 :mod:`cenep.infrastructure.pdf.extractor` 中完成，
其结果被映射为本模块定义的结构化数据。

分层理由：解析库属于"实现细节"，而"一页文本长什么样、一次提取有哪些状态"
属于领域语言。把它们分开，界面与业务可以只依赖领域模型，
未来替换解析库（例如换用 pdfplumber）不需要改动上层。

关键约定（与任务书 1.1 一致）：

1. **缺失值保持 ``None``**，绝不补 0。
2. **不静默猜测**：无法判定的一律记为明确状态，交由上层或人工处理。
3. 页码从 **1** 开始，逐页一一对应，不合并、不重排。
4. 原始文件只读，提取过程不得修改原文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "PdfExtractionStatus",
    "PdfPage",
    "PdfExtractionResult",
    "normalize_page_text",
    "is_meaningful_text",
]


class PdfExtractionStatus(str, Enum):
    """单次 PDF 提取的总体状态。

    ``DUPLICATE`` 虽在任务书 4.4 中列出，但它属于"与已有记录比较"的结论，
    需要数据库或应用层参与，因此**不由提取器产生**；此处保留该取值，
    供应用服务层在识别到重复文件时使用。
    """

    SUCCESS = "success"
    """文本提取成功，且至少有一页存在可用文本层。"""

    NEEDS_OCR = "needs_ocr"
    """文件可正常打开，但没有可用文本层（疑似扫描件）。

    注意：这**不是失败**，也不等于已提取到内容；上层必须提示需要 OCR，
    而不是把它当作解析成功。
    """

    FAILED = "failed"
    """文件损坏、不是 PDF、无法打开或解析过程抛错。"""

    DUPLICATE = "duplicate"
    """文件内容（SHA-256）与已登记文件相同。由应用层判定，提取器不产生。"""


#: 判定"存在可用文本层"所需的最少可见字符数。
#:
#: 少数 PDF 会包含空白页或仅含页码的空页，若把"任意页有 1 个字符"当作有文本层，
#: 扫描件中被嵌入页码时会误判。要求整篇文档可见字符总数达到该阈值。
MIN_MEANINGFUL_CHARS = 8


def normalize_page_text(raw: str | None) -> str:
    """把解析库返回的原始页文本规范化为可存储的字符串。

    只做**无损**规范化：

    - ``None`` → ``""``（解析库对空白页可能返回 ``None``）；
    - 统一换行为 ``\\n``（PDF 常见 ``\\r\\n`` / ``\\r``）；
    - 去掉行尾空白，避免存储体积浪费。

    **不做**：不合并空白、不修正错字、不删减字符、不猜测表格结构。
    真实账单文本中"数字被换行截断""汉字间插空格"等现象属于原始证据，
    必须原样保留，交由 P0-2 的规则解析处理。
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):  # pragma: no cover - 防御性
        raise TypeError(f"页文本必须是字符串或 None，实际为 {type(raw).__name__}")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def is_meaningful_text(text: str) -> bool:
    """判断文本是否含有非空白内容。"""
    return bool(text.strip())


@dataclass(frozen=True)
class PdfPage:
    """PDF 的一页。

    Attributes:
        page_number: 页码，**从 1 开始**，与 PDF 中的物理页序一致。
        text: 该页的文本。无文本层时为空字符串（不是 ``None``，
            以便与"字段缺失"的语义区分：这里"没有文本"就是确定的事实）。
        char_count: 该页文本的字符数（含空白），便于快速判断页面是否有内容。
    """

    page_number: int
    text: str = ""
    char_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.page_number, int) or self.page_number < 1:
            raise ValueError(f"页码必须是从 1 开始的整数，实际为 {self.page_number!r}")
        if not isinstance(self.text, str):
            raise TypeError(f"页文本必须是字符串，实际为 {type(self.text).__name__}")
        if self.char_count != len(self.text):
            object.__setattr__(self, "char_count", len(self.text))

    @property
    def has_text(self) -> bool:
        """该页是否存在非空白文本。"""
        return is_meaningful_text(self.text)

    def snippet(self, limit: int = 80) -> str:
        """返回压缩空白后的短摘要，供日志与界面预览使用。

        仅用于展示；**不得**用摘要替代原始文本作为证据。
        """
        if limit <= 0:
            return ""
        collapsed = " ".join(self.text.split())
        return collapsed[:limit]

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典。"""
        return {
            "page_number": self.page_number,
            "text": self.text,
            "char_count": self.char_count,
            "has_text": self.has_text,
        }


@dataclass(frozen=True)
class PdfExtractionResult:
    """一次 PDF 提取的完整结果。

    Attributes:
        file_hash: 文件内容的 SHA-256（小写十六进制，64 位）。
        file_name: 原始文件名（仅名称，不含目录，避免泄露本地路径）。
        file_size_bytes: 文件字节数。
        page_count: 页数。解析失败时为 0。
        pages: 逐页结果，按页码升序，一一对应。
        text_layer_available: 是否存在可用文本层。
            **只有**状态为 ``SUCCESS`` 时才可能为 ``True``；失败与需 OCR 均为 ``False``。
        status: 总体状态。
        parser_name: 解析器名称（实现细节的快照，用于追溯）。
        parser_version: 解析器版本。
        errors: 错误信息列表（人类可读）。成功时为空。
        error_code: 机器可读的错误代码，成功时为 ``None``。
    """

    file_hash: str
    file_name: str
    file_size_bytes: int
    page_count: int
    status: PdfExtractionStatus
    text_layer_available: bool = False
    pages: tuple[PdfPage, ...] = field(default_factory=tuple)
    parser_name: str = ""
    parser_version: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.page_count < 0:
            raise ValueError("页数不能为负")
        if self.file_size_bytes < 0:
            raise ValueError("文件大小不能为负")
        # 页码必须与列表位置严格一致
        for index, page in enumerate(self.pages, start=1):
            if page.page_number != index:
                raise ValueError(
                    f"页码必须从 1 连续递增：第 {index} 个元素的 page_number 为 {page.page_number}"
                )
        if len(self.pages) != self.page_count:
            raise ValueError(
                f"page_count({self.page_count}) 与 pages 长度({len(self.pages)}) 不一致"
            )
        # 只有成功才允许声称有文本层，防止把扫描件误标为可用
        if self.text_layer_available and self.status is not PdfExtractionStatus.SUCCESS:
            raise ValueError(
                f"状态为 {self.status.value} 时不得声称存在可用文本层"
            )

    @property
    def is_success(self) -> bool:
        """提取是否成功。"""
        return self.status is PdfExtractionStatus.SUCCESS

    @property
    def needs_ocr(self) -> bool:
        """是否需要 OCR 才能获得文本。"""
        return self.status is PdfExtractionStatus.NEEDS_OCR

    @property
    def is_failed(self) -> bool:
        """是否解析失败。"""
        return self.status is PdfExtractionStatus.FAILED

    @property
    def total_char_count(self) -> int:
        """全部页面文本的字符总数。"""
        return sum(page.char_count for page in self.pages)

    def page(self, page_number: int) -> PdfPage:
        """按页码取页（页码从 1 开始）。

        Raises:
            IndexError: 页码越界。
        """
        if page_number < 1 or page_number > len(self.pages):
            raise IndexError(f"页码越界：{page_number}（共 {len(self.pages)} 页）")
        return self.pages[page_number - 1]

    def pages_with_text(self) -> tuple[PdfPage, ...]:
        """返回存在非空白文本的页面。"""
        return tuple(page for page in self.pages if page.has_text)

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典。

        ``None`` 保持为 ``None``（JSON ``null``），**不转换为 0**。
        """
        return {
            "file_hash": self.file_hash,
            "file_name": self.file_name,
            "file_size_bytes": self.file_size_bytes,
            "page_count": self.page_count,
            "text_layer_available": self.text_layer_available,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "status": self.status.value,
            "pages": [page.to_dict() for page in self.pages],
            "errors": list(self.errors),
            "error_code": self.error_code,
        }
