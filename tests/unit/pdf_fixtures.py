"""P0-1 测试用 PDF 生成工具。

**为什么不用真实账单做测试样本：**

真实电费账单含客户名称、用电户号等隐私信息，**不得提交到公开仓库**（任务书 10.1 第 10 条）。
因此测试样本全部在运行时用代码生成，仓库内不保存任何 PDF 二进制。

**中文用例如何做到真实有效：**

不嵌入 CJK 字体（系统字体 9–19 MB，提交进仓库不可接受）。改为构造
``Type0`` 字体 + ``Identity-H`` 编码 + ``ToUnicode`` CMap 的 PDF：
字形本身不渲染，但字符编码到 Unicode 的映射是真实存在的，
``pypdf`` 会据此提取出真正的中文字符串。这样"中文链路"是被真实执行的，
而不是被跳过或断言成 ASCII。

生成物仅 1–2 KB，且不依赖任何额外库。
"""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

__all__ = [
    "build_cjk_pdf",
    "build_blank_pdf",
    "build_multipage_pdf",
    "build_single_page_pdf",
    "write_bytes",
]


def _add_type0_font(writer: PdfWriter, text: str):
    """在 writer 中登记一个带 ToUnicode 的 Type0 字体，返回字体引用。

    字形编号约定为 ``字符序号 + 1``，与 ToUnicode CMap 一一对应。
    """
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    items = [(index + 1, char) for index, char in enumerate(text)]
    lines.append(f"{len(items)} beginbfchar")
    for gid, char in items:
        lines.append(f"<{gid:04X}> <{ord(char):04X}>")
    lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]

    cmap_stream = DecodedStreamObject()
    cmap_stream.set_data("\n".join(lines).encode("ascii"))
    cmap_ref = writer._add_object(cmap_stream)

    descriptor = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/FontDescriptor"),
            NameObject("/FontName"): NameObject("/CENEPCJK"),
            NameObject("/Flags"): NumberObject(4),
            NameObject("/FontBBox"): ArrayObject([NumberObject(0)] * 4),
            NameObject("/ItalicAngle"): NumberObject(0),
            NameObject("/Ascent"): NumberObject(800),
            NameObject("/Descent"): NumberObject(-200),
            NameObject("/CapHeight"): NumberObject(700),
            NameObject("/StemV"): NumberObject(80),
        }
    )
    desc_ref = writer._add_object(descriptor)

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/CENEPCJK"),
            NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/DescendantFonts"): ArrayObject(
                [
                    DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/CIDFontType2"),
                            NameObject("/BaseFont"): NameObject("/CENEPCJK"),
                            NameObject("/CIDSystemInfo"): DictionaryObject(
                                {
                                    NameObject("/Registry"): TextStringObject("Adobe"),
                                    NameObject("/Ordering"): TextStringObject("Identity"),
                                    NameObject("/Supplement"): NumberObject(0),
                                }
                            ),
                            NameObject("/FontDescriptor"): desc_ref,
                            NameObject("/DW"): NumberObject(1000),
                        }
                    )
                ]
            ),
            NameObject("/ToUnicode"): cmap_ref,
        }
    )
    return writer._add_object(font)


def _attach_cjk_text(writer: PdfWriter, page, text: str) -> None:
    """把中文文本写入指定页（通过 Type0 字体 + 十六进制字符串）。"""
    font_ref = _add_type0_font(writer, text)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    codes = "".join(f"{index + 1:04X}" for index in range(len(text)))
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 800 Td <{codes}> Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def _attach_ascii_text(writer: PdfWriter, page, text: str) -> None:
    """把 ASCII 文本写入指定页。

    使用 PDF 标准 14 字体之一（Helvetica），**无需嵌入字体文件**，
    因此生成的 PDF 只有几百字节，且文本可被真实提取。
    """
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 800 Td ({escaped}) Tj ET".encode("latin-1", "replace"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def build_cjk_pdf(pages_text: list[str]) -> bytes:
    """生成一个包含中文文本的 PDF，逐页文本与 ``pages_text`` 一一对应。"""
    if not pages_text:
        raise ValueError("至少需要一页文本")
    writer = PdfWriter()
    for text in pages_text:
        page = writer.add_blank_page(width=595, height=842)
        _attach_cjk_text(writer, page, text)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_single_page_pdf(text: str = "CENEP single page bill") -> bytes:
    """生成单页 PDF，含可被真实提取的 ASCII 文本。"""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    _attach_ascii_text(writer, page, text)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_multipage_pdf(pages_text: list[str]) -> bytes:
    """生成多页 PDF，每页文本不同，用于验证页码与文本一一对应。"""
    if not pages_text:
        raise ValueError("至少需要一页文本")
    writer = PdfWriter()
    for text in pages_text:
        page = writer.add_blank_page(width=595, height=842)
        _attach_ascii_text(writer, page, text)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_blank_pdf(page_count: int = 1) -> bytes:
    """生成无任何文本内容的 PDF（用于模拟"无可用文本层"的扫描件）。"""
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def write_bytes(path: Path | str, data: bytes) -> Path:
    """把字节写入文件并返回 Path。"""
    target = Path(path)
    target.write_bytes(data)
    return target
