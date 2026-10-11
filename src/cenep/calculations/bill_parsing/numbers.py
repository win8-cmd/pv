"""账单文本的数值与日期解析（纯函数）。

只做"文本 → 值"的转换，不做字段语义判断。

关键约束（来自真实账单实测，见 ``REAL_BILL_VERIFICATION.md``）：

1. **禁止取"标签后第一个数字"**：真实账单标签里含 ``-110千伏``、``-35千伏``
   等电压等级数字，盲目取第一个数字会得到 ``-110``。
2. 小数点与小数位可能被换行切开（``1787644.`` ⏎ ``3``），需先拼接。
3. 括号表示负数：``(9,206.37)`` → ``-9206.37``。
4. 单位可能独立出现（``万元``、``MWh``），必须按单位换算；
   **单位不明时不得擅自换算**，由调用方决定是否待复核。
5. 金额与电量一律 ``Decimal``，绝不使用 ``float``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable

__all__ = [
    "AMOUNT_PATTERN",
    "DATE_PATTERN",
    "MULTIPLIERS",
    "NUMBER_UNIT_SUFFIXES",
    "PARAMETER_UNITS",
    "YEN_UNITS",
    "KWH_UNITS",
    "PRICE_UNITS",
    "AmountMatch",
    "label_window",
    "normalize_for_matching",
    "parse_amount",
    "parse_date",
    "scan_amounts",
]

#: 日期：``YYYY-MM-DD``
DATE_PATTERN = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

#: 金额/电量字面量。
#:
#: **顺序很关键**：必须先匹配"带小数"的形态，否则 ``0.76297`` 会被截成 ``0``
#: （实测踩坑：平均电价被解析为 0）。
#: ``(?<!\d)`` 只防止数字中间截断，不排除前导 ``.``，
#: 因此句末句号（``1202916.``）不会被吃进来。
#:
#: **允许小数点与小数位之间夹行内空白**：真实账单会出现
#: ``1787644.`` ⏎ ``3``、``339059.`` ⏎ ``33`` 这类"小数位被换行切开"的形态。
#: 直接在模式里跨过去，**不修改文本**，从而保住"匹配位置 → 原文位置"的一一映射。
AMOUNT_PATTERN = re.compile(
    r"""
    (?<!\d)
    (?:
        \d+(?:,\d{3})*[ \t\u3000]*\.[ \t\u3000]*\n?[ \t\u3000]*\d+   # 1234.56 / 1,234,567.89
      | \d+(?:,\d{3})*                                             # 1234 / 1,234,567
    )
    """,
    re.VERBOSE,
)

#: 数字后紧跟这些词时，它不是金额/电量，而是**运行参数**（电压等级、频率等）
PARAMETER_UNITS: tuple[str, ...] = ("千伏安", "千伏", "千瓦", "千乏", "赫兹", "伏")
PARAMETER_UNITS_ASCII: tuple[str, ...] = ("kVA", "kV", "kW", "Hz", "V")

#: 兼容旧名（保留以避免外部引用失效）
NUMBER_UNIT_SUFFIXES: tuple[str, ...] = PARAMETER_UNITS + PARAMETER_UNITS_ASCII

#: 明确表示"金额"的单位（``￥`` 是账单中"合计"行常用的全角货币符号）
YEN_UNITS: tuple[str, ...] = ("元/千瓦时", "元/千瓦· 月", "万元", "亿元", "￥", "元")

#: 明确表示"电量"的单位
KWH_UNITS: tuple[str, ...] = ("万千瓦时", "千瓦时", "MWh", "kWh")

#: 明确表示"单价"的单位
PRICE_UNITS: tuple[str, ...] = ("元/千瓦时",)

#: 单位 → 换算倍率。只换算**明确写出**的单位。
MULTIPLIERS: dict[str, Decimal] = {
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
    "万千瓦时": Decimal("10000"),
    "MWh": Decimal("1000"),
    "kWh": Decimal("1"),
    "千瓦时": Decimal("1"),
    "元": Decimal("1"),
}

#: 汉字之间的**行内**空白（空格/制表符）。
#: **不能包含换行**：换行是"字段之间的分隔"，必须保留，
#: 否则相邻字段会被合并到同一"行"，逐行取数的前提就被破坏
#: （实测踩坑：``本期电量\n8780498千瓦时\n电量明细`` 被并成一行，
#: 导致 8780498 的窗口里混入计量点数值）。


@dataclass(frozen=True)
class AmountMatch:
    """一个数值候选。

    Attributes:
        value: 已按明确单位换算、并带上符号的数值。
        literal: 原文数值字面量。
        start/end: 在传入片段中的下标范围。
        unit: 识别到的单位；未识别为 ``None``。
        is_negative: 是否为负数（来自前导 ``-`` 或括号）。
        prefix: 数值之前的少量原文（用于判断符号与上下文）。
    """

    value: Decimal
    literal: str
    start: int
    end: int
    unit: str | None
    is_negative: bool
    prefix: str

    @property
    def is_amount(self) -> bool:
        """是否带明确的金额单位。"""
        return self.unit in YEN_UNITS

    @property
    def is_energy(self) -> bool:
        """是否带明确的电量单位。"""
        return self.unit in KWH_UNITS

    @property
    def is_price(self) -> bool:
        """是否带明确的单价单位。"""
        return self.unit in PRICE_UNITS

    @property
    def has_explicit_unit(self) -> bool:
        return self.unit is not None


def normalize_for_matching(text: str) -> str:
    """生成用于**匹配**的规范化文本：删除汉字之间的行内空格。

    只用于标签匹配；证据仍保存原文。

    **保留换行**：换行是字段之间的分隔，合并行会破坏逐行取数。

    实现委托给 :func:`build_index_map`，保证"规范化文本"与
    "位置映射"永远来自**同一套规则**，不会各自演化导致错位。
    """
    normalized, _ = build_index_map(text)
    return normalized


#: 规范化时被视为"汉字侧"的字符：**只含中日韩表意文字**。
#: 注意**不含**全角标点（``：``、``、`` 等）——若把标点也算作汉字侧，
#: ``户号： 用电类别`` 这类"标点+空格+汉字"会被误删空格，
#: 导致 :func:`build_index_map` 与 :func:`normalize_for_matching` 结果不一致。
_IDEOGRAPH = re.compile(r"[\u3000-\u9fff]")


def build_index_map(
    original: str,
    *,
    wrap_fixes: Mapping[str, str] | None = None,
) -> tuple[str, list[int]]:
    """生成匹配文本，并给出"匹配文本下标 → 原文下标"的映射。

    这是**证据必须来自原文**的关键工具：匹配在规范化/修复后的副本上进行，
    但证据片段要用原文，因此需要把匹配位置映射回原文。

    处理分两步（顺序固定）：

    1. **标签修复**（``wrap_fixes``）：把被换行切开的标签拼回整串
       （如 ``其中增值税专用发票金\\n额``）。该步骤会删除字符，
       因此位置映射必须同步跟踪。
    2. **行内空格删除**：只删"汉字之间"的空格（不含换行、不含标点相邻的空格），
       与 :func:`normalize_for_matching` 完全一致。

    Args:
        original: 原始页文本。
        wrap_fixes: ``{被切开的形态: 拼接后的形态}``；可选。

    Returns:
        ``(匹配文本, 映射表)``。``映射表[i]`` 是匹配文本第 ``i`` 个字符
        在原文中的下标；映射单调不减。
    """
    # --- 步骤 1：标签修复，同时跟踪原文位置 -------------------------------
    staged_chars: list[str] = []
    staged_positions: list[int] = []
    index = 0
    length = len(original)
    fixes = tuple((wrap_fixes or {}).items())
    while index < length:
        matched = False
        for broken, whole in fixes:
            if broken and original.startswith(broken, index):
                span = len(broken) - 1
                for offset, char in enumerate(whole):
                    staged_chars.append(char)
                    staged_positions.append(min(index + min(offset, span), length - 1))
                index += len(broken)
                matched = True
                break
        if matched:
            continue
        staged_chars.append(original[index])
        staged_positions.append(index)
        index += 1

    # --- 步骤 2：删除汉字之间的行内空格 -----------------------------------
    parts: list[str] = []
    mapping: list[int] = []
    staged_length = len(staged_chars)
    for position, char in enumerate(staged_chars):
        if char in " \t\u3000":
            previous = staged_chars[position - 1] if position > 0 else ""
            following = staged_chars[position + 1] if position + 1 < staged_length else ""
            if _IDEOGRAPH.match(previous) and _IDEOGRAPH.match(following):
                continue
        parts.append(char)
        mapping.append(staged_positions[position])
    return "".join(parts), mapping
    return "".join(parts), mapping


def minimal_evidence_span(
    normalized: str,
    start: int,
    end: int,
    *,
    context: int = 16,
) -> tuple[int, int]:
    """在**规范化文本**上求出一个"最小证据片段"的范围。

    片段以标签与数值为锚点，向两侧各取少量上下文，并在**换行处收敛**：

    - 起点回退到上一行行首（不跨行，避免带入无关内容）；
    - 终点默认收到本行行尾；
    - 若数值之后紧接着换行且换行后是**单位**，则吞掉该换行与单位，
      以保留"数值与单位被换行切开"的关键信息。

    Returns:
        ``(片段起点, 片段终点)``，均为规范化文本下标。
    """
    length = len(normalized)
    begin = max(0, start - context)
    # 起点不跨行：回退到本行行首
    line_start = normalized.rfind("\n", 0, start)
    if line_start >= 0:
        begin = max(begin, line_start + 1)

    finish = min(length, end + 6)
    # 终点不跨多行：默认收到本行行尾
    line_end = normalized.find("\n", end)
    if line_end >= 0:
        finish = min(finish, line_end)
    # 若"数值"之后紧接着换行，且换行后是单位，则把该换行与单位纳入片段
    tail_after_line = normalized[line_end + 1 : line_end + 9] if line_end >= 0 else ""
    if tail_after_line and _starts_with_unit(tail_after_line):
        unit_end = line_end + 1 + len(_leading_unit(tail_after_line))
        finish = max(finish, unit_end)
    return begin, finish


def _leading_unit(text: str) -> str:
    """返回文本开头的单位（若有）。"""
    stripped = text.lstrip()
    offset = len(text) - len(stripped)
    for unit in _KNOWN_UNITS:
        if stripped.startswith(unit):
            return " " * offset + unit
    return ""


def _starts_with_unit(text: str) -> bool:
    return bool(_leading_unit(text))


def span_to_original(
    span: tuple[int, int],
    mapping: list[int],
    original: str,
) -> str:
    """把规范化文本上的片段范围映射回原文，返回原文片段。

    映射表长度为 0（空文本）时返回空串。
    """
    if not mapping:
        return ""
    begin, end = span
    begin = max(0, min(begin, len(mapping) - 1))
    if end <= begin:
        return ""
    last = min(end, len(mapping)) - 1
    original_begin = mapping[begin]
    original_end = mapping[last] + 1
    # 向后吞掉与末字符同属"单位/换行"的原文空白，让片段读起来自然
    while original_end < len(original) and original[original_end] in " \t":
        original_end += 1
    return original[original_begin:original_end]


def label_value_lines(
    text: str,
    start: int,
    size: int = 60,
    *,
    max_skip: int = 1,
    is_value_line: Callable[[str], bool] | None = None,
) -> list[str]:
    """返回标签之后**逐行**的数值区候选行。

    调用方按顺序尝试；一次性返回多行是为了支持"标签与数值之间夹着
    若干说明行"的真实排版。

    Args:
        text: 规范化文本。
        start: 标签结束位置。
        size: 单行最大长度。
        max_skip: **允许跳过多少个"非数值行"**。
            真实账单的 ``工商业电费：`` 后面先跟标签自身的多行说明
            （``用电户-110千伏-...``、``工商业两部制、...``），
            数值在第 3 行才出现，因此该字段需要更大的跳过上限。
        is_value_line: 判定"这一行算不算数值行"的谓词；``None`` 时按
            "是否含任意数字"判断。调用方可用更严格的谓词
            （如"含金额形状数字"）跳过说明行。

    Returns:
        候选行列表（按出现顺序）。跳过超过 ``max_skip`` 行仍无数值时停止。
    """
    index = start
    length = len(text)
    while index < length and text[index] in " \t\r\n":
        index += 1

    lines: list[str] = []
    skipped = 0
    while index < length and skipped <= max_skip:
        limit = min(length, index + size)
        line_end = text.find("\n", index, limit)
        if line_end < 0:
            lines.append(text[index:limit])
            break
        line = text[index:line_end]
        is_value = (
            is_value_line(line) if is_value_line is not None else any(ch.isdigit() for ch in line)
        )
        if is_value:
            lines.append(line)
            # 找到数值即停止：一个"数值块"已经确定。
            # 若继续向后收集，会把相邻字段（峰谷比例、计量点明细等）
            # 的数字一并纳入，制造假冲突（实测踩坑）。
            break
        skipped += 1
        index = line_end + 1
        while index < length and text[index] in " \t\r\n":
            index += 1
    return lines


def label_values_block(text: str, start: int, size: int = 60) -> str:
    """兼容接口：返回标签之后"第一段可用的数值行"。

    仅供不需要区分行的调用方（如账期日期）使用；
    需要精确定位的字段请使用 :func:`label_value_lines`。
    """
    lines = label_value_lines(text, start, size)
    return lines[0] if lines else ""


#: 兼容旧名
def label_window(text: str, start: int, size: int = 60) -> tuple[str, int]:
    """兼容旧接口：返回 ``(数值区文本, 截断长度)``。"""
    block = label_values_block(text, start, size)
    return block, len(block)


#: 与数值直接相连但**不属于已知单位**的标记。
#: 用于区分"裸数值"（单位在表头，可采纳）与"带未知单位"（必须交人工复核）。
UNKNOWN_UNIT = "?"


#: 全部可识别单位，**按长度降序**排列。
#: 必须最长优先：``千瓦时``（电量）要先于 ``千瓦``（功率）匹配，
#: ``元/千瓦时``（单价）要先于 ``元``（金额）匹配（实测踩坑）。
_KNOWN_UNITS: tuple[str, ...] = tuple(
    sorted(
        set(
            PRICE_UNITS
            + KWH_UNITS
            + YEN_UNITS
            + PARAMETER_UNITS
            + PARAMETER_UNITS_ASCII
            + ("元/千瓦· 月",)
        ),
        key=len,
        reverse=True,
    )
)


def _unit_after(segment: str, end: int) -> str | None:
    """返回紧跟在数值之后的单位。

    Returns:
        - 已知单位字符串（``元``/``千瓦时``/``万元`` 等）；
        - :data:`UNKNOWN_UNIT`（``"?"``）：紧跟一个**无法识别**的单位字符，
          调用方应视为"单位不明"并交人工复核；
        - ``None``：后面是空白/换行/标点（**裸数值**，单位可能在表头），
          或者紧接的是**运行参数单位**（电压/功率/频率，
          如标签里的 ``-110千伏``／``-35千伏``）——两者都由调用方排除。
    """
    tail = segment[end : end + 8]
    for unit in _KNOWN_UNITS:
        if tail.startswith(unit):
            # 参数类单位（电压/功率/频率）不作为金额或电量单位返回，
            # 调用方据此把该数值排除。
            if unit in PARAMETER_UNITS or unit in PARAMETER_UNITS_ASCII:
                return None
            return unit

    if not tail or tail[0] in " \t\r\n":
        return None
    if tail[0].isascii() and not tail[0].isalnum():
        return None
    if tail[0] in "，。；：、（）()[]％%":
        return None
    # 紧跟一个不认识的非空白字符 → 单位不明
    return UNKNOWN_UNIT


def _is_parameter_construct(segment: str, start: int, end: int) -> bool:
    """判断数值是否属于"数字+运行参数单位"结构（电压等级等），应跳过。

    只对**参数类**单位返回 ``True``：电压（``千伏``/``伏``）、
    功率（``千瓦``）、频率（``赫兹``）等。
    电量单位（``千瓦时``）与金额单位（``元``）不属于参数，必须保留。

    Important:
        本函数**必须最长匹配**：``千瓦时`` 以 ``千瓦`` 开头，
        若按前缀判断会把电量单位误判为参数单位（实测踩坑：
        ``8780498千瓦时`` 因此被整条丢弃）。因此这里复用
        :func:`_unit_after` 的识别结果。
    """
    tail = segment[end : end + 8]
    # 先尝试识别完整单位；若识别出的已知单位不是参数类，则不是参数结构
    for unit in _KNOWN_UNITS:
        if tail.startswith(unit):
            return unit in PARAMETER_UNITS or unit in PARAMETER_UNITS_ASCII
    return False


def scan_amounts(segment: str) -> list[AmountMatch]:
    """扫描片段中的全部数值候选，附带符号、单位与换算结果。

    **不返回**："数字+运行参数单位"结构（``-110千伏`` 等）。
    """
    results: list[AmountMatch] = []
    for match in AMOUNT_PATTERN.finditer(segment):
        literal = match.group(0)
        start, end = match.start(), match.end()
        # 字面量可能含行内空白（小数位被换行切开的形态）；
        # 校验单位/符号时要用**非空白字符的末尾位置**。
        token_end = end
        while token_end > start and segment[token_end - 1] in " \t\u3000":
            token_end -= 1
        if _is_parameter_construct(segment, start, token_end):
            continue

        prefix_raw = segment[max(0, start - 12) : start]

        # 行首编号（``5.根据《省发改委...``、``1.本期电量``）不是业务数值。
        # 实测踩坑：备注段落以"5."开头，被当成金额 5 混入候选。
        # 判定：位于行首，且数值后面紧跟"点号 + 非数字"（真小数会继续跟数字）。
        if start == 0:
            remainder = segment[token_end:]
            if remainder.startswith(".") and not remainder[1:2].isdigit():
                continue

        # 被括号包住的**短整数**是条目编号（``(1)``、``(5)``），不是数值。
        # 实测踩坑：口径说明行 `3.工商业电费=(1)市场化购电电费+...`
        # 会把 `(1)`、`(5)` 当成金额候选，制造假冲突。
        #
        # 判定必须同时满足：
        #   - 左右都被括号包住（公式写作 ``+(5)`` 时前缀结尾是 ``)``，故不能只看前缀）；
        #   - 字面量是不含小数点与千分位的短整数。
        # 真实金额如 ``(9,206.37)`` 含小数/逗号，因此不会被误伤。
        prefix_stripped = prefix_raw.rstrip()
        suffix_raw = segment[token_end : token_end + 3]
        enclosed = prefix_stripped.endswith(("(", "（")) and suffix_raw.lstrip().startswith((")", "）"))
        if enclosed and "." not in literal and "," not in literal and len(literal) <= 3:
            continue

        unit = _unit_after(segment, token_end)
        if unit is None and start > 0 and segment[start - 1] == "￥":
            # 账单"合计"行使用前缀货币符号：￥6699241.94
            unit = "￥"

        # 符号：前导 '-'，或中文括号/半角括号包裹
        prefix = segment[max(0, start - 10) : start]
        is_negative = bool(re.search(r"-\s*$", prefix))
        suffix = segment[token_end : token_end + 3]
        # 括号负数的严格判定：左括号必须**独立**（行首或前面是空白/分隔符）。
        # 否则会把公式里的编号误判为负数
        # （实测踩坑：``(5)政府基金及附加`` 被解析成 -5）。
        stripped_prefix = prefix.rstrip()
        paren_standalone = (
            not stripped_prefix or stripped_prefix[-1] in " \t\u3000:：,，、(（+=/"
        )
        if (
            paren_standalone
            and stripped_prefix.endswith(("(", "（"))
            and suffix.lstrip().startswith((")", "）"))
        ):
            is_negative = True

        value = parse_amount(literal)
        if value is None:
            continue
        if unit is not None:
            value = value * MULTIPLIERS.get(unit, Decimal("1"))
        if is_negative:
            value = -abs(value)

        results.append(
            AmountMatch(
                value=value,
                literal=literal,
                start=start,
                end=end,
                unit=unit,
                is_negative=is_negative,
                prefix=prefix,
            )
        )
    return results


def parse_amount(literal: str) -> Decimal | None:
    """把金额/电量字面量转为 ``Decimal``（不含单位换算与符号）。

    容错：

    - 千分位 ``1,234.56``；
    - **字面量内部夹有空白/换行**（``1787644.\\n3``，小数位被换行切开）；
    - 句末句号（``1202916.``）——去掉尾点后按整数解析。

    Returns:
        ``Decimal``；无法解析时返回 ``None``（**不返回 0**）。
    """
    if not isinstance(literal, str):
        return None
    # 去掉内部所有空白（含换行）：这是"小数位被换行切开"形态的关键
    cleaned = re.sub(r"[\s\u3000]", "", literal).replace(",", "")
    if cleaned.endswith("."):
        cleaned = cleaned[:-1]
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date(text: str) -> tuple[int, int, int] | None:
    """从文本中解析第一个 ``YYYY-MM-DD``。

    Returns:
        ``(year, month, day)``；未找到或非法返回 ``None``
        （**不返回"今天"之类的默认值**）。
    """
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day


def join_wrapped_numbers(text: str) -> str:
    """把被换行切开的小数点拼接回去：``"1787644.\\n3"`` → ``"1787644.3"``。

    真实账单会出现 ``339059.`` ⏎ ``33``、``1787644.`` ⏎ ``3`` 这类形态。
    """
    return re.sub(r"(\d)\.\s*\n\s*(\d)", r"\1.\2", text)
