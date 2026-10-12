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

### 阶段 3（完成）与阶段 4（部分）：导入服务层与账单落库（2026-10-12）

**新增**

- `src/cenep/data/template_mapping.py`：模板行 → 账单六类实体。
  空单元格保持 `None`（不补 0）；金额/电量转 `Decimal`；
  支持"元/MWh → 元/kWh"显式换算并留痕；
  领域约束失败（负电量等）转为**可定位的导入问题并丢弃该行**，不让整份导入崩溃。
- `src/cenep/data/bill_import_service.py`：两阶段导入用例。
  `preview()` **只读**（计数 + 问题定位 + 重复候选）；
  `apply()` 写入，支持取消 / 仅导入有效 / 全部导入，
  重复记录支持跳过 / 替换 / 保留；存在阻断问题时拒绝"全部导入"；
  取消导入不写任何数据；持久化经 `BillRepository` 协议注入。
- `src/cenep/infrastructure/schema_v2.py`：模式版本 2 的表结构。
  新增 `bill`、`bill_fee_item`、`bill_tou_item`、`bill_meter_point`、
  `bill_import_batch`、`bill_validation_issue`。
  **金额与电量用 `TEXT` 存十进制字符串**（不再用 `REAL`）；
  `NULL` 表示未提供；金额列**允许负值**（真实账单存在合法负费用）。
- `src/cenep/infrastructure/bill_repository.py`：`SqliteBillRepository`。
  六类实体读写、批次在单事务写入、业务键唯一索引兜底、
  人工确认与复核状态更新、样本不得确认。

**模式迁移**

`SCHEMA_VERSION` 由 **1 提升到 2**，并在 `MIGRATIONS[1]` 登记 1 → 2 的
真实结构变更。由于是**纯新增**（不删列、不改列类型、不动既有数据），
迁移复用幂等的 `CREATE TABLE/INDEX IF NOT EXISTS`，对既有 v1 库只补建新表。
**`bill_record` 保留不动**，以非破坏方式并存。
新增测试实测：v1 库升级后版本变为 2、旧项目与旧 `bill_record` 数据完整保留。

**实测结果**

- 全量测试 **793 passed**（0 failed / 0 error / 0 skipped），
  较上一轮增加 56 例；
- 新增 `test_schema_v2_enums.py`（35 例）：**在建库阶段就拦住 DDL 枚举
  与领域枚举的漂移**。实测中确实发现 3 处漂移并修正
  （`ImportOutcome` 的 `成功/失败` 应为 `全部导入/导入失败`；
  `MeteringBasis` 的 `发电` 应为 `其他`；
  `TimeOfUsePeriod` 的 `尖/峰/谷/其它` 应为 `尖峰/高峰/低谷/其他`）；
- 新增 `test_bill_persistence.py`（18 例）：含"保存→关闭→重开仍可读回"、
  金额 `Decimal` 精确往返（不出现浮点尾数）、
  `None` 与 `Decimal(0)` 严格区分、负费用保留、两个月样本端到端回归、
  重复导入的跳过/替换、业务键唯一索引兜底。

**修复的自身缺陷**

1. `_bill_from_row` 未读回 `confirmation` 列，导致"已确认"账单重开后
   被误认为"待确认"——已修复并加断言；
2. 唯一的业务键冲突抛出原始 `sqlite3.IntegrityError`，
   未翻译为 `PersistenceError`——已修复。

**仍未完成**

人工录入界面与服务、GUI 接入、账单页面与报告导出未实现；
GUI 未启动；未推送。

### 阶段 3 完成：人工录入与 GUI 接入（2026-10-12）

**新增**

- `src/cenep/application/bill_service.py`：账单应用服务。
  - Excel 导入：`preview_import()`（只读）/ `apply_import()`；
  - **人工录入**：`create_bill()` / `update_bill()` / `delete_bill()`；
  - **复制上月**：`copy_bill()` —— 继承户号等静态信息，
    **金额与电量必须显式给出，不继承上月数值**（避免最易发生的虚增数据事故），
    复核与确认状态重置；
  - 查询与筛选：`list_bills()` / `list_bills_by_review_status()` / `summarize()`；
  - **确认闸门**：`usable_bills()` 是"可用于正式测算"的唯一出口
    （已确认 + 非样本 + 复核状态非"存在疑问"）；
  - `validate_project_bills()`：对项目全部账单重跑 13 类校验。
- `src/cenep/ui/bill_page.py`：账单页面。
  项目选择、账单列表、详情与校验结果、新增/编辑/复制上月/删除/人工确认、
  导入 Excel（含**导入预览对话框**：计数、阻断提示、逐行错误定位、
  重复项与处置选择）、生成模板文件下载。
- 主窗口改为标签页布局（注入 `BillService` 时）：
  「项目」「电费账单」「未开放功能」；未注入时退化为原单页模式，**既有行为不变**。
- `cenep.app` 新增 `build_bill_service()`，与项目服务共用同一数据库文件。
- 未开放功能列表更新：PDF 自动识别与 OCR 明确标注**已取消**，
  并说明改用"人工录入 + Excel 模板导入"。

**测试（新增 68 例，共 861）**

- `tests/unit/test_bill_service.py`（50 例）：人工录入、空值不补 0、
  非法数值/日期/单位被拒、整体替换语义、修改后须重新确认、
  已确认删除需显式授权、复制上月的三项安全规则、
  **确认闸门**（未确认/存在疑问不得测算、样本不得确认）、汇总不把缺失当 0、
  与 Excel 导入共用同一套 13 类校验。
- `tests/unit/test_gui_bill_page.py`（16 例）：真实创建控件并断言
  标签页出现、按钮启用状态、表格列、未提供字段显示"未提供"而非 0、
  确认后可用计数变化、删除流程、**失败走 QMessageBox.critical 且不写数据**、
  样本确认失败必须报错、PDF 路线已取消的披露。

**分层守卫增强**

- `test_no_hardcoded_fake_success_results` 现在覆盖 `ui/` 下**全部**文件，
  且只检查**用户可见的字符串字面量**（排除文档字符串）——
  实测中该守卫先是漏掉新页面，改成全目录后又把文档里的说明文字误判为违规。
- 新增 `test_ui_does_not_touch_excel_or_sql_directly`（界面层不得直接用
  openpyxl/sqlite3/写 SQL）与 `test_ui_uses_application_service_for_bills`。

**实测**

- 全量测试 **861 passed**（0 failed / 0 error / 0 skipped）；
- **GUI 真实启动验证通过**：`QT_QPA_PLATFORM=offscreen` 下真实构造
  `MainWindow(project_service, bill_service)`，标签页为
  `['项目', '电费账单', '未开放功能']`，账单页含 8 个操作按钮，
  数据库模式版本读出为 2；
- 未做人工目视验收（无显示器），界面为程序化断言。

**修复的自身缺陷**

1. `usable_bills()` 原先只看领域层的"已确认 + 非样本"，
   会放行被标记"存在疑问"的账单 —— 已追加该条件并补测试；
2. `update_bill()` 用"先插后删"实现，触发业务键唯一索引冲突 ——
   改为**就地 UPDATE**，并重置确认为"待确认"；
3. `_review_status()` 收到 `ReviewStatus` 枚举成员时抛
   "not a valid ReviewStatus"（`str` 子类的经典陷阱）—— 已先判断枚举成员；
4. `update_bill()` 把 `is_sample` 塞进 `ManualBillInput` 导致 `TypeError` —— 已修正。

**仍未完成**

报告导出（Excel/PDF）与负荷数据导入未实现；打包未做；未推送。

### 阶段 4（部分）：账单事实报告接入（2026-10-12）

**新增**

- `src/cenep/data/report_data.py`：报告数据装配（**纯数据，不含 Excel 依赖**）。
  - 区分三类数据：**原始事实** / **计算值** / **缺失待核实**；
  - `format_optional()` 把 `None` 显示为"未提供"，**不显示 0**，
    且**拒绝 `float`**（防浮点混入报告）；
  - 合计只累加**已提供**的账单，缺失不参与求和；全部缺失时返回 `None` 而非 0；
  - `fee_baseline_subtotal()` 只累加"未包含在其他费用中"且"纳入基准电费=是"的项，
    无参与项返回 `None`（避免被读成"合计为零"）；
  - `completeness_findings()` 回答 5 个固定问题，结论只有
    **满足 / 不满足 / 待核实**，**不做评分**。
- `src/cenep/data/report_writer.py`：写成 6 张工作表的 xlsx。
  `报告说明` / `数据概览` / `数据完整性` / `账单事实` / `费用明细` / `分时与计量点`
  （末表含计量点与 13 类校验明细）。金额与电量以**文本**写入以保留十进制精度；
  表头加粗、冻结首行、列宽自适应；**无公式**（事实快照，无需重算）。
- `BillService.build_report()`（只组装不写文件）与 `export_report()`（写文件）。
- 账单页面新增「导出账单报告」按钮。

**明确不做（安全边界）**

- **不计算收益率、回收期、NPV/IRR 等经济性结论**；
- **不把账单展示平均电价当作光伏边际节省电价**（规格书第 5.3 节），
  该字段只作为原始事实出现，报告中不存在"节省电价/边际电价"推导列；
- 缺少分时电量时只报告"无法精确评估"，**不给出估算值**；
- 未人工确认的账单在报告中明确标注"不得用于正式测算"。

**测试（新增 50 例，共 911）**

- `tests/unit/test_bill_report.py`（45 例）：空值显示"未提供"而非 0、
  合计跳过缺失、费用基准小计的口径、账期连续性与跨年判断、
  确认状态判断、可追溯性判断、分时电量齐备性判断、
  三种结论取值受控（不出评分）、
  **报告不得出现经济性指标**、平均电价不得作为推导列、
  6 张表顺序、扩展名修正、父目录创建、**包内无宏**、**无公式**、
  金额文本保精度、负费用保留、明细行数与数据一致、
  以及"SQLite → 报告文件"的端到端导出。
- `tests/unit/test_gui_bill_page.py` 增补 5 例报告导出界面测试：
  按钮存在、空项目拒绝导出、点击后**真实生成** 6 张表、取消不产生文件、
  写入失败必须报错。

**验证证据**

- 全量测试 **911 passed**（0 failed / 0 error / 0 skipped）；
- 端到端实测：人工录入 + Excel 导入两条入口各写一条账单 →
  导出报告 → 用 Office 结构检查器（`check_office.py`）校验
  **verdict = pass**，6 张工作表齐备；
- 单文件行数最大 951（上限 1200）。

**仍未完成**

负荷数据导入、光伏发电量模拟、经济性测算、报告 PDF 版本、打包未实现；未推送。

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
