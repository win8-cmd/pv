# P0-1 最终复核报告

- 复核日期：2026-10-11
- 复核对象：PR [#2](https://github.com/win8-cmd/pv/pull/2)，分支 `phase2/bill-pdf-text-extraction`
- 复核范围：状态语义、模型约束、测试覆盖、调用方处理、文档一致性、CI 与提交一致性
- 复核方式：**实际读取代码与运行测试**，不采信历史报告结论

---

## 1. 复核结论

**P0-1 通过最终复核，无阻塞问题。建议合并。**

| 复核项 | 结论 |
|---|---|
| 1. 状态定义与实际代码一致 | 通过 |
| 2. 模型约束与测试一致 | 通过 |
| 3. 存在"中间页失败、其他页成功"的异常测试 | 通过（已实际运行验证） |
| 4. 调用方对 `partial` 的处理正确 | 通过（当前无生产调用方，规则已内建） |
| 5. 文档一致性 | 已修正（见第 5 节） |
| 6. 过时状态与数量标注 | 已修正 |
| 7. CI 与最新提交 SHA 一致 | 见第 6 节（以本轮实测为准，未引用历史记录） |

---

## 2. 状态定义与实际代码一致性

`src/cenep/domain/pdf_extraction.py` 中 `PdfExtractionStatus` 实际取值：

| 状态 | 实际定义 | 提取器是否产生 |
|---|---|---|
| `SUCCESS` | 全部页面提取成功且文本可用 | 是 |
| `PARTIAL` | 部分页面失败，但其他页面文本可用 | 是 |
| `NEEDS_OCR` | 整份文档没有获得可用文本 | 是 |
| `FAILED` | 文件缺失/为空/非 PDF/损坏 | 是 |
| `DUPLICATE` | 内容哈希与已登记文件相同 | **否**（由应用层判定） |

`src/cenep/infrastructure/pdf/extractor.py` 的决策表（四象限，互斥穷尽）：

```text
文本可用 + 无错误 -> SUCCESS
文本可用 + 有错误 -> PARTIAL        （error_code=page_extraction_failed）
无文本   + 有错误 -> NEEDS_OCR      （error_code=page_extraction_failed）
无文本   + 无错误 -> NEEDS_OCR      （error_code=no_text_layer）
```

**文件读取失败路径**（缺失/空/非 PDF/损坏）走 `_failure()` → `FAILED`，
`page_count=0`、`pages=()`，不产生 `PARTIAL`。

### 2.1 两个维度未混淆

| 字段 | 语义 | `PARTIAL` 时取值 |
|---|---|---|
| `text_layer_available` | 文档**有没有可用文本** | `True` |
| `is_complete` | 结果**是否完整** | `False` |

提取器中 `text_layer_available=text_layer_available` 不再与状态绑定
（原缺陷正是把它写成 `... and status is SUCCESS`），复核确认已修正。

---

## 3. 模型约束与测试一致性

`PdfExtractionResult._check_status_consistency()` 实际强制的不变量：

| 状态 | 强制约束 |
|---|---|
| `SUCCESS` | 不得有 `errors`；`text_layer_available` 必须为 `True`；必须有页面 |
| `PARTIAL` | `text_layer_available` 必须为 `True`；必须有 `errors`；至少一页有文本 |
| `NEEDS_OCR` / `FAILED` | `text_layer_available` 必须为 `False` |
| `FAILED` | `page_count` 必须为 0 |
| 全部 | `status` 必须是 `PdfExtractionStatus`；页码从 1 连续；`page_count` 与 `pages` 长度一致 |

对应测试（`TestPartialStatusModelConstraints`，8 例）覆盖：
`partial` 缺文本层 / 缺错误 / 无成功页，`success` 带错误 / 缺文本层，
`failed` 含页面，`status` 非枚举，以及**合法 `partial` 可正常构造**（防止约束过度）。

**一致性判定：代码中的每一条约束都有对应用例；每个用例都对应一条实际约束。**
不存在"约束无测试"或"测试断言超出实际约束"的情况。

---

## 4. 中间页失败测试的实际验证

任务书第 2.3 项要求确认存在"中间页提取失败、其他页面成功"的异常测试。

**实际存在且已运行通过**：

| 用例 | 覆盖位置 |
|---|---|
| `TestStatusSemantics::test_b_single_page_failure_is_partial_not_needs_ocr` | **中间页**（3 页中的第 2 页） |
| `TestStatusSemantics::test_b_first_page_failure_also_partial` | 首页边界 |
| `TestStatusSemantics::test_b_last_page_failure_also_partial` | 末页边界 |

中间页用例的实际断言（摘录）：

- `status is PdfExtractionStatus.PARTIAL`，且 `is not SUCCESS`、`is not NEEDS_OCR`；
- `text_layer_available is True`（文本确实可用）；
- `page_count == 3` 且页码序列为 `[1, 2, 3]`；
- 第 1、3 页文本保留，第 2 页为空且仍占正确页码位；
- `errors` 含 `第 2 页`，`error_code == page_extraction_failed`，
  `extraction_error_count == 1`。

**运行证据**（本轮实测）：

```text
tests/unit/test_pdf_extraction.py::TestStatusSemantics::test_b_single_page_failure_is_partial_not_needs_ocr
1 passed in 0.49s
```

状态语义相关用例共 **19 个**（`TestStatusSemantics` 11 + `TestPartialStatusModelConstraints` 8），
`tests/unit/test_pdf_extraction.py` 共 **75 个**。

> **故障注入实现说明**：测试通过替换 `PageObject.extract_text` 并**按页面内容标记**
> 只让目标页抛错。此前两次尝试（替换类方法无条件抛错 → 所有页一起失败；
> 只替换实例方法 → 提取器自建 reader 覆盖不到）均已记录在 R9，
> 当前实现是唯一能真实触发"单页失败"的方式。

---

## 5. 调用方对 `partial` 的处理

全仓库检索结果：**生产代码中只有 2 个文件**使用提取状态——
`domain/pdf_extraction.py`（定义）与 `infrastructure/pdf/extractor.py`（产生）。

**当前不存在 UI、应用服务或仓储调用方**（P0-5 才接入）。因此：

1. 不存在"只处理 `SUCCESS` 与 `NEEDS_OCR`、漏掉 `PARTIAL`"的一线代码；
2. 为防后续调用方误用，规则已**内建到领域模型**而非仅写在文档里：
   `is_complete` 明确表达"结果是否完整"，
   并在 P0-2 设计中进一步规定
   `BillFieldSet.is_usable_for_calculation` 必须要求
   `extraction_status is SUCCESS`（见 `P0_2_FIELD_EVIDENCE_MODEL.md` 第 4.3 节）。
3. `summarize()` 与 `to_dict()` 均输出 `is_complete` / `is_partial`，
   使调用方无需自行推断。

**结论：当前无违规调用方；已通过模型属性与后续设计要求防止误用。**

---

## 6. 文档一致性修正

### 6.1 本轮修正内容

| 文档 | 问题 | 修正 |
|---|---|---|
| `README.md` | 第 2 节"已实现功能"列的是第一阶段功能，却写"321 个用例全部通过"，且未说明 PDF 提取仍在 PR 中 | 明确标注**功能状态分层**：第一阶段已在 `main`；P0-1 在 PR #2 审阅中尚未合并；并说明从 `main` 检出不会包含 PDF 功能 |
| `docs/ACCEPTANCE_CRITERIA.md` | "本次实测结果"仍写 244 | 更新为 321，并说明该文档是**第一阶段**验收标准、`main` 基线为 244；版本升至 r5 并新增第 5 版行 |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 基线期望写 244 | 更新为"当前分支 321，`main` 为 244" |
| `docs/PRD.md` | 覆盖要求写 244 | 更新为"当前 321" |
| `docs/ROADMAP.md` | 第一阶段门槛写 244 | 保留 244 但标注为**第一阶段基线** |
| `docs/phase2/PHASE2_RECON_REPORT.md` | 数字为核查当时快照，易被当作当前值 | 顶部新增**数字时效说明**，并在第 8 项标注"核查当时 `main` 基线" |

### 6.2 历史快照的处理原则

`docs/PROGRESS_LOG.md` 各轮记录中的 199 / 234 / 244 / 302 / 321
**一律保留不改写**——它们是各轮当时的真实实测值，是可审计的历史。
区分方式：

- **当前状态**：`docs/TEST_PLAN.md` 与 `README.md` 的分布表（实测 321）；
- **历史快照**：`PROGRESS_LOG.md` 各轮小节，及明确标注为"第一阶段基线"的数字。

### 6.3 测试数量实测（本轮）

| 测试文件 | 用例数 |
|---|---:|
| `tests/unit/test_validation.py` | 52 |
| `tests/unit/test_self_consumption.py` | 42 |
| `tests/unit/test_layering.py` | 18 |
| `tests/unit/test_package_import.py` | 21 |
| `tests/unit/test_gui_main_window.py` | 17 |
| `tests/unit/test_pdf_extraction.py` | 75 |
| `tests/integration/test_database.py` | 51 |
| `tests/integration/test_database_memory_and_schema_version.py` | 45 |
| **合计** | **321** |

---

## 7. CI 与最新提交一致性

**本节以本轮实际触发并查询到的运行结果为准，未引用任何历史 CI 记录。**

见本报告随附的提交与运行记录（`docs/PROGRESS_LOG.md` 对应轮次），
关键要求：

1. 运行的 `head_sha` 必须与分支最新提交 SHA **逐字符一致**；
2. Python 3.11 与 3.14 两个作业均须 `success`；
3. 跳过门禁必须报告 `skipped=0`；
4. 架构分层检查与工作树洁净检查须通过。

---

## 8. 遗留风险（不影响合并建议）

1. **`DUPLICATE` 状态无提取器路径**：由应用层判定，P0-4/P0-5 接入时需补集成测试。
2. **多页同时部分失败**（失败页 ≥ 2 且仍有文本）：决策表逻辑覆盖，
   但测试仅覆盖"单页失败"与"全部失败"两端，**中间情形无用例**。
3. **加密 PDF**：仅尝试空口令，无口令交互，未做相关测试。
4. **超大/恶意 PDF**：无模糊测试与资源限制。
5. **真实账单回归**：P0-1 已对 2 份真实账单金标准核验（见
   `REAL_BILL_VERIFICATION.md`），但**未覆盖** 2025-01～08 的 8 份账单。
6. 继承前期：内存库多线程并发、真实显示器界面观感、多进程并发写、
   打包发布、覆盖率数值——均未验证。

---

## 9. 合并建议

**建议合并 PR #2。** 理由：

1. 状态语义缺陷已修复并由 19 个专项用例锁定；
2. 321 个用例全绿，第一阶段 244 个无回归；
3. 分层约束与架构规则完好（PDF 库仅在基础设施层）；
4. 无真实账单、无客户标识信息进入仓库；
5. 文档一致性已修正，当前状态与历史快照已明确区分。

**合并前用户需确认的两点**：

1. PR #2 的分支包含 P0-2 的**设计文档**（`docs/phase2/P0_2_*.md`），
   但**不含任何 P0-2 代码**（遵守"不把 P0-2 代码混入 P0-1"的要求）。
   如不希望设计文档随 P0-1 合并，可要求先剔除。
2. 合并后 P0-2 代码将从更新后的 `main` 新建独立分支开发。

**未合并 PR #2**，等待授权。
