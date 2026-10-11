# P0-2 首批测试清单与验收标准

- 设计日期：2026-10-11
- 对应任务：第二阶段 P0-2（电费账单关键字段识别）
- 期望值来源：`docs/phase2/P0_2_REGRESSION_BASELINE.md`（已冻结）
- 状态：**清单已冻结，测试代码未编写**（P0-2 代码在 PR #2 合并后于独立分支开发）

---

## 1. 首批开发范围（任务书第四节）

| 编号 | 字段 | 优先级 |
|---|---|---|
| F1 | 账期开始日 | 最高 |
| F2 | 账期结束日 | 最高 |
| F3 | 正式总用电量 | 最高 |
| F4 | 账单总金额 | 最高 |
| F5 | 增值税发票金额 | 最高 |
| F6 | 账单展示平均电价 | 最高 |
| F7 | 工商业电费及费用勾稽 | 最高 |

配套必需项：5 个费用分项（市场化购电电费、上网环节线损费用、输配电费、
系统运行费、政府性基金及附加）、功率因数调整电费、需量电费。

---

## 2. 测试夹具设计

### 2.1 内联最小文本片段

在测试模块内以字符串常量保存，**只保留字段标签与数值所在的行**，
删除户名、户号、地址、受电点、电能表编号、二维码说明等。

**命名**：`BILL_2025_09_SNIPPET`、`BILL_2025_10_SNIPPET`

**每份片段必须包含的关键行**（据真实账单）：

```text
账单周期  <开始日>
至 <结束日>
 本期电量
 8780498千瓦时
 本期电费
 6699241.94元
 其中增值税专用发票金额
 6534168.58元
工商业电费：用电户-110千伏-大工业用电-工商业两部制、用电户-35千伏-非居民照明-工商业单一制
8780498 6708448.31
其中：(1)市场化购电电费 3840051.76
(2)上网环节线损费用 179343.47
(3)输配电费 2000662.04
(4)系统运行费 291512.53
(5)政府性基金及附加 396878.51
功率因数调整电费 -9206.37
本期您的平均电价0.76297元/千瓦时
 本期您的需（容）量电费为1202916元
```

> 上述片段**故意保留**真实排版缺陷（标签与数值跨行、标签内含 `-110`/`-35`、
> 数量与金额同行），以便回归真实解析难点。
> 提交前必须扫描确认不含任何客户标识信息。

### 2.2 可选的真实文件回归

用 `pytest.mark.skipif` 检测账单目录是否存在：
存在则跑完整账单回归，不存在则跳过并注明"本机无真实账单样本"。
**跳过不得计入通过数**（CI 已有跳过门禁，会因此失败——故该用例须打独立标记，
且不纳入默认门禁统计，实现时需与 `tests.yml` 的门禁逻辑协调）。

---

## 3. 测试清单

### 3.1 账期（F1/F2）

| 用例 | 输入特征 | 期望 |
|---|---|---|
| `test_parse_period_2025_09` | 标准两行账期 | `billing_period_start == date(2025,9,1)`，`end == date(2025,9,30)` |
| `test_parse_period_2025_10` | 标准两行账期 | `2025-10-01` / `2025-10-31` |
| `test_parse_period_cross_month` | `2025-08-26` 至 `2025-09-25` | 分别解析，所属月份取结束月，证据含口径说明 |
| `test_parse_period_end_before_start_is_invalid` | 结束日早于开始日 | `status == invalid`，不得静默交换 |
| `test_parse_period_missing_returns_missing` | 片段无账期 | `status == missing`，`value is None`，`requires_manual_confirmation is True` |
| `test_billing_days_computed_inclusive` | 9 月账期 | 计费天数 30（含首尾） |

### 3.2 正式总用电量（F3）

| 用例 | 输入特征 | 期望 |
|---|---|---|
| `test_total_consumption_2025_09` | `本期电量` ⏎ `8780498千瓦时` | `Decimal("8780498")`，单位 `kWh` |
| `test_total_consumption_2025_10` | 同上 | `Decimal("7479418")` |
| `test_total_consumption_label_value_on_different_lines` | 标签与数值跨行 | 仍能解析（R3） |
| `test_total_consumption_not_summed_from_metering_points` | 片段同时含 `8770300`、`8516838` | **取 `8780498`**，且证据页码为第 1 页；**不得**取另两个值 |
| `test_total_consumption_never_summed` | 只给出计量点分项、无权威字段 | `status == missing`，**不得**求和推导 |
| `test_total_consumption_thousand_separator` | `8,780,498` | `Decimal("8780498")` |
| `test_total_consumption_missing_is_none_not_zero` | 无该字段 | `value is None`，**断言不等于 `Decimal(0)`** |

### 3.3 金额字段（F4/F5）

| 用例 | 输入特征 | 期望 |
|---|---|---|
| `test_bill_total_2025_09` | `本期电费` ⏎ `6699241.94元` | `Decimal("6699241.94")` |
| `test_bill_total_2025_10` | 同上 | `Decimal("5471334.24")` |
| `test_vat_invoice_2025_09` | `其中增值税专用发票金额` ⏎ `6534168.58元` | `Decimal("6534168.58")` |
| `test_vat_invoice_2025_10` | 同上 | `Decimal("5330721.18")` |
| `test_total_and_vat_are_separate_fields` | 同一片段 | 两字段独立保存，**值不同**，不合并、不互相覆盖 |
| `test_amount_trailing_zero_equivalence` | `1787644.30` vs 文本 `1787644.3` | `Decimal` 比较相等（防止字符串比较假不一致） |
| `test_amount_parenthesised_negative` | `(1,234.56)` | `Decimal("-1234.56")` |
| `test_amount_unit_wan_yuan` | `12.5万元` | `Decimal("125000")` 且记录换算依据 |
| `test_amount_unit_unknown_not_converted` | 数值无单位且表头无单位 | `status == needs_review`，**不得**擅自按元处理 |
| `test_amounts_are_decimal_not_float` | 任意金额字段 | 类型为 `Decimal`；断言 `not isinstance(value, float)` |

### 3.4 平均电价（F6）

| 用例 | 输入特征 | 期望 |
|---|---|---|
| `test_average_price_2025_09` | `本期您的平均电价0.76297元/千瓦时` | `Decimal("0.76297")`，单位 `元/kWh` |
| `test_average_price_2025_10` | 同上 | `Decimal("0.73152")` |
| `test_average_price_unit_is_price_not_amount` | 片段含金额与电价 | 电价字段单位必须是 `元/kWh`，**不得**与 `元` 字段混用 |
| `test_average_price_not_overwritten_by_recomputed` | 同片段 | 保存账单原值；若同时计算了"总金额/总电量"，该值必须存到**另一字段**，原字段值不变 |

### 3.5 费用分项与勾稽（F7）

| 用例 | 输入特征 | 期望 |
|---|---|---|
| `test_five_fees_2025_09` | 五项标签+数值 | 五项分别正确、单位 `元` |
| `test_five_fees_2025_10` | 同上 | 五项分别正确 |
| `test_industrial_commercial_fee_not_first_number_after_label` | `工商业电费：用电户-110千伏-...` ⏎ `8780498 6708448.31` | **取 `6708448.31`**；断言结果 **不等于** `Decimal("-110")` 也 **不等于** `Decimal("-35")`（R1 专项） |
| `test_quantity_and_amount_on_same_line_distinguished` | `8780498 6708448.31` | 电量与金额分别归属正确字段（R5） |
| `test_power_factor_adjustment_keeps_negative` | `功率因数调整电费 -9206.37` | `Decimal("-9206.37")`，**断言 < 0**；不得取绝对值 |
| `test_demand_charge_separate_and_not_in_five_items` | 含需量电费 | `demand_charge == Decimal("1202916")`；断言五项之和**不含**该值 |
| `test_reconciliation_relation1_2025_09` | 五项之和 vs 工商业电费 | 差额 `0.00`，`is_within_tolerance is True` |
| `test_reconciliation_relation1_2025_10` | 同上 | 差额 `0.00` |
| `test_reconciliation_relation2_2025_09` | 工商业电费 + 功率因数调整 vs 本期电费 | `6699241.94`，差额 `0.00` |
| `test_reconciliation_relation2_2025_10` | 同上 | `5471334.24`，差额 `0.00` |
| `test_reconciliation_within_tolerance_boundary` | 人为制造 0.02 元差额 | **通过**（容差为 ≤ 0.02） |
| `test_reconciliation_exceeds_tolerance_warns` | 人为制造 0.03 元差额 | 生成 `WARNING`；**断言原始金额字段未被修改** |
| `test_reconciliation_skipped_when_participant_missing` | 缺任一分项 | 勾稽不成立；**断言未用 0 代入** |

### 3.6 冲突、缺失与单位（防错专项）

| 用例 | 输入特征 | 期望 |
|---|---|---|
| `test_conflict_two_different_candidates_needs_review` | 同一字段两处不同值且都属权威口径 | `status == needs_review`，`value is None`，`candidates` 含两者，`requires_manual_confirmation is True` |
| `test_conflict_does_not_pick_first` | 同上，且首个候选是错值 | 断言 `value is None`（**不是**首个候选） |
| `test_conflict_does_not_pick_max_or_min` | 同上 | 断言 `value is None` |
| `test_identical_candidates_are_single_value` | 同一字段两处相同值 | `status == parsed`，`len(set(candidates)) == 1` |
| `test_missing_field_never_zero` | 任一必需字段缺失 | `value is None`；**断言 `value != Decimal(0)`** |
| `test_unparseable_value_is_invalid_not_zero` | 值形如 `--` 或 `N/A` | `status == invalid`，`value is None` |
| `test_every_field_has_evidence` | 任意 `parsed` 字段 | 至少一条 `FieldEvidence`，且 `page_number >= 1`、`source_text` 非空 |
| `test_evidence_preserves_original_text` | 含空格/换行的原文 | `source_text` 与原文逐字符一致（未被规范化） |
| `test_field_records_parser_version` | 任意字段 | `parser_version` 非空且等于模块常量 |

### 3.7 与 P0-1 的状态联动（防止部分提取当完整账单）

| 用例 | 输入 | 期望 |
|---|---|---|
| `test_partial_extraction_not_usable_for_calculation` | `extraction_status=PARTIAL`，字段全部解析成功 | `is_usable_for_calculation is False` |
| `test_needs_ocr_extraction_not_usable` | `extraction_status=NEEDS_OCR` | `is_usable_for_calculation is False` |
| `test_failed_extraction_not_usable` | `extraction_status=FAILED` | `is_usable_for_calculation is False` |
| `test_success_extraction_with_conflict_not_usable` | `SUCCESS` 但存在冲突字段 | `is_usable_for_calculation is False` |
| `test_success_extraction_all_parsed_is_usable` | `SUCCESS` 且字段齐备、勾稽通过 | `is_usable_for_calculation is True` |
| `test_parse_success_is_not_bill_valid` | `SUCCESS` 且全部 `parsed` | 断言字段集状态**不等于**"账单已确认/valid"——解析成功 ≠ 账单有效 |

### 3.8 非功能与架构

| 用例 | 期望 |
|---|---|
| `test_parsing_layer_has_no_pdf_or_qt_dependency` | 由既有 `test_layering.py` 覆盖（`calculations` 禁止 pypdf/Qt/sqlite3） |
| `test_parser_is_pure_function` | 同一输入重复调用结果相同；不写文件、不访问数据库 |
| `test_no_float_in_money_path` | 扫描解析模块源码，金额运算不使用 `float(` |
| `test_fixture_contains_no_customer_identifiers` | 扫描内联 fixture，断言不含 `户名`、`户号`、`用电地址`、`受电点`、电能表编号等实际值 |

---

## 4. 验收标准

### 4.1 功能验收

| 编号 | 条件 | 判定方式 |
|---|---|---|
| A1 | 6 类首批字段在 2 份账单片段上全部解析正确 | 上述用例全绿 |
| A2 | 26 项冻结数值全部匹配（`Decimal` 精确比较） | 基线比对用例全绿 |
| A3 | 两条勾稽关系差额均为 0.00 元 | 勾稽用例全绿 |
| A4 | 容差 0.02 元边界与超差告警行为正确 | 边界用例全绿 |
| A5 | 标签内含 `-110`/`-35` 时**不误取**为金额 | R1 专项用例全绿 |
| A6 | 正式总用电量不由计量点或分时电量推导 | R8 专项用例全绿 |
| A7 | 缺失字段保持 `None`，绝不为 0 | 专项用例全绿 |
| A8 | 冲突字段进入 `needs_review` 且 `value is None` | 冲突用例全绿 |
| A9 | 负费用（功率因数调整）保留负号 | 专项用例全绿 |
| A10 | 展示平均电价独立保存且不被重算值覆盖 | 专项用例全绿 |
| A11 | 每个字段可追溯到页码、原文与规则版本 | 证据用例全绿 |
| A12 | P0-1 提取状态非 `SUCCESS` 时字段集不可用于测算 | 联动用例全绿 |

### 4.2 质量门禁

| 编号 | 条件 |
|---|---|
| Q1 | Python 3.11 与 3.14 的 CI 均通过 |
| Q2 | 无失败、无错误、无跳过（跳过门禁不得被绕过） |
| Q3 | 原有测试无回归 |
| Q4 | 分层约束通过（解析层无 pypdf/Qt/sqlite3） |
| Q5 | `git diff --check` 退出码 0 |
| Q6 | 仓库内无真实账单 PDF、无客户名称/户号/地址 |
| Q7 | 未删除测试、未放宽断言 |

### 4.3 明确不在本轮验收范围

- EL 完整费用明细解析（仅首批 5 个分项）
- 分时电量与电价解析（P0-3）
- 数据库落库与迁移（P0-4）
- 人工复核界面（P0-5）
- OCR（本阶段不做）
- 2025-01～08 八份账单的字段核验（未核验，不得声称已核验）

---

## 5. 实现顺序建议

1. 货币与数值解析工具（含 `Decimal`、千分位、括号负数、跨行拼接）+ 其单元测试；
2. 账期解析 + 测试；
3. 权威字段取数框架（标签白名单 + 证据 + 冲突判定）+ 测试；
4. 4 个金额字段与平均电价 + 测试；
5. 5 个费用分项 + 勾稽 + 测试；
6. 与 P0-1 状态联动 + 测试；
7. 内联 fixture 脱敏自查测试。

每步完成即跑全量测试，确保无回归。
