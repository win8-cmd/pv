# P0-2 字段与证据模型设计

- 设计日期：2026-10-11
- 适用任务：第二阶段 P0-2（电费账单关键字段识别）
- 状态：**设计已冻结，代码未实现**（P0-2 代码将在 PR #2 合并后于独立分支开发）

---

## 1. 设计目标

1. 每个识别出的字段都能**追溯到来源页与原文片段**（可审计）。
2. **缺失保持缺失**，绝不用 0 填充。
3. **冲突不静默取一个**，必须显式暴露并进入人工复核。
4. 单位与量纲不混用：`元/kWh`（单价）、`元`（金额）、`kWh`（电量）严格区分。
5. 解析规则**带版本号**，便于账单版式变化时追溯与维护。
6. 解析器**纯函数**：输入页文本，输出结构化结果；不碰 PDF 文件、不碰数据库、不碰界面。

---

## 2. 分层与放置位置（遵守既有架构约束）

| 组件 | 放置位置 | 允许依赖 | 禁止依赖 |
|---|---|---|---|
| 字段与证据模型（本设计第 3–5 节） | `src/cenep/domain/bill_fields.py` | 标准库（`dataclasses`/`enum`/`decimal`） | pypdf、Qt、sqlite3 |
| 字段解析器 | `src/cenep/calculations/bill_parsing/` | 标准库、`cenep.domain` | pypdf、Qt、sqlite3、pandas |
| 货币工具（解析与比较） | `src/cenep/calculations/bill_parsing/money.py` | `decimal` | — |

**为什么解析器放 `calculations`**：它是"文本 → 结构化值"的**纯业务规则**，
本质与消纳计算同类（确定性、可单独测试、无 IO）。
由现成的 `tests/unit/test_layering.py::test_pdf_libraries_only_allowed_in_infrastructure`
保证它无法引入 PDF 库。

**数据流**：

```text
infrastructure/pdf/extractor.py     （P0-1，已实现）
        │  产出 PdfExtractionResult（页文本）
        ▼
calculations/bill_parsing/*         （P0-2，纯规则）
        │  产出 BillFieldSet（字段 + 证据 + 冲突 + 问题）
        ▼
application/*                       （P0-5，用例编排与落库）
        ▼
domain/bill_fields.py 的模型  →  infrastructure 仓储
```

---

## 3. 状态与严重程度枚举

### 3.1 字段识别状态（`FieldStatus`）

| 取值 | 含义 | 是否可直接用于测算 |
|---|---|---|
| `parsed` | 唯一候选，解析成功且格式合法 | 仍需校验与用户确认 |
| `needs_review` | 存在多个不同候选值，或单位不明 | **否** |
| `missing` | 未找到该字段 | **否** |
| `invalid` | 找到了但格式非法（如日期不合法） | **否** |

> **关键**：`parsed` **不等于**"可用于正式测算"。
> 任务书 7.4 明确"解析成功不等于账单有效"。
> 能否进入测算由字段集整体状态与用户确认共同决定（见第 7 节）。

### 3.2 校验问题严重程度（复用既有 `Severity`）

沿用 `cenep.domain.validation.Severity`（`ERROR` / `WARNING` / `INFO`），
不新造枚举，避免同一概念两套取值。

---

## 4. 核心模型

### 4.1 `FieldEvidence` —— 单条证据

```python
@dataclass(frozen=True)
class FieldEvidence:
    page_number: int          # 来源页码，从 1 开始
    source_text: str          # 命中的原文片段（保留原样，含换行与空格）
    raw_value: str            # 原文中的数值字面量，如 "6,708,448.31"
    label: str                # 命中的字段标签，如 "工商业电费："
    rule_id: str              # 命中的规则标识，如 "industrial_commercial_fee.v1"
```

**硬性要求**：

- `source_text` 必须是**原文**，不得规范化（不删空格、不合并行）。
- `source_text` 必须是**最小原文片段**（不是整页）：以标签与数值为锚点截取，
  并按需跨行保留被换行切开的数值与单位。**必须**是原始页文本的连续子串。
  规范化只发生在匹配阶段，证据保留原始形态。
- 一条字段可以有**多条证据**（同一字段在账单多处出现）。
- 证据只增不改：人工修正**不得**覆盖或删除原始证据。

### 4.2 `BillField` —— 一个字段的完整结果

```python
@dataclass
class BillField:
    name: str                          # 标准字段名，如 "total_consumption"
    unit: str | None                   # "kWh" / "元" / "元/kWh" / None（单位不明）
    status: FieldStatus
    value: Decimal | date | str | None # 唯一确定时的标准化值；否则 None
    raw_value: str | None              # 首个/唯一候选的原文
    evidences: tuple[FieldEvidence, ...]  # 全部证据
    candidates: tuple[Decimal, ...]    # 全部不同候选值（用于冲突展示）
    issues: tuple[ValidationIssue, ...]
    parser_version: str                # 解析规则版本
    requires_manual_confirmation: bool # 是否必须人工确认
```

**构造时强制的不变量**（在 `__post_init__` 校验）：

| 不变量 | 违反时 |
|---|---|
| `status == parsed` 时 `value is not None` 且 `len(set(candidates)) == 1` | 抛 `ValueError` |
| `status == needs_review` 时 `len(set(candidates)) > 1` 或单位不明 | 抛 `ValueError` |
| `status == missing` 时 `value is None` 且 `evidences == ()` | 抛 `ValueError` |
| `value is None` 时 `requires_manual_confirmation` 必须为 `True` | 抛 `ValueError` |
| 金额类字段（`unit == "元"`）不得是 `float` | 抛 `TypeError` |

> 这些约束把"缺失不等于 0""冲突必须暴露"固化在类型层面，
> 与 P0-1 中 `PdfExtractionResult` 的做法一致。

### 4.2.1 首批字段标识符清单（与 `P0_2_REGRESSION_BASELINE.md` 逐字一致）

字段名是**跨文档与代码的唯一契约**，必须逐字一致。
下表为标准字段名与单位的权威清单，三份文档（基线 / 本设计 / 测试清单）
均以此为准：

| 标准字段名 | 中文含义 | 单位 |
|---|---|---|
| `billing_period_start` | 账期开始日 | （日期） |
| `billing_period_end` | 账期结束日 | （日期） |
| `total_consumption` | 正式总用电量 | kWh |
| `bill_total_amount` | 账单总金额 | 元 |
| `vat_invoice_amount` | 增值税发票金额 | 元 |
| `displayed_average_price` | 账单展示平均电价 | 元/kWh |
| `industrial_commercial_fee` | 工商业电费 | 元 |
| `market_purchase_fee` | 市场化购电电费 | 元 |
| `grid_loss_fee` | 上网环节线损费用 | 元 |
| `transmission_distribution_fee` | 输配电费 | 元 |
| `system_operation_fee` | 系统运行费 | 元 |
| `government_fund_fee` | 政府性基金及附加 | 元 |
| `power_factor_adjustment_fee` | 功率因数调整电费 | 元 |
| `demand_charge` | 需量电费 | 元 |

参与"五项之和"的字段（任一缺失则勾稽不成立）：

```text
market_purchase_fee
+ grid_loss_fee
+ transmission_distribution_fee
+ system_operation_fee
+ government_fund_fee
= industrial_commercial_fee          （核对关系 1）
```

```text
industrial_commercial_fee
+ power_factor_adjustment_fee
= bill_total_amount                  （核对关系 2）
```

**不参与**上述求和：`demand_charge`（需量电费）、`vat_invoice_amount`（发票金额）。

> 单位纪律：`元/kWh` 是单价，`元` 是金额，`kWh` 是电量，
> 三者不得存入同一字段（任务书 5.2）。

### 4.3 `BillFieldSet` —— 一次解析的完整结果

```python
@dataclass
class BillFieldSet:
    fields: Mapping[str, BillField]     # 标准字段名 → 字段
    parser_version: str
    page_count: int
    extraction_status: PdfExtractionStatus   # 来自 P0-1 的提取状态
    issues: tuple[ValidationIssue, ...]      # 跨字段问题
    reconciliation: ReconciliationResult | None
```

**与 P0-1 的强关联（防止把部分提取当成完整账单）**：

```python
class ConfirmationStatus(str, Enum):
    PENDING = "pending"      # 解析完成，等待人工复核
    CONFIRMED = "confirmed"  # 已人工确认
    REJECTED = "rejected"    # 人工复核后驳回

@dataclass(frozen=True)
class BillConfirmation:
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    note: str | None = None
    # confirmed 时必须有确认人与确认时间；pending 时不得携带二者

@dataclass(frozen=True)
class BillFieldSet:
    ...
    confirmation: BillConfirmation = PENDING_CONFIRMATION

    @property
    def is_parsed_and_ready_for_review(self) -> bool:
        """解析是否完成、结果是否可供复核（**不等于可进入测算**）。"""
        return (
            self.extraction_status is PdfExtractionStatus.SUCCESS   # 必须完整提取
            and self.all_required_fields_parsed
            and not self.fields_requiring_review
            and not self.has_reconciliation_mismatch
        )

    @property
    def is_usable_for_calculation(self) -> bool:
        """是否可用于**正式经济性测算**——必须同时满足"可复核"与"已确认"。"""
        return self.is_parsed_and_ready_for_review and self.is_confirmed
```

**三个阶段必须显式区分**（禁止两段式判断）：

| 阶段 | 判据 | 允许做什么 |
|---|---|---|
| 解析完成、可供复核 | `is_parsed_and_ready_for_review` | 展示字段与证据、供人工核对 |
| 存在缺失/冲突/勾稽异常 | `blocking_reasons` 非空 | 必须人工复核，**不得**进入测算 |
| 已由用户确认 | `confirmation.status is CONFIRMED` | 才可能进入正式测算 |

**硬性闸门**：`is_usable_for_calculation` **必须**包含"已确认"这一条。
缺少它，调用方就会仅凭解析成功进入正式测算——这正是本设计要禁止的行为。
未确认时该属性恒为 `False`。

**确认不能绕过复核**：`confirm()` 在存在阻塞问题（提取不完整、必需字段缺失、
字段冲突、勾稽超差）时**拒绝确认并抛 `ValueError`**；确认人不得为空白。
`reject()` 用于人工判定不可用。

若 `extraction_status` 不是 `SUCCESS`（例如 `partial` / `needs_ocr` / `failed`），
则**无论字段识别得多完整**，都不得判定为可用于测算——
这条直接落实任务书"不得把部分提取结果当作完整账单"。

### 4.4 `ReconciliationResult` —— 费用勾稽

```python
@dataclass(frozen=True)
class ReconciliationResult:
    relation: str                 # 关系标识，如 "five_items_plus_pf_equals_total"
    expected: Decimal             # 计算值
    actual: Decimal               # 账单标注值
    tolerance: Decimal            # 容差，默认 Decimal("0.02")
    participating_fields: tuple[str, ...]   # 参与字段名（便于界面展示与追溯）

    @property
    def difference(self) -> Decimal: ...
    @property
    def is_within_tolerance(self) -> bool: ...
```

**行为要求**：

- 任一参与字段 `value is None` → 勾稽**不成立**，返回 `None` 或标记为未校验，
  **不得**用 0 代入。
- 超差 → 生成 `WARNING` 级 `ValidationIssue`，包含差额与参与字段清单，
  **不得**修改任何字段的 `value`。

---

## 5. 冲突处理规则（本设计的核心防错点）

### 5.1 什么算冲突

同一标准字段在账单中出现**两个及以上不同的数值候选**时即为冲突。
典型来源：第 1 页汇总值与第 2 页计量点明细值并存。

**实测反例（真实账单）**：

| 位置 | 标识 | 值 |
|---|---|---:|
| 第 1 页 | `本期电量`（权威字段） | 8780498 |
| 第 2 页 | 正向有功（总） | 8770300 |
| 第 2 页 | 计费电量（含线损与加减） | 8516838 |

三者互不相同。**正式总用电量只能取 `本期电量`**，
另两个值**不是**同一口径，不得作为候选参与"择一"。

### 5.2 冲突判定与处置

```text
候选值去重后
  ├── 数量 == 0 → status=missing
  ├── 数量 == 1 → status=parsed
  └── 数量 >= 2 → status=needs_review，requires_manual_confirmation=True
                   value 保持 None（不选任何一个）
                   candidates 保存全部候选值
                   生成 WARNING 问题，说明冲突位置与证据页码
```

**禁止**：
- 取第一个；
- 取最大/最小；
- 取出现次数最多的（除非规则明确且可追溯到账单原文说明）；
- 用重算值替换账单标注值。

### 5.3 权威字段白名单

对"正式总用电量"等关键字段，解析规则使用**权威标签白名单**：
只有命中白名单标签（如 `本期电量`）才作为候选；
计量点表内的数值即使量纲相同也**不进入候选集**，
而是作为**交叉核对信息**记录（用于发现异常，不用于取值）。

---

## 6. 数字与日期解析规则（对应真实排版踩坑）

### 6.1 金额与电量

| 场景 | 规则 |
|---|---|
| 千分位 | 去掉 `,` 后转 `Decimal` |
| 小数点与小数位被切开 | 先做跨行拼接，再解析；不得把 `339059.` 解析为 `339059` |
| 括号负数 | `(1,234.56)` → `Decimal("-1234.56")` |
| 正负号 | 保留 `+`/`-`；功率因数调整电费为负是**合法业务数据** |
| 单位换算 | `万元` → ×10000；`MWh` → ×1000 kWh。<br>**单位不明时不得擅自换算**，置 `needs_review` |
| 精度 | 全程 `Decimal`，禁止用 `float` 做金额运算或等值比较 |

### 6.2 日期与账期

| 场景 | 规则 |
|---|---|
| 标准格式 | `YYYY-MM-DD` |
| 跨月账期 | 开始日与结束日**分别**解析，允许不同月；结束日必须 ≥ 开始日，否则 `invalid` |
| 账单所属月份 | 由账期结束日所在月确定；跨月时记录该口径并在字段证据中说明 |
| 计费天数 | 由开始日与结束日计算（含首尾），仅作校验辅助，不作为独立权威字段 |

### 6.3 防误取规则（R1，必须实现）

**禁止取"标签后第一个数字"。** 真实反例：

```text
工商业电费：用电户-110千伏-大工业用电-工商业两部制、用电户-35千伏-非居民照明-工商业单一制
8780498 6708448.31
```

若按"标签后第一个数字"取值会得到 `-110`（电压等级），完全错误。

**要求**：

1. 匹配前先归一化文本用于**定位**，但证据保存原文。
2. 取数时必须在标签附近的**数值区**中取，并满足量纲/格式约束：
   - 金额：`\d{1,3}(,\d{3})*(\.\d+)?` 且数值合理（不为电压等级量级）；
   - 必须跳过形如 `-110千伏`、`-35千伏` 的"数字+单位"结构。
3. 取到的候选必须通过**上下文断言**（例如与"元"或表头顺序一致）。
4. 若一条规则命中多个候选 → 按 5.2 判定冲突，不静默取一个。

---

## 7. 字段集整体状态判定

```text
extraction_status != SUCCESS
    → 不可用于测算（无论字段多完整）

extraction_status == SUCCESS
    ├── 任一必需字段 status != parsed             → 需人工复核，不可测算
    ├── 任一必需字段 requires_manual_confirmation → 需人工复核，不可测算
    ├── 勾稽存在且超差                             → 需人工复核（告警），不可测算
    └── 以上皆否 → is_parsed_and_ready_for_review = True（**仍不可测算**）
                     │
                     └── confirmation.status is CONFIRMED ?
                             ├── 否（pending） → 不可测算（不得跳过确认）
                             ├── 否（rejected）→ 不可测算
                             └── 是            → is_usable_for_calculation = True
```

**一句话总结**：`is_usable_for_calculation`
= `is_parsed_and_ready_for_review` **且** `is_confirmed`。

必需字段（本轮首批）：`billing_period_start`、`billing_period_end`、
`total_consumption`、`bill_total_amount`、`vat_invoice_amount`、
`displayed_average_price`、`industrial_commercial_fee`。

### 7.1 证据的最小化要求

`FieldEvidence.source_text` **必须是"最小原文片段"**，而非整页文本：

- 片段以**标签 + 数值**为锚点，向两侧各取少量上下文；
- 起点不跨行，终点默认收到本行行尾；
- **但**当数值与单位被换行切开时（``…为-9206.37`` ⏎ ``元，…``），
  片段必须吞掉换行并把单位纳入，以保留可追溯性；
- 小数位被换行切开时（``1787644.`` ⏎ ``3``）片段同样必须完整覆盖该数值；
- 证据必须来自**原文**：匹配可用规范化副本，
  但证据要按位置映射回原文截取，**不得**把规范化文本冒充原文；
- 证据必须是原始页文本的**连续子串**（实现上有测试逐字符校验）。

**可追溯性要求**：结果对象必须能回答"该值来自哪一页、哪段原文、哪条规则、
哪一版规则"，缺一不可（任务书 5.3）。

---

## 8. 规则版本管理

| 项目 | 约定 |
|---|---|
| 版本常量 | 每个解析模块定义 `PARSING_VERSION`，如 `"0.1.0"` |
| 版本语义 | 规则改动（标签、正则、口径）→ 提升版本号 |
| 追溯 | 每个 `BillField` 记录解析时的 `parser_version` |
| 历史结果 | 旧结果按当时的版本解释，**不得**用新规则重新解释旧结果 |
| 文档同步 | 版本变化必须同步更新 `docs/CALCULATION_SPEC.md`（或新增的账单解析规格文档） |

---

## 9. 本设计明确不做的事

1. **不实现代码**——本文件仅为设计；P0-2 代码在独立分支开发。
2. **不修改数据库结构**——字段落库属 P0-4，本轮不触碰 `SCHEMA_VERSION`。
3. **不实现 OCR**——无文本层账单仍由 P0-1 标记 `needs_ocr`。
4. **不实现费用明细的完整解析**——本轮首批仅 6 类（见 `P0_2_TEST_CHECKLIST.md`）。
5. **不做自动更正**——任何冲突与超差都只告警，交人工处理。
