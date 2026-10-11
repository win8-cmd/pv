"""电费账单首批字段解析器。

**纯函数**：输入页文本序列，输出 :class:`~cenep.domain.bill_fields.BillFieldSet`。
不读写文件、不访问数据库、不依赖界面。

字段名与规则版本见 ``docs/phase2/P0_2_REGRESSION_BASELINE.md``。

防错要点（全部来自真实账单实测）：

- **R1**：禁止取"标签后第一个数字"。真实标签含 ``-110千伏``、``-35千伏``，
  盲目取数会得到 ``-110``/``-35``。本实现跳过"数字+参数单位"结构。
- **R2**：标签可能被换行切断（``其中增值税专用发票金`` ⏎ ``额``），需先拼接。
- **R3**：标签与数值可能被换行分隔，取数在标签后的窗口内扫描，
  且窗口在**空行处截断**（否则会取到下一段落的无关数值）。
- **R5**：数量与金额可能同行相邻（``8780498 6708448.31``）。
- **R6**：小数点与小数位可能被切开（``1787644.`` ⏎ ``3``），需先拼接。
- **R8**：正式总用电量只取权威标签 ``本期电量``；计量点明细行不参与候选。
- **冲突**：同一字段出现多个不同数值 → ``needs_review``，``value`` 保持 ``None``。
- **缺失**：保持 ``None``，绝不补 0。
- **单位**：单位不明时不擅自换算，置 ``needs_review``。
"""

from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from cenep.calculations.bill_parsing.numbers import (
    AMOUNT_PATTERN,
    KWH_UNITS,
    build_index_map,
    minimal_evidence_span,
    span_to_original,
    PRICE_UNITS,
    UNKNOWN_UNIT,
    YEN_UNITS,
    AmountMatch,
    normalize_for_matching,
    scan_amounts,
)
from cenep.domain.bill_fields import (
    FIELD_UNITS,
    BillField,
    BillFieldSet,
    FieldEvidence,
    FieldName,
    FieldStatus,
    ReconciliationResult,
)
from cenep.domain.pdf_extraction import PdfExtractionStatus
from cenep.domain.validation import Severity, ValidationIssue

__all__ = ["PARSING_VERSION", "parse_bill_fields"]

#: 解析规则版本。规则（标签、正则、口径）变化时必须提升。
PARSING_VERSION = "0.1.0"

#: 标签后用于取数的窗口长度（字符），窗口内遇空行即截断
SEARCH_WINDOW = 60

#: 单价类字段：单位写作 ``元/千瓦时``，与金额字段区分
_PRICE_FIELDS = frozenset({FieldName.DISPLAYED_AVERAGE_PRICE.value})

#: 电量类字段：要求单位明确为 kWh
_CONSUMPTION_FIELDS = frozenset({FieldName.TOTAL_CONSUMPTION.value})

#: 金额类字段：要求单位明确为 ``元``（或可换算的 万元/亿元）
_AMOUNT_FIELDS = frozenset(
    {
        FieldName.BILL_TOTAL_AMOUNT.value,
        FieldName.VAT_INVOICE_AMOUNT.value,
        FieldName.INDUSTRIAL_COMMERCIAL_FEE.value,
        FieldName.MARKET_PURCHASE_FEE.value,
        FieldName.GRID_LOSS_FEE.value,
        FieldName.TRANSMISSION_DISTRIBUTION_FEE.value,
        FieldName.SYSTEM_OPERATION_FEE.value,
        FieldName.GOVERNMENT_FUND_FEE.value,
        FieldName.POWER_FACTOR_ADJUSTMENT_FEE.value,
        FieldName.DEMAND_CHARGE.value,
    }
)

#: 明确表示"元"的单位集合（含可换算单位）——见 numbers.YEN_UNITS
#: 电量与单价单位集合同理来自 numbers 模块，避免两处定义不一致。

#: 标签字面量中可能被换行切开的形态（真实账单出现过）
#: 标签被换行切开的形态 → 拼接后的整串。
#: 供 :func:`build_index_map` 的 ``wrap_fixes`` 使用；该函数会同步维护
#: "匹配文本位置 → 原文位置"的映射，因此修复后证据仍取原文。
_LABEL_WRAP_FIXES: dict[str, str] = {
    "其中增值税专用发票金\n额": "其中增值税专用发票金额",
    "增值税专用发票金\n额": "增值税专用发票金额",
    "本期您的平均电\n价": "本期您的平均电价",
}


class _Rule:
    """一个字段的取数规则。"""

    __slots__ = ("field", "labels", "expects_unit", "prefer")

    def __init__(
        self,
        field: FieldName,
        labels: Sequence[str],
        *,
        expects_unit: str | None = "amount",
        prefer: str = "first",
    ) -> None:
        self.field = field
        self.labels = tuple(labels)
        #: 期望单位类别："amount"（元）/ "consume"（kWh）/ "price"（元/kWh）/ None（不校验）
        self.expects_unit = expects_unit
        #: 多候选时的选取策略："first"（默认，唯一候选才是常态）/"last"（数量+金额同行时取后者的金额）
        self.prefer = prefer


_RULES: tuple[_Rule, ...] = (
    _Rule(FieldName.TOTAL_CONSUMPTION, ("本期电量",), expects_unit="consume"),
    _Rule(FieldName.BILL_TOTAL_AMOUNT, ("本期电费",), expects_unit="amount"),
    _Rule(
        FieldName.VAT_INVOICE_AMOUNT,
        ("其中增值税专用发票金额", "增值税专用发票金额"),
        expects_unit="amount",
    ),
    _Rule(FieldName.DISPLAYED_AVERAGE_PRICE, ("本期您的平均电价", "平均电价"), expects_unit="price"),
    _Rule(FieldName.MARKET_PURCHASE_FEE, ("(1)市场化购电电费", "市场化购电电费"), expects_unit="amount"),
    _Rule(FieldName.GRID_LOSS_FEE, ("(2)上网环节线损费用", "上网环节线损费用"), expects_unit="amount"),
    _Rule(FieldName.TRANSMISSION_DISTRIBUTION_FEE, ("(3)输配电费", "输配电费"), expects_unit="amount"),
    _Rule(FieldName.SYSTEM_OPERATION_FEE, ("(4)系统运行费", "系统运行费"), expects_unit="amount"),
    _Rule(
        FieldName.GOVERNMENT_FUND_FEE,
        ("(5)政府性基金及附加", "政府性基金及附加"),
        expects_unit="amount",
    ),
    _Rule(FieldName.POWER_FACTOR_ADJUSTMENT_FEE, ("功率因数调整电费",), expects_unit="amount"),
    _Rule(
        FieldName.DEMAND_CHARGE,
        ("需（容）量电费为", "需(容)量电费为", "需（容）量电费", "需量电费"),
        expects_unit="amount",
    ),
)


class _Candidate:
    """一个候选值及其证据。"""

    __slots__ = ("value", "raw", "evidence", "unit")

    def __init__(self, value: Decimal, raw: str, evidence: FieldEvidence, unit: str | None) -> None:
        self.value = value
        self.raw = raw
        self.evidence = evidence
        self.unit = unit


@dataclass(frozen=True)
class _PageView:
    """一页的两种视图：用于匹配的文本 + 用于证据的原文与位置映射。

    **为什么必须并存**：匹配需要删掉汉字之间的空格才可靠，
    但证据必须是**原文**（任务书要求：不得把规范化文本冒充原文）。
    ``mapping[i]`` 给出匹配文本下标 ``i`` 对应的原文下标。
    """

    page_number: int
    original: str
    matched: str
    mapping: tuple[int, ...]

    def evidence_snippet(self, span: tuple[int, int]) -> str:
        """把匹配文本上的片段范围映射回原文，返回原文片段。"""
        return span_to_original(span, list(self.mapping), self.original)

    def line_spans(self, start: int, size: int, *, max_skip: int = 1, is_value_line=None):
        """从 ``start`` 起按行收集"数值块"，返回 ``[(行文本, 绝对起点, 序号)]``。

        收集规则与 :func:`cenep.calculations.bill_parsing.numbers.label_value_lines`
        一致（含"跳过若干说明行"和"命中数值即停止"），
        但额外给出每行在匹配文本中的**绝对起点**，以便把匹配位置映射回原文。
        """
        text = self.matched
        length = len(text)
        index = start
        while index < length and text[index] in " \t\r\n":
            index += 1

        predicate = is_value_line or (lambda line: any(ch.isdigit() for ch in line))
        results: list[tuple[str, int, int]] = []
        skipped = 0
        ordinal = 0
        while index < length and skipped <= max_skip:
            limit = min(length, index + size)
            line_end = text.find("\n", index, limit)
            if line_end < 0:
                results.append((text[index:limit], index, ordinal))
                break
            line = text[index:line_end]
            if predicate(line):
                results.append((line, index, ordinal))
                # 行尾是小数点 → 小数位被换行切开（``1787644.`` ⏎ ``3``），
                # 必须继续往后取，让"跨行数值模式"把它整体匹配，
                # 否则会被当成"整数 1787644"而在小数点处截断。
                if line.rstrip().endswith("."):
                    skipped += 1
                    ordinal += 1
                    index = line_end + 1
                    while index < length and text[index] in " \t\r\n":
                        index += 1
                    continue
                break
            skipped += 1
            ordinal += 1
            index = line_end + 1
            while index < length and text[index] in " \t\r\n":
                index += 1
        return results


def _build_page_views(pages: Sequence[str]) -> list[_PageView]:
    """把每页原文转成 :class:`_PageView`（匹配文本 + 位置映射）。"""
    views: list[_PageView] = []
    for index, original in enumerate(pages, start=1):
        matched, mapping = build_index_map(original, wrap_fixes=_LABEL_WRAP_FIXES)
        views.append(
            _PageView(
                page_number=index,
                original=original,
                matched=matched,
                mapping=tuple(mapping),
            )
        )
    return views


def _locate_labels(text: str, labels: Sequence[str]) -> list[tuple[int, str]]:
    """定位全部标签出现位置，按位置升序。"""
    hits: list[tuple[int, str]] = []
    for label in labels:
        start = 0
        while True:
            index = text.find(label, start)
            if index < 0:
                break
            hits.append((index, label))
            start = index + len(label)
    return sorted(hits)


def _unit_matches(unit: str | None, expects: str | None) -> bool:
    """判断识别到的单位是否满足字段的期望单位类别。"""
    if expects is None:
        return True
    if expects == "amount":
        return unit in YEN_UNITS
    if expects == "consume":
        return unit in KWH_UNITS
    if expects == "price":
        return unit in PRICE_UNITS
    return True


def _select_candidates(matches: Sequence[AmountMatch], expects: str | None) -> tuple[list[AmountMatch], int]:
    """从窗口内的全部数值里挑选属于本字段的候选。

    策略（对应任务书"多候选冲突进入人工复核、单位不明不擅自处理"）：

    1. **优先带明确期望单位的数值**（金额要 ``元``、电量要 ``kWh``、单价要 ``元/千瓦时``）。
       这一条直接挡住标签里的 ``-110千伏``（运行参数单位）与同行相邻的另一种量纲。
    2. 若窗口内**没有任何**带期望单位的数值，则本行的裸数值按字段类型采纳
       —— 真实账单确实存在只写数值、单位在表头的列（如费用明细表）。
    3. 裸数值多于一个且互不相同时，仍作为候选交给冲突判定（不在这里择一）。

    Returns:
        ``(候选列表, 因单位不符被排除的数量)``
    """
    typed = [m for m in matches if _unit_matches(m.unit, expects)]
    if typed:
        return typed, len(matches) - len(typed)
    # 无带期望单位的数值：只采纳**真正的裸数值**（无单位），
    # 带未知单位的数值（UNKNOWN_UNIT）一律不采纳，交人工复核。
    bare = [m for m in matches if m.unit is None]
    if bare:
        return bare, len(matches) - len(bare)
    return [], len(matches)


def _has_amount_like_number(line: str) -> bool:
    """判断该行是否含有"金额/电量形状"的数值。

    "金额形状" = 带千分位或带小数点。
    真实账单里的说明行含的是裸整数（``-110千伏``、``-35千伏``、``序号``），
    而真实金额行形如 ``8780498 6708448.31``。

    用于 :func:`label_value_lines` 判断"这一行算不算数值行"，
    从而跳过说明行去取真正的数据行（实测踩坑：
    ``工商业电费：`` 之后紧跟两行电压等级说明）。
    """
    for match in AMOUNT_PATTERN.finditer(line):
        literal = match.group(0)
        if "," in literal or "." in literal:
            return True
    return False


def _is_formula_line(line: str) -> bool:
    """判断是否为口径说明/公式行（非数据行）。

    真实账单末尾有"备注"段落，形如::

        3.工商业电费=(1)市场化购电电费+(2)上网环节线损费用+...

    这类行里出现的数字是**条目编号**，不是金额。若不排除，
    会把 ``(5)`` 之类误当作数值（实测踩坑）。
    """
    if "=" in line and "+" in line:
        return True
    return "+(" in line or "+（" in line


def _is_explanatory_line(line: str) -> bool:
    """判断是否为"说明/引用"行（非数据行）。

    真实账单的备注段落会**提到字段名但不含该字段的数值**，例如::

        5.根据《省发改委关于第三监管周期湖北电网输配电价有关事项的通知》
        (鄂发改价管[2023]163号)规定，...

    其中 ``[2023]``、``163`` 是文号，不是金额。若不排除，
    会混入候选并制造假冲突（实测踩坑）。
    """
    if "《" in line or "》" in line:
        return True
    if "[" in line or "]" in line:
        return True
    return "第" in line and "号" in line


#: 行尾这些字符表示"数值可能还被切断"，需要借下一行补全（通常是单位）
_LOOKAHEAD_TAIL = ("为", "是", "计", "＝", "=")

def _select_line_candidate(
    line: str,
    line_start: int,
    matches: Sequence[AmountMatch],
    expects: str | None,
) -> tuple[AmountMatch | None, int]:
    """从某行的全部数值中选出属于本字段的一个候选。

    返回 ``(选中的候选或 None, 被排除的数量)``。

    规则与 :func:`_select_candidates` 相同，但额外要求候选的**证据片段包含该数值**：
    真实账单里"标签名"也会出现在引用型文字中（如文号 ``[2023]163号``），
    这类数值不应算作候选（实测踩坑）。

    Args:
        line: 该行的匹配文本。
        line_start: 该行在整页匹配文本中的绝对起点。
        matches: 该行扫描出的全部数值（其下标相对 ``line``）。
        expects: 期望单位类别。
    """
    del line_start  # 目前仅用于文档说明；位置由调用方结合 match.start 计算
    selected, rejected = _select_candidates(matches, expects)
    if not selected:
        return None, rejected
    # 一行内同量纲多个数值时取第一个，其余计入排除
    rejected += len(selected) - 1
    return selected[0], rejected


def _collect_candidates(
    views: Sequence[_PageView], rule: _Rule
) -> tuple[list[_Candidate], int]:
    """收集候选值（匹配在 ``view.matched`` 上，证据取原文片段）。

    标签变体按规则顺序**优先级**处理：某页命中第一个**能取到数值**的变体后，
    该页不再尝试其余变体，也不再扫描后续页（后续页多为计量点/分时明细，
    口径与首页汇总不同）。

    同一标签在同一页的多次出现都会检查（这是"真冲突"的来源），
    但**按数值去重**——账单会把同一数值以不同措辞复述，那属于同一条数据。

    Returns:
        ``(候选列表, 因单位不符/单位不明被排除的数量)``。
    """
    candidates: list[_Candidate] = []
    rejected_for_unit = 0

    for view in views:
        for label in rule.labels:  # 标签变体按优先级
            label_candidates: list[_Candidate] = []
            seen_values: set[Decimal] = set()

            for label_start, _hit in _locate_labels(view.matched, (label,)):
                line_spans = view.line_spans(label_start + len(label), SEARCH_WINDOW)
                for line, line_start, ordinal in line_spans:
                    if _is_formula_line(line) or _is_explanatory_line(line):
                        continue
                    # 计量点明细行不做候选（R8）
                    if "正向有功" in line or "正向无功" in line:
                        continue
                    # 行尾是小数点 → 小数位被换行切开，拼接后续行后整体扫描
                    scan_text = line
                    if line.rstrip().endswith("."):
                        tails = [
                            later
                            for later, _s, later_ordinal in line_spans
                            if later_ordinal > ordinal
                        ]
                        if tails:
                            scan_text = line + "\n" + "\n".join(tails)

                    matches = scan_amounts(scan_text)
                    if not matches:
                        continue
                    chosen, rejected = _select_line_candidate(
                        scan_text, line_start, matches, rule.expects_unit
                    )
                    rejected_for_unit += rejected
                    if chosen is None:
                        continue
                    if chosen.value in seen_values:
                        continue

                    match_end = line_start + chosen.end
                    snippet = view.evidence_snippet(
                        minimal_evidence_span(view.matched, label_start, match_end)
                    )
                    # 证据片段必须真的包含这个数值，否则说明该标签只是被"提及"
                    # （如备注里的文号），不应作为候选。
                    normalized_literal = chosen.literal.replace("\n", "").replace(" ", "")
                    if normalized_literal not in snippet.replace("\n", "").replace(" ", ""):
                        continue

                    seen_values.add(chosen.value)
                    label_candidates.append(
                        _Candidate(
                            value=chosen.value,
                            raw=chosen.literal,
                            unit=chosen.unit,
                            evidence=FieldEvidence(
                                page_number=view.page_number,
                                source_text=snippet,
                                raw_value=chosen.literal,
                                label=label,
                                rule_id=f"{rule.field.value}.v1",
                            ),
                        )
                    )
                    break  # 每个标签出现处只取一个候选

            if label_candidates:
                return label_candidates, rejected_for_unit

    return candidates, rejected_for_unit


def _build_field(
    rule: _Rule,
    candidates: Sequence[_Candidate],
    *,
    rejected_for_unit: int = 0,
) -> BillField:
    """根据候选构造字段，落实冲突 / 单位不明 / 缺失规则。"""
    field_name = rule.field.value
    unit = FIELD_UNITS.get(rule.field)

    if not candidates:
        # 有数值但单位不明 → 不擅自换算，进入人工复核
        if rejected_for_unit:
            return BillField(
                name=field_name,
                status=FieldStatus.NEEDS_REVIEW,
                unit=None,
                value=None,
                candidates=(),
                issues=(
                    ValidationIssue(
                        issue_code="unit_unknown",
                        field_name=field_name,
                        message=(
                            f"{field_name} 找到数值但单位无法确定，未擅自换算；"
                            "已保持未定状态，请人工复核。"
                        ),
                        severity=Severity.WARNING,
                    ),
                ),
                parser_version=PARSING_VERSION,
                requires_manual_confirmation=True,
            )
        return BillField(
            name=field_name,
            status=FieldStatus.MISSING,
            unit=unit,
            value=None,
            issues=(
                ValidationIssue(
                    issue_code="field_missing",
                    field_name=field_name,
                    message=f"未找到字段 {field_name} 的权威标签，值保持为空（不补 0）。",
                    severity=Severity.WARNING,
                ),
            ),
            parser_version=PARSING_VERSION,
            requires_manual_confirmation=True,
        )

    all_evidence = tuple(c.evidence for c in candidates)
    distinct = sorted({c.value for c in candidates})

    if len(distinct) > 1:
        return BillField(
            name=field_name,
            status=FieldStatus.NEEDS_REVIEW,
            unit=unit,
            value=None,
            raw_value=candidates[0].raw,
            evidences=all_evidence,
            candidates=tuple(distinct),
            issues=(
                ValidationIssue(
                    issue_code="conflicting_candidates",
                    field_name=field_name,
                    message=(
                        f"{field_name} 出现多个不同候选值："
                        f"{'、'.join(str(v) for v in distinct)}。"
                        "已保持未定状态，请人工复核（不自动择一）。"
                    ),
                    severity=Severity.WARNING,
                ),
            ),
            parser_version=PARSING_VERSION,
            requires_manual_confirmation=True,
        )

    value = distinct[0]
    return BillField(
        name=field_name,
        status=FieldStatus.PARSED,
        unit=unit,
        value=value,
        raw_value=candidates[0].raw,
        evidences=all_evidence,
        candidates=tuple(distinct),
        issues=(),
        parser_version=PARSING_VERSION,
        requires_manual_confirmation=False,
    )


def _parse_period_dates(views: Sequence[_PageView]) -> tuple[BillField, BillField]:
    """解析账期开始日与结束日（证据取原文片段）。

    真实账单形态为::

        账单周期
        2025-09-01
        至
        2025-09-30

    规则：

    - 按日期在原文中出现的**先后顺序**判定：第一个是开始日，第二个是结束日；
    - 若第二个日期早于第一个（顺序颠倒），结束日置 ``invalid``，
      **不自动交换**——那会掩盖账单本身的数据错误；
    - 只有一个日期或没有日期时，结束日置 ``missing``。
    """
    found: list[tuple[date, FieldEvidence]] = []

    for view in views:
        anchor = view.matched.find("账单周期")
        if anchor < 0:
            continue
        # 账期横跨多行（开始日 / "至" / 结束日），因此取一块连续区域
        window_text = view.matched[anchor : anchor + 120]
        for match in _DATE_ITER(window_text):
            year, month, day = match
            try:
                value = date(year, month, day)
            except ValueError:
                continue
            literal = f"{year:04d}-{month:02d}-{day:02d}"
            offset = window_text.find(literal)
            absolute_start = anchor + (offset if offset >= 0 else 0)
            snippet = view.evidence_snippet(
                minimal_evidence_span(view.matched, anchor, absolute_start + len(literal))
            )
            found.append(
                (
                    value,
                    FieldEvidence(
                        page_number=view.page_number,
                        source_text=snippet,
                        raw_value=literal,
                        label="账单周期",
                        rule_id="billing_period.v1",
                    ),
                )
            )

    def _missing(field: FieldName, what: str) -> BillField:
        return BillField(
            name=field.value,
            status=FieldStatus.MISSING,
            unit=FIELD_UNITS.get(field),
            issues=(
                ValidationIssue(
                    issue_code="field_missing",
                    field_name=field.value,
                    message=f"未找到账期{what}，值保持为空。",
                    severity=Severity.WARNING,
                ),
            ),
            parser_version=PARSING_VERSION,
            requires_manual_confirmation=True,
        )

    if not found:
        return (
            _missing(FieldName.BILLING_PERIOD_START, "开始日"),
            _missing(FieldName.BILLING_PERIOD_END, "结束日"),
        )

    first_value = found[0][0]
    start_field = BillField(
        name=FieldName.BILLING_PERIOD_START.value,
        status=FieldStatus.PARSED,
        unit=FIELD_UNITS.get(FieldName.BILLING_PERIOD_START),
        value=first_value,
        raw_value=first_value.isoformat(),
        evidences=(found[0][1],),
        candidates=(),
        parser_version=PARSING_VERSION,
        requires_manual_confirmation=False,
    )

    if len(found) == 1:
        return start_field, _missing(FieldName.BILLING_PERIOD_END, "结束日")

    second_value = found[1][0]

    if second_value < first_value:
        # 顺序颠倒：属数据错误，置 invalid 并交人工确认（不自动交换）
        return start_field, BillField(
            name=FieldName.BILLING_PERIOD_END.value,
            status=FieldStatus.INVALID,
            unit=FIELD_UNITS.get(FieldName.BILLING_PERIOD_END),
            value=None,
            raw_value=second_value.isoformat(),
            evidences=(found[1][1],),
            candidates=(),
            issues=(
                ValidationIssue(
                    issue_code="period_end_before_start",
                    field_name=FieldName.BILLING_PERIOD_END.value,
                    message=(
                        f"账期结束日 {second_value.isoformat()} 早于开始日 "
                        f"{first_value.isoformat()}，顺序异常；请人工确认，不自动交换。"
                    ),
                    severity=Severity.ERROR,
                ),
            ),
            parser_version=PARSING_VERSION,
            requires_manual_confirmation=True,
        )

    return start_field, BillField(
        name=FieldName.BILLING_PERIOD_END.value,
        status=FieldStatus.PARSED,
        unit=FIELD_UNITS.get(FieldName.BILLING_PERIOD_END),
        value=second_value,
        raw_value=second_value.isoformat(),
        evidences=(found[1][1],),
        candidates=(),
        parser_version=PARSING_VERSION,
        requires_manual_confirmation=False,
    )


def _DATE_ITER(text: str):
    from cenep.calculations.bill_parsing.numbers import DATE_PATTERN

    for match in DATE_PATTERN.finditer(text):
        yield tuple(int(g) for g in match.groups())


def _parse_industrial_fee(views: Sequence[_PageView], rule: _Rule) -> BillField:
    """解析工商业电费（证据取原文片段）。

    真实账单该处形如::

        工商业电费：用电户-110千伏-大工业用电-...
        工商业两部制、用电户-35千伏-非居民照明-...
        明-工商业单一制
        8780498 6708448.31

    标签之后紧跟的是**电压等级**（``-110``、``-35``），必须跳过；
    真正的电费在若干行之后，且与计费电量同行（``电量 金额``），
    因此取该行**最后一个**裸数值（金额在后）。
    """
    candidates: list[_Candidate] = []
    rejected = 0
    seen_values: set[Decimal] = set()

    for view in views:
        for label in rule.labels:
            for label_start, _hit in _locate_labels(view.matched, (label,)):
                # 工商业电费在账单里会出现两次：
                #   ① 顶部"用能分析"，标签后跟多行说明，数值在后面几行；
                #   ② 末尾"口径说明" `3.工商业电费=(1)...`（公式，非数据）。
                # 因此放宽跳过上限，并显式跳过公式行与引用/说明行。
                line_spans = view.line_spans(
                    label_start + len(label),
                    SEARCH_WINDOW + 40,
                    max_skip=6,
                    is_value_line=_has_amount_like_number,
                )
                for line, line_start, _ordinal in line_spans:
                    if _is_formula_line(line) or _is_explanatory_line(line):
                        continue
                    matches = scan_amounts(line)
                    if not matches:
                        continue
                    typed = [m for m in matches if m.unit in YEN_UNITS]
                    if typed:
                        chosen = typed[0]
                    else:
                        bare = [m for m in matches if m.unit is None]
                        if not bare:
                            rejected += len(matches)
                            continue
                        chosen = bare[-1]  # "计费电量 金额"同行 → 金额在后

                    if chosen.value in seen_values:
                        continue
                    match_end = line_start + chosen.end
                    snippet = view.evidence_snippet(
                        minimal_evidence_span(view.matched, label_start, match_end)
                    )
                    normalized_literal = chosen.literal.replace("\n", "").replace(" ", "")
                    if normalized_literal not in snippet.replace("\n", "").replace(" ", ""):
                        continue
                    seen_values.add(chosen.value)
                    candidates.append(
                        _Candidate(
                            value=chosen.value,
                            raw=chosen.literal,
                            unit=chosen.unit,
                            evidence=FieldEvidence(
                                page_number=view.page_number,
                                source_text=snippet,
                                raw_value=chosen.literal,
                                label=label,
                                rule_id=f"{rule.field.value}.v1",
                            ),
                        )
                    )
                    break

            if candidates:
                return _build_field(rule, candidates, rejected_for_unit=rejected)

    return _build_field(rule, candidates, rejected_for_unit=rejected)


def _build_reconciliations(fields: dict[str, BillField]) -> tuple[ReconciliationResult, ...]:
    """构造费用勾稽结果。任一参与字段未确定则**不构造**（不得用 0 代入）。"""
    results: list[ReconciliationResult] = []

    five_names = (
        FieldName.MARKET_PURCHASE_FEE,
        FieldName.GRID_LOSS_FEE,
        FieldName.TRANSMISSION_DISTRIBUTION_FEE,
        FieldName.SYSTEM_OPERATION_FEE,
        FieldName.GOVERNMENT_FUND_FEE,
    )
    five_values = [fields[name.value].value for name in five_names]
    industrial = fields[FieldName.INDUSTRIAL_COMMERCIAL_FEE.value].value

    if all(isinstance(v, Decimal) for v in five_values) and isinstance(industrial, Decimal):
        results.append(
            ReconciliationResult(
                relation="five_items_equals_industrial_commercial",
                expected=sum(five_values, Decimal("0")),
                actual=industrial,
                participating_fields=tuple(n.value for n in five_names)
                + (FieldName.INDUSTRIAL_COMMERCIAL_FEE.value,),
            )
        )

    power_factor = fields[FieldName.POWER_FACTOR_ADJUSTMENT_FEE.value].value
    total = fields[FieldName.BILL_TOTAL_AMOUNT.value].value
    if (
        isinstance(industrial, Decimal)
        and isinstance(power_factor, Decimal)
        and isinstance(total, Decimal)
    ):
        results.append(
            ReconciliationResult(
                relation="industrial_plus_power_factor_equals_total",
                expected=industrial + power_factor,
                actual=total,
                participating_fields=(
                    FieldName.INDUSTRIAL_COMMERCIAL_FEE.value,
                    FieldName.POWER_FACTOR_ADJUSTMENT_FEE.value,
                    FieldName.BILL_TOTAL_AMOUNT.value,
                ),
            )
        )

    return tuple(results)


def parse_bill_fields(
    pages: Sequence[str],
    *,
    page_count: int | None = None,
    extraction_status: PdfExtractionStatus = PdfExtractionStatus.SUCCESS,
) -> BillFieldSet:
    """解析账单字段。

    Args:
        pages: 逐页文本（来自 P0-1 的 ``PdfExtractionResult.pages``）。
        page_count: 页数；``None`` 时取 ``len(pages)``。
        extraction_status: P0-1 的提取状态。**非 ``SUCCESS`` 时字段集不可用于测算。**

    Returns:
        :class:`~cenep.domain.bill_fields.BillFieldSet`。

    Note:
        业务问题（缺失、冲突、单位不明）通过字段状态表达，**不抛异常**，
        以便界面逐条展示并交人工复核。

        返回结果的 ``confirmation`` 为 ``PENDING``：**解析成功不等于可以进入
        正式测算**，必须经 :meth:`BillFieldSet.confirm` 人工确认。
    """
    views = _build_page_views(pages)
    resolved_page_count = len(pages) if page_count is None else page_count

    fields: dict[str, BillField] = {}

    period_start, period_end = _parse_period_dates(views)
    fields[FieldName.BILLING_PERIOD_START.value] = period_start
    fields[FieldName.BILLING_PERIOD_END.value] = period_end

    # 只认带冒号的形态：账单末尾的"口径说明"写作 `3.工商业电费=(1)...`，
    # 不含冒号；若也匹配，会从说明段落里取到无关数字（实测踩坑）。
    industrial_rule = _Rule(
        FieldName.INDUSTRIAL_COMMERCIAL_FEE, ("工商业电费：",), expects_unit="amount"
    )
    fields[FieldName.INDUSTRIAL_COMMERCIAL_FEE.value] = _parse_industrial_fee(
        views, industrial_rule
    )

    for rule in _RULES:
        candidates, rejected = _collect_candidates(views, rule)
        fields[rule.field.value] = _build_field(rule, candidates, rejected_for_unit=rejected)

    reconciliations = _build_reconciliations(fields)

    issues: list[ValidationIssue] = []
    for field_obj in fields.values():
        issues.extend(field_obj.issues)
    for rel in reconciliations:
        issue = rel.to_issue()
        if issue is not None:
            issues.append(issue)

    return BillFieldSet(
        fields=fields,
        parser_version=PARSING_VERSION,
        page_count=resolved_page_count,
        extraction_status=extraction_status,
        issues=tuple(issues),
        reconciliations=reconciliations,
    )
