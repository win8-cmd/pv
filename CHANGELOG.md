# 变更记录（CHANGELOG）

本文件记录 CENEP 各阶段的**实际交付与变更**，用于回答
"当前版本到底有什么、改过什么"。

格式约定：

- 版本号与 `src/cenep/__init__.py::__version__` 保持一致；
- 日期为实际完成日期；
- **只记录已实测通过的内容**，未验证项一律写入"未验证"小节；
- 破坏性变更必须写明迁移方式与旧数据兼容结论。

---

## [未发布] V2.1 — 账单人工录入与 Excel 标准模板整合

**阶段状态**：进行中（阶段 0 已完成，阶段 1 进行中）

### 阶段 0：仓库审计与开发基线（2026-10-12）

**新增**

- `docs/V2.1_BASELINE.md`：V2.1 开发基线报告。记录最新 commit、
  环境与依赖版本、测试实测结果、CI 运行、模块清单、已有/缺失功能、
  冲突与风险清单、待确认事项。

**实测数据（可复核）**

- 最新 commit：`2e8b2b8a9d6129aeeb6804df353a47f6bbc150ea`（`main`，工作区干净）
- 测试：**412 passed**（0 failed / 0 error / 0 skipped）
- 环境：Python 3.14.7；PySide6 6.12.0、pandas 3.0.6、openpyxl 3.1.5、
  pypdf 6.20.0、pytest 9.1.1
- CI 矩阵：Python 3.11.17 与 3.14.8（ubuntu-latest，`QT_QPA_PLATFORM=offscreen`）

**核实结论**

- PR #3 状态：`closed` / **`merged: true`** / `merge_commit_sha = 7669e828…`
  （列表接口对已合并 PR 返回 `merged: null`，以单条接口为准）
- `needs_manual_review` 语义**实测正确**：未就绪必复核、未确认必复核；
  仅"就绪且已确认"可免除复核

**未验证**

- GUI 交互、Windows 打包、Excel/PDF 导出、数据库 v1→v2 迁移、真实账单复核
  （详见基线报告附录 B）

### 阶段 1：项目骨架与基础文档（2026-10-12，进行中）

**变更（路线调整）**

- **取消**"电费账单 PDF / 图片自动识别、OCR、复杂版式识别"开发任务；
  正式入口改为**人工录入 + Excel 标准模板导入**。
- 仓库中已实现的 PDF 文本提取（P0-1）与 PDF 字段解析（P0-2）代码
  **保留但冻结**：不删除、不再扩展，其任何输出仍必须经人工确认后才可使用。

**新增**

- `CHANGELOG.md`（本文件）
- `tests/unit/test_needs_manual_review.py`：`needs_manual_review` 语义专项回归
  测试（规格书第四十四节要求），以该属性本身为断言目标。

**修改**

- `README.md`：未实现功能清单按新路线改写；补充模板与账单文件的存放与 Git 规则。
- `docs/ROADMAP.md`：第二阶段目标、前置条件、交付物、验收门槛按
  人工录入 + Excel 模板路线重写。
- `docs/PRD.md`：账单导入条目改为人工录入 + Excel 模板；
  OCR 条目标注为已取消。
- `docs/ARCHITECTURE.md`：分层规则补充 `data`（Excel 读写）层；
  修正过时的分层守卫测试名称。
- `docs/TEST_PLAN.md`：分层守卫描述与当前实现一致。
- `.gitignore`：放行软件自带的标准模板目录。

**未验证**

- 模板生成与导入（阶段 2 交付）；本阶段未新增任何导入功能。


### 阶段 2：账单标准 Excel 模板与数据模型（2026-10-12）

**新增**

- `src/cenep/data/bill_template_spec.py`：模板**结构规范**（纯数据，无 Excel 依赖）。
  定义 7 张工作表的字段、单位、枚举、必填性、说明，13 类校验项与使用说明条目。
- `src/cenep/data/template_writer.py`：模板生成器（openpyxl）。
  首行字段标题、冻结首行、启用筛选、枚举下拉、关键字段批注、
  `使用说明` 与 `数据校验` 预置内容、样本表显著警示。**不依赖宏。**
- `src/cenep/data/bill_validation.py`：13 类数据校验（规格书第 27 节）。
  只报告不改数；口径不一致不求和；缺失视为未知而非 0；费用包含关系参与判定。
- `src/cenep/domain/bill_models.py`：账单六类实体
  （`ElectricityBill`、`BillFeeItem`、`BillTimeOfUseItem`、`BillMeterPoint`、
  `BillImportBatch`、`BillValidationIssue`）。
- CLI 新增 `bill-template` 命令（`--out` / `--dir`），可直接生成模板。

**数据模型关键决策**

- 金额与电量一律 `Decimal`，**拒绝 `float`**（规格书第 30 节）；
- **空值（`None`）与零值（`Decimal(0)`）严格区分**，不作任何自动补零；
- 负费用合法（功率因数调整电费保留负号）；总电量非负；
- 需量单位必须显式 `kW` 或 `kVA`；
- 费用项只有"未包含在其他费用中"且"纳入基准电费"为是时才计入基准合计；
- 计量点同时"已计入首页总量"且"允许纳入汇总"时**禁止自动汇总**；
- 未确认账单不得进入正式测算；样本数据不得确认。

**实测结果**

- 全量测试 **647 passed**（0 failed / 0 error / 0 skipped）；
  其中本阶段新增：模板 78、账单模型 86、数据校验 46、CLI 模板 5；
  分层守卫由 18 增至 22 例（新增 data 层与 Excel 库边界）。
- 模板文件 31 KB，7 张工作表，业务表 `max_row = 1`（**只写表头，不预置数据行**）。

**未验证**

- GUI 未启动；Excel **导入**（读取）未实现，属阶段 3；
- 数据库未改动（`SCHEMA_VERSION` 仍为 1，`MIGRATIONS` 仍为空）；
- 模板未在真实 Excel 客户端中打开验证（仅用 openpyxl 读回核对结构）。

---

### 阶段 3（部分）：Excel 导入读取层（2026-10-12）

**新增**

- `src/cenep/data/template_reader.py`：读取标准模板并做表头/列映射。
  - 文件级检查：不存在 / 非普通文件 / 空文件 / 损坏文件 → `TemplateReadError`；
  - 工作表检查：缺失必需工作表、业务表缺必需字段 → 结构化错误（含明细）；
  - 模板版本识别（从 `使用说明` 解析，不匹配时给出警告）；
  - **默认排除** `使用说明`、`数据校验`、`样本参考_勿直接测算`（仅记警告）；
  - 列映射：允许**列顺序变化**、支持**中文别名**、去单位后缀宽松匹配；
  - 未识别列**保留并报告**，不静默丢弃；重复表头保留首次出现者；
  - 数据行保留 Excel 真实行号（空行跳过但行号不重排）以便错误定位；
  - 空单元格返回 `None`，**不补 0**；负值**如实读出**（合法性由校验层判定）；
  - `TemplateRow` 提供 `decimal()` / `date()` 转换，支持千分位文本、
    `YYYY-MM-DD` / `YYYY/MM/DD` 文本与 Excel 日期单元格；
  - `compute_file_hash()` 提供 SHA-256，供重复文件识别。
- `tests/unit/test_bill_import.py`：**55 例**，覆盖规格书第 39 节全部 17 类情形。

**实测结果**

- 全量测试 **702 passed**（0 failed / 0 error / 0 skipped）；
- 分层守卫 22 例、`git diff --check` 通过。

**本阶段尚未完成（不得宣称阶段 3 完成）**

- 导入**服务层**：有效/警告/无效记录计数、导入预览、错误汇总、
  重复账单判定与"跳过 / 替换 / 保留"决策、导入批次落库——均未实现；
- 人工录入界面与保存/重开——未实现；
- 数据库未改动（`SCHEMA_VERSION` 仍为 1）；
- 未接入 GUI。

---

## [0.1.0] 第一阶段 — 工程骨架与核心规则冻结

**状态**：已完成并合入 `main`（PR #1，merge commit `4b6f1cb8`）

**交付**

- 分层模块化单体：`domain` / `calculations` / `application` /
  `infrastructure` / `ui`，依赖方向由 AST 测试强制。
- 11 个领域实体契约与 SQLite 全量模式（`SCHEMA_VERSION = 1`，12 张表）。
- 光伏消纳逐时段计算（自用 / 上网 / 购电、三个比例指标、能量守恒自检）。
- 项目 CRUD、安全删除（`RESTRICT`）、校验机制、桌面界面、命令行入口。
- 文档：`ARCHITECTURE.md`、`DATA_MODEL.md`、`CALCULATION_SPEC.md`、
  `PRD.md`、`ROADMAP.md`、`TEST_PLAN.md`、`ACCEPTANCE_CRITERIA.md`、
  `AI_DEVELOPMENT_GUIDE.md`。
- 第一阶段测试基线：244 个用例。

**修复（复核轮）**

- 内存数据库跨事务失效；
- 模式版本静默降级（改为显式报错 + `MISSING_VERSION` 哨兵）；
- 元数据完整性保护与测试数量统一。

---

## 第二阶段 P0-1 — PDF 导入与页级文本提取

**状态**：已完成并合入 `main`（PR #2，merge commit `c43d6845`）

**交付**

- `infrastructure/pdf/`：基于 `pypdf` 的页级文本提取、SHA-256、文本层判定。
- `domain/pdf_extraction.py`：`success` / `partial` / `needs_ocr` / `failed` /
  `duplicate` 状态语义与模型约束。
- 修正状态语义缺陷：拆分 `partial` 与 `needs_ocr`，
  `text_layer_available` 与"提取是否完整"解耦。
- 测试：PDF 提取 75 例、状态语义 19 例。

**注意**：该能力属于**已取消的自动识别路线**，自 V2.1 起冻结。

---

## 第二阶段 P0-2 — 首批账单字段识别

**状态**：已完成并合入 `main`（PR #3，merge commit `7669e828`）

**交付**

- `domain/bill_fields.py`：字段与证据模型、`ConfirmationStatus`
  三态确认闸门（`pending` / `confirmed` / `rejected`）。
  **未确认不得进入正式测算**。
- `calculations/bill_parsing/`：账期、正式总用电量、账单总金额、
  增值税发票金额、展示平均电价、工商业电费与两项费用勾稽；
  字段证据为**最小原文片段**且必须来自原文。
- 测试：字段识别 66 例、确认与证据 25 例。

**注意**：该能力基于 PDF 文本，属于**已取消的自动识别路线**，
自 V2.1 起冻结（保留为实验能力，不再扩展）。
