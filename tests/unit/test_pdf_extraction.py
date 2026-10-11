"""P0-1 PDF 导入与页级文本提取测试。

覆盖任务书 4.5 列出的 12 项必测情况，外加领域模型自身的约束与异常路径。

测试样本全部由 :mod:`tests.unit.pdf_fixtures` 在运行时生成，
**不提交任何真实账单或 PDF 二进制**。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cenep.domain.pdf_extraction import (
    PdfExtractionResult,
    PdfExtractionStatus,
    PdfPage,
    is_meaningful_text,
    normalize_page_text,
)
from cenep.infrastructure.pdf.extractor import (
    ERROR_CODE_CORRUPT,
    ERROR_CODE_EMPTY_FILE,
    ERROR_CODE_NOT_A_FILE,
    ERROR_CODE_NOT_FOUND,
    ERROR_CODE_NOT_PDF,
    PARSER_NAME,
    PdfExtractionError,
    compute_file_hash,
    extract_pdf,
    parser_version,
    summarize,
)
from tests.unit.pdf_fixtures import (
    build_blank_pdf,
    build_cjk_pdf,
    build_multipage_pdf,
    build_single_page_pdf,
    write_bytes,
)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# 4.5-1 正常单页 PDF
# ---------------------------------------------------------------------------


class TestSinglePagePdf:
    def test_single_page_extraction_succeeds(self, workdir: Path) -> None:
        path = write_bytes(workdir / "single.pdf", build_single_page_pdf("CENEP bill 2025"))
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.SUCCESS
        assert result.is_success
        assert result.page_count == 1
        assert len(result.pages) == 1
        assert result.text_layer_available is True
        assert result.parser_name == PARSER_NAME
        assert result.parser_version == parser_version()
        assert result.errors == ()
        assert result.error_code is None

    def test_single_page_text_is_extracted(self, workdir: Path) -> None:
        path = write_bytes(workdir / "single.pdf", build_single_page_pdf("CENEP bill 2025"))
        result = extract_pdf(path)
        assert "CENEP bill 2025" in result.page(1).text

    def test_file_metadata_is_recorded(self, workdir: Path) -> None:
        data = build_single_page_pdf("meta")
        path = write_bytes(workdir / "账单-2025-09.pdf", data)
        result = extract_pdf(path)

        assert result.file_name == "账单-2025-09.pdf"
        assert result.file_size_bytes == len(data)
        assert result.file_hash == hashlib.sha256(data).hexdigest()
        assert len(result.file_hash) == 64

    def test_file_name_does_not_leak_directory(self, workdir: Path) -> None:
        """只保存文件名，不把本地目录结构写进数据。"""
        nested = workdir / "客户A" / "2025"
        nested.mkdir(parents=True)
        path = write_bytes(nested / "bill.pdf", build_single_page_pdf("x"))
        result = extract_pdf(path)

        assert result.file_name == "bill.pdf"
        assert str(workdir) not in result.file_name


# ---------------------------------------------------------------------------
# 4.5-2 正常多页 PDF
# ---------------------------------------------------------------------------


class TestMultipagePdf:
    def test_multipage_page_count_and_order(self, workdir: Path) -> None:
        texts = ["PAGE-ONE alpha", "PAGE-TWO bravo", "PAGE-THREE charlie"]
        path = write_bytes(workdir / "multi.pdf", build_multipage_pdf(texts))
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.SUCCESS
        assert result.page_count == 3
        assert len(result.pages) == 3

    def test_pages_are_not_merged_and_keep_page_numbers(self, workdir: Path) -> None:
        """多页文本不得被错误合并而丢失页码。"""
        texts = ["PAGE-ONE alpha", "PAGE-TWO bravo", "PAGE-THREE charlie"]
        path = write_bytes(workdir / "multi.pdf", build_multipage_pdf(texts))
        result = extract_pdf(path)

        for index, expected in enumerate(texts, start=1):
            page = result.page(index)
            assert page.page_number == index
            assert expected in page.text
            # 每页只含自己的内容，不能出现其它页的标记
            for other in texts:
                if other != expected:
                    assert other not in page.text

    def test_multipage_cjk_text(self, workdir: Path) -> None:
        """中文多页提取：每页中文内容独立且不串页。"""
        texts = ["第一页 总用电量 8780498", "第二页 账单总金额 6699241.94"]
        path = write_bytes(workdir / "multi_cjk.pdf", build_cjk_pdf(texts))
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.SUCCESS
        assert result.page_count == 2
        assert "总用电量" in result.page(1).text
        assert "账单总金额" in result.page(2).text
        assert "账单总金额" not in result.page(1).text


# ---------------------------------------------------------------------------
# 4.5-3 中文文本 PDF
# ---------------------------------------------------------------------------


class TestChineseText:
    def test_chinese_characters_are_extracted_intact(self, workdir: Path) -> None:
        text = "电费账单 户名：岚图汽车科技有限公司 用电类别：大工业用电"
        path = write_bytes(workdir / "cjk.pdf", build_cjk_pdf([text]))
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.SUCCESS
        assert text in result.page(1).text

    def test_chinese_punctuation_and_digits(self, workdir: Path) -> None:
        text = "账单周期：2025-09-01 至 2025-09-30，总金额 6,699,241.94 元"
        path = write_bytes(workdir / "cjk2.pdf", build_cjk_pdf([text]))
        result = extract_pdf(path)
        assert text in result.page(1).text

    def test_chinese_text_char_count_matches(self, workdir: Path) -> None:
        text = "电费账单"
        path = write_bytes(workdir / "cjk3.pdf", build_cjk_pdf([text]))
        result = extract_pdf(path)
        page = result.page(1)
        assert page.char_count == len(page.text) == len(text)


# ---------------------------------------------------------------------------
# 4.5-4 空文件
# ---------------------------------------------------------------------------


class TestEmptyFile:
    def test_empty_file_reports_failure_not_success(self, workdir: Path) -> None:
        path = write_bytes(workdir / "empty.pdf", b"")
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.FAILED
        assert result.is_failed
        assert result.error_code == ERROR_CODE_EMPTY_FILE
        assert result.page_count == 0
        assert result.text_layer_available is False
        assert result.errors, "必须给出失败原因"

    def test_empty_file_hash_is_computed(self, workdir: Path) -> None:
        path = write_bytes(workdir / "empty.pdf", b"")
        result = extract_pdf(path)
        assert result.file_hash == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# 4.5-5 损坏的 PDF
# ---------------------------------------------------------------------------


class TestCorruptPdf:
    def test_truncated_pdf_reports_failure(self, workdir: Path) -> None:
        """把正常 PDF 截断为前半部分，模拟损坏文件。"""
        data = build_multipage_pdf(["page one content", "page two content"])
        truncated = data[: len(data) // 3]
        path = write_bytes(workdir / "corrupt.pdf", truncated)
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.FAILED
        assert result.error_code in {ERROR_CODE_CORRUPT, ERROR_CODE_NOT_PDF}
        assert result.errors

    def test_header_only_pdf_reports_failure(self, workdir: Path) -> None:
        path = write_bytes(workdir / "header_only.pdf", b"%PDF-1.4\n")
        result = extract_pdf(path)
        assert result.status is PdfExtractionStatus.FAILED
        assert result.error_code is not None

    def test_corrupt_pdf_does_not_raise(self, workdir: Path) -> None:
        """损坏文件必须返回结果对象，不得让程序崩溃。"""
        path = write_bytes(workdir / "corrupt2.pdf", b"%PDF-1.7\n\x00\x01\x02 garbage not a pdf")
        result = extract_pdf(path)  # 不应抛异常
        assert isinstance(result, PdfExtractionResult)
        assert result.status is PdfExtractionStatus.FAILED

    def test_corrupt_and_blank_have_different_status(self, workdir: Path) -> None:
        """BILL-013 的提取层对应检查：损坏文件与无文本层文件状态必须不同。"""
        corrupt = extract_pdf(write_bytes(workdir / "c.pdf", b"%PDF-1.4\nbroken"))
        blank = extract_pdf(write_bytes(workdir / "b.pdf", build_blank_pdf(1)))

        assert corrupt.status is PdfExtractionStatus.FAILED
        assert blank.status is PdfExtractionStatus.NEEDS_OCR
        assert corrupt.status is not blank.status


# ---------------------------------------------------------------------------
# 4.5-6 非 PDF 文件
# ---------------------------------------------------------------------------


class TestNotAPdf:
    def test_plain_text_file_is_rejected(self, workdir: Path) -> None:
        path = write_bytes(workdir / "notes.pdf", "这不是 PDF，只是改了扩展名的文本".encode("utf-8"))
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.FAILED
        assert result.error_code in {ERROR_CODE_NOT_PDF, ERROR_CODE_CORRUPT}
        assert result.page_count == 0

    def test_binary_non_pdf_file_is_rejected(self, workdir: Path) -> None:
        path = write_bytes(workdir / "image.pdf", bytes(range(256)) * 8)
        result = extract_pdf(path)
        assert result.status is PdfExtractionStatus.FAILED

    def test_directory_is_rejected(self, workdir: Path) -> None:
        directory = workdir / "a_directory"
        directory.mkdir()
        result = extract_pdf(directory)

        assert result.status is PdfExtractionStatus.FAILED
        assert result.error_code == ERROR_CODE_NOT_A_FILE

    def test_missing_file_is_rejected(self, workdir: Path) -> None:
        result = extract_pdf(workdir / "does_not_exist.pdf")
        assert result.status is PdfExtractionStatus.FAILED
        assert result.error_code == ERROR_CODE_NOT_FOUND


# ---------------------------------------------------------------------------
# 4.5-7 无可用文本层的 PDF
# ---------------------------------------------------------------------------


class TestNoTextLayer:
    def test_blank_pdf_is_needs_ocr_not_success(self, workdir: Path) -> None:
        """无文本层不得被误判为解析成功。"""
        path = write_bytes(workdir / "scan.pdf", build_blank_pdf(2))
        result = extract_pdf(path)

        assert result.status is PdfExtractionStatus.NEEDS_OCR
        assert result.needs_ocr
        assert result.is_success is False
        assert result.text_layer_available is False
        assert result.page_count == 2, "页数仍应如实反映文件结构"

    def test_blank_pages_are_present_but_empty(self, workdir: Path) -> None:
        path = write_bytes(workdir / "scan.pdf", build_blank_pdf(3))
        result = extract_pdf(path)

        assert len(result.pages) == 3
        for index, page in enumerate(result.pages, start=1):
            assert page.page_number == index
            assert page.text == ""
            assert page.has_text is False
        assert result.pages_with_text() == ()

    def test_whitespace_only_text_is_not_a_text_layer(self, workdir: Path) -> None:
        """只有空白字符不算有文本层。"""
        path = write_bytes(workdir / "ws.pdf", build_single_page_pdf("        "))
        result = extract_pdf(path)
        assert result.text_layer_available is False
        assert result.status is PdfExtractionStatus.NEEDS_OCR

    def test_result_rejects_text_layer_claim_when_not_cuccessful(self) -> None:
        """领域模型自身必须阻止"非成功状态却声称有文本层"。"""
        page = PdfPage(page_number=1, text="abc")
        with pytest.raises(ValueError, match="不得声称存在可用文本层"):
            PdfExtractionResult(
                file_hash="a" * 64,
                file_name="x.pdf",
                file_size_bytes=10,
                page_count=1,
                status=PdfExtractionStatus.NEEDS_OCR,
                text_layer_available=True,
                pages=(page,),
            )


# ---------------------------------------------------------------------------
# 4.5-8 文件哈希是否稳定
# ---------------------------------------------------------------------------


class TestFileHash:
    def test_hash_matches_hashlib(self, workdir: Path) -> None:
        data = build_cjk_pdf(["电费账单"])
        path = write_bytes(workdir / "h.pdf", data)
        assert compute_file_hash(path) == hashlib.sha256(data).hexdigest()

    def test_hash_is_stable_across_calls_and_paths(self, workdir: Path) -> None:
        data = build_single_page_pdf("same content")
        first = write_bytes(workdir / "a.pdf", data)
        second = write_bytes(workdir / "different_name.pdf", data)

        assert compute_file_hash(first) == compute_file_hash(second)
        assert extract_pdf(first).file_hash == extract_pdf(second).file_hash
        assert compute_file_hash(first) == compute_file_hash(first)

    def test_hash_changes_with_content(self, workdir: Path) -> None:
        one = write_bytes(workdir / "one.pdf", build_single_page_pdf("content one"))
        two = write_bytes(workdir / "two.pdf", build_single_page_pdf("content two"))
        assert extract_pdf(one).file_hash != extract_pdf(two).file_hash

    def test_hash_ignores_file_name(self, workdir: Path) -> None:
        """同一内容不同文件名必须得到相同哈希（任务书 7.3）。"""
        data = build_cjk_pdf(["内容一致"])
        a = extract_pdf(write_bytes(workdir / "2025-09.pdf", data))
        b = extract_pdf(write_bytes(workdir / "九月账单副本.pdf", data))
        assert a.file_hash == b.file_hash
        assert a.file_name != b.file_name

    def test_hash_of_missing_file_raises(self, workdir: Path) -> None:
        with pytest.raises(PdfExtractionError):
            compute_file_hash(workdir / "nope.pdf")


# ---------------------------------------------------------------------------
# 4.5-9 页码与文本是否一一对应
# ---------------------------------------------------------------------------


class TestPageNumberMapping:
    def test_page_numbers_are_sequential_from_one(self, workdir: Path) -> None:
        path = write_bytes(workdir / "m.pdf", build_multipage_pdf([f"unique-{i}" for i in range(1, 6)]))
        result = extract_pdf(path)

        assert [page.page_number for page in result.pages] == [1, 2, 3, 4, 5]

    def test_each_page_maps_to_its_own_text(self, workdir: Path) -> None:
        texts = [f"CONTENT-{i}-MARKER" for i in range(1, 6)]
        path = write_bytes(workdir / "m.pdf", build_multipage_pdf(texts))
        result = extract_pdf(path)

        for index, expected in enumerate(texts, start=1):
            assert expected in result.page(index).text

    def test_page_accessor_rejects_out_of_range(self, workdir: Path) -> None:
        path = write_bytes(workdir / "m.pdf", build_multipage_pdf(["only one"]))
        result = extract_pdf(path)
        with pytest.raises(IndexError):
            result.page(2)
        with pytest.raises(IndexError):
            result.page(0)

    def test_result_rejects_inconsistent_page_numbers(self) -> None:
        pages = (PdfPage(page_number=2, text="a"),)
        with pytest.raises(ValueError, match="页码必须从 1 连续递增"):
            PdfExtractionResult(
                file_hash="b" * 64,
                file_name="x.pdf",
                file_size_bytes=1,
                page_count=1,
                status=PdfExtractionStatus.SUCCESS,
                text_layer_available=True,
                pages=pages,
            )

    def test_result_rejects_page_count_mismatch(self) -> None:
        pages = (PdfPage(page_number=1, text="a"),)
        with pytest.raises(ValueError, match="page_count"):
            PdfExtractionResult(
                file_hash="c" * 64,
                file_name="x.pdf",
                file_size_bytes=1,
                page_count=2,
                status=PdfExtractionStatus.SUCCESS,
                text_layer_available=True,
                pages=pages,
            )


# ---------------------------------------------------------------------------
# 4.5-10 解析异常是否返回明确状态
# ---------------------------------------------------------------------------


class TestExplicitFailureStates:
    def test_every_failure_has_code_and_message(self, workdir: Path) -> None:
        cases = {
            "missing.pdf": None,
            "empty.pdf": b"",
            "notpdf.pdf": b"not a pdf at all",
            "corrupt.pdf": b"%PDF-1.4\ntruncated",
        }
        for name, data in cases.items():
            path = workdir / name
            if data is not None:
                path.write_bytes(data)
            result = extract_pdf(path)
            assert result.status is PdfExtractionStatus.FAILED, name
            assert result.error_code, f"{name} 缺少错误代码"
            assert result.errors, f"{name} 缺少错误信息"
            assert result.text_layer_available is False

    def test_failure_never_claims_pages(self, workdir: Path) -> None:
        path = write_bytes(workdir / "bad.pdf", b"garbage")
        result = extract_pdf(path)
        assert result.page_count == 0
        assert result.pages == ()
        assert result.total_char_count == 0

    def test_none_path_raises_programming_error(self) -> None:
        with pytest.raises(PdfExtractionError):
            extract_pdf(None)  # type: ignore[arg-type]

    def test_summarize_omits_full_text(self, workdir: Path) -> None:
        """摘要不得包含完整页文本（原始证据不进常规日志）。"""
        secret = "SENSITIVE-CUSTOMER-NAME"
        path = write_bytes(workdir / "s.pdf", build_single_page_pdf(secret))
        payload = summarize(extract_pdf(path))
        assert secret not in str(payload)
        assert payload["status"] == "success"
        assert "pages" not in payload


# ---------------------------------------------------------------------------
# 4.5-11 临时文件是否正确清理
# ---------------------------------------------------------------------------


class TestNoLeftoverFiles:
    def test_extraction_creates_no_extra_files(self, workdir: Path) -> None:
        """提取过程不写任何临时文件，目录内容不得变化。"""
        path = write_bytes(workdir / "keep.pdf", build_multipage_pdf(["a", "b"]))
        before = sorted(p.name for p in workdir.iterdir())

        extract_pdf(path)

        after = sorted(p.name for p in workdir.iterdir())
        assert after == before
        assert after == ["keep.pdf"]

    def test_no_temp_suffix_files(self, workdir: Path) -> None:
        path = write_bytes(workdir / "keep.pdf", build_single_page_pdf("x"))
        extract_pdf(path)
        leftovers = [p.name for p in workdir.iterdir() if p.suffix in {".tmp", ".temp", ".part"}]
        assert leftovers == []


# ---------------------------------------------------------------------------
# 4.5-12 原始 PDF 是否保持不变
# ---------------------------------------------------------------------------


class TestSourceFileUntouched:
    def test_content_and_mtime_unchanged(self, workdir: Path) -> None:
        data = build_multipage_pdf(["page one", "page two"])
        path = write_bytes(workdir / "original.pdf", data)
        before_bytes = path.read_bytes()
        before_stat = path.stat()

        extract_pdf(path)

        assert path.read_bytes() == before_bytes, "原始 PDF 内容不得被修改"
        after_stat = path.stat()
        assert after_stat.st_size == before_stat.st_size
        assert after_stat.st_mtime == before_stat.st_mtime

    def test_repeated_extraction_is_stable(self, workdir: Path) -> None:
        """重复提取同一文件必须得到一致结果（便于重复导入识别）。"""
        path = write_bytes(workdir / "repeat.pdf", build_multipage_pdf(["same", "content"]))
        first = extract_pdf(path)
        second = extract_pdf(path)

        assert first.file_hash == second.file_hash
        assert first.page_count == second.page_count
        assert [p.text for p in first.pages] == [p.text for p in second.pages]
        assert first.status is second.status


# ---------------------------------------------------------------------------
# 领域模型：文本规范化
# ---------------------------------------------------------------------------


class TestNormalizePageText:
    def test_none_becomes_empty_string(self) -> None:
        assert normalize_page_text(None) == ""

    def test_line_endings_are_unified(self) -> None:
        assert normalize_page_text("a\r\nb\rc") == "a\nb\nc"

    def test_trailing_whitespace_removed_but_content_kept(self) -> None:
        assert normalize_page_text("  金额 100 元   \n  电量 5 kWh  ") == "  金额 100 元\n  电量 5 kWh"

    def test_internal_content_is_not_modified(self) -> None:
        """真实账单的"数字换行截断""汉字间插空格"必须原样保留。"""
        raw = "输配需量电费 2143.225806 83585.81\n国 网 湖 北 省 电 力 公 司"
        assert normalize_page_text(raw) == raw

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError):
            normalize_page_text(123)  # type: ignore[arg-type]

    def test_meaningful_text_detection(self) -> None:
        assert is_meaningful_text("x") is True
        assert is_meaningful_text("  \n\t ") is False
        assert is_meaningful_text("") is False


class TestPdfPageModel:
    def test_page_number_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            PdfPage(page_number=0)
        with pytest.raises(ValueError):
            PdfPage(page_number=-1)

    def test_char_count_is_derived(self) -> None:
        page = PdfPage(page_number=1, text="电费账单")
        assert page.char_count == 4

    def test_snippet_collapses_whitespace(self) -> None:
        page = PdfPage(page_number=1, text="总  用电量\n8780498")
        assert page.snippet(10) == "总 用电量 8780"
        assert page.snippet(0) == ""
        assert len(page.snippet(4)) == 4

    def test_to_dict_is_serializable(self) -> None:
        page = PdfPage(page_number=1, text="abc")
        payload = page.to_dict()
        assert payload["page_number"] == 1
        assert payload["text"] == "abc"
        assert payload["has_text"] is True


class TestResultSerialization:
    def test_to_dict_has_required_fields(self, workdir: Path) -> None:
        path = write_bytes(workdir / "d.pdf", build_multipage_pdf(["x", "y"]))
        payload = extract_pdf(path).to_dict()

        for key in (
            "file_hash",
            "file_name",
            "page_count",
            "text_layer_available",
            "parser_name",
            "parser_version",
            "status",
            "pages",
            "errors",
        ):
            assert key in payload
        assert payload["page_count"] == 2
        assert len(payload["pages"]) == 2

    def test_failure_dict_keeps_none_not_zero(self, workdir: Path) -> None:
        """缺失/不可用必须保持 None，不能补成 0。"""
        path = write_bytes(workdir / "e.pdf", b"")
        payload = extract_pdf(path).to_dict()
        assert payload["error_code"] == ERROR_CODE_EMPTY_FILE
        assert payload["text_layer_available"] is False
        assert payload["pages"] == []


class TestParserMetadata:
    def test_parser_name_is_pypdf(self) -> None:
        assert PARSER_NAME == "pypdf"

    def test_parser_version_is_real_not_hardcoded(self) -> None:
        """解析器版本必须来自实际安装的库，便于结果追溯。"""
        import pypdf

        assert parser_version() == pypdf.__version__
        assert parser_version() != ""
