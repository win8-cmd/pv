# CENEP 完成结论日志（PROGRESS LOG）

- 文件用途：**每一轮开发或复核完成后，在本文件追加一条结论记录，并同步到 GitHub。**
- 记录原则：只写实际执行过的内容与实测数字；未验证事项必须显式列出，不得省略。
- 最新记录在最上面（倒序），便于快速查看当前状态。

---

## 1. 完成轮次索引

| 轮次 | 日期 | 任务 | 分支 | 结论 | 用例数 | CI |
|---|---|---|---|---:|---|
| R12 | 2026-10-11 | P0-1 最终复核与 P0-2 开发准备 | `phase2/bill-pdf-text-extraction` | 通过（建议合并，待授权） | 321 | 全绿 |
| R11 | 2026-10-11 | 真实账单核验与 P0-2 回归预期冻结 | `phase2/bill-pdf-text-extraction` | 通过（待复核合并） | 321 | 全绿 |
| R10 | 2026-10-11 | 记录状态语义修复的 CI 结论 | `phase2/bill-pdf-text-extraction` | 通过（待复核合并） | 321 | 全绿 |
| R9 | 2026-10-11 | P0-1 复核修复：拆分 partial 与 needs_ocr 状态语义 | `phase2/bill-pdf-text-extraction` | 通过（本地证据） | 321 | 见 R10 |
| R8 | 2026-10-11 | 记录 P0-1 的 CI 实测结论 | `phase2/bill-pdf-text-extraction` | 通过（待复核合并） | 302 | 全绿 |
| R7 | 2026-10-11 | 第二阶段 P0-1：PDF 导入与页级文本提取 | `phase2/bill-pdf-text-extraction` | 通过（本地证据） | 302 | 见 R8 |
| R6 | 2026-10-11 | 记录本轮 CI 实测结论 | `fix/stage1-review-memory-db-and-schema-version` | 通过（待授权合并） | 244 | 全绿 |
| R5 | 2026-10-11 | 合并前最终复核与文档版本同步 | `fix/stage1-review-memory-db-and-schema-version` | 通过（本地证据） | 244 | 见 R6 |
| R4 | 2026-10-11 | 元数据完整性修复与测试数量统一 | `fix/stage1-review-memory-db-and-schema-version` | 通过（待审阅合并） | 244 | 全绿 |
| R3 | 2026-10-11 | 建立完成结论日志与每轮更新约定 | `fix/stage1-review-memory-db-and-schema-version` | 完成（待随 PR #1 合并） | 234 | 全绿 |
| R2 | 2026-10-11 | 第一阶段代码复核与缺陷修复 | `fix/stage1-review-memory-db-and-schema-version` | 通过（待审阅合并） | 234 | 全绿 |
| R1 | 2026-10-11 | 第一阶段工程骨架与核心规则冻结 | `main` | 通过（已合并至 main） | 199 | 无（当时尚未配置） |

---

## 2. R12 — P0-1 最终复核与 P0-2 开发准备

- 完成日期：2026-10-11
- 任务来源：P0-1 最终复核与 P0-2 开发准备任务书
- 分支：`phase2/bill-pdf-text-extraction`
- 结论：**P0-1 通过最终复核，建议合并**（未合并，等待授权）；P0-2 设计已就绪

### 2.1 P0-1 复核结论（实际读码 + 运行测试）

| 复核项 | 结论 |
|---|---|
| 状态定义与代码一致 | 通过（`SUCCESS`/`PARTIAL`/`NEEDS_OCR`/`FAILED` 由提取器产生，`DUPLICATE` 由应用层判定） |
| 模型约束与测试一致 | 通过（每条约束有对应用例，反之亦然） |
| "中间页失败"异常测试存在 | 通过（已实际运行，`1 passed in 0.49s`） |
| 调用方正确处理 `partial` | 通过（当前无生产调用方；规则已内建） |
| 文档一致性 | 已修正（见 2.3） |
| CI 与最新提交一致 | 通过（见 2.5，本轮实测未引用历史记录） |

**决策表（四象限互斥穷尽）**：

```text
文本可用 + 无错误 -> SUCCESS
文本可用 + 有错误 -> PARTIAL   （error_code=page_extraction_failed）
无文本   + 有错误 -> NEEDS_OCR （error_code=page_extraction_failed）
无文本   + 无错误 -> NEEDS_OCR （error_code=no_text_layer）
```

### 2.2 中间页失败测试的实测证据

`TestStatusSemantics::test_b_single_page_failure_is_partial_not_needs_ocr`
覆盖 3 页中的**第 2 页**失败，断言：`status is PARTIAL`、
`is not SUCCESS`、`is not NEEDS_OCR`、`text_layer_available is True`、
页码序列 `[1,2,3]`、第 1/3 页文本保留、第 2 页为空且占正确页码位、
`errors` 含"第 2 页"、`error_code == page_extraction_failed`、
`extraction_error_count == 1`。另有首页/末页两个边界用例。

状态语义专项共 **19 例**（`TestStatusSemantics` 11 + `TestPartialStatusModelConstraints` 8）；
`tests/unit/test_pdf_extraction.py` 共 **75 例**。

### 2.3 文档一致性修正（本轮）

| 文档 | 修正 |
|---|---|
| `README.md` | 新增**功能状态分层标注**：第一阶段已在 `main`；PDF 提取在 PR #2 审阅中尚未合并；从 `main` 检出不含该功能、测试数也少于 321 |
| `docs/ACCEPTANCE_CRITERIA.md` | 当前实测 244 → **321**；说明该文档是第一阶段验收标准、`main` 基线 244；版本升至 r5 |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 基线期望更新为"当前分支 321，`main` 为 244" |
| `docs/PRD.md` | 覆盖要求更新为"当前 321" |
| `docs/ROADMAP.md` | 保留 244，明确标注为"第一阶段基线" |
| `docs/phase2/PHASE2_RECON_REPORT.md` | 顶部新增**数字时效说明**，标明其数字是核查当时快照 |

**历史快照原则**：`PROGRESS_LOG` 各轮的 199/234/244/302/321 **保留不改写**，
通过"当前状态 vs 历史快照"的明确标注避免新旧结论矛盾。

### 2.4 P0-2 开发准备（仅设计文档，无 P0-2 代码）

| 文件 | 内容 |
|---|---|
| `docs/phase2/P0_2_REGRESSION_BASELINE.md` | 冻结 26 项已核验数值（含单位、来源页、原文标记）；两条勾稽关系（差额均 0.00 元）；0.02 元容差与"超差只告警、不改原始值"；**8 条取数防错规则**（R1 禁止取标签后第一个数字，反例 −110/−35）；脱敏内联夹具方案 |
| `docs/phase2/P0_2_FIELD_EVIDENCE_MODEL.md` | `FieldEvidence` / `BillField` / `BillFieldSet` / `ReconciliationResult` 设计；不变量在类型层面强制；冲突处理（≥2 候选 → `needs_review`，`value` 为 `None`，禁止取首/最大/最小）；权威字段白名单；与 P0-1 状态联动（非 `SUCCESS` 不可用于测算）；分层放置（模型在 `domain`，纯规则解析器在 `calculations`） |
| `docs/phase2/P0_2_TEST_CHECKLIST.md` | 首批 7 类字段约 70 项测试清单；12 条功能验收标准 + 7 条质量门禁；明确不在本轮验收范围 |
| `docs/phase2/P0_1_FINAL_REVIEW.md` | 本次复核报告，含合并建议与遗留风险 |

**遵守约束**：P0-2 **代码未提交到本分支**；
数据库结构、`SCHEMA_VERSION`、账单字段、UI 均未改动。

### 2.5 测试与 CI（本轮实测）

本机：Windows 11 专业版 10.0.22621 / Python 3.14.7

| 检查 | 结果 |
|---|---|
| `python -m pytest -p no:cacheprovider` | **321 passed**（0 failed / 0 error / 0 skipped） |
| `python -m pytest --collect-only -q` | 8 个文件，合计 321 |
| `python -m pytest -q tests/unit/test_layering.py` | 18 passed |
| `git diff --check` | 退出码 0 |

CI（**本轮实际触发并查询，未引用历史记录**）：

| 项目 | 值 |
|---|---|
| 运行 | [38148416341](https://github.com/win8-cmd/pv/actions/runs/38148416341) |
| `head_sha` | `3e1708f6fd1e3786fbe15f0b4836fd5898a94c7a`（与分支最新提交**逐字符一致**） |
| Python 3.14 | **success**（`321 passed in 2.08s`） |
| Python 3.11 | **success**（`321 passed in 3.45s`） |
| 跳过门禁 | 无跳过用例（`passed=321`） |
| 架构分层检查 | 通过（18 例） |
| 工作树洁净检查 | 通过 |

### 2.6 本轮变更文件

`README.md`、`docs/ACCEPTANCE_CRITERIA.md`、`docs/AI_DEVELOPMENT_GUIDE.md`、
`docs/PRD.md`、`docs/ROADMAP.md`、`docs/phase2/PHASE2_RECON_REPORT.md`（修改）；
`docs/phase2/P0_1_FINAL_REVIEW.md`、`docs/phase2/P0_2_REGRESSION_BASELINE.md`、
`docs/phase2/P0_2_FIELD_EVIDENCE_MODEL.md`、`docs/phase2/P0_2_TEST_CHECKLIST.md`（新增）。

**未改动任何代码与测试。**

### 2.7 仍未验证的项目

1. **2025-01～08 共 8 份账单的字段值**未核验（仅确认可提取）。
2. **多页同时部分失败**（失败页 ≥ 2 且仍有文本）：逻辑覆盖，用例仅覆盖两端。
3. **`DUPLICATE` 状态无提取器路径**，需 P0-4/P0-5 接入时补集成测试。
4. **加密 PDF 口令交互、超大/恶意 PDF 模糊测试**未做。
5. **`电费数据汇总.md` 与账单的一致性**未核对；代表日曲线能否代表整月形态未知。
6. 继承 R9 第 4.8 节的其余未验证项。

### 2.8 后续建议

1. **授权合并 PR #2**（P0-1）。合并前需确认：本分支含 P0-2 **设计文档**但不含 P0-2 代码，
   如不希望设计文档随 P0-1 合并，可要求先剔除。
2. 合并后从更新后的 `main` 新建分支开发 P0-2，按 `P0_2_TEST_CHECKLIST.md` 第 5 节的实现顺序推进。
3. P0-2 必须优先实现 R1 防误取规则（标签内含 −110/−35），该坑已在核验中实际踩到。

---

## 3. R11 — 真实账单核验与 P0-2 回归预期冻结

- 完成日期：2026-10-11
- 任务来源：用户提供两份真实账单的实际路径（此前按文件名检索未命中）
- 分支：`phase2/bill-pdf-text-extraction`
- 结论：**完成**（核验报告已入库并推送；CI 见本节）

### 3.1 背景

第二阶段任务书第 10 节要求"所有回归预期都要在原 PDF 中找到对应字段后再冻结"。
此前 R7 的现状核查报告如实记录了"按任务书所列文件名全盘检索未找到这两份账单"。
本次用户给出了实际路径，两份账单文件名为 `2025-09账单.pdf` 与 `2025-10账单.pdf`
（与任务书所列 `本三9月账单.pdf` / `东本三厂10月账单.pdf` 不同，
这解释了此前按文件名检索为何未命中）。

### 3.2 核验结论

**任务书第 10 节表格的 26 项数值（2 份账单 × 13 项）全部在原始 PDF 中
逐字段找到且完全一致，费用勾稽差额为 0.00 元。**

| 项目 | 结果 |
|---|---|
| 一致 | 26 / 26 |
| 不一致 | 0 |
| 提取状态 | 两份均 `success`、`is_complete=True`、文本层可用 |
| 页数 | 9 月 4 页 / 10 月 5 页 |

费用勾稽（由账单原文备注第 3、4 条自身定义口径）：

```text
市场化购电电费 + 上网环节线损费用 + 输配电费 + 系统运行费 + 政府性基金及附加
= 工商业电费
工商业电费 + 功率因数调整电费 = 本期电费/合计
```

9 月：6,708,448.31 → +(−9,206.37) = 6,699,241.94（与"本期电费"一致）
10 月：5,509,070.05 → +(−37,735.81) = 5,471,334.24（与"本期电费"一致）

因此任务书 6.4 节的核对公式在本账单上成立，且任务书 10.1 节的口径要求
均得到原始账单佐证。

### 3.3 真实文本特征（P0-2 的实现约束）

核验过程中实测到 8 项排版特征，直接决定 P0-2 不能依赖简单行内正则：

1. 数字被换行截断（`339059.` ⏎ `33`）；
2. 汉字之间插入空格（`电 费 账 单`）；
3. 标签自身跨行断开（`工商业电费：` + `用电户-110千伏-...`）；
4. 标签与数值被换行分隔（`本期电量` ⏎ `8780498千瓦时`）；
5. **标签内含数字**（`-110千伏`、`-35千伏`）——简单取"标签后第一个数字"
   会取到 −110/−35（本次核验即踩中此坑）；
6. 数量与金额同行相邻（`8780498 6708448.31`）；
7. 小数点与小数位分离；
8. 单位独立成行，需与列绑定。

### 3.4 重要反证：正式总用电量不能由计量点累加

9 月账单第 2 页"电量明细"同时出现 `正向有功（总）8770300` 与
`8516838`（含线损与加减后的计费电量），而第 1 页权威"本期电量"为 `8780498`。
**三者互不相同**，为任务书 10.1 节第 7 条提供了真实反证。

### 3.5 附加发现：存在代表日负荷曲线

同目录 `电费数据汇总.md` 含：10 个月月度汇总 +
**10 个月 × 24 小时**的电量与直接交易电价。

**必须准确表述其边界**：这是每天 24 个整点、且**每月仅一个代表日**，
不等于全月逐时负荷曲线。因此任务书 11.1 节"仅凭月账单不能精确计算自用率"
的结论**依然成立**；但它可在明确标注来源与精度等级的前提下用于估算。
该文件为第三方整理，可信度应低于账单原始字段。

### 3.6 本报告明确未做的事

1. **未实现字段提取代码**——核验由一次性比对脚本完成，不是产品功能；P0-2 才实现解析器。
2. **未核验 2025-01 至 2025-08 的 8 份账单字段**（仅确认可提取）。
3. **未核对** `电费数据汇总.md` 与账单 PDF 的一致性。
4. **未把任何账单文件复制进仓库**——只记录数值结论与文本特征。
5. **未修改**任何代码或测试。

### 3.7 变更文件与 CI

| 文件 | 变更 |
|---|---|
| `docs/phase2/REAL_BILL_VERIFICATION.md` | 新增：核验报告（逐字段比对、勾稽推导、文本特征、口径确认、未做事项、P0-2 冻结建议） |
| `docs/phase2/PHASE2_RECON_REPORT.md` | 更新：原文称账单不可访问，现补充实际路径与核验状态并交叉引用，避免文档结论矛盾 |

| 项目 | 值 |
|---|---|
| 提交 | `330ab0a15e0b2ec6be8a150e50a09a6b8d1c63ae`（docs(phase2): 核验真实账单并冻结 P0-2 回归预期） |
| 运行 | [38147308495](https://github.com/win8-cmd/pv/actions/runs/38147308495)，`head_sha` 与提交完全一致 |
| 结果 | Python 3.14 与 3.11 **均 success**；321 passed |
| 测试 | 321 passed（未改代码与测试） |

### 3.8 仍未验证的项目

1. **2025-01～08 共 8 份账单的字段值**未核验（仅确认可提取）。
2. **`电费数据汇总.md` 与账单的一致性**未核对：其月度汇总、代表日曲线
   均未与账单 PDF 逐项比对。
3. **代表日曲线是否可代表整月负荷形态**未知（每月仅一日采样）。
4. **字段提取代码尚未实现**（P0-2 任务），当前所有数值均由人工比对脚本得出。
5. 任务书中的 `本三6月账单 (1).pdf` 为 **0 字节空文件**，
   提取器正确判为 `failed/empty_file`；该文件本身无内容可核验。
6. 继承 R9 第 2.8 节的其余未验证项。

### 3.9 后续建议

1. 复核并合并 PR #2；合并后进入 **P0-2**。
2. P0-2 的回归测试数据获取方式建议二选一（见核验报告第 9 节）：
   引用仓库外路径并在缺失时 skip，或从账单截取**不含户名/户号/地址**的最小文本片段
   作为内联 fixture（后者更适合 CI 双版本稳定运行）。
3. P0-2 开工前应把本次核验到的 8 项文本特征转成解析规则的设计输入，
   并针对第 5 项（标签内含数字）设置专门的防误取规则。

---

## 4. R10 — 记录状态语义修复的 CI 结论

- 完成日期：2026-10-11
- 任务来源：R9 推送后触发的 GitHub Actions 结果记录
- 分支：`phase2/bill-pdf-text-extraction`
- 结论：**通过**（等待仓库所有者复核，未合并）

### 4.1 对应提交与 PR

| 项目 | 值 |
|---|---|
| 提交完整 SHA | `7619ac1e2551b12761c79dba0fb082131282ef8b` |
| 提交信息 | fix(phase2): 拆分 PDF 提取的 partial 与 needs_ocr 状态语义 |
| PR | [PR #2](https://github.com/win8-cmd/pv/pull/2)（open，未合并） |

### 4.2 GitHub Actions 运行

| 项目 | 值 |
|---|---|
| 运行链接 | [38146878129](https://github.com/win8-cmd/pv/actions/runs/38146878129) |
| `head_sha` | `7619ac1e2551b12761c79dba0fb082131282ef8b`（与该提交**完全一致**，非旧提交的绿色结果） |
| `head_branch` | `phase2/bill-pdf-text-extraction` |
| 事件 | `pull_request` |
| 运行状态 | `completed` / `success` |

### 4.3 Python 3.11 与 3.14 的最终状态

| 作业 | Python | 状态 | 完整测试套件 |
|---|---|---|---|
| `pytest (Python 3.14)` | 3.14.8 | **success** | `321 passed in 3.92s` |
| `pytest (Python 3.11)` | 3.11.17 | **success** | `321 passed in 2.57s` |

其他步骤（两个作业一致）：

| 步骤 | 结果 |
|---|---|
| 跳过用例门禁 | 无跳过用例，全部用例已真实执行（passed=321） |
| 架构分层检查 | 通过（18 例，含 PDF 库分层规则） |
| 工作树洁净检查 | 工作树干净：测试未污染仓库 |

### 4.4 结论说明

R9 记录本地证据，R10 记录远程 CI 结论。本地与 CI 用例数一致（均为 321），
且 CI 在 Python 3.11 与 3.14 上均通过，说明状态语义修复在两个受支持版本上都成立。

### 4.5 仍未验证的项目

见 R9 第 2.8 节。重申：

1. **真实账单字段识别准确性**属 P0-2，本轮未验证任何字段值；
2. 任务书指定的两份真实账单在本机不存在，未验证其数值；
3. **多页同时部分失败（失败页 ≥ 2 且仍有可用文本）**未单独构造测试；
   决策表逻辑覆盖该情形，但没有用例锁定。
4. PR #2 **未合并**，按要求未执行合并。

### 4.6 后续建议

1. 复核并合并 PR #2；合并后进入 P0-2。
2. 若希望闭合第 2.5 节第 3 项，可在 P0-4/P0-5 引入真实多页部分失败样本时补一条测试。

---

## 5. R9 — P0-1 复核修复：拆分 partial 与 needs_ocr 状态语义

- 完成日期：2026-10-11
- 任务来源：P0-1 复核问题修复指令（PR #2 复核意见）
- 分支：`phase2/bill-pdf-text-extraction`
- 结论：**完成**（本地证据；CI 结论见 R10）

### 5.1 问题原因

修复前提取器的状态决策把两种本质不同的情况都归为 `needs_ocr`：

1. **整份 PDF 没有可用文本层**（疑似扫描件）——根本没有文本可取；
2. **部分页面提取失败**——文本可用，但本次结果**不完整**。

更严重的是第 2 种情况下 `text_layer_available` 被置为 `False`
（原实现为 `text_layer_available and status is SUCCESS`），
于是"文本确实可用、只是没取全"被描述成"文档没有文本层"，
与事实相反。二者对账单导入与人工复核的含义完全不同：
前者应复核/重新提取并保留已取到的文本，后者需要 OCR 等另一条路径。

### 5.2 状态定义（修复后）

| 状态 | 场景 | `text_layer_available` | `is_complete` |
|---|---|---|---|
| `success` | 全部页面提取成功且文本可用 | `True` | `True` |
| `partial` | 部分页面失败，但其他页面有可用文本 | **`True`** | `False` |
| `needs_ocr` | 整份文档没有获得可用文本 | `False` | `False` |
| `failed` | 文件缺失/为空/非 PDF/损坏 | `False` | `False` |
| `duplicate` | 内容哈希与已登记文件相同（应用层判定） | — | — |

语义澄清：

- `text_layer_available` 表示"**文档里有没有可用文本**"，与提取是否完整**无关**；
- `is_complete`（等价于 `status == success`）表示"**结果是否完整**"，
  账单导入必须用它判断能否当作完整账单。

`needs_ocr` 的两种子情形由 `error_code` 区分：
`no_text_layer`（页面本身没有文本）与 `page_extraction_failed`（所有页面提取均失败）。

提取器的决策表（四象限，互斥且穷尽）：

```text
文本可用 + 无错误 -> SUCCESS
文本可用 + 有错误 -> PARTIAL
无文本   + 有错误 -> NEEDS_OCR（error_code=page_extraction_failed）
无文本   + 无错误 -> NEEDS_OCR（error_code=no_text_layer）
```

### 5.3 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `src/cenep/domain/pdf_extraction.py` | 新增 `PARTIAL` 状态；新增 `is_partial`/`is_complete`/`failed_pages`/`extraction_error_count`；`_check_status_consistency()` 在类型层面拒绝自相矛盾组合；`to_dict()` 增加 `is_complete`/`is_partial` |
| `src/cenep/infrastructure/pdf/extractor.py` | 决策表重写（四象限）；`text_layer_available` 不再与状态挂钩；新增并导出两个 `error_code` 常量；`summarize()` 增加完整性字段 |
| `tests/unit/pdf_fixtures.py` | 新增 `find_page_number_by_marker()`，用于按内容精确定位页码 |
| `tests/unit/test_pdf_extraction.py` | 新增 `TestStatusSemantics`（测试 A/B/C/D 等 14 例）与 `TestPartialStatusModelConstraints`（8 例） |
| `docs/ARCHITECTURE.md` | 状态表改为四状态 + 两个维度说明 + 为何必须区分 |
| `docs/TEST_PLAN.md` | 数量更新；4.6 明细补充状态语义两组测试 |
| `docs/phase2/PHASE2_RECON_REPORT.md` | P0-1 领域模型的状态集合说明 |
| `README.md` | 数量同步 |

### 5.4 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 新增 `PARTIAL` 而不是复用 `NEEDS_OCR` | 两者后续处理路径不同（复核/重提取 vs OCR），语义必须分离 |
| `text_layer_available` 只表示"文本是否可用" | 字段名即语义；把它当"是否完全成功"用正是原缺陷的根源。完整性另用 `is_complete` 表达 |
| 不把部分失败统一标为 `SUCCESS` | 那会掩盖数据不完整，导致不完整账单被当成完整账单使用 |
| 用 `error_code` 区分 `needs_ocr` 的两种成因 | 让上层无需解析自然语言错误信息即可区分"扫描件"与"提取全失败" |
| 约束放进领域模型 `__post_init__` | 把状态语义固化在类型层面，而不是只靠测试与调用方自觉 |
| 测试故障注入按**页面内容标记**定位 | 替换类方法会让所有页一起失败、替换实例方法又覆盖不到提取器自建的 reader；按内容命中只让目标页失败（详见 2.5） |

### 5.5 测试故障注入的实现过程（留痕）

要测"单页失败"，必须真实触发该分支。过程中试错两次：

1. **替换 `PageObject.extract_text` 类方法并无条件抛错** →
   **所有页面一起失败**，结果变成 `needs_ocr`，根本测不出 `PARTIAL`；
2. **只替换某页实例的方法** → `extract_pdf` 内部新建 `PdfReader`，
   每次取到的是全新页对象，实例补丁覆盖不到，页面根本没失败；

最终方案：替换类方法，但由包装函数**读取该页内容流**判断是否命中标记，
只对命中的页抛错，其余页调用原始实现。这样恰好只让一页失败。
辅助函数 `find_page_number_by_marker()` 会先确认标记存在，
避免标记写错导致"什么都没失败"却被误认为测到了。

### 5.6 测试结果（实测）

本机：Windows 11 专业版 10.0.22621 / Python 3.14.7

| 命令 | 结果 |
|---|---|
| `python -m pytest -p no:cacheprovider` | **321 passed**（0 failed / 0 error / 0 skipped） |
| `python -m pytest --collect-only -q` | 8 个文件，合计 321 |
| `python -m pytest -q tests/unit/test_layering.py` | 18 passed |
| `git diff --check` | 通过（退出码 0） |

用例变化：302 → **321**（新增 19，全部为状态语义与模型约束回归）。
原有 302 个用例**全部保留且通过**，无删除、无跳过、无放宽断言。

### 5.7 状态传播检查（步骤 4）

全仓库检索 `PdfExtractionStatus` / `NEEDS_OCR` / `text_layer_available`：

- 生产代码中只有 `domain/pdf_extraction.py` 与 `infrastructure/pdf/extractor.py` 使用；
- **尚无 UI / 应用服务 / 仓储消费该状态**（P0-5 才会接入），
  因此不存在"只判断 SUCCESS 与 NEEDS_OCR"的遗漏分支；
- 提取器决策表为四象限互斥穷尽；领域模型对 `NEEDS_OCR`/`FAILED`
  使用元组成员判断，新增状态不会落进未处理分支；
- 已通过 `is_complete` 明确表达"能否当作完整账单"，
  避免后续把"PDF 提取成功"等同于"账单有效"。

### 5.8 仍未验证的项目

1. **真实账单字段识别准确性**：属 P0-2，本轮未验证任何字段值。
2. **任务书指定的两份账单**（`本三9月账单.pdf`、`东本三厂10月账单.pdf`）
   在本机不存在，未验证其数值。
3. **多页同时部分失败（失败页 ≥ 2 且仍有可用文本）**：
   决策表逻辑覆盖，但测试只覆盖"单页失败"与"全部失败"两端，中间情形未单独构造。
4. 加密 PDF 口令交互、超大/恶意 PDF 模糊测试、OCR——均未实现/未验证。
5. 继承 R7 第 3.8 节的其余未验证项。

### 5.9 后续建议

1. 复核并合并 PR #2；合并后进入 P0-2。
2. P0-2 起应把"`is_complete` 为假时不得进入正式测算"写成调用方约束
   （P0-5 在服务层落实）。

---

## 6. R8 — 记录 P0-1 的 CI 实测结论

- 完成日期：2026-10-11
- 任务来源：R7 推送后触发的 GitHub Actions 结果记录
- 分支：`phase2/bill-pdf-text-extraction`
- 结论：**通过**（等待仓库所有者复核，未合并）

### 6.1 对应提交与 PR

| 项目 | 值 |
|---|---|
| 提交完整 SHA | `dd9e1283d85daf725c94a8d10329dde17e4b87c7` |
| 提交信息 | feat(phase2): P0-1 PDF 导入与页级文本提取 |
| PR | [PR #2](https://github.com/win8-cmd/pv/pull/2)（open，未合并） |
| 基线 | `4b6f1cb86d81ebe0d9769213d6244cec3746ba6b`（PR #1 合并提交） |

### 6.2 GitHub Actions 运行

| 项目 | 值 |
|---|---|
| 运行链接 | [38145950589](https://github.com/win8-cmd/pv/actions/runs/38145950589) |
| `head_sha` | `dd9e1283d85daf725c94a8d10329dde17e4b87c7`（与该提交**完全一致**，非旧提交的绿色结果） |
| `head_branch` | `phase2/bill-pdf-text-extraction` |
| 事件 | `pull_request` |
| 运行状态 | `completed` / `success` |

### 6.3 Python 3.11 与 3.14 的最终状态

| 作业 | Python | 状态 | 完整测试套件 |
|---|---|---|---|
| `pytest (Python 3.14)` | 3.14.8 | **success** | `302 passed in 2.11s` |
| `pytest (Python 3.11)` | 3.11.17 | **success** | `302 passed in 1.70s` |

其他步骤（两个作业一致）：

| 步骤 | 结果 |
|---|---|
| 跳过用例门禁 | 无跳过用例，全部用例已真实执行（passed=302） |
| 架构分层检查 | 通过（含新增的"PDF 库只允许基础设施层"三条检查） |
| 工作树洁净检查 | 工作树干净：测试未污染仓库 |
| 依赖安装 | 含 `pypdf`，在 Python 3.11 与 3.14 上均安装成功 |

### 6.4 结论说明

R7 记录本地证据，R8 记录远程 CI 结论，两者分开，避免把"本地通过"当成"远程通过"。
本地与 CI 的用例数一致（均为 302），且 CI 在 Python 3.11 上也通过，
说明 `pypdf` 依赖在项目声明的下限版本上可用。

### 6.5 仍未验证的项目

见 R7 第 2.8 节。特别重申两条：

1. **任务书 10 节指定的两份真实账单在本机不存在**，未验证其任何字段值；
   P0-1 亦不含字段识别逻辑，字段准确性属 P0-2 的验证范围。
2. 本 PR **未合并**；按要求未执行合并，等待复核授权。

### 6.6 后续建议

1. 复核并合并 PR #2；合并后进入 **P0-2：电费账单关键字段识别**。
2. P0-2 开工前应取得一份可核对的真实账单，逐字段核对后再冻结回归预期；
   在见到原始 PDF 之前，任务书 10 节表格不得当作真值使用。

---

## 7. R7 — 第二阶段 P0-1：PDF 导入与页级文本提取

- 完成日期：2026-10-11
- 任务来源：第二阶段开发要求文档，任务 P0-1
- 分支：`phase2/bill-pdf-text-extraction`（自最新 `main` 创建）
- 结论：**完成**（本地证据；CI 结论见 R8）

### 7.1 执行前的仓库核查（不采信任务书基线）

| 项目 | 实测值 |
|---|---|
| 远程 `main` 最新提交 | `4b6f1cb86d81ebe0d9769213d6244cec3746ba6b` |
| 该提交内容 | **Merge pull request #1**——第一阶段成果已被仓库所有者合并 |
| 任务书所称基线 | 与远程 `main` 实测一致 |
| 新建分支 | `phase2/bill-pdf-text-extraction`（与 `origin/main` 差异 `0 0`） |
| 核查报告 | `docs/phase2/PHASE2_RECON_REPORT.md` |

**重要变化**：PR #1 已合并，第一阶段三项缺陷修复均已进入 `main`，
第二阶段从干净 `main` 起步，无需在旧分支上叠加。

### 7.2 真实账单可用性（已在核查报告中如实说明）

- 任务书指定的 `本三9月账单.pdf`、`东本三厂10月账单.pdf`：**全盘搜索后确认不存在**，
  因此**未**对任务书 10 节表格的预期值做任何验证，也不声称已验证。
- 环境中另有 **18 份**同类真实账单（国网湖北，大工业用电，110kV），
  位于仓库之外，仅用于本地冒烟与后续回归，**不提交仓库**。

### 7.3 本任务实现内容

| 文件 | 内容 |
|---|---|
| `src/cenep/domain/pdf_extraction.py` | **纯领域模型**：`PdfExtractionStatus`、`PdfPage`、`PdfExtractionResult`、`normalize_page_text`、`is_meaningful_text`；不依赖 pypdf/Qt/sqlite3 |
| `src/cenep/infrastructure/pdf/extractor.py` | pypdf 页级提取、SHA-256、文本层判定、异常映射；失败返回结果对象而非抛异常 |
| `src/cenep/infrastructure/pdf/__init__.py` | 包声明 |
| `tests/unit/pdf_fixtures.py` | 运行时生成测试 PDF（单页/多页/中文/空白），**不提交任何 PDF 二进制** |
| `tests/unit/test_pdf_extraction.py` | 56 个用例，覆盖 4.5 的 12 项必测情况 |
| `tests/unit/test_layering.py` | 把"完全禁止 PDF 库"收紧为"只允许基础设施层"，并新增两条反向检查 |
| `pyproject.toml` | 新增运行依赖 `pypdf>=5.0` |

### 7.4 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 领域模型与解析器分属两层 | 解析库是实现细节；上层只依赖领域模型，将来换库不影响业务与界面 |
| 选 `pypdf` 6.20.0 | 纯 Python（`py3-none-any`，401 KB）、无 C 扩展、3.11–3.14 均可用、多页与中文均实测可用 |
| 失败返回结果对象而非抛异常 | 界面层可稳定展示失败原因而不崩溃（4.6 验收要求）；只有参数非法才抛异常 |
| 不使用临时文件 | 从设计上消除"临时文件清理"风险（4.5 第 11 项），并保证原文件只读 |
| 中文测试不嵌入字体 | 系统 CJK 字体 9–19 MB，提交仓库不可接受；改用 `Type0` + `Identity-H` + `ToUnicode` 构造仅 ~1.6 KB 的 PDF，中文提取被**真实执行**而非跳过 |
| 领域模型禁止"非成功却声称有文本层" | 防止扫描件被误标为解析成功（4.6 验收要求），把约束放在类型层面而非只靠测试 |
| `duplicate` 不由提取器产生 | 重复判定需要与已有记录比较，属应用层职责，提取器无法也不应判断 |
| 中文规范化只做无损处理 | 真实账单存在"数字换行截断""汉字间插空格"，这些是原始证据，必须原样保留交给 P0-2 |

### 7.5 测试结果（实测）

本机：Windows 11 专业版 10.0.22621 / Python 3.14.7

| 命令 | 结果 |
|---|---|
| `python -m pip install -e ".[dev]"` | 成功（依赖声明含 pypdf，安装通过） |
| `python -m pytest -p no:cacheprovider` | **302 passed**（0 failed / 0 error / 0 skipped） |
| `python -m pytest --collect-only -q` | 8 个文件，合计 302 |
| `git diff --check` | 通过（退出码 0） |

用例变化：244 → **302**（新增 58：PDF 提取 56 + 架构分层 2）。
第一阶段 244 个用例**全部保留且通过**，无回归。

### 7.6 真实账单冒烟（本地，未入库）

对 6 份真实账单实测，全部 `success` 且页码一一对应：

| 文件 | 状态 | 页数 | 字符数 |
|---|---|---:|---:|
| 真实账单 A | success | 2 | 2426 |
| 真实账单 B | success | 3 | 3617 |
| 真实账单 C | success | 4 | 5402 |
| 真实账单 D | success | 4 | 4550 |
| 真实账单 E | success | 5 | 6379 |
| 真实账单 F | success | 5 | 6413 |

同时确认：任务书 4.5 的 12 项必测情况在合成样本上逐一覆盖；
损坏文件与无文本层文件状态不同（对应 BILL-013 的提取层部分）。

### 7.7 提交与推送

| 项目 | 值 |
|---|---|
| 分支 | `phase2/bill-pdf-text-extraction` |
| 提交信息 | `feat(phase2): P0-1 PDF 导入与页级文本提取` |
| 提交完整 SHA | 见 R8（避免自引用） |
| 强制推送 | 未使用 |
| 是否修改 `main` | **未修改** |

### 7.8 仍未验证的项目

1. **真实账单字段识别准确性**：P0-1 只做文本提取，字段识别属 P0-2，本轮**未验证**任何字段值。
2. **任务书 10 节两份指定账单的预期值**：文件不可访问，未验证。
3. **OCR**：本阶段明确不实现；无文本层文件只标记 `needs_ocr`。
4. **加密 PDF 的口令输入**：仅尝试空口令，失败即明确报错；未做口令交互。
5. **超大 PDF / 恶意 PDF 的健壮性**：未做模糊测试与资源限制。
6. 内存库多线程并发、真实显示器界面观感、多进程并发写、打包发布、覆盖率数值
   ——继承 R2 第 6.8 节，仍未验证。

### 7.9 后续建议

1. 复核并合并本 PR（P0-1），CI 通过后进入 **P0-2：关键字段识别**。
2. P0-2 需先取一份真实账单，**逐字段核对**后冻结回归预期；
   任务书 10 节表格在未见到原始 PDF 前不得当作真值。
3. P0-4 需处理 `ProcessingStatus` 扩展（`needs_ocr`/`duplicate` 等）与
   `CHECK` 约束迁移。

---

## 8. R6 — 记录本轮 CI 实测结论

- 完成日期：2026-10-11
- 任务来源：R5 推送后触发的 GitHub Actions 结果记录
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- 结论：**通过**（等待仓库所有者授权合并）

### 8.1 对应提交

| 项目 | 值 |
|---|---|
| 提交完整 SHA | `f9bd8fb74cbea98d88da27b1765c3a435a5a240d` |
| 提交信息 | docs: 同步第一阶段验收文档版本并完成最终复核 |
| 分支 | `fix/stage1-review-memory-db-and-schema-version` |

### 8.2 GitHub Actions 运行

| 项目 | 值 |
|---|---|
| 运行链接 | [38123146880](https://github.com/win8-cmd/pv/actions/runs/38123146880) |
| `head_sha` | `f9bd8fb74cbea98d88da27b1765c3a435a5a240d`（与上表提交**完全一致**，非旧提交的绿色结果） |
| `head_branch` | `fix/stage1-review-memory-db-and-schema-version` |
| 事件 | `pull_request` |
| 运行状态 | `completed` / `success` |

### 8.3 Python 3.11 与 3.14 的最终状态

| 作业 | Python | 状态 | 完整测试套件 |
|---|---|---|---|
| `pytest (Python 3.14)` | 3.14.8 | **success** | `244 passed in 2.93s` |
| `pytest (Python 3.11)` | 3.11.17 | **success** | `244 passed in 1.74s` |

从 CI 日志核对到的其他步骤（两个作业均一致）：

| 步骤 | 结果 |
|---|---|
| 跳过用例门禁 | 无跳过用例，全部用例已真实执行（passed=244） |
| 架构分层检查 | 通过 |
| 工作树洁净检查 | 工作树干净：测试未污染仓库 |
| 依赖版本 | PySide6 6.12.0 / pandas 3.0.6 / openpyxl 3.1.5 / pytest 9.1.1 |

### 8.4 PR 当前状态

| 项目 | 值 |
|---|---|
| PR | [#1](https://github.com/win8-cmd/pv/pull/1) |
| 状态 | **open（未合并）** |
| 说明 | 本轮**未执行合并**，也未推送到 `main`，等待仓库所有者复核授权 |

### 8.5 说明

R5 记录的是本地证据（收集、完整测试、`git diff --check`、CI 守卫本地复现）；
R6 记录的是**推送后远程 CI 的真实结论**。两者分开记录，
以避免把"本地通过"表述成"远程 CI 通过"。

---

## 9. R5 — 合并前最终复核与文档版本同步

- 完成日期：2026-10-11
- 任务来源：第一阶段最终修正与合并前验收执行任务书
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- 结论：**通过**（等待仓库所有者授权合并，本轮未合并 PR）

### 9.1 执行前的远程状态核对

不直接采信任务书给出的提交号，先实测远程：

| 项目 | 实测值 |
|---|---|
| 本地分支 | `fix/stage1-review-memory-db-and-schema-version` |
| 本地 HEAD | `f9edf8e572b4cc1360cd91d34cd59bfbe016e0fb` |
| 远程分支 SHA | `f9edf8e572b4cc1360cd91d34cd59bfbe016e0fb` |
| 与远程差异 | `0 0`（完全同步） |
| `main` 远程 SHA | `5494436195dbc1a81eb61717ee79722768618964`（本轮**未触碰**） |
| 工作区状态 | 干净，无未提交变更，无需要归属识别的他人改动 |

任务书所述的"最新提交 f9edf8e"经核对属实。

### 9.2 实际修改的文件及原因

本轮**未修改任何代码与测试**（元数据保护逻辑经复核已完整，见 2.3），
仅修正文档的当前状态描述：

| 文件 | 修改内容 | 原因 |
|---|---|---|
| `docs/TEST_PLAN.md` | 文档版本 `2026.10-stage1-r3` → `r4` | 内容已记录 R4 的实测结果，但版本标识未跟上，与 `PROGRESS_LOG` 记录的轮次不一致 |
| `docs/ACCEPTANCE_CRITERIA.md` | 文档版本 `2026.10-stage1-r2` → `2026.10-stage1-r4`（标题改为"第 4 版：合并前最终复核"）；补充 4 个版本的对照表与"文档版本命名口径"说明 | 文档内容早已覆盖 R3/R4（含新增 A17），但版本号仍停留在 r2，属自相矛盾 |
| `README.md` | 顶部补充"当前状态：第一阶段已完成，正在 PR #1 审阅中，尚未合并到 `main`"，并给出审阅分支与 PR 链接 | 原文只写"开发分支 main"，易被误认为代码已在 main，与实际不符 |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 第 9 节第 6 条由"`main` 分支尚无任何提交"改为当前真实状态（main 已有 3 个提交、改动走分支 + PR）；第 2 条补充强制推送的**唯一例外条件**及其核验要求 | 前者是过期陈述；后者与 R1 中"经授权改写作者身份"的史实冲突，未说明例外会让后续开发者无法解释既有历史 |

**未改动**：`src/`、`tests/` 下任何文件。

### 9.3 数据库元数据保护逻辑复核结论

对 `src/cenep/infrastructure/database.py` 与
`tests/integration/test_database_memory_and_schema_version.py` 逐条复核，
任务书列出的四组规则**均成立**，因此按要求**未重复修改代码**：

| 规则 | 代码依据 | 测试依据 | 结论 |
|---|---|---|---|
| 4.1 真正的新数据库可初始化 | `_read_schema_state()` 在 `schema_meta` 不存在时返回 `(False, MISSING_VERSION)`；`initialize_schema()` 走 `_apply_schema()` 建表、建索引并写入版本号 | `TestMissingVersionRecordIsNotTreatedAsNewDatabase::test_truly_empty_database_is_still_initializable` | 成立 |
| 4.2 元数据不完整必须拒绝 | 表存在但无记录或值为 `NULL` → `(True, MISSING_VERSION)` → 抛 `SchemaVersionError`，且**在写入任何内容之前**抛出 | `test_initialize_rejects_missing_version_record`、`test_initialize_does_not_write_current_version`、`test_null_version_value_is_not_treated_as_new_database`、`test_empty_meta_table_without_version_is_rejected` | 成立 |
| 4.2 不当作新库、不写版本号、不补表 | 拒绝路径无任何 `CREATE`/`INSERT`/`UPDATE`；`schema_meta` 与结构保持原样 | `test_initialize_does_not_write_current_version`（版本行仍缺失）、`test_initialize_does_not_adopt_structure_when_other_tables_exist`（`report` 表未被补回、表集合不变）、`test_metadata_table_existing_alone_is_rejected`（未补齐业务表） | 成立 |
| 4.2 不破坏已有业务数据 | 拒绝路径只读；业务表与数据不动 | `test_business_data_survives_rejected_initialization`（写入项目后拒绝，`count()` 仍为 1） | 成立 |
| 4.3 当前版本幂等 | `stored == SCHEMA_VERSION` 分支仅执行 `CREATE ... IF NOT EXISTS`，不改版本号 | `test_current_version_is_idempotent`、`test_current_version_preserves_existing_data`、`test_current_version_with_missing_tables_is_repaired` | 成立 |
| 4.3 高于支持版本安全拒绝 | `_check_schema_version()` 对 `stored > SCHEMA_VERSION` 抛 `SchemaVersionError` | `test_future_version_is_rejected`、`test_future_version_is_not_silently_downgraded`、`test_future_version_rejected_before_any_write` | 成立 |
| 4.3 低版本仅在存在迁移步骤时迁移 | `_check_schema_version()` 查 `MIGRATIONS`；`_apply_migrations()` 逐步执行 SQL 后才推进版本号，缺步骤即抛错 | `test_older_version_without_migration_is_rejected`、`test_registered_migration_upgrades_real_structure`、`test_missing_migration_step_stops_upgrade` | 成立 |
| 4.3 不得只改版本号不迁移结构 | 版本推进发生在每步迁移 SQL **执行之后**；缺步骤直接失败 | 同上两条（用真实 `ALTER TABLE` 验证结构确实改变） | 成立 |
| 4.4 拒绝时事务正确回滚 | `initialize_schema()` 全部逻辑位于 `Database.transaction()` 内；`SchemaVersionError` 属非 `sqlite3.Error` 异常分支 → 执行 `ROLLBACK` 后原样上抛 | `test_initialize_does_not_write_current_version`、`test_initialize_does_not_adopt_structure_when_other_tables_exist`（断言拒绝后库状态与拒绝前完全一致） | 成立 |

补充说明：验证回滚的测试**复用同一个 `Database` 实例**进行检查，
因此回滚确实由同一事务管理器完成，而非"连接关闭后自然消失"的假象。

### 9.4 测试收集命令与数量

```powershell
.venv\Scripts\python.exe -m pytest --collect-only -q -p no:cacheprovider
```

| 测试文件 | 用例数 |
|---|---:|
| `tests/unit/test_validation.py` | 52 |
| `tests/unit/test_self_consumption.py` | 42 |
| `tests/unit/test_layering.py` | 16 |
| `tests/unit/test_package_import.py` | 21 |
| `tests/unit/test_gui_main_window.py` | 17 |
| `tests/integration/test_database.py` | 51 |
| `tests/integration/test_database_memory_and_schema_version.py` | 45 |
| **合计** | **244** |

- 实际收集测试文件数：**7**
- 实际用例总数：**244**
- 收集错误：**无**（退出码 0）
- 与 `docs/TEST_PLAN.md` 逐项对照：分布表、5 个单元明细小节、2 个集成明细小节、
  合计与小计**全部一致**（脚本比对结果为 True）

### 9.5 完整测试的真实结果

```powershell
.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

```
244 passed in 5.74s
```

| 指标 | 值 |
|---|---|
| 通过 | 244 |
| 失败（failed） | 0 |
| 错误（error） | 0 |
| 跳过（skipped） | 0 |

未删除任何用例，未新增跳过标记，未放宽任何断言。

### 9.6 git diff --check

```powershell
git diff --check
```

无输出，退出码 **0**（无空白字符错误、无补丁格式问题）。

### 9.7 CI 三项守卫的本地复现

不能仅凭本地测试宣称远程 CI 通过，但也需确认守卫逻辑本身有效：

| 守卫 | 本地复现结果 |
|---|---|
| 架构分层检查 | `tests/unit/test_layering.py` 16 个用例全部通过 |
| 跳过用例门禁 | 按 CI 同一正则解析真实输出：`parsed passed=244`、`parsed skipped=0` → 门禁 PASS |
| 工作树洁净检查 | `git status --porcelain` 为空 → PASS（测试未污染仓库） |

### 9.8 提交与推送

| 项目 | 值 |
|---|---|
| 本轮起点提交 | `f9edf8e572b4cc1360cd91d34cd59bfbe016e0fb`（执行前远程与本地的共同 HEAD，已核对一致） |
| 提交信息 | `docs: 同步第一阶段验收文档版本并完成最终复核` |
| 推送分支 | `origin/fix/stage1-review-memory-db-and-schema-version` |
| 强制推送 | **未使用**（全程普通推送） |
| 是否修改 `main` | **未修改** |

> 本节不写入包含本文件的提交自身的 SHA（那会造成自引用且无法在写入前获知）。
> 该提交的完整 SHA、对应的 GitHub Actions 运行链接以及 Python 3.11 / 3.14
> 的最终状态，记录在紧随其后的 **R6** 中。

### 9.9 最新 GitHub Actions

本轮提交推送后触发的新运行结果见 **R6**（待该运行结束后据实记录）。
本地已复现 CI 的三项守卫（见 2.7），但**本地通过不等于远程 CI 通过**，
因此本节不预先声称 CI 结论。

### 9.10 PR 当前状态

| 项目 | 值 |
|---|---|
| PR | [#1](https://github.com/win8-cmd/pv/pull/1) |
| 状态 | **open（未合并，未授权合并）** |
| 合并前要求 | 仓库所有者复核 |

### 9.11 仍未验证的项目

1. **PR #1 未合并**，本轮按要求未执行合并，也未推送到 `main`。
2. **物理显示器上的界面观感与真实鼠标点击回放**：自动化验证在 Qt `offscreen`
   平台完成，未在真实显示器上人工确认布局。
3. **真实电费账单数据与真实电价数据**：第一阶段明确不含，无真实样本参与测试。
4. **多进程并发写压力测试**：未做；内存库的**多线程**并发访问亦未验证。
5. **数据库模式迁移的真实场景**：迁移机制已用真实 `ALTER TABLE` 测试验证，
   但 `SCHEMA_VERSION` 仍为 1、`MIGRATIONS` 为空，尚无历史版本可迁。
6. **元数据损坏形态未穷举**：仅覆盖"缺记录""值为 NULL""空元数据表"
   "只有元数据表"四种；未覆盖 `schema_meta` 表被改成完全不同的列结构等情况。
7. **打包与安装程序**：未实现，仅支持源码方式安装。
8. **代码覆盖率数值**：未采集为验收指标。
9. **文档数量无自动化校验**：`TEST_PLAN` 与实测数量目前靠人工/脚本比对，
   尚未固化为测试用例。

### 9.12 后续建议

1. 由仓库所有者复核并**授权合并** PR #1；合并后本轮文档与修复进入 `main`。
2. （可选）把"文档数量与 `pytest --collect-only` 一致"固化为自动化测试，
   闭合 2.11 第 9 项。
3. （可选）演练首个真实迁移（`SCHEMA_VERSION` 提升到 2 并登记真实 `ALTER TABLE`），
   闭合 2.11 第 5 项。
4. 以上闭合后再评估是否进入第二阶段（电费账单导入与数据提取）。
   **本轮未开始第二阶段。**

---

## 10. R4 — 元数据完整性修复与测试数量统一

- 完成日期：2026-10-11
- 任务来源：复核意见（PR #1 的两项问题）
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- 结论：**完成**（等待复核，未合并）

### 10.1 完成内容

| 编号 | 问题 | 状态 | 实际做法 |
|---|---|---|---|
| 1 | `_read_schema_version()` 未区分"元数据表不存在"与"表存在但缺版本记录" | 完成 | 新增 `_read_schema_state()` 返回 `(表是否存在, 版本或 MISSING_VERSION)`；后者改为抛 `SchemaVersionError` |
| 2 | `TEST_PLAN.md` 分布表与明细分节数量不一致 | 完成 | 以 `pytest --collect-only -q` 实际输出为准重写分布表与各小节数量；补齐新增文件的明细小节 |

### 10.2 缺陷原因与修复

**缺陷：元数据不完整被当作新数据库**

- 原因：`_read_schema_version()` 对两种情形都返回 `None`——
  ① `schema_meta` 表不存在；② 表存在但缺 `schema_version` 记录。
  `initialize_schema()` 见到 `None` 即走"新数据库"分支，
  **写入当前版本号**并把结构未知的库当新库接纳。
- 该缺陷**不是运行中发现的故障，而是复核代码时发现的**；
  修复前其错误行为还被一个测试固化：
  旧用例 `test_missing_version_row_in_existing_meta_table` 断言
  "缺版本记录时写入当前版本"。
- 修复：新增 `MISSING_VERSION` 哨兵与 `_read_schema_state()`，严格区分三种状态；
  `initialize_schema()` 与 `schema_version()` 在"表在但缺版本记录"时都抛
  `SchemaVersionError`，**不写版本号、不补齐缺失表、不接纳未知结构**。
  `NULL` 版本值同样视为元数据不完整。
- 对照场景保持可用：版本号**有效**但缺表属"缺表"，仍可幂等补齐；
  只有 `schema_meta` 表不存在才允许按新库初始化。

**文档缺陷：测试数量不一致**

- `TEST_PLAN.md` 分布表写 `test_validation.py` 52、`test_self_consumption.py` 42，
  但明细分节 4.1/4.2 仍写 51/41（沿用了更早一轮的数字）；
  新增的 `test_database_memory_and_schema_version.py` 完全未进入明细分节。
- 修复：以实际收集结果重写分布表（7 个文件、合计 244）、
  修正 4.1–4.5 数量、补齐 5.1（编号化）与新增 5.2。
- 同时审计全部文档，把当前状态数量统一为 244
  （README、PRD、ROADMAP、AI_DEVELOPMENT_GUIDE、ACCEPTANCE_CRITERIA）。
  R1/R2 小节中的 199/234 属于**历史快照**，故意保留不追溯修改。

### 10.3 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 用独立哨兵而非 `-1` 或空字符串表示"表在但缺版本" | `-1` 会被误当版本号参与比较；哨兵可与 `None` 明确区分且为假值 |
| "表在但缺版本记录"一律拒绝，不做结构推断 | 推断"结构看起来像当前版本"会把猜测变成写入依据；拒绝可由人工修元数据后恢复，猜错则可能破坏数据 |
| 拒绝时不改动任何东西（不写、不补表、不建索引） | 拒绝必须是"无所作为"，否则仍会对结构未知的库产生副作用 |
| 保留"版本有效但缺表可幂等补齐" | 该场景结构版本明确，属正常修复，与元数据损坏性质不同 |
| 重写而非删除错误用例 | 该用例固化了错误语义；直接删除会丢失"这里曾有分歧"的信息，重写为对照组更有价值 |
| R1/R2 的历史数字不追溯改写 | 结论日志的生命力在于如实；追溯改写会让"当时实测是什么"无从考证 |

### 10.4 测试结果（实测）

本机：Windows 11 专业版 10.0.22621 / Python 3.14.7

| 命令 | 结果 |
|---|---|
| `python -m pip install -e ".[dev]"` | 成功 |
| `python -m pytest -p no:cacheprovider` | **244 passed**（0 failed / 0 error / 0 skipped） |
| `git diff --check` | 通过（退出码 0） |
| `python -m pytest --collect-only -q` | 7 个文件，合计 244 |

本次新增 10 个用例（234 → 244），未删除其他测试、未放宽任何断言：

| 用例 | 验证点 |
|---|---|
| `test_schema_version_query_rejects_missing_record` | 查询版本号时报错，不沉默返回 `None` |
| `test_initialize_rejects_missing_version_record` | 初始化抛 `SchemaVersionError` |
| `test_initialize_does_not_write_current_version` | **不写入当前版本号** |
| `test_initialize_does_not_adopt_structure_when_other_tables_exist` | 其他业务表存在时，不改结构、不补 `report` 表 |
| `test_business_data_survives_rejected_initialization` | 既有业务数据保留 |
| `test_null_version_value_is_not_treated_as_new_database` | `NULL` 版本同样视为元数据不完整 |
| `test_empty_meta_table_without_version_is_rejected` | 空 `schema_meta` 表被拒绝 |
| `test_metadata_table_existing_alone_is_rejected` | 只有元数据表的半成品库被拒绝 |
| `test_truly_empty_database_is_still_initializable` | 对照组：真正空库仍可初始化 |
| `test_current_version_with_missing_tables_is_repaired` | 对照组：版本有效时缺表可修复 |
| `test_sentinel_is_distinct_from_none` | 哨兵与 `None` 可区分 |

### 10.5 CI 实测

| 运行 | 触发提交 | Python 3.14 | Python 3.11 |
|---|---|---|---|
| [run 38121815648](https://github.com/win8-cmd/pv/actions/runs/38121815648) | `c45e63d` | success（`244 passed in 1.26s`） | success（`244 passed in 1.79s`） |

跳过用例门禁输出"无跳过用例，全部用例已真实执行（passed=244）"，
架构分层检查与工作树洁净检查均通过。

### 10.6 变更文件清单

| 文件 | 变更 |
|---|---|
| `src/cenep/infrastructure/database.py` | `_read_schema_state()`、`MISSING_VERSION` 哨兵、初始化与查询的元数据校验 |
| `tests/integration/test_database_memory_and_schema_version.py` | 替换错误语义用例，新增 10 个用例 |
| `docs/TEST_PLAN.md` | 分布表与明细小节数量按实测重写，新增 5.2 |
| `docs/ACCEPTANCE_CRITERIA.md` | 新增验收项 A17、缺陷对照行、CI 运行表 |
| `docs/ARCHITECTURE.md` | 元数据保护规则与 `MISSING_VERSION` 说明 |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 第 5 节新增"元数据完整性红线" |
| `README.md`、`docs/PRD.md`、`docs/ROADMAP.md` | 数量同步为 244 |

### 10.7 Git 状态

| 项目 | 值 |
|---|---|
| 提交 | `c45e63d` fix: 区分"元数据表不存在"与"缺版本记录"，并统一测试数量 |
| 推送状态 | 已推送至 `origin/fix/stage1-review-memory-db-and-schema-version` |
| 强制推送 | 未使用 |
| PR | PR #1 保持 open，**未合并**（按要求等待复核） |

### 10.8 未完成事项（如实披露）

1. **PR #1 仍为 open**，本轮修复未合并到 main。
2. 元数据修复属**代码评审发现的缺陷**，非运行中故障；除新增用例覆盖的场景外，
   未穷举所有可能的元数据损坏形态（例如 `schema_meta` 表结构被改成别的列）。
3. 内存库多线程并发、真实显示器观感、真实账单与电价数据、
   多进程并发写、打包发布、覆盖率数值——继承 R2 第 3.8 节，仍未验证。
4. 结论日志与文档数量目前靠人工同步，**无自动化校验**（可将
   `--collect-only` 结果与文档比对做成测试）。

### 10.9 下一轮建议

1. 复核本轮修复与 PR #1，合并后使日志与修复进入 main。
2. （可选）增加"文档数量与实测一致"的自动化校验，闭合第 2.8 节第 4 项。
3. 三项缺陷（内存库、版本降级、元数据完整性）闭合后，再考虑进入第二阶段。

---

## 11. R3 — 建立完成结论日志与每轮更新约定

- 完成日期：2026-10-11
- 任务来源：用户要求"生成本轮已完成的结论文件同步到 GitHub，后续每次完成后执行此类操作"
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- 结论：**完成**

### 11.1 完成内容

| 编号 | 要求 | 状态 | 实际做法 |
|---|---|---|---|
| 1 | 生成本轮已完成的结论文件 | 完成 | 新增 `docs/PROGRESS_LOG.md`；补录 R1、R2 两轮完整结论 |
| 2 | 同步到 GitHub | 完成 | 提交并推送到 PR #1 分支；已用 GitHub API 校验文件确实可从远程取回 |
| 3 | 后续每次完成后执行此类操作 | 完成 | 写入制度而非仅口头约定：`docs/AI_DEVELOPMENT_GUIDE.md` 完成定义新增条目并新增第 10.1 节操作步骤；`README.md` 文档索引与工作约定同步标注 |

### 11.2 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 采用单一累计文件而非每轮一个文件 | 一个位置即可看到全部历史与当前状态；避免文件分散、索引失同步 |
| 最新记录在最上面（倒序） | 查看"当前状态"是最高频需求 |
| 固定九节模板（完成内容 / 缺陷或变更原因 / 关键设计决策 / 测试结果 / CI 实测 / 变更文件清单 / Git 状态 / 未完成事项 / 下一轮建议） | 模板固定才能跨轮次横向对比，也避免遗漏"未完成事项"这一最易被省略的部分 |
| 同时补录 R1 与 R2 | 只记录最新一轮会让上一轮结论无从追溯；R1 的自我纠正记录尤其值得留痕 |
| 把约定写进 AI_DEVELOPMENT_GUIDE 的完成定义并列为完成条件 | 仅写进日志本身容易被后续开发者忽略；纳入 DoD 才有约束力 |
| 本轮也单独记为 R3 | 轮次记录应自洽——新增约定后第一件应用它的事就是记录本轮自身 |

### 11.3 测试结果（实测）

本机：Windows 11 专业版 10.0.22621 / Python 3.14.7

| 命令 | 结果 |
|---|---|
| `python -m pytest -p no:cacheprovider` | **234 passed**（0 failed / 0 error / 0 skipped） |
| `python -m pytest --collect-only -q` | 收集正常，合计 234 |
| `git diff --check` | 通过（退出码 0） |

本轮为纯文档变更，未改动任何代码或测试，用例数与 R2 相同（234）。

### 11.4 CI 实测

| 运行 | 触发提交 | 结果 |
|---|---|---|
| [run 38121391733](https://github.com/win8-cmd/pv/actions/runs/38121391733) | `67145e4`（新增 PROGRESS_LOG） | Python 3.14 与 3.11 均 success |

### 11.5 变更文件清单

| 文件 | 变更 |
|---|---|
| `docs/PROGRESS_LOG.md` | 新增（本文件，含 R1–R3 记录与维护规则） |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 完成定义新增条目；新增第 10.1 节每轮更新步骤与命令 |
| `README.md` | 文档索引加入 PROGRESS_LOG；标注每轮更新约定 |

### 11.6 Git 状态

| 项目 | 值 |
|---|---|
| 提交 | `67145e4` docs: 新增完成结论日志 PROGRESS_LOG，并确立每轮更新约定 |
| 推送状态 | 已推送至 `origin/fix/stage1-review-memory-db-and-schema-version` |
| 强制推送 | 未使用 |

### 11.7 未完成事项（如实披露）

1. **R3 与 PR #1 的其余变更尚未合并到 main**：PR #1 仍为 open；因此
   `docs/PROGRESS_LOG.md` 目前只存在于 PR 分支，合并后才出现在 main。
2. 本文件仍由人工按约定维护，**没有自动化校验**（例如校验索引表与各轮小节一致、
   或校验记录中的用例数与 `pytest --collect-only` 实际数量一致）。
3. 其余未验证事项继承 R2 第 3.8 节，本轮未涉及。

### 11.8 下一轮建议

1. 审阅并合并 PR #1，使结论日志进入 main。
2. （可选）为 PROGRESS_LOG 增加一致性校验测试，闭合第 2.7 节第 2 项。
3. 之后按约定执行：每轮完成时先更新本文件，再推送。

---

## 12. R2 — 第一阶段代码复核与缺陷修复

- 完成日期：2026-10-11
- 任务来源：第一阶段代码复核与缺陷修复任务书
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- Pull Request：[PR #1](https://github.com/win8-cmd/pv/pull/1)（open，mergeable: clean）
- 结论：**通过**（复核新增验收项 A14–A16 全部通过；等待审阅合并）

### 12.1 完成内容

| 编号 | 任务书要求 | 状态 | 实际做法与证据 |
|---|---|---|---|
| 1 | 修复内存数据库问题 | 完成 | 采用共享缓存内存库 + 实例级锚定连接；新增 14 个用例覆盖建表→写入→结束事务→重开事务→读取 |
| 2 | 增强模式版本保护 | 完成 | 初始化前读取现有版本并分类处理；未来/旧版本抛 `SchemaVersionError`，**版本号保持原值**；新增迁移注册表与阶梯执行 |
| 3 | 修正文档测试统计和日期 | 完成 | 验收日期 `2026-02-01` → `2026-10-11`（实测）；各文件用例数统一为 234；文档版本 → `2026.10-stage1-r2` |
| 4 | 增加自动化测试工作流 | 完成 | `.github/workflows/tests.yml`；已在 GitHub 真实运行 3 轮，均 success |
| 5 | 完整回归测试 | 完成 | 安装 + 全量 pytest + collect-only + `git diff --check`，实测数字见 1.4 |
| 6 | Git 要求 | 完成 | 开发前工作树干净；提交到独立分支并创建 PR；**全程未使用强制推送** |
| 7 | 最终交付 | 完成 | 本轮报告已提交给用户；本文件为持久化结论 |

### 12.2 缺陷原因与修复

**缺陷 1：内存数据库跨事务失效**

- 原因：`Database.transaction()` 每次新建连接并在结束时关闭，而 SQLite 普通内存库**按连接隔离**，连接关闭即销毁。初始化建表后连接关闭，表随之消失。
- 修复前实测：`schema_version = None`、`tables = ()`、任意事务报 `PersistenceError: no such table: project`。
- 修复：改用共享缓存内存库（`file:<唯一名>?mode=memory&cache=shared`），由 `Database` 实例持有常驻**锚定连接**维持库存活；每实例唯一库名保证隔离；`:memory:` 作为便捷别名；URI 漏写 `cache=shared` 时自动补齐；新增 `close()` 与 `with` 支持。
- 修复后实测：`schema_version = 1`、`tables count = 12`、跨事务读取正常、仓储 CRUD 全部可用。

**缺陷 2：模式版本静默降级**

- 原因：`initialize_schema()` 无条件把 `schema_meta.schema_version` 写为当前版本。
- 修复前实测：版本置 `99` 后重新初始化 → 被**静默改写为 `1`**。
- 修复：新增版本分类校验与 `SchemaVersionError`（`PersistenceError` 子类）：

| 数据库中的版本 | 行为 |
|---|---|
| 无 `schema_meta` 表（空库） | 建表并写入 `SCHEMA_VERSION` |
| 等于 `SCHEMA_VERSION` | 幂等执行 `CREATE ... IF NOT EXISTS`，不改版本号 |
| 高于 `SCHEMA_VERSION` | 抛 `SchemaVersionError`，**保持原版本号不变**，拒绝读写 |
| 低于且有迁移步骤 | 按阶梯执行迁移 SQL，每步后推进版本号 |
| 低于且无迁移步骤 | 抛 `SchemaVersionError`，拒绝自动升级 |

### 12.3 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 保留内存数据库，而非取消支持 | 任务书允许二选一；内存库便于后续测试，且共享缓存方案只需一个锚定连接即可保持"每次事务新建连接"的既有并发模型 |
| 每实例生成唯一内存库名 | 避免不同 `Database` 实例意外看到同一内存库（该问题在开发中被隔离测试发现并修正） |
| 旧版本无迁移步骤时**拒绝**而非部分升级 | 部分升级会造成"版本号前进但结构未迁移"的假升级，风险高于拒绝启动 |
| 迁移 SQL 执行成功后才推进版本号 | 保证结构与版本号原子一致 |
| 新增 `SchemaVersionError` 而非复用 `PersistenceError` | 调用方可精确区分"版本不兼容"与一般持久化故障；同时继承 `PersistenceError` 保持兼容 |
| CI 增加独立的"跳过用例门禁" | 任务书明确禁止以跳过测试获得绿色结果；仅靠"没有失败"无法证明没有跳过 |

### 12.4 测试结果（实测）

本机环境：Windows 11 专业版 10.0.22621 / Python 3.14.7 / Git 2.55.0.windows.4
依赖版本：PySide6 6.12.0、pandas 3.0.6、openpyxl 3.1.5、pytest 9.1.1、numpy 2.5.4

| 命令 | 结果 |
|---|---|
| `python -m pip install -e ".[dev]"` | 成功（退出码 0） |
| `python -m pytest -p no:cacheprovider` | **234 passed**（0 failed / 0 error / 0 skipped） |
| `git diff --check` | 通过（退出码 0，无空白字符错误） |
| `python -m pytest --collect-only -q` | 收集正常，合计 234 |
| `tests/integration/test_database_memory_and_schema_version.py` | 35 passed |
| `tests/integration/test_database.py` | 51 passed |
| `tests/unit/test_self_consumption.py` | 42 passed |

用例分布（实测 `--collect-only -q`）：

| 测试文件 | 用例数 |
|---|---:|
| `tests/unit/test_validation.py` | 52 |
| `tests/unit/test_self_consumption.py` | 42 |
| `tests/unit/test_layering.py` | 16 |
| `tests/unit/test_package_import.py` | 21 |
| `tests/unit/test_gui_main_window.py` | 17 |
| `tests/integration/test_database.py` | 51 |
| `tests/integration/test_database_memory_and_schema_version.py` | 35 |
| **合计** | **234** |

无回归：原有用例 199 个全部通过，新增 35 个。

### 12.5 CI 实测（GitHub Actions，非本地推定）

| 运行 | 触发提交 | Python 3.14 | Python 3.11 |
|---|---|---|---|
| [run 38120849843](https://github.com/win8-cmd/pv/actions/runs/38120849843) | `6afa5af` | success | success |
| [run 38121051833](https://github.com/win8-cmd/pv/actions/runs/38121051833) | `7f90a75` | success | success |
| [run 38121160023](https://github.com/win8-cmd/pv/actions/runs/38121160023) | `3f2519d` | success | success |

从 CI 日志核对到的实测事实：

| 项目 | Python 3.14.8 | Python 3.11.17 |
|---|---|---|
| 完整测试套件 | `234 passed in 1.58s` | `234 passed in 1.47s` |
| 跳过用例门禁 | 无跳过用例，全部用例已真实执行（passed=234） | 同左 |
| 架构分层检查 | 通过 | 通过 |
| 工作树洁净检查 | 工作树干净：测试未污染仓库 | 同左 |

该项结果同时消除了"Python 3.11 兼容性未验证"这一限制。

### 12.6 变更文件清单

相对 `main`：13 个文件，+1064 / −85

| 文件 | 变更 |
|---|---|
| `src/cenep/infrastructure/database.py` | +317/−28 内存库共享缓存与锚定连接、版本校验、迁移阶梯、`close()` |
| `src/cenep/domain/exceptions.py` | +22 新增 `SchemaVersionError` |
| `src/cenep/domain/__init__.py` | +2 导出新异常 |
| `tests/integration/test_database_memory_and_schema_version.py` | 新增 +415（35 用例） |
| `tests/conftest.py` | +8 内存库夹具语义说明与资源释放 |
| `.github/workflows/tests.yml` | 新增 +126 |
| `README.md` | +25/−14 |
| `docs/ACCEPTANCE_CRITERIA.md` | +60/−5 |
| `docs/ARCHITECTURE.md` | +41/−6 |
| `docs/AI_DEVELOPMENT_GUIDE.md` | +28/−19 |
| `docs/TEST_PLAN.md` | +13/−5 |
| `docs/PRD.md` | +3/−3 |
| `docs/ROADMAP.md` | +4/−4 |
| `docs/PROGRESS_LOG.md` | 新增（本文件） |

### 12.7 Git 状态

| 项目 | 值 |
|---|---|
| 开发前工作树 | 干净，无用户未提交修改 |
| 提交 1 | `6afa5af` fix: 修复内存数据库跨事务失效与模式版本静默降级 |
| 提交 2 | `7f90a75` ci: 测试汇总行可靠输出，并新增跳过用例门禁 |
| 提交 3 | `3f2519d` docs: 记录 CI 实测结果，消除两项未验证事项 |
| 推送状态 | 已推送至 `origin/fix/stage1-review-memory-db-and-schema-version`（`0 0` 同步） |
| 强制推送 | **未使用** |
| 敏感文件 | 未提交数据库、账单、密钥、缓存 |

### 12.8 未完成事项（如实披露）

1. **CI 与代码变更尚未合并到 main**：PR #1 仍为 open，等待审阅。
2. **内存库多线程并发访问**未验证（仅单实例单线程）。
3. **真实显示器界面观感与真实鼠标点击回放**未验证（自动化在 Qt `offscreen`）。
4. **真实电费账单数据与真实电价数据**未提供（本阶段明确不含）。
5. **多进程并发写压力测试**未做。
6. **迁移框架仅具骨架**：机制经真实 `ALTER TABLE` 与"缺步骤即停止"测试验证，但 `SCHEMA_VERSION` 仍为 1，注册表为空。
7. **打包与安装程序**未实现。
8. **覆盖率数值**未采集为验收指标。

### 12.9 下一轮建议

1. 审阅并合并 PR #1。
2. （可选）演练首个真实迁移：把 `SCHEMA_VERSION` 提升到 2 并登记一条真实 `ALTER TABLE`，验证迁移路径在真实场景下可用。
3. （可选）为内存库补多线程并发测试，闭合 1.8 第 2 项。
4. 上述闭合后再进入第二阶段：电费账单导入与数据提取。**本轮未开始第二阶段。**

---

## 13. R1 — 第一阶段工程骨架与核心规则冻结

- 完成日期：2026-10-11
- 任务来源：第一阶段工程骨架与核心规则冻结任务书
- 分支：`main`
- 结论：**通过**（13 项验收项全部通过）

### 13.1 完成内容

在空仓库（`git ls-remote` 无任何 ref、`No commits yet on main`）基础上从零建立：

| 类别 | 内容 |
|---|---|
| 工程骨架 | 分层包结构 `domain` / `calculations` / `application` / `infrastructure` / `ui`；`pyproject.toml`（Python ≥3.11、依赖、pytest 配置、`cenep` 与 `cenep-gui` 入口）、`.gitignore`、`.gitattributes`、`.env.example` |
| 领域层 | 11 个实体契约与全部枚举（`models.py`）、校验规则与结构化问题清单（`validation.py`）、5 类业务异常（`exceptions.py`） |
| 计算层 | 光伏消纳计算：逐时段自发自用/余电上网/电网购电 + 三个比例指标 + 零分母返回未定义 + 能量守恒自检 + 输入指纹 |
| 持久化 | SQLite 12 张表建表语句、事务与回滚、参数化 SQL、外键 RESTRICT 删除策略、`Project` 完整 CRUD |
| 应用服务层 | `ProjectService`：校验 → 计算 → 持久化的用例编排 |
| 表现层 | 最小 PySide6 主窗口：项目列表增删改查、消纳计算输入与结果展示、未开放功能声明 |
| 命令行 | `python -m cenep.cli`：9 个子命令，无 GUI 也能验证计算与持久化 |
| 文档 | 8 份：PRD、ARCHITECTURE、DATA_MODEL、CALCULATION_SPEC、ROADMAP、TEST_PLAN、ACCEPTANCE_CRITERIA、AI_DEVELOPMENT_GUIDE |
| 测试 | 199 个用例，含架构分层 AST 守卫与 Qt `offscreen` 界面测试 |

### 13.2 核心计算结果（标准验收案例）

输入 `load = [3, 8, 2]`、`pv = [5, 4, 2]`（kWh）：

| 指标 | 结果 |
|---|---:|
| 总用电量 | 13 kWh |
| 总光伏发电量 | 11 kWh |
| 自用电量 | 9 kWh |
| 余电上网电量 | 2 kWh |
| 电网购电量 | 4 kWh |
| 自用率 | 9/11 ≈ 0.818182 |
| 负荷覆盖率 | 9/13 ≈ 0.692308 |
| 余电比例 | 2/11 ≈ 0.181818 |

数值与任务书表格逐项一致；能量守恒自检通过。

### 13.3 测试结果（实测）

| 命令 | 结果 |
|---|---|
| `python -m pytest` | **199 passed**（0 failed / 0 error / 0 skipped） |
| `git diff --check` | 通过 |
| GUI 真实启动 | 事件循环启动并正常退出（退出码 0），界面计算结果正确 |
| 推送后复核 | 重新克隆仓库，以克隆自身 `src/` 运行测试 → 199 passed |

界面启动实测输出：`GUI_VISIBLE=True`、`GUI_EXIT_CODE=0`、界面计算结果含 `9.000000` 等验收数值。

### 13.4 Git 状态

| 项目 | 值 |
|---|---|
| 开发前仓库 | 空仓库（无提交、无工作树内容），未覆盖任何既有内容 |
| 提交 | `613b6fc` feat → `9a494a5` docs → `5494436` docs |
| 作者 | `Sterling--Q <335395661+win8-cmd@users.noreply.github.com>` |
| 推送状态 | 已推送至 `origin/main`（`0 0` 同步） |
| 强制推送 | 使用过一次（经仓库所有者明确授权），用于把占位作者 `CENEP Developer` 修正为真实身份；改写前后树对象哈希逐一比对，**内容完全一致** |

### 13.5 本轮的自我纠正记录（留痕）

开发过程中由真实执行发现并修复的问题：Qt `setData` 把 `str` 枚举降级为普通字符串；异常文本泄漏枚举类名（`[Severity.ERROR]`）；`SelfConsumptionResult` docstring 声称负荷覆盖率"可以大于 1"（与公式矛盾的文档缺陷）；`pyproject.toml` 声明 `readme = "README.md"` 而该文件当时不存在；工作区 Windows 文件权限故障阻塞沙箱写入（已按权限诊断流程修复）。

### 13.6 未完成事项（R1 结束时）

真实显示器界面观感、鼠标点击回放、真实账单与电价数据、多文件库并发写、迁移框架、打包安装程序、覆盖率数值。

### 13.7 下一轮建议（R1 结束时）

进入第二阶段账单导入与数据提取。实际下一轮执行的是**代码复核与缺陷修复（R2）**，
即任务书要求的先复核、再推进下一阶段。

---

## 14. 本文件的维护规则（后续每轮必读）

每一轮完成后，按以下步骤操作，**不要跳过第 3、5 步**：

1. **收集证据**：实际运行测试与校验命令，记录真实数字（命令、通过数、失败数、跳过数）。禁止凭记忆或估算填写。
2. **取 Git 事实**：`git log --oneline`、`git status --short --branch`、`git rev-parse HEAD`、与远程的 `rev-list --left-right --count`。
3. **确认未验证事项**：把本轮仍未验证的能力写清，不允许省略或用"基本完成"模糊表述。
4. **追加记录**：在 `## 1. 完成轮次索引` 表格顶部插入一行，并在索引下方插入新的 `## R<n> — <任务名>` 小节，沿用 R2 的九个小节结构（完成内容 / 缺陷或变更原因 / 关键设计决策 / 测试结果 / CI 实测 / 变更文件清单 / Git 状态 / 未完成事项 / 下一轮建议）。
5. **同步文档一致性**：若用例数量、版本号或验收日期变化，同步更新 `README.md`、`docs/TEST_PLAN.md`、`docs/ACCEPTANCE_CRITERIA.md`，避免本文件与它们互相矛盾。
6. **提交并推送**：按当轮约定提交到 PR 分支或 main，并确认远程同步状态；在记录中如实写明是"已推送"还是"仅本地提交"。

轮次编号规则：`R1`、`R2`…… 连续递增；同一轮内的多次补充提交不新开轮次，直接补充该轮记录。
