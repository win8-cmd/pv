"""`needs_manual_review` 语义专项回归测试（规格书第四十四节）。

规格书要求：**以下任一情况必须触发人工复核**——

1. 数据尚未解析就绪；
2. 数据尚未得到确认。

必须有回归测试确保该状态**不能被错误判定为"无需复核"**。

这些用例**以 `needs_manual_review` 本身为断言目标**（此前的用例是间接覆盖），
用来锁死"未就绪必复核、未确认必复核"这两条闸门与
"只有就绪且确认才无需复核"这一唯一豁免路径。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cenep.calculations.bill_parsing import parse_bill_fields
from cenep.domain.bill_fields import BillField, BillFieldSet, FieldName, FieldStatus
from cenep.domain.pdf_extraction import PdfExtractionStatus
from tests.unit.bill_fixtures import BILL_2025_09_SNIPPET

CONFIRMED_BY = "regression-tester"


def _parse(snippet: str = BILL_2025_09_SNIPPET, **kwargs) -> BillFieldSet:
    return parse_bill_fields([snippet], page_count=1, **kwargs)


# ---------------------------------------------------------------------------
# 条件①：数据尚未解析就绪 → 必须人工复核
# ---------------------------------------------------------------------------


class TestNotParsedRequiresManualReview:
    """未就绪（提取不完整 / 缺失 / 冲突 / 勾稽超差）一律需要人工复核。"""

    @pytest.mark.parametrize(
        "status",
        [
            PdfExtractionStatus.PARTIAL,
            PdfExtractionStatus.NEEDS_OCR,
            PdfExtractionStatus.FAILED,
            PdfExtractionStatus.DUPLICATE,
        ],
    )
    def test_extraction_not_success_requires_manual_review(
        self, status: PdfExtractionStatus
    ) -> None:
        """提取状态非 SUCCESS：未就绪 → 必须人工复核。"""
        result = _parse(extraction_status=status)
        assert result.is_complete_extraction is False
        assert result.is_parsed_and_ready_for_review is False
        assert result.needs_manual_review is True, f"{status.value} 必须要求人工复核"
        assert result.is_usable_for_calculation is False

    def test_missing_required_field_requires_manual_review(self) -> None:
        """必需字段缺失：未就绪 → 必须人工复核。"""
        result = _parse("账单周期\n2025-09-01\n至\n2025-09-30\n")
        assert result.all_required_fields_parsed is False
        assert result.needs_manual_review is True
        assert result.missing_fields, "应能列出缺失字段"

    def test_conflicting_field_requires_manual_review(self) -> None:
        """同一字段出现多个不同候选：未就绪 → 必须人工复核。"""
        snippet = " 本期电量\n 8780498千瓦时\n电量明细\n 本期电量\n 8770300千瓦时\n"
        result = _parse(snippet)
        assert result.conflicted_fields == (FieldName.TOTAL_CONSUMPTION.value,)
        assert result.is_parsed_and_ready_for_review is False
        assert result.needs_manual_review is True

    def test_reconciliation_mismatch_requires_manual_review(self) -> None:
        """勾稽超差：未就绪 → 必须人工复核。"""
        snippet = BILL_2025_09_SNIPPET.replace("6699241.94元", "6699249.94元")
        result = _parse(snippet)
        assert result.has_reconciliation_mismatch is True
        assert result.needs_manual_review is True

    def test_not_ready_always_blocking_reasons_not_empty(self) -> None:
        """未就绪时必须给出可展示的阻塞原因，便于界面形成复核待办。"""
        result = _parse("", extraction_status=PdfExtractionStatus.FAILED)
        assert result.needs_manual_review is True
        assert result.blocking_reasons, "未就绪却没有任何阻塞原因说明"


# ---------------------------------------------------------------------------
# 条件②：数据尚未确认 → 必须人工复核
# ---------------------------------------------------------------------------


class TestUnconfirmedRequiresManualReview:
    """完全就绪但未确认：仍然必须人工复核。"""

    def test_ready_but_unconfirmed_requires_manual_review(self) -> None:
        result = _parse()
        # 就绪
        assert result.is_parsed_and_ready_for_review is True
        # 但未确认 → 必须复核
        assert result.is_confirmed is False
        assert result.needs_manual_review is True, "未确认的账单必须要求人工复核"
        assert result.is_usable_for_calculation is False

    def test_rejected_requires_manual_review(self) -> None:
        """被驳回的结果仍需人工处理，不得视为无需复核。"""
        rejected = _parse().reject(rejected_by=CONFIRMED_BY, reason="影像不清晰")
        assert rejected.is_confirmed is False
        assert rejected.needs_manual_review is True
        assert rejected.is_usable_for_calculation is False


# ---------------------------------------------------------------------------
# 唯一豁免路径：就绪 **且** 已确认
# ---------------------------------------------------------------------------


class TestOnlyReadyAndConfirmedSkipsManualReview:
    def test_ready_and_confirmed_does_not_need_manual_review(self) -> None:
        confirmed = _parse().confirm(confirmed_by=CONFIRMED_BY)
        assert confirmed.is_parsed_and_ready_for_review is True
        assert confirmed.is_confirmed is True
        assert confirmed.needs_manual_review is False, "就绪且已确认才可免除人工复核"
        assert confirmed.is_usable_for_calculation is True

    def test_confirmation_alone_cannot_skip_review(self) -> None:
        """只"已确认"但未就绪：仍必须复核（确认闸门拒绝该确认）。"""
        result = _parse("账单周期\n2025-09-01\n至\n2025-09-30\n")
        with pytest.raises(ValueError):
            result.confirm(confirmed_by=CONFIRMED_BY)
        assert result.needs_manual_review is True

    def test_needs_manual_review_is_exactly_not_usable_or_not_confirmed(self) -> None:
        """语义不变式：``needs_manual_review == not is_confirmed``。"""
        samples = [
            _parse(),
            _parse(extraction_status=PdfExtractionStatus.PARTIAL),
            _parse("账单周期\n2025-09-01\n至\n2025-09-30\n"),
            _parse().confirm(confirmed_by=CONFIRMED_BY),
        ]
        for result in samples:
            assert result.needs_manual_review is (not result.is_confirmed)

    def test_cannot_mark_usable_without_confirmation_via_any_public_route(self) -> None:
        """不得存在"未确认却可用"的公开路径。

        遍历公开属性与 `to_dict()`：只要 `is_confirmed` 为假，
        `is_usable_for_calculation` 必须为假，且 `needs_manual_review` 必须为真。
        """
        for result in (
            _parse(),
            _parse(extraction_status=PdfExtractionStatus.PARTIAL),
            _parse(""),
        ):
            payload = result.to_dict()
            if not result.is_confirmed:
                assert result.is_usable_for_calculation is False
                assert payload["is_usable_for_calculation"] is False
                assert payload["needs_manual_review"] is True
                assert payload["confirmation"]["status"] in {"pending", "rejected"}


# ---------------------------------------------------------------------------
# 边界：字段级复核标记同样必须触发复核
# ---------------------------------------------------------------------------


class TestFieldLevelReviewFlagPropagates:
    def test_field_requiring_confirmation_blocks_readiness(self) -> None:
        """任一字段要求人工确认，字段集即"未就绪"，从而需要复核。"""
        result = _parse()
        target = result.require(FieldName.TOTAL_CONSUMPTION)
        rebuilt = BillField(
            name=target.name,
            status=FieldStatus.MISSING,
            unit=target.unit,
            value=None,
            requires_manual_confirmation=True,
        )
        fields = dict(result.fields)
        fields[target.name] = rebuilt
        mutated = BillFieldSet(
            fields=fields,
            parser_version=result.parser_version,
            page_count=result.page_count,
            extraction_status=result.extraction_status,
            reconciliations=result.reconciliations,
        )
        assert mutated.fields_requiring_review, "应能列出待复核字段"
        assert mutated.is_parsed_and_ready_for_review is False
        assert mutated.needs_manual_review is True
        assert mutated.is_usable_for_calculation is False

    def test_amount_missing_is_none_not_zero(self) -> None:
        """复核相关边界：缺失金额为 None，绝不为 0。"""
        result = _parse("账单周期\n2025-09-01\n至\n2025-09-30\n")
        field = result.require(FieldName.BILL_TOTAL_AMOUNT)
        assert field.value is None
        assert field.value != Decimal(0)
        assert field.requires_manual_confirmation is True
