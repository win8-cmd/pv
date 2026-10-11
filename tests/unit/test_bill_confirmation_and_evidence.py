"""为 PR #3 两项阻塞问题补充的回归测试（测试先行）。

覆盖：

- **任务一**：解析状态与"正式测算资格"必须分离——未确认不得进入正式测算。
- **任务二**：字段证据必须是"最小原文片段"，且来自**原文**而非规范化副本。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from cenep.calculations.bill_parsing import PARSING_VERSION, parse_bill_fields
from cenep.domain.bill_fields import (
    BillConfirmation,
    BillField,
    BillFieldSet,
    ConfirmationStatus,
    FieldName,
    FieldStatus,
)
from cenep.domain.pdf_extraction import PdfExtractionStatus
from tests.unit.bill_fixtures import BILL_2025_09_SNIPPET, BILL_2025_10_SNIPPET


def _parse(snippet: str, *, page_count: int = 1) -> BillFieldSet:
    return parse_bill_fields([snippet], page_count=page_count)


# ---------------------------------------------------------------------------
# 任务一：解析状态 vs 正式测算资格
# ---------------------------------------------------------------------------


class TestConfirmationIsRequiredForCalculation:
    """核心：**解析成功 ≠ 可进入正式测算**，必须经人工确认。"""

    def test_parsed_and_complete_but_unconfirmed_cannot_enter_calculation(self) -> None:
        """必需字段齐全、勾稽通过，但尚未确认 → 不得进入正式测算。"""
        result = _parse(BILL_2025_09_SNIPPET)

        # 解析层面确实全部成功
        assert result.is_complete_extraction is True
        assert result.all_required_fields_parsed is True
        assert result.has_reconciliation_mismatch is False
        assert result.is_parsed_and_ready_for_review is True

        # 但没有任何确认记录 → 不得进入正式测算
        assert result.confirmation.status is ConfirmationStatus.PENDING
        assert result.is_confirmed is False
        assert result.is_usable_for_calculation is False, (
            "未确认的账单不得被标记为可进入正式测算"
        )

    def test_confirmed_result_can_enter_calculation(self) -> None:
        """满足完整提取、字段复核、勾稽与确认后，才允许进入正式测算。"""
        result = _parse(BILL_2025_09_SNIPPET)
        confirmed = result.confirm(confirmed_by="tester", note="已逐字段核对原文")

        assert confirmed.confirmation.status is ConfirmationStatus.CONFIRMED
        assert confirmed.confirmation.confirmed_by == "tester"
        assert confirmed.confirmation.confirmed_at is not None
        assert confirmed.is_confirmed is True
        assert confirmed.is_usable_for_calculation is True

    def test_confirm_does_not_mutate_original_result(self) -> None:
        """确认返回新结果，原结果仍为未确认（不可变语义）。"""
        result = _parse(BILL_2025_09_SNIPPET)
        _ = result.confirm(confirmed_by="tester")
        assert result.confirmation.status is ConfirmationStatus.PENDING
        assert result.is_usable_for_calculation is False

    def test_confirmed_marker_alone_is_not_enough(self) -> None:
        """确认状态不能凭"解析成功"自动建立：必须显式给出确认人。"""
        result = _parse(BILL_2025_09_SNIPPET)
        with pytest.raises(ValueError, match="确认人"):
            result.confirm(confirmed_by="   ")

    def test_conflict_blocks_confirmation(self) -> None:
        """存在冲突的字段：即使试图确认，也必须拒绝。"""
        snippet = " 本期电量\n 8780498千瓦时\n电量明细\n 本期电量\n 8770300千瓦时\n"
        result = _parse(snippet)
        assert result.conflicted_fields == ("total_consumption",)
        with pytest.raises(ValueError):
            result.confirm(confirmed_by="tester")

    def test_missing_required_field_blocks_calculation_even_if_confirmed(self) -> None:
        """缺失必需字段：不得进入正式测算（且确认应被拒绝）。"""
        result = _parse("账单周期\n2025-09-01\n至\n2025-09-30\n")
        assert result.all_required_fields_parsed is False
        assert result.is_usable_for_calculation is False
        with pytest.raises(ValueError):
            result.confirm(confirmed_by="tester")

    def test_conflicted_never_usable_even_with_confirmation_flag(self) -> None:
        """冲突字段不得进入正式测算（构造为已确认也不能放行）。"""
        field = BillField(
            name=FieldName.TOTAL_CONSUMPTION.value,
            status=FieldStatus.NEEDS_REVIEW,
            unit="kWh",
            value=None,
            candidates=(Decimal("1"), Decimal("2")),
            requires_manual_confirmation=True,
        )
        fields = _full_required_fields()
        fields[FieldName.TOTAL_CONSUMPTION.value] = field
        result = BillFieldSet(
            fields=fields,
            parser_version=PARSING_VERSION,
            page_count=1,
            extraction_status=PdfExtractionStatus.SUCCESS,
            confirmation=BillConfirmation(
                status=ConfirmationStatus.CONFIRMED,
                confirmed_by="tester",
                confirmed_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
            ),
        )
        assert result.conflicted_fields == (FieldName.TOTAL_CONSUMPTION.value,)
        assert result.is_usable_for_calculation is False

    @pytest.mark.parametrize(
        "status",
        [
            PdfExtractionStatus.PARTIAL,
            PdfExtractionStatus.NEEDS_OCR,
            PdfExtractionStatus.FAILED,
        ],
    )
    def test_non_success_extraction_cannot_enter_calculation(
        self, status: PdfExtractionStatus
    ) -> None:
        """PDF 提取状态非 SUCCESS：不得进入正式测算。"""
        result = parse_bill_fields([BILL_2025_09_SNIPPET], page_count=1, extraction_status=status)
        assert result.is_complete_extraction is False
        assert result.is_usable_for_calculation is False
        with pytest.raises(ValueError):
            result.confirm(confirmed_by="tester")

    def test_reconciliation_mismatch_blocks_confirmation(self) -> None:
        """勾稽超差：需人工复核，不得直接确认进入测算。"""
        snippet = BILL_2025_09_SNIPPET.replace("6699241.94元", "6699249.94元")
        result = _parse(snippet)
        assert result.has_reconciliation_mismatch is True
        assert result.is_usable_for_calculation is False
        with pytest.raises(ValueError):
            result.confirm(confirmed_by="tester")

    def test_rejected_result_cannot_enter_calculation(self) -> None:
        """人工复核后判定"驳回"：不得进入正式测算。"""
        result = _parse(BILL_2025_09_SNIPPET)
        rejected = result.reject(rejected_by="tester", reason="账单影像不清晰")
        assert rejected.confirmation.status is ConfirmationStatus.REJECTED
        assert rejected.is_usable_for_calculation is False

    def test_confirmation_status_enum_covers_three_states(self) -> None:
        """必须显式区分：待确认 / 已确认 / 已驳回。"""
        assert {item.value for item in ConfirmationStatus} == {
            "pending",
            "confirmed",
            "rejected",
        }

    def test_review_status_is_exposed_without_confirmation(self) -> None:
        """确认尚未建立时，仍应能表达"可供复核"这一中间状态。"""
        result = _parse(BILL_2025_09_SNIPPET)
        assert result.is_parsed_and_ready_for_review is True
        assert result.is_confirmed is False
        payload = result.to_dict()
        assert payload["is_parsed_and_ready_for_review"] is True
        assert payload["is_confirmed"] is False
        assert payload["is_usable_for_calculation"] is False
        assert payload["confirmation"]["status"] == "pending"


def _full_required_fields() -> dict[str, BillField]:
    """构造一组合乎要求、可直接用于构造 BillFieldSet 的字段。"""
    from cenep.domain.bill_fields import FieldEvidence

    evidence = FieldEvidence(
        page_number=1,
        source_text="本期电量 8780498千瓦时",
        raw_value="8780498",
        label="本期电量",
        rule_id="total_consumption.v1",
    )
    return {
        FieldName.BILLING_PERIOD_START.value: BillField(
            name=FieldName.BILLING_PERIOD_START.value,
            status=FieldStatus.PARSED,
            unit="date",
            value=date(2025, 9, 1),
            evidences=(evidence,),
        ),
        FieldName.BILLING_PERIOD_END.value: BillField(
            name=FieldName.BILLING_PERIOD_END.value,
            status=FieldStatus.PARSED,
            unit="date",
            value=date(2025, 9, 30),
            evidences=(evidence,),
        ),
        FieldName.TOTAL_CONSUMPTION.value: BillField(
            name=FieldName.TOTAL_CONSUMPTION.value,
            status=FieldStatus.PARSED,
            unit="kWh",
            value=Decimal("8780498"),
            evidences=(evidence,),
        ),
        FieldName.BILL_TOTAL_AMOUNT.value: BillField(
            name=FieldName.BILL_TOTAL_AMOUNT.value,
            status=FieldStatus.PARSED,
            unit="元",
            value=Decimal("6699241.94"),
            evidences=(evidence,),
        ),
        FieldName.VAT_INVOICE_AMOUNT.value: BillField(
            name=FieldName.VAT_INVOICE_AMOUNT.value,
            status=FieldStatus.PARSED,
            unit="元",
            value=Decimal("6534168.58"),
            evidences=(evidence,),
        ),
        FieldName.DISPLAYED_AVERAGE_PRICE.value: BillField(
            name=FieldName.DISPLAYED_AVERAGE_PRICE.value,
            status=FieldStatus.PARSED,
            unit="元/kWh",
            value=Decimal("0.76297"),
            evidences=(evidence,),
        ),
        FieldName.INDUSTRIAL_COMMERCIAL_FEE.value: BillField(
            name=FieldName.INDUSTRIAL_COMMERCIAL_FEE.value,
            status=FieldStatus.PARSED,
            unit="元",
            value=Decimal("6708448.31"),
            evidences=(evidence,),
        ),
    }


# ---------------------------------------------------------------------------
# 任务二：证据必须是"最小原文片段"
# ---------------------------------------------------------------------------


class TestEvidenceIsMinimalOriginalSnippet:
    def test_evidence_contains_label_and_value(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        for name in ("total_consumption", "bill_total_amount", "vat_invoice_amount"):
            field_obj = result.require(name)
            joined = "".join(ev.source_text for ev in field_obj.evidences).replace("\n", "")
            label = field_obj.evidences[0].label.replace("\n", "")
            assert label in joined, f"{name} 证据应含标签"
            assert str(field_obj.value).split(".")[0] in joined, f"{name} 证据应含数值"

    def test_evidence_is_not_the_whole_page(self) -> None:
        """证据不得等于整页文本，且不得包含远离目标字段的内容。"""
        result = _parse(BILL_2025_09_SNIPPET)
        for name, field_obj in result.fields.items():
            for evidence in field_obj.evidences:
                assert evidence.source_text != BILL_2025_09_SNIPPET, f"{name} 证据等于整页文本"
                assert len(evidence.source_text) < len(BILL_2025_09_SNIPPET), (
                    f"{name} 证据未做截短"
                )

    def test_evidence_excludes_unrelated_far_content(self) -> None:
        """证据不得包含页面远端（末尾）的无关内容。"""
        result = _parse(BILL_2025_09_SNIPPET)
        # 该片段位于页面末尾，离"本期电量"很远
        far_marker = "平均电价0.76297"
        field_obj = result.require("total_consumption")
        for evidence in field_obj.evidences:
            assert far_marker not in evidence.source_text, "证据包含远离目标字段的内容"

    def test_evidence_excludes_other_fields_values(self) -> None:
        """证据不应把相邻字段的数值一起带上（保持最小）。"""
        result = _parse(BILL_2025_09_SNIPPET)
        field_obj = result.require("total_consumption")
        for evidence in field_obj.evidences:
            assert "6699241.94" not in evidence.source_text, "证据混入了本期电费金额"

    def test_evidence_preserves_cross_line_unit(self) -> None:
        """数值与单位被换行切开时，证据必须能追溯（保留换行与单位）。"""
        snippet = (
            "本期电量\n 8780498千瓦时\n"
            "剩余优先发电价差损益 86926.94 本期您的实际功率因数调整电费为-9206.37\n"
            "元，较上期增长38385.73元。\n"
        )
        result = _parse(snippet)
        field_obj = result.require("power_factor_adjustment_fee")
        assert field_obj.value == Decimal("-9206.37")
        joined = "\n".join(ev.source_text for ev in field_obj.evidences)
        assert "-9206.37" in joined, "证据必须含负号与数值"
        assert "元" in joined, "证据必须保留跨行的单位"
        assert "38385.73" not in joined, "证据不得带入同行之后的无关数值"

    def test_evidence_preserves_split_decimal_point(self) -> None:
        """小数位被换行切开时，证据仍能追溯该数值。"""
        result = _parse(BILL_2025_10_SNIPPET)
        field_obj = result.require("transmission_distribution_fee")
        assert field_obj.value == Decimal("1787644.30")
        joined = "".join(ev.source_text for ev in field_obj.evidences).replace("\n", "")
        assert "1787644" in joined

    def test_evidence_comes_from_original_not_normalized(self) -> None:
        """证据必须来自原文：原文中的行内空格应被保留。"""
        snippet = " 本期电量\n 8780498千瓦时\n"
        spaced = "电 费 账 单\n" + snippet
        result = _parse(spaced)
        field_obj = result.require("total_consumption")
        for evidence in field_obj.evidences:
            # 规范化会删掉"电 费 账 单"里的空格；证据里若出现该短语，
            # 必须保持原文的空格形态
            if "电费账单" in evidence.source_text.replace(" ", ""):
                assert "电 费 账 单" in evidence.source_text, (
                    "证据疑似来自规范化副本而非原文"
                )

    def test_evidence_snippet_is_local_for_every_parsed_field(self) -> None:
        """所有已解析字段的证据都应远小于整页。"""
        result = _parse(BILL_2025_09_SNIPPET)
        page_length = len(BILL_2025_09_SNIPPET)
        for name, field_obj in result.fields.items():
            if field_obj.status is not FieldStatus.PARSED:
                continue
            for evidence in field_obj.evidences:
                assert len(evidence.source_text) <= page_length // 2, (
                    f"{name} 证据过长（{len(evidence.source_text)}/{page_length}）"
                )

    def test_evidence_page_number_correct_multi_page(self) -> None:
        """多页文档：证据页码必须指向真实来源页。"""
        page1 = "账单周期\n2025-09-01\n至\n2025-09-30\n"
        page2 = " 本期电量\n 8780498千瓦时\n"
        page3 = " 本期电费\n 6699241.94元\n"
        result = parse_bill_fields([page1, page2, page3], page_count=3)
        assert result.require("total_consumption").evidence_pages() == (2,)
        assert result.require("bill_total_amount").evidence_pages() == (3,)
        assert result.require("billing_period_start").evidence_pages() == (1,)

    def test_evidence_source_text_is_not_normalized_copy(self) -> None:
        """证据文本必须能在**原始页文本**中找到（逐字符）。"""
        page = " 本期电量\n 8780498千瓦时\n 本期电费\n 6699241.94元\n"
        result = parse_bill_fields([page], page_count=1)
        for field_obj in result.fields.values():
            for evidence in field_obj.evidences:
                assert evidence.source_text in page, (
                    "证据片段必须是原始页文本的连续子串"
                )

    def test_redaction_checks_still_hold(self) -> None:
        """脱敏要求继续满足：证据不得含客户标识。"""
        from tests.unit.bill_fixtures import CUSTOMER_IDENTIFIER_KEYWORDS

        result = _parse(BILL_2025_09_SNIPPET)
        for field_obj in result.fields.values():
            for evidence in field_obj.evidences:
                for keyword in CUSTOMER_IDENTIFIER_KEYWORDS:
                    assert keyword not in evidence.source_text
