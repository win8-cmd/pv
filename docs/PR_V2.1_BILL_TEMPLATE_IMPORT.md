# PR: V2.1 账单标准 Excel 模板、导入、人工录入与报告接入

## 摘要

按《总体开发与电费账单模板整合执行规格书 V1.0》实现电费账单的**人工录入 + 标准 Excel 模板导入**路线，
并完成模式版本 2 的账单落库与账单事实报告导出。

**本 PR 不含 PDF/OCR 自动识别开发**——该路线已按要求取消；
第一阶段已冻结的 PDF 代码保留不动、不再扩展。

- 基线：`main` @ `2e8b2b8a`
- 分支：`feature/v2.1-bill-template-import`（10 个提交）
- 测试：**913 passed**（基线 412 → +501），0 failed / 0 error / 0 skipped
- 单文件最大 951 行（上限 1200）

## 变更内容

### 1. 标准 Excel 模板（7 张工作表）

- `data/bill_template_spec.py`：模板**结构规范**（纯数据，无 Excel 依赖）。
- `data/template_writer.py`：生成器。首行字段标题、冻结首行、启用筛选、
  枚举下拉、关键字段批注、使用说明与数据校验预置内容、样本表显著警示。

实测：7 张表齐备；月度汇总 36 列 / 分时 16 / 费用 17 / 计量点 15 / 校验 9 / 样本 5；
约 31 KB；扩展名 `.xlsx`，包内**无 `vbaProject`**；
**业务表 `max_row = 1`**（只写表头，不预置数据行，避免示例被当作正式数据）；
校验表结果默认"待检查"；样本表默认不参与导入。

### 2. 账单数据模型与 13 类校验

- `domain/bill_models.py`：六类实体（`ElectricityBill`、`BillFeeItem`、
  `BillTimeOfUseItem`、`BillMeterPoint`、`BillImportBatch`、`BillValidationIssue`）。
- `data/bill_validation.py`：13 类校验（V01–V13），**只报告不改数**。

核心数据纪律：

| 规则 | 说明 |
|---|---|
| 金额与电量一律 `Decimal` | **拒绝 `float`**（`to_decimal` 抛 `TypeError`） |
| `None` ≠ `Decimal(0)` | "未提供"与"确为零"严格区分，**无任何自动补零** |
| 负费用合法 | 功率因数调整电费保留负号（实测 `-9206.37`） |
| 需量单位 | 只能是 `kW` 或 `kVA` |
| 费用口径 | 仅"未包含在其他费用中"且"纳入基准电费=是"才计入基准合计 |
| 计量点 | 同时"已计入首页总量"且"允许纳入汇总"时**禁止自动汇总**（V05 阻断） |
| 确认闸门 | 未确认不得用于正式测算；样本不得确认 |
| 平均电价 | **不得作为光伏边际节省电价**（规格书 5.3 节） |

### 3. Excel 导入（读取 → 映射 → 服务）

- `data/template_reader.py`：文件级/工作表级检查、模板版本识别、
  默认排除说明/校验/样本三张表、**列顺序无关**、**中文别名**（约 70 组）、
  未知列保留并报告、**真实行号定位**、空值不补 0、负值如实读出。
- `data/template_mapping.py`：模板行 → 领域对象；支持"元/MWh → 元/kWh"显式换算并留痕；
  领域约束失败转为**可定位的导入问题并丢弃该行**，不让整份导入崩溃。
- `data/bill_import_service.py`：两阶段用例。`preview()` **只读**；
  `apply()` 支持**取消 / 仅导入有效 / 全部导入**，重复记录支持**跳过 / 替换 / 保留**；
  有阻断问题时拒绝"全部导入"；取消导入**不写任何数据**。

### 4. 模式版本 2 与账单落库

- `infrastructure/schema_v2.py`：新增 6 张表 + 13 个索引。
  **金额与电量用 `TEXT` 存十进制字符串**（不再用 `REAL`，避免浮点精度影响勾稽）；
  **金额列允许负值**（真实账单存在合法负费用）。
- `infrastructure/bill_repository.py`：`SqliteBillRepository`，批次单事务写入、
  业务键唯一索引兜底、人工确认、样本不得确认。
- `SCHEMA_VERSION` 1 → 2，`MIGRATIONS[1]` 登记真实变更。
  纯新增，复用幂等 DDL；**`bill_record` 逐字未变**，以非破坏方式并存。

### 5. 人工录入、GUI 与报告

- `application/bill_service.py`：导入、人工录入、编辑、删除、
  **复制上月**（金额与电量**必须显式给出、不继承上月数值**）、
  汇总、**确认闸门 `usable_bills()`**、报告导出。
- `ui/bill_page.py`：账单列表/详情、增删改、人工确认、
  **导入预览对话框**（计数、阻断提示、逐行错误定位、重复项处置）、
  生成模板、导出报告。
- 主窗口改为标签页（项目 / 电费账单 / 未开放功能）；
  **未注入账单服务时退化为原单页模式，既有行为不变**。
- `data/report_data.py` + `data/report_writer.py`：6 张工作表的账单事实报告
  （报告说明 / 数据概览 / 数据完整性 / 账单事实 / 费用明细 / 分时与计量点）。
  **明确不含收益率、回收期、NPV/IRR 等经济性结论**。

## 数据库迁移安全性

| 检查项 | 结果 |
|---|---|
| `bill_record` 建表语句 | **逐字未变**（905 字符比对一致） |
| 是否含 `DROP` / `ALTER` / `DELETE` | **无** |
| v1 库升级演练（实跑） | 12 表 / 版本 1 → 18 表 / 版本 2，v2 表齐备，旧项目与旧 `bill_record` 数据**完整保留**，`bill` 与 `bill_record` 并存 |

## 文档修正（审计发现的 13 处冲突）

基线审计发现文档与代码严重不一致，本 PR 一并修正：

- 7 份文档把用例数写作 321 / 244，实际 412（现为 913）；
- `README` 仍称 "PR #1 审阅中未合并"、"PR #2 审阅中尚未合并"（实际均已合并）；
- `ARCHITECTURE.md` 引用**已不存在**的测试名
  `test_pdf_and_ocr_libraries_not_used_in_stage_one`；
- PDF/OCR 表述统一改为**已取消**，并说明改走人工录入 + Excel 模板导入。

新增 `docs/V2.1_BASELINE.md`（阶段 0 交付物）与
`docs/V2.1_AUDIT_AND_DIRECTION.md`（仓库基线审查与方向冻结报告）。

## 分层纪律

实测各层内部依赖：

```
domain           -> []
calculations     -> ['domain']
data             -> ['domain']
application      -> ['calculations', 'data', 'domain', 'infrastructure']
infrastructure   -> ['domain']
ui               -> ['app', 'application', 'domain']
```

审查中发现并修复：`ui/bill_page.py` 曾直接调用
`data.template_writer.write_template` 与 `data.report_writer`，绕过应用层。
现已改为经 `BillService` 与新增的 `application/report_files.py`，
界面层**完全不再导入 `cenep.data` / `cenep.infrastructure`**，并新增两条守卫防回退。

## 测试

| 层次 | 数量 |
|---|---:|
| 基线（`main` @ 2e8b2b8a） | 412 |
| **本 PR** | **913** |
| 新增 | **+501** |

新增测试文件：

| 文件 | 例数 | 覆盖重点 |
|---|---:|---|
| `test_bill_models.py` | 86 | Decimal/float、空值语义、需量单位、确认闸门、费用包含关系、计量点汇总规则 |
| `test_bill_template.py` | 78 | 7 表结构、无宏、下拉、批注、样本隔离、规范与实写一致性 |
| `test_bill_import.py` | 55 | 规格书第 39 节 17 类情形（别名、列序、未知列、损坏文件、重复账期…） |
| `test_bill_service.py` | 50 | 人工录入、复制上月三项安全规则、确认闸门、汇总不把缺失当 0 |
| `test_bill_validation.py` | 46 | 13 类校验口径、只报告不改数、缺失≠0 |
| `test_bill_report.py` | 45 | 报告规则与产出、无经济性结论、无公式、金额文本保精度 |
| `test_schema_v2_enums.py` | 35 | DDL 枚举 ↔ 领域枚举逐字比对 + 内存库约束实测 |
| `test_bill_import_service.py` | 35 | 预览只读、用户决策、重复处置、取消不落库 |
| `test_gui_bill_page.py` | 21 | 真实控件、未提供显示、失败走 `QMessageBox.critical` 且不写数据 |
| `test_cli_bill_template.py` | 5 | CLI `bill-template` 端到端 |

### 验证证据

- 连续 3 次全量运行均 913 passed，**无 flake**；
- 报告文件用 Office 结构检查器 `check_office.py` 校验 **verdict = pass**，6 表齐备；
- GUI 真实启动验证：`QT_QPA_PLATFORM=offscreen` 下构造
  `MainWindow(项目服务, 账单服务)`，标签页 `['项目','电费账单','未开放功能']`，
  schema 版本读出为 2；
- 端到端：人工录入 + Excel 导入两条入口各写一条账单 → 导出报告；
- `compileall` 通过；`git diff --check` 通过；
- 敏感信息扫描：无密钥/口令、无 `pdf`/`db`/`xlsx`/日志入库、无客户标识与本地绝对路径。

## 边界与未完成（不宣称已完成）

**本 PR 明确不做**：PDF 自动识别、OCR、账单图片识别、
依赖 PDF 解析结果自动进入正式测算、经济性测算（IRR/NPV/回收期）。

**未验证事项**：

1. **人工目视验收未做**——无显示器，GUI 结论均来自程序化断言与 offscreen 启动；
2. **模板与报告未在真实 Excel 客户端打开验证**——仅用 openpyxl 读回 + 结构检查器；
3. **未做打包**，未在干净环境安装验证；
4. 负荷数据导入、光伏发电量模拟、湖北分时电价、经济性测算、报告 PDF 版本**未开始**。

## 评审建议关注点

1. **模式迁移策略**：`MIGRATIONS[1]` 复用幂等 `CREATE TABLE/INDEX IF NOT EXISTS`
   而非 `ALTER TABLE`（因是纯新增）。请确认这一取舍可接受。
2. **金额存储改用 `TEXT`**：新表 `bill` 用 `TEXT` 存十进制字符串，
   而第一阶段 `bill_record` 仍为 `REAL`，两者并存。请确认后续是否统一。
3. **确认闸门语义**：`usable_bills()` = 已确认 + 非样本 + 复核状态非"存在疑问"。
   其中"待复核"**可以**确认（否则形成"先复核才能确认、复核又要先确认"的死循环）；
   "存在疑问"**绝不**可用于测算。
4. **报告不含经济性结论**是有意为之，请确认符合预期。
5. `docs/V2.1_AUDIT_AND_DIRECTION.md` 中的待确认项 Q1–Q6
   （模板是否入库、GUI 测试是否引入 pytest-qt、PDF 报告库、已冻结 PDF 代码去留、
   湖北电价政策来源、是否引入 pvlib）**仍需决策**。
