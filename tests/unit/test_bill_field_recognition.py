"""P0-2 字段识别测试（测试先行）。

覆盖 `docs/phase2/P0_2_TEST_CHECKLIST.md` 第 3.1–3.6 节中属于**首批范围**的用例：
账期（F1/F2）、正式总用电量（F3）、金额字段（F4/F5）、平均电价（F6）、
工商业电费与费用勾稽（F7），以及冲突 / 缺失 / 单位防错。

测试数据使用 `tests/unit/bill_fixtures.py` 中**已脱敏的最小红文本片段**，
不使用任何真实账单文件。

设计原则在断言中体现：

- 金额与电量一律 ``Decimal``，绝不与 ``float`` 比较；
- 缺失一律 ``None``，且断言**不等于 0**；
- 冲突时 ``value`` 必须为 ``None``（禁止静默择一）；
- 正式总用电量只能取权威字段，不得由计量点或分项求和。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from cenep.calculations.bill_parsing import (
    PARSING_VERSION,
    parse_bill_fields,
)
from cenep.domain.bill_fields import (
    FIELD_UNITS,
    REQUIRED_FIELDS,
    UNIT_KWH,
    UNIT_YUAN,
    UNIT_YUAN_PER_KWH,
    BillField,
    BillFieldSet,
    FieldName,
    FieldStatus,
    ReconciliationResult,
)
from cenep.domain.pdf_extraction import PdfExtractionStatus
from cenep.domain.validation import Severity
from tests.unit.bill_fixtures import (
    BILL_2025_09_SNIPPET,
    BILL_2025_10_SNIPPET,
    CUSTOMER_IDENTIFIER_KEYWORDS,
    EXPECTED_2025_09,
    EXPECTED_2025_10,
    FIVE_ITEM_KEYS,
)


def _parse(snippet: str, *, page_count: int = 1) -> BillFieldSet:
    """用单一页文本构造字段集（把整段片段当作第 1 页）。"""
    return parse_bill_fields([snippet], page_count=page_count)


def _value(fieldset: BillFieldSet, name: str | FieldName):
    return fieldset.require(name).value


# ---------------------------------------------------------------------------
# 3.1 账期（F1/F2）
# ---------------------------------------------------------------------------


class TestBillingPeriod:
    def test_parse_period_2025_09(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        assert _value(result, "billing_period_start") == date(2025, 9, 1)
        assert _value(result, "billing_period_end") == date(2025, 9, 30)

    def test_parse_period_2025_10(self) -> None:
        result = _parse(BILL_2025_10_SNIPPET)
        assert _value(result, "billing_period_start") == date(2025, 10, 1)
        assert _value(result, "billing_period_end") == date(2025, 10, 31)

    def test_parse_period_cross_month(self) -> None:
        snippet = "账单周期\n2025-08-26\n至\n2025-09-25\n本期电量\n1千瓦时"
        result = _parse(snippet)
        assert _value(result, "billing_period_start") == date(2025, 8, 26)
        assert _value(result, "billing_period_end") == date(2025, 9, 25)

    def test_parse_period_end_before_start_is_invalid(self) -> None:
        snippet = "账单周期\n2025-09-30\n至\n2025-09-01\n"
        result = _parse(snippet)
        period_end = result.require("billing_period_end")
        assert period_end.status is FieldStatus.INVALID
        assert period_end.value is None, "非法账期不得静默交换首尾"

    def test_parse_period_missing_returns_missing(self) -> None:
        result = _parse("本期电量\n100千瓦时\n")
        field_start = result.require("billing_period_start")
        assert field_start.status is FieldStatus.MISSING
        assert field_start.value is None
        assert field_start.requires_manual_confirmation is True

    def test_billing_days_computed_inclusive(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        assert result.billing_days == 30

    def test_dates_are_date_objects_not_strings(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        assert isinstance(_value(result, "billing_period_start"), date)
        assert result.require("billing_period_start").unit == FIELD_UNITS[FieldName.BILLING_PERIOD_START]


# ---------------------------------------------------------------------------
# 3.2 正式总用电量（F3）
# ---------------------------------------------------------------------------


class TestTotalConsumption:
    @pytest.mark.parametrize(
        "snippet, expected",
        [
            (BILL_2025_09_SNIPPET, Decimal("8780498")),
            (BILL_2025_10_SNIPPET, Decimal("7479418")),
        ],
    )
    def test_total_consumption_baseline(self, snippet: str, expected: Decimal) -> None:
        result = _parse(snippet)
        field_obj = result.require("total_consumption")
        assert field_obj.status is FieldStatus.PARSED
        assert field_obj.value == expected
        assert field_obj.unit == UNIT_KWH

    def test_total_consumption_label_value_on_different_lines(self) -> None:
        """标签与数值被换行分隔时仍能解析。"""
        snippet = " 本期电量\n 8780498千瓦时\n"
        assert _value(_parse(snippet), "total_consumption") == Decimal("8780498")
    def test_total_consumption_not_summed_from_metering_points(self) -> None:
        """权威字段优先：不得取计量点或分项电量。

        真实账单第 2 页的"电量明细"给出多个与总量**不同**的数值
        （8770300 / 8516838 等），解析必须只认权威标签"本期电量"，
        且不得把这些分项相加。
        """
        snippet = (
            " 本期电量\n 8780498千瓦时\n"
            "电量明细\n"
            "正向有功（总） 4126.42 4285.88 55000 8770300\n"
            "正向有功（尖峰） 387.11 402.71 55000 858000\n"
            "正向有功（总） 4128.92 4288.5 55000 8776900 0 9647 -263109 8516838\n"
        )
        field_obj = _parse(snippet).require("total_consumption")
        assert field_obj.value == Decimal("8780498")
        for wrong in (Decimal("8770300"), Decimal("8516838"), Decimal("8776900")):
            assert field_obj.value != wrong, f"不得取计量点值 {wrong}"

    def test_total_consumption_never_summed(self) -> None:
        """只有分项、没有权威字段时必须 missing，不得求和推导。"""
        snippet = (
            "正向有功（尖峰） 858000\n"
            "正向有功（峰） 2605350\n"
            "正向有功（谷） 1862300\n"
            "正向有功（平） 3444100\n"
        )
        field_obj = _parse(snippet).require("total_consumption")
        assert field_obj.status is FieldStatus.MISSING
        assert field_obj.value is None
        # 明确断言没有把分项加起来
        assert field_obj.value != Decimal("858000") + Decimal("2605350")

    def test_total_consumption_thousand_separator(self) -> None:
        snippet = " 本期电量\n 8,780,498千瓦时\n"
        assert _value(_parse(snippet), "total_consumption") == Decimal("8780498")

    def test_total_consumption_missing_is_none_not_zero(self) -> None:
        snippet = "账单周期\n2025-09-01\n至\n2025-09-30\n"
        field_obj = _parse(snippet).require("total_consumption")
        assert field_obj.value is None
        assert field_obj.value != Decimal(0), "缺失不得补成 0"

    def test_consumption_is_decimal_not_float(self) -> None:
        value = _value(_parse(BILL_2025_09_SNIPPET), "total_consumption")
        assert isinstance(value, Decimal)
        assert not isinstance(value, float)


# ---------------------------------------------------------------------------
# 3.3 金额字段（F4/F5）
# ---------------------------------------------------------------------------


class TestAmountFields:
    @pytest.mark.parametrize(
        "snippet, expected_total, expected_vat",
        [
            (BILL_2025_09_SNIPPET, Decimal("6699241.94"), Decimal("6534168.58")),
            (BILL_2025_10_SNIPPET, Decimal("5471334.24"), Decimal("5330721.18")),
        ],
    )
    def test_bill_total_and_vat_baseline(
        self, snippet: str, expected_total: Decimal, expected_vat: Decimal
    ) -> None:
        result = _parse(snippet)
        assert _value(result, "bill_total_amount") == expected_total
        assert _value(result, "vat_invoice_amount") == expected_vat
        assert result.require("bill_total_amount").unit == UNIT_YUAN

    def test_total_and_vat_are_separate_fields(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        total = _value(result, "bill_total_amount")
        vat = _value(result, "vat_invoice_amount")
        assert total != vat, "总金额与发票金额是不同数值，必须分别保存"
        assert total == Decimal("6699241.94")
        assert vat == Decimal("6534168.58")

    def test_amount_trailing_zero_equivalence(self) -> None:
        """1787644.30 与文本 1787644.3 按十进制数值相等。"""
        result = _parse(BILL_2025_10_SNIPPET)
        assert _value(result, "transmission_distribution_fee") == Decimal("1787644.30")
        assert _value(result, "system_operation_fee") == Decimal("325751.10")

    def test_amount_with_split_decimal_point(self) -> None:
        """10 月输配电费在原文中被切开：1787644. ⏎ 3 —— 必须拼接后解析。"""
        assert _value(_parse(BILL_2025_10_SNIPPET), "transmission_distribution_fee") == Decimal(
            "1787644.30"
        )

    def test_amount_parenthesised_negative(self) -> None:
        snippet = "功率因数调整电费 (9,206.37)\n"
        assert _value(_parse(snippet), "power_factor_adjustment_fee") == Decimal("-9206.37")

    def test_amount_unit_wan_yuan(self) -> None:
        snippet = " 本期电费\n 12.5万元\n"
        assert _value(_parse(snippet), "bill_total_amount") == Decimal("125000")

    def test_amount_unit_unknown_not_converted(self) -> None:
        """数值存在但单位无法确定时不得擅自按元处理。"""
        snippet = " 本期电费\n 6699241.94桶\n"
        field_obj = _parse(snippet).require("bill_total_amount")
        assert field_obj.status is not FieldStatus.PARSED, "单位不明不得判为 parsed"
        assert field_obj.value is None
        assert field_obj.requires_manual_confirmation is True

    def test_amounts_are_decimal_not_float(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        for name in ("bill_total_amount", "vat_invoice_amount", "industrial_commercial_fee"):
            value = _value(result, name)
            assert isinstance(value, Decimal), f"{name} 必须是 Decimal"
            assert not isinstance(value, float)

    def test_missing_amount_is_none_not_zero(self) -> None:
        snippet = "账单周期\n2025-09-01\n至\n2025-09-30\n"
        field_obj = _parse(snippet).require("bill_total_amount")
        assert field_obj.value is None
        assert field_obj.value != Decimal(0)


# ---------------------------------------------------------------------------
# 3.4 账单展示平均电价（F6）
# ---------------------------------------------------------------------------


class TestDisplayedAveragePrice:
    @pytest.mark.parametrize(
        "snippet, expected",
        [
            (BILL_2025_09_SNIPPET, Decimal("0.76297")),
            (BILL_2025_10_SNIPPET, Decimal("0.73152")),
        ],
    )
    def test_average_price_baseline(self, snippet: str, expected: Decimal) -> None:
        field_obj = _parse(snippet).require("displayed_average_price")
        assert field_obj.value == expected
        assert field_obj.unit == UNIT_YUAN_PER_KWH

    def test_average_price_unit_is_price_not_amount(self) -> None:
        """单价与金额不得混用字段。"""
        result = _parse(BILL_2025_09_SNIPPET)
        assert result.require("displayed_average_price").unit == UNIT_YUAN_PER_KWH
        assert result.require("bill_total_amount").unit == UNIT_YUAN
        # 电价与总金额是不同量纲，数值不应相等
        assert _value(result, "displayed_average_price") != _value(result, "bill_total_amount")

    def test_average_price_not_overwritten_by_recomputed(self) -> None:
        """账单标注的平均电价必须原样保留，重算值不得覆盖它。

        说明：9 月账单的重算值恰好等于展示值（0.76297），
        因此这里**不能**用"两者不同"来证明隔离性；
        正确的验证是：解析结果中的该字段始终来自账单原文证据，
        而不是由其他字段计算得出的。
        """
        result = _parse(BILL_2025_09_SNIPPET)
        field_obj = result.require("displayed_average_price")
        assert field_obj.value == Decimal("0.76297")
        # 值必须来自原文证据（账单标注），而不是重算
        assert field_obj.evidences, "展示平均电价必须带原文证据"
        assert any("0.76297" in ev.source_text for ev in field_obj.evidences)
        # 即便重算值恰好相同，字段的规则标识也必须指向原文取值规则
        assert all(ev.rule_id.startswith("displayed_average_price") for ev in field_obj.evidences)


# ---------------------------------------------------------------------------
# 3.5 费用分项与勾稽（F7）—— 含 R1 专项
# ---------------------------------------------------------------------------


class TestFeeItems:
    @pytest.mark.parametrize(
        "snippet, expected",
        [
            (BILL_2025_09_SNIPPET, EXPECTED_2025_09),
            (BILL_2025_10_SNIPPET, EXPECTED_2025_10),
        ],
    )
    def test_five_items_baseline(self, snippet: str, expected: dict) -> None:
        result = _parse(snippet)
        for name in (
            "market_purchase_fee",
            "grid_loss_fee",
            "transmission_distribution_fee",
            "system_operation_fee",
            "government_fund_fee",
        ):
            assert _value(result, name) == expected[name], f"{name} 与基线不一致"

    @pytest.mark.parametrize("snippet", [BILL_2025_09_SNIPPET, BILL_2025_10_SNIPPET])
    def test_industrial_commercial_fee_not_first_number_after_label(self, snippet: str) -> None:
        """R1 专项：标签内含 -110 / -35 电压等级，禁止取标签后第一个数字。"""
        field_obj = _parse(snippet).require("industrial_commercial_fee")
        assert field_obj.value is not None, "必须解析出工商业电费"
        assert field_obj.value != Decimal("-110"), "不得把电压等级 -110 当作金额"
        assert field_obj.value != Decimal("-35"), "不得把电压等级 -35 当作金额"

    def test_industrial_commercial_fee_baseline(self) -> None:
        assert _value(_parse(BILL_2025_09_SNIPPET), "industrial_commercial_fee") == Decimal(
            "6708448.31"
        )
        assert _value(_parse(BILL_2025_10_SNIPPET), "industrial_commercial_fee") == Decimal(
            "5509070.05"
        )

    def test_quantity_and_amount_on_same_line_distinguished(self) -> None:
        """8780498 6708448.31 —— 前者是电量，后者是金额。"""
        result = _parse(BILL_2025_09_SNIPPET)
        assert _value(result, "industrial_commercial_fee") == Decimal("6708448.31")
        assert _value(result, "total_consumption") == Decimal("8780498")

    def test_power_factor_adjustment_keeps_negative(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        value = _value(result, "power_factor_adjustment_fee")
        assert value == Decimal("-9206.37")
        assert value < 0, "负费用必须保留负号，不得取绝对值"

    def test_demand_charge_separate_and_not_in_five_items(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        demand = _value(result, "demand_charge")
        assert demand == Decimal("1202916")
        five_sum = sum(_value(result, key) for key in (
            "market_purchase_fee",
            "grid_loss_fee",
            "transmission_distribution_fee",
            "system_operation_fee",
            "government_fund_fee",
        ))
        assert five_sum != demand
        assert five_sum + demand != _value(result, "industrial_commercial_fee")


class TestReconciliation:
    @pytest.mark.parametrize(
        "snippet, expected",
        [
            (BILL_2025_09_SNIPPET, EXPECTED_2025_09),
            (BILL_2025_10_SNIPPET, EXPECTED_2025_10),
        ],
    )
    def test_reconciliation_relations_match_baseline(self, snippet: str, expected: dict) -> None:
        result = _parse(snippet)
        relations = {r.relation: r for r in result.reconciliations}
        assert relations, "必须产出勾稽结果"

        # 关系 1：五项之和 = 工商业电费
        rel1 = next(r for k, r in relations.items() if "five_items" in k or "industrial" in k)
        assert rel1.expected == expected["industrial_commercial_fee"]
        assert rel1.absolute_difference == Decimal("0.00")
        assert rel1.is_within_tolerance is True

        # 关系 2：工商业电费 + 功率因数调整 = 本期电费
        rel2 = next(r for k, r in relations.items() if "total" in k)
        assert rel2.expected == expected["bill_total_amount"]
        assert rel2.absolute_difference == Decimal("0.00")
        assert rel2.is_within_tolerance is True

    def test_reconciliation_participating_fields_recorded(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        for rel in result.reconciliations:
            assert rel.participating_fields, "必须记录参与字段以便追溯与展示"

    def test_reconciliation_does_not_modify_original_amounts(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        assert _value(result, "bill_total_amount") == Decimal("6699241.94")
        assert _value(result, "industrial_commercial_fee") == Decimal("6708448.31")


class TestReconciliationToleranceUnit:
    """容差行为直接用 ``ReconciliationResult`` 验证（不依赖解析器）。"""

    def _make(self, expected: str, actual: str) -> ReconciliationResult:
        return ReconciliationResult(
            relation="five_items_equals_industrial",
            expected=Decimal(expected),
            actual=Decimal(actual),
            participating_fields=("market_purchase_fee", "industrial_commercial_fee"),
        )

    def test_within_tolerance_exact(self) -> None:
        rel = self._make("100.00", "100.00")
        assert rel.absolute_difference == Decimal("0.00")
        assert rel.is_within_tolerance is True
        assert rel.to_issue() is None

    def test_within_tolerance_boundary_inclusive(self) -> None:
        """差额恰好等于 0.02 元视为通过（容差含边界）。"""
        rel = self._make("100.02", "100.00")
        assert rel.absolute_difference == Decimal("0.02")
        assert rel.is_within_tolerance is True
        assert rel.to_issue() is None

    def test_exceeds_tolerance_produces_warning(self) -> None:
        rel = self._make("100.03", "100.00")
        assert rel.is_within_tolerance is False
        issue = rel.to_issue()
        assert issue is not None
        assert issue.severity is Severity.WARNING
        assert "100.03" in issue.message and "100.00" in issue.message

    def test_negative_difference_uses_absolute_value(self) -> None:
        rel = self._make("99.99", "100.01")
        assert rel.difference == Decimal("-0.02")
        assert rel.is_within_tolerance is True

    def test_float_tolerance_rejected(self) -> None:
        with pytest.raises(TypeError):
            ReconciliationResult(
                relation="r",
                expected=Decimal("1"),
                actual=Decimal("1"),
                participating_fields=("a",),
                tolerance=0.02,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# 3.6 冲突、缺失与单位（防错专项）
# ---------------------------------------------------------------------------


class TestConflictHandling:
    def test_conflict_two_different_candidates_needs_review(self) -> None:
        snippet = " 本期电量\n 8780498千瓦时\n电量明细\n 本期电量\n 8770300千瓦时\n"
        field_obj = _parse(snippet).require("total_consumption")
        assert field_obj.status is FieldStatus.NEEDS_REVIEW
        assert field_obj.value is None, "冲突时不得选任何一个候选值"
        assert field_obj.requires_manual_confirmation is True
        assert set(field_obj.candidates) == {Decimal("8780498"), Decimal("8770300")}

    def test_conflict_does_not_pick_first(self) -> None:
        snippet = " 本期电量\n 111千瓦时\n 本期电量\n 999千瓦时\n"
        field_obj = _parse(snippet).require("total_consumption")
        assert field_obj.value is None
        assert field_obj.value != Decimal("111")

    def test_conflict_does_not_pick_max_or_min(self) -> None:
        snippet = " 本期电量\n 111千瓦时\n 本期电量\n 999千瓦时\n"
        field_obj = _parse(snippet).require("total_consumption")
        assert field_obj.value not in (Decimal("111"), Decimal("999"))

    def test_identical_candidates_are_single_value(self) -> None:
        # 两页给出相同数值：去重后只有一个候选，应判为 parsed
        result = parse_bill_fields(
            [" 本期电量\n 8780498千瓦时\n", " 本期电量\n 8780498千瓦时\n"], page_count=2
        )
        field_obj = result.require("total_consumption")
        assert field_obj.status is FieldStatus.PARSED
        assert field_obj.value == Decimal("8780498")
        assert len(set(field_obj.candidates)) == 1


class TestEvidenceAndTraceability:
    def test_every_parsed_field_has_evidence(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        for name, field_obj in result.fields.items():
            if field_obj.status is FieldStatus.PARSED:
                assert field_obj.evidences, f"{name} 缺少来源证据"
                for ev in field_obj.evidences:
                    assert ev.page_number >= 1
                    assert ev.source_text.strip()
                    assert ev.rule_id.strip()

    def test_evidence_preserves_original_text(self) -> None:
        """证据必须是原文，不得存入规范化后的文本。"""
        result = _parse(BILL_2025_09_SNIPPET)
        field_obj = result.require("total_consumption")
        joined = "\n".join(ev.source_text for ev in field_obj.evidences)
        assert "8780498" in joined

    def test_field_records_parser_version(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        assert result.parser_version == PARSING_VERSION
        for field_obj in result.fields.values():
            assert field_obj.parser_version == PARSING_VERSION

    def test_evidence_page_number_multi_page(self) -> None:
        """多页时证据页码必须指向真实来源页。"""
        page1 = "账单周期\n2025-09-01\n至\n2025-09-30\n"
        page2 = " 本期电量\n 8780498千瓦时\n"
        result = parse_bill_fields([page1, page2], page_count=2)
        field_obj = result.require("total_consumption")
        assert field_obj.evidence_pages() == (2,)


# ---------------------------------------------------------------------------
# 3.7 与 P0-1 的状态联动
# ---------------------------------------------------------------------------


class TestExtractionStatusLinkage:
    def test_partial_extraction_not_usable_for_calculation(self) -> None:
        result = parse_bill_fields(
            [BILL_2025_09_SNIPPET, ""],
            page_count=2,
            extraction_status=PdfExtractionStatus.PARTIAL,
        )
        assert result.is_complete_extraction is False
        assert result.is_usable_for_calculation is False, "部分提取不得进入正式测算"

    @pytest.mark.parametrize(
        "status",
        [PdfExtractionStatus.NEEDS_OCR, PdfExtractionStatus.FAILED],
    )
    def test_needs_ocr_and_failed_not_usable(self, status: PdfExtractionStatus) -> None:
        result = parse_bill_fields([BILL_2025_09_SNIPPET], page_count=1, extraction_status=status)
        assert result.is_usable_for_calculation is False

    def test_success_extraction_with_all_fields_is_usable(self) -> None:
        result = _parse(BILL_2025_09_SNIPPET)
        assert result.is_complete_extraction is True
        assert result.is_usable_for_calculation is True

    def test_parse_success_is_not_bill_valid(self) -> None:
        """解析成功不等于账单有效：字段集不携带任何"已确认"状态。"""
        result = _parse(BILL_2025_09_SNIPPET)
        payload = result.to_dict()
        assert "is_usable_for_calculation" in payload
        assert "confirmed" not in payload
        assert not hasattr(result, "is_confirmed")


# ---------------------------------------------------------------------------
# 3.8 非功能与脱敏自查
# ---------------------------------------------------------------------------


class TestFixtureRedaction:
    def test_fixture_contains_no_customer_identifiers(self) -> None:
        """夹具不得含客户标识。"""
        for snippet in (BILL_2025_09_SNIPPET, BILL_2025_10_SNIPPET):
            for keyword in CUSTOMER_IDENTIFIER_KEYWORDS:
                assert keyword not in snippet, f"夹具含客户标识关键词：{keyword}"

    def test_fixture_has_no_long_digit_identifiers(self) -> None:
        """不得出现 13 位以上连续数字（户号/电能表编号特征）。"""
        import re

        for snippet in (BILL_2025_09_SNIPPET, BILL_2025_10_SNIPPET):
            for match in re.findall(r"\d{13,}", snippet):
                pytest.fail(f"夹具疑似含长编号：{match}")


class TestParserPurity:
    def test_parser_is_deterministic(self) -> None:
        first = _parse(BILL_2025_09_SNIPPET)
        second = _parse(BILL_2025_09_SNIPPET)
        assert first.to_dict() == second.to_dict()

    def test_parsing_layer_has_no_float_in_money_path(self) -> None:
        """解析层源码中不得对金额使用 float()。"""
        import re
        from pathlib import Path

        directory = Path(__file__).resolve().parents[2] / "src" / "cenep" / "calculations" / "bill_parsing"
        offenders = []
        for path in directory.rglob("*.py"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bfloat\s*\(", line):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
        assert not offenders, "金额路径不得使用 float()：\n" + "\n".join(offenders)


class TestRequiredFieldDiscipline:
    def test_all_required_fields_declared(self) -> None:
        assert len(REQUIRED_FIELDS) == 7

    def test_missing_required_field_blocks_calculation(self) -> None:
        snippet = "账单周期\n2025-09-01\n至\n2025-09-30\n"  # 无任何金额字段
        result = _parse(snippet)
        assert result.all_required_fields_parsed is False
        assert result.is_usable_for_calculation is False

    def test_bill_field_rejects_unknown_name(self) -> None:
        with pytest.raises(ValueError, match="未知字段名"):
            BillField(name="total_amount", status=FieldStatus.MISSING, requires_manual_confirmation=True)
