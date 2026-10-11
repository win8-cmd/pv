# CENEP AI 开发操作手册（AI_DEVELOPMENT_GUIDE）

- 适用仓库：`D:\CENEP`（中国工商业分布式光伏项目经济评价软件）
- 技术栈：Python 3.11+ / PySide6 / SQLite / pytest
- 当前阶段：`第一阶段：工程骨架与核心规则冻结`（见 `src/cenep/__init__.py` 的 `STAGE`）
- 本文档的每一条规则都以当前代码为依据；文中出现的测试名、文件路径、常量名均可在仓库中检索到。

---

## 1. 文档定位与适用范围

本文档是任何继续本项目的 AI 开发者（以及人类开发者）的**操作手册**，规定"什么能做、什么不能做、做完要跑什么命令"。

适用范围：

| 场景 | 是否受本文档约束 |
|---|---|
| 修改 `src/cenep/**` 任何代码 | 是 |
| 修改 `tests/**` | 是 |
| 修改 `docs/**` 或其他说明文件 | 是 |
| 修改 `pyproject.toml` 依赖或 pytest 配置 | 是 |
| 只读地浏览代码、回答问题 | 否（但结论必须真实） |

本文档**不**描述尚未实现的功能。当前阶段真实实现的能力只有：项目基础信息的 SQLite 持久化（增删改查）、光伏消纳计算、输入校验与错误提示。以下能力**尚未实现**，任何文档、注释、界面文案或提交说明都不得声称其存在：电费账单 PDF 解析与 OCR、光伏发电量模拟、完整财务现金流与 IRR/NPV 模型、报告导出（Excel/PDF）、分时电价收益测算、储能与电力市场交易。界面中的 `NOT_IMPLEMENTED_FEATURES`（`src/cenep/ui/main_window.py`）是这些未开放功能的权威清单。

---

## 2. 不可违反的架构规则

依赖方向（唯一允许的方向）：

```
表现层 cenep.ui  →  应用服务层 cenep.application  →  领域层 cenep.domain / cenep.calculations
                                    ↓
                        基础设施层 cenep.infrastructure（由应用服务层调用）
```

### 2.1 规则表

| 编号 | 规则 | 自动执行方式 | 无自动执行时的兜底 |
|---|---|---|---|
| A1 | 领域层与计算层禁止导入 `PySide6`、`shiboken6`、`sqlite3`、`pandas`、`numpy`、`openpyxl`、`pdfminer`、`PyPDF2`、`pypdf`、`fitz`、`requests` | `tests/unit/test_layering.py::TestLayerIsolation::test_domain_and_calculation_layers_have_no_forbidden_imports`（对 `domain`、`calculations` 两个层参数化，AST 解析真实 import） | — |
| A2 | 领域层与计算层禁止导入 `cenep.ui`、`cenep.infrastructure`、`cenep.application` | 同上测试的内部前缀检查；另见 `test_domain_layer_does_not_import_infrastructure`、`test_calculations_do_not_import_ui` | — |
| A3 | 基础设施层禁止导入界面层 | `tests/unit/test_layering.py::TestLayerIsolation::test_infrastructure_does_not_import_ui` | 基础设施层禁止导入应用层的具体规则**仅靠评审**，当前无测试 |
| A4 | 界面层禁止包含业务公式（`min(` 与 `max(` 同时出现、或对 `total_self_consumption` 做比例运算） | `tests/unit/test_layering.py::TestUIContainsNoBusinessFormulas::test_self_consumption_rates_are_not_computed_in_ui`（逐行文本扫描，跳过 `#` 注释行） | 该扫描是启发式的：变量改名后可能漏检，因此仍需人工评审逐行确认界面不出现任何业务公式 |
| A5 | 界面层禁止直接导入 `sqlite3`、禁止包含 SQL 语句 | `tests/unit/test_layering.py::TestUIContainsNoBusinessFormulas::test_ui_does_not_import_sqlite_or_run_sql` | 该测试对 SQL 的判断是"文本中出现 `select ` 就必须同时出现 `sql`"，属于启发式，写完界面文案后必须自检，避免出现英文 `select ` 字样 |
| A6 | 界面层必须通过应用服务访问业务能力 | `tests/unit/test_layering.py::TestUIContainsNoBusinessFormulas::test_ui_uses_application_service`（断言 `ui/main_window.py` 文本同时含 `ProjectService` 与 `run_self_consumption`） | — |
| A7 | 应用服务层不得复制领域公式 | `tests/unit/test_layering.py::TestUIContainsNoBusinessFormulas::test_service_does_not_contain_formulas`（断言 `application/project_service.py` 文本不含 `min(`、`max(`） | 该测试是文本级检查，聚合逻辑（如 `sum(`、除法）不会被捕获，靠评审保证 |
| A8 | 禁止把全部功能塞进单个文件：单文件不超过 1200 行 | `tests/unit/test_layering.py::TestProjectStructure::test_no_oversized_single_file` | — |
| A9 | 分层目录必须真实存在且各自含实现文件 | `tests/unit/test_layering.py::TestProjectStructure::test_module_count_reflects_layering` | — |
| A10 | 关键模块必须存在（`domain/models.py`、`calculations/self_consumption.py`、`application/project_service.py`、`infrastructure/database.py`、`ui/main_window.py` 等） | `tests/unit/test_layering.py::TestProjectStructure::test_expected_modules_exist` | — |
| A11 | 第一阶段任何层都不得引入 PDF/OCR 库（`pdfminer`、`PyPDF2`、`pypdf`、`fitz`、`pytesseract`、`cv2`、`PIL`） | `tests/unit/test_layering.py::TestLayerIsolation::test_pdf_and_ocr_libraries_not_used_in_stage_one` | — |
| A12 | 不得留下未实现占位：核心模块禁止 `NotImplementedError`，全包禁止只有 `pass` 的函数体 | `TestNoFakeImplementations::test_no_not_implemented_placeholders_in_core_paths`、`TestNoFakeImplementations::test_no_functions_with_only_pass_body` | — |
| A13 | 持久化必须走仓储或应用服务，不得在界面/领域层写 SQL | **无自动测试**，仅靠评审 | 评审要点：`cenep.infrastructure.database` 之外不得出现 SQL 字面量 |
| A14 | 基础设施层不得自行决定业务计算规则 | **无自动测试**，仅靠评审 | 评审要点：`infrastructure/` 不导入 `cenep.calculations` |
| A15 | 计算模块不得读取界面控件 | 由 A1/A2 间接保证（计算层导入 Qt 即失败），**"读取控件"本身无专门测试** | 评审要点：`calculations/` 中不得出现任何 Qt 类型名 |

### 2.2 各层职责（写代码前先对号入座）

| 层 | 目录 | 允许做 | 禁止做 |
|---|---|---|---|
| 领域层 | `src/cenep/domain/` | 数据模型（`models.py`）、校验规则（`validation.py`）、业务异常（`exceptions.py`） | 导入 Qt/SQLite/pandas；持有界面状态；调用仓储 |
| 计算层 | `src/cenep/calculations/` | 纯函数计算、结构化结果对象 | 读写数据库、读写文件、访问界面、导入 `cenep.application` |
| 应用服务层 | `src/cenep/application/` | 组织业务流程（校验 → 落库 → 返回结果）、装配依赖、提供用例方法 | 写 SQL、复制公式、import Qt |
| 基础设施层 | `src/cenep/infrastructure/` | SQLite 连接、事务、仓储、模式定义；后续文件读取与报表导出 | 导入界面层；决定业务口径 |
| 表现层 | `src/cenep/ui/` | 采集输入、调用应用服务、展示结果 | 任何业务公式、任何 SQL、直接实例化仓储或 `Database` |

### 2.3 违反架构的典型写法（一律拒绝）

```python
# 反例 1：界面层自己算消纳率（违反 A4）
rate = sum(min(l, p) for l, p in zip(load, pv)) / sum(pv)

# 反例 2：界面层直接查库（违反 A5、A13）
conn = sqlite3.connect(db_path)
rows = conn.execute("SELECT * FROM project").fetchall()

# 反例 3：计算层为了"方便"读数据库（违反 A1、A2）
from cenep.infrastructure.database import ProjectRepository

# 反例 4：应用服务层复制领域公式（违反 A7）
total = sum(min(l, p) for l, p in zip(load, pv))
```

正确写法：界面调用 `ProjectService.run_self_consumption(...)`；应用服务调用 `calculate_self_consumption(...)`；仓储负责 SQL；计算层保持纯函数。

---

## 3. 修改现有代码的流程

按顺序执行，不得跳步。

1. **读代码与文档**：先读要改的模块全文（不要只读片段），并读 `docs/CALCULATION_SPEC.md`（计算口径）、`docs/DATA_MODEL.md`（数据模型）与本文档（开发规则）。
2. **跑基线测试**：修改前必须先确认基线是绿的，否则无法区分"我改坏了"和"本来就坏了"。

   ```powershell
   .venv\Scripts\python.exe -m pytest -q
   ```

   基线期望：当前分支为 `321 passed`（第一阶段在 `main` 上为 244；数量会随新增测试增长，关键是 `0 failed`）。

3. **小步修改**：一次只改一个关注点。不顺手重构无关代码，不格式化整个文件，不修改不属于本次任务的测试。
4. **同步文档**：口径变化同步 `docs/CALCULATION_SPEC.md`；数据模型变化同步 `docs/DATA_MODEL.md`；架构或流程规则变化同步本文档（必要时同步 `docs/ARCHITECTURE.md`）。
5. **跑全量测试**：`.venv\Scripts\python.exe -m pytest -q`，必须全绿。只跑单个文件不足以证明没有破坏其他层。
6. **检查 git 状态**：

   ```powershell
   git status --short
   git diff --check
   git diff --stat
   ```

   确认改动范围与预期一致，无多余文件、无空白符错误、无真实数据库或账单文件混入。

---

## 4. 新增模块的标准流程

### 4.1 新代码放在哪里

| 新增内容 | 目标位置 | 关键约束 |
|---|---|---|
| 领域数据模型 / 枚举 | `src/cenep/domain/models.py` | 主键一律 UUID4 字符串（`new_id()`）；时间戳一律 UTC ISO 8601（`utc_now_iso()`）；电量 kWh、金额元、容量 kWp；字段名区分 `energy_kwh` 与 `power_kw` |
| 校验规则 | `src/cenep/domain/validation.py` | 只判断"数据是否可用"，绝不修正数据；问题代码用模块级 `ISSUE_*` 常量，界面与测试按代码断言而不是按中文文案 |
| 业务异常 | `src/cenep/domain/exceptions.py` | 必须继承 `CENEPError`；未实现的能力抛 `UnsupportedOperationError`，不得返回假结果 |
| 计算公式 | `src/cenep/calculations/` 新模块 | 纯函数；结构化结果 dataclass；非法输入抛 `ValidationError` 并携带结构化 `issues` |
| 业务流程 / 用例 | `src/cenep/application/` | 组织"校验 → 落库 → 返回"；不写 SQL、不写公式 |
| 持久化 | `src/cenep/infrastructure/database.py`（表结构）与新的仓储类 | 参数化 SQL；`PRAGMA foreign_keys = ON`；异常翻译为 `EntityNotFoundError` / `EntityAlreadyExistsError` / `ValidationError` / `PersistenceError` |
| 界面 | `src/cenep/ui/` | 只采集输入、调用应用服务、展示结果；错误必须弹 `QMessageBox` 明确提示，不得静默吞掉 |

### 4.2 新增一个计算的强制要求

以 `src/cenep/calculations/self_consumption.py` 为模板，新增计算必须满足：

1. **必须放在 `cenep/calculations/`**，不得放在 `ui/`、`application/` 或 `infrastructure/`。
2. **必须是纯函数**：显式输入（数值序列等）+ 显式输出（返回结果对象），不读界面控件、不访问数据库、不写文件、不读环境变量。
3. **必须返回结构化结果对象**：`dataclass`（如 `@dataclass(frozen=True) class SelfConsumptionResult`），而不是格式化文本；结果需带 `calculation_version` 与输入指纹（`input_fingerprint`），保证可追溯。
4. **非法输入必须抛 `ValidationError` 且携带结构化 issues**，而不是静默修正。禁止截断、补齐、取绝对值、把 `NaN` 当 0、把缺失值当 0。
5. **零分母的指标返回 `None`**（未定义），禁止写成 `0` 或 `0.0`；落库时 `status` 记 `undefined`。
6. **必须在计算内部做守恒自检**（如 `check_energy_balance()`），守恒不成立说明实现有缺陷。
7. **只能通过应用服务被界面调用**：界面不得直接 import `cenep.calculations`。参考 `ProjectService.run_self_consumption`：

   ```python
   # src/cenep/application/project_service.py 中的既有写法
   def run_self_consumption(self, load, pv, *, interval_minutes=None):
       return calculate_self_consumption(load, pv, interval_minutes=interval_minutes)
   ```

8. **必须提升版本号**：新增或变更公式 → 在计算模块中提升 `CALCULATION_VERSION`（`src/cenep/calculations/self_consumption.py` 内为 `"0.1.0"`）；影响计算口径的假设变化 → 提升 `ASSUMPTIONS_VERSION`（`src/cenep/domain/models.py` 内为 `"2026.02-stage1"`）；新增计算模块时同步考虑 `CALCULATION_ENGINE_VERSION`。
9. **必须同步 `docs/CALCULATION_SPEC.md`**，并在 `MetricName`（`domain/models.py`）中登记新的指标名，使结果可落库、可追溯。

### 4.3 新增模块检查清单

- [ ] 代码放在了正确的层，且该层没有出现越界 import。
- [ ] 新函数有完整类型标注，`from __future__ import annotations` 保持与现有文件一致。
- [ ] 非法输入路径抛 `ValidationError`（或返回 `ValidationResult`），绝不修改调用方传入的数据。
- [ ] 新增了对应的单元测试与（涉及落库时的）集成测试，并已实际运行通过。
- [ ] `.venv\Scripts\python.exe -m pytest -q` 全绿。
- [ ] 版本号与文档已同步；`docs/CALCULATION_SPEC.md` 与 `docs/DATA_MODEL.md` 的对应章节已更新。
- [ ] 未在模块中留下 `pass` 空实现、`NotImplementedError` 占位或假成功返回值。

---

## 5. 变更数据模型的标准流程

按以下顺序执行，顺序不可调换：

1. **修改 `src/cenep/domain/models.py`**：新增/修改实体字段、枚举值与默认值。枚举取值必须与数据库 `CHECK` 约束一致。
2. **修改 `src/cenep/infrastructure/database.py` 中的 `SCHEMA_STATEMENTS`**：同步建表语句、`CHECK` 约束、外键与索引；如新增业务表，同步更新 `BUSINESS_TABLES`（`tests/integration/test_database.py::TestSchemaInitialization::test_initialize_creates_all_tables` 会逐表核对）。
3. **提升 `SCHEMA_VERSION`**（当前值为 `1`）。该值由 `Database.initialize_schema()` 写入 `schema_meta` 表。

   > **元数据完整性红线**：`Database._read_schema_state()` 返回
   > `(元数据表是否存在, 版本或 MISSING_VERSION 哨兵)`。
   > **只有 `schema_meta` 表不存在时，才允许按新数据库初始化。**
   > 若表存在但缺 `schema_version` 记录，`initialize_schema()` 会抛
   > `SchemaVersionError`，且**不写版本号、不补齐缺失表、不接纳未知结构**。
   > 不要试图"顺手补一个版本号"——结构版本未知时补版本号等于静默破坏数据。
   > 不要把 `MISSING_VERSION` 与 `None` 混为一谈：`None` 专指元数据表不存在。
   > 该行为由 `tests/integration/test_database_memory_and_schema_version.py::TestMissingVersionRecordIsNotTreatedAsNewDatabase`
   > 逐条断言（含"其他业务表仍存在时初始化不改动结构"）。
4. **在迁移注册表 `MIGRATIONS` 中登记真实的表结构变更**（`src/cenep/infrastructure/database.py`）。
   现状：`MIGRATIONS: dict[int, tuple[str, ...]] = {}` 已就位，键为**升级前**版本号，
   值为把该版本升级到 `键 + 1` 的 SQL 序列；`Database._apply_migrations()` 会按阶梯
   逐步执行，并在每一步之后更新 `schema_meta`。
   - 提升 `SCHEMA_VERSION` 到 `2` 时，必须登记从 `1` 到 `2` 的**真实**结构变更，例如：

     ```python
     MIGRATIONS = {
         1: (
             "ALTER TABLE project ADD COLUMN grid_connection_date TEXT",
         ),
     }
     ```

   - 未登记迁移步骤时，打开旧版本数据库会抛 `SchemaVersionError` 并**拒绝启动**，
     不会出现"仅改版本号、结构却没变"的假升级。
   - 迁移语句要求：幂等可重入（先 `PRAGMA table_info` 探测再决定是否 `ALTER TABLE`）；
     加列必须允许 `NULL` 或提供默认值，不得要求已有行立即满足新的非空约束；
     禁止 `DROP TABLE` / `DROP COLUMN` 式重建；确需重建时走
     "新建临时表 → 复制数据 → 校验行数与内容 → 原子替换 → 保留备份"的完整路径并在文档中说明。
   - 迁移机制本身已由测试覆盖：
     `tests/integration/test_database_memory_and_schema_version.py::TestSchemaVersionProtection::test_registered_migration_upgrades_real_structure`
     验证迁移真的执行 `ALTER TABLE`（而非只改版本号），
     `::test_missing_migration_step_stops_upgrade` 验证缺步骤时停止升级。
   - **版本号提升必须与迁移代码在同一次提交中落地。**
5. **更新 `docs/DATA_MODEL.md`**。该文件是数据模型的权威说明（声明与 `SCHEMA_STATEMENTS` 逐字段一致）；字段、类型、约束或索引的任何改动都必须同时修改 `src/cenep/domain/models.py`、`src/cenep/infrastructure/database.py` 与本文件。**不要在未读这些文件的情况下改动它们**；若发现文档与代码不一致，以代码为准并先修正文档，再继续改代码。
6. **增加集成测试**（放在 `tests/integration/`）：至少覆盖新表的建表、字段往返（写入后重新用新连接读取）、约束拒绝非法值、外键行为、以及迁移路径（对旧版本库执行迁移后结构与数据均正确）。

**硬性红线**：已存在的用户数据库（默认位于 `%LOCALAPPDATA%\CENEP\cenep.db`）**不能被破坏性重建**。禁止任何形式的"删除数据库文件后重建"、"DROP TABLE 后重建"、"清空表再导入"作为升级手段。用户数据丢失不可逆，任何方案都必须先保留备份并可在失败时回退。

---

## 6. 变更计算规则的标准流程

1. **提升 `CALCULATION_VERSION`**：位于 `src/cenep/calculations/self_consumption.py`（当前 `"0.1.0"`）。结果对象 `SelfConsumptionResult.calculation_version` 会把它带出，落库时写入 `calculation_run.calculation_version`。
2. **同步 `docs/CALCULATION_SPEC.md`**：该文件头部声明"本文件是计算口径的唯一权威说明。代码与此文件必须保持一致"，并记录 `CALCULATION_VERSION`、`ASSUMPTIONS_VERSION` 与对应用户代码路径。任何公式、分母含义、单位或边界处理变化都必须同时改这份文件。
3. **说明口径变化对历史结果追溯的影响**：
   - 历史结果以 `calculation_run`（含 `calculation_version` 与 `input_snapshot`）和 `result_record`（每条记录一个指标，含 `status`）的形式保存。
   - 口径变化后，**旧运行记录继续按当时的版本解释**，不得用新口径重新解释旧结果，也不得静默重算并覆盖历史记录。
   - 如需用新口径得到可比结果，必须创建新的 `calculation_run`，让新旧版本并存、可对比。
   - 旧版本与新版本不可直接比较时，必须在文档与界面提示中明确写出这一点。
4. **不得修改历史计算结果的解释**：`docs/CALCULATION_SPEC.md` 中已发布版本的公式描述属于历史事实。新版本文档应新增版本章节或明确标注版本分界，而不是回改旧版本的描述使历史结果看起来"从来如此"。
5. **同步测试**：至少更新验收案例数值断言、能量守恒断言与边界用例（参考 `tests/unit/test_self_consumption.py`），并确认 `tests/unit/test_gui_main_window.py::TestCalculationFromGui::test_calculation_output_contains_acceptance_values` 中的界面数值断言随之更新。

---

## 7. 编写测试的规则

### 7.1 分工

| 目录 | 范围 | 允许依赖 |
|---|---|---|
| `tests/unit/` | 领域模型、校验规则、计算函数、分层约束、界面构造与交互（无显示器） | 不得依赖真实文件系统持久化状态；数据库用 `Database(":memory:")` 或 `tmp_path` |
| `tests/integration/` | 数据库建表与版本、仓储 CRUD、事务与回滚、约束与异常翻译、内存库生命周期、模式版本保护、应用服务与落库 | 使用 `tmp_path` 下的真实 SQLite 文件，或共享缓存内存库 |

### 7.2 硬性规则

1. **测试必须使用临时数据库（`tmp_path`）**，严禁触碰 `%LOCALAPPDATA%\CENEP\cenep.db`。使用 `tests/conftest.py` 提供的夹具：`db_path`（`tmp_path / "test_cenep.db"`）、`database`（已建表）、`memory_database`、`repository`、`sample_project`、`project_service`。
   使用内存库时注意：`Database(":memory:")` 已被实现为**共享缓存内存库**并由实例持有锚定连接，可以跨事务读写；但它**不能跨 `Database` 实例共享**，用完请调用 `close()` 或使用 `with` 语句。不要绕开 `Database` 直接用 `sqlite3.connect(":memory:")` 建表后交给仓储，那会重现"表随连接消失"的问题。
2. **`tests/conftest.py` 的 `_isolate_default_database` 是 `autouse` 自动夹具**：它对每个测试把环境变量 `CENEP_DB_PATH` 重定向到 `tmp_path_factory.mktemp("cenep-default-db")` 下的临时库。因此即使被测代码走了默认路径分支（如 `ProjectService()` 不传 `database`），也不会碰到真实库。该行为由 `tests/integration/test_database.py::TestRealDatabaseSafety::test_default_database_path_is_redirected_in_tests` 与 `test_temp_database_is_not_inside_user_data_dir` 显式断言。**不要删除、不要覆盖、不要绕过这个夹具。**
3. **断言必须校验数值与能量守恒**：使用 `pytest.approx` 而不是 `==` 比较浮点；对消纳类计算必须断言两条守恒关系（`total_pv == 自用 + 上网`、`total_load == 自用 + 购电`），并调用 `result.check_energy_balance()`。参考 `tests/unit/test_self_consumption.py::test_energy_conservation_relations`。
4. **非法输入必须断言两件事**：明确报错（异常类型 + `issue_code`），且**原始数据未被修改**。参考 `tests/unit/test_self_consumption.py::TestInvalidInputRaises::test_invalid_input_is_not_silently_corrected` 与 `tests/unit/test_validation.py::TestRequireValidEnergySeries::test_input_data_is_not_modified`；落库场景还需断言库内行数/内容未变（如 `tests/integration/test_database.py::TestProjectCrud::test_update_with_invalid_name_rejected`）。
5. **GUI 测试使用 `QT_QPA_PLATFORM=offscreen`**：`tests/unit/test_gui_main_window.py` 在模块导入时执行 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` 并打 `pytest.mark.gui` 标记（标记已在 `pyproject.toml` 注册）。若 PySide6 缺失，测试必须 `skip` 并给出原因，而不是假装通过。手工运行 GUI 测试时：

   ```powershell
   $env:QT_QPA_PLATFORM = "offscreen"; .venv\Scripts\python.exe -m pytest tests\unit\test_gui_main_window.py -q
   ```

6. **只断言真实行为**：测试名与断言必须描述实际发生的检查。不得写"永远通过"的测试、不得 mock 掉被测逻辑本身、不得为了让测试通过而放宽断言。

### 7.3 新增领域单元测试模板

```python
"""新增领域规则单元测试。

约定：只测纯函数与校验规则，不触碰数据库与界面。
"""

from __future__ import annotations

import pytest

from cenep.domain.exceptions import ValidationError
from cenep.domain.validation import ISSUE_NEGATIVE, check_energy_series

# 标准验收案例（与 docs/CALCULATION_SPEC.md 保持一致）
LOAD = [3, 8, 2]
PV = [5, 4, 2]


def test_valid_input_passes() -> None:
    result = check_energy_series(LOAD, PV, interval_minutes=60)
    assert result.is_valid is True
    assert result.status == "valid"


def test_negative_value_is_rejected_with_stable_issue_code() -> None:
    result = check_energy_series([-1.0, 2.0], [1.0, 2.0])
    assert result.is_valid is False
    assert ISSUE_NEGATIVE in result.error_codes()


def test_invalid_input_raises_and_does_not_modify_source_data() -> None:
    load = [1.0, -2.0, 3.0]
    pv = [1.0, 2.0, 3.0]
    snapshot = (list(load), list(pv))

    with pytest.raises(ValidationError) as excinfo:
        from cenep.domain.validation import require_valid_energy_series

        require_valid_energy_series(load, pv)

    assert ISSUE_NEGATIVE in excinfo.value.issue_codes()
    assert (load, pv) == snapshot  # 原始数据未被修改
```

### 7.4 新增仓储集成测试模板

```python
"""新增仓储集成测试。

约定：使用 conftest 的 database / repository / sample_project 夹具，
     全部落在 tmp_path，绝不触碰用户真实数据库。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cenep.application.project_service import ProjectService
from cenep.domain.exceptions import EntityNotFoundError
from cenep.domain.models import Project
from cenep.infrastructure.database import Database, ProjectRepository


def test_repository_roundtrip_on_temp_database(database: Database, repository: ProjectRepository) -> None:
    project = Project(name="集成测试项目", location="湖北省武汉市")
    repository.add(project)

    loaded = repository.get(project.project_id)
    assert loaded is not None
    assert loaded.name == "集成测试项目"
    assert loaded.location == "湖北省武汉市"


def test_data_is_really_persisted_on_disk(database: Database, db_path: Path) -> None:
    """用全新连接与全新服务实例重新读取，证明真的落盘。"""
    ProjectService(database).create_project(name="落盘验证项目")

    reopened = ProjectService(Database(db_path))
    assert [item.name for item in reopened.list_projects()] == ["落盘验证项目"]


def test_missing_entity_raises(repository: ProjectRepository) -> None:
    with pytest.raises(EntityNotFoundError):
        repository.get_or_raise("0" * 32)
```

---

## 8. 禁止事项清单

| 编号 | 禁止行为 | 说明 |
|---|---|---|
| B1 | 空实现 / 占位返回 | 不得用 `pass` 函数体或 `NotImplementedError` 冒充功能；未实现的能力必须抛 `UnsupportedOperationError` 并在界面显式说明尚未开放 |
| B2 | 假成功提示 | 不得在没有真实完成操作时提示"保存成功""已导出"等。界面错误必须走 `QMessageBox.critical` / `warning` 明确报错 |
| B3 | 静默修正用户数据 | 不截断、不补齐序列、不取绝对值、不把 `NaN`/缺失当 0、不把非法值替换为默认值 |
| B4 | 未定义指标写成 0 | 零分母或数据缺失时，比例指标必须为 `None` 并标 `status="undefined"`，不得写 0 |
| B5 | 绕过校验直接写库 | 不得跳过领域校验或跳过仓储层，直接用 SQL 写入业务数据 |
| B6 | 在 UI 里写公式 | 界面只能调用应用服务；任何 `min/max/比例/求和` 形式的业务计算都属于越界 |
| B7 | 删除或重置用户未提交的修改 | 不得清理工作区未提交改动、不得 `git checkout -- .`、不得删除用户文件来"让测试通过" |
| B8 | 把真实项目数据库、账单文件、密钥提交进仓库 | `.gitignore` 已排除 `*.db`、`*.sqlite*`、`*.pdf`、`*.xlsx`、`.env`、`*.pem`、`*.key` 等；不得用 `git add -f` 绕过 |
| B9 | 编造验证结果 | 不得声称跑过未跑的测试、不得引用不存在的测试名或文件、不得把"代码已写"等同于"功能已验证" |
| B10 | 破坏性处理用户既有数据库 | 禁止删库重建、`DROP TABLE` 重建、清空表后重导 |
| B11 | 修改历史计算结果的解释 | 旧版本口径与旧结果必须保持原样可追溯 |
| B12 | 引入 PDF/OCR/财务模型等未实现能力 | 第一阶段不得引入 PDF/OCR 依赖，也不得用估算公式替代未实现的财务模型 |

---

## 9. 提交与变更管理

每次提交前必须执行以下命令并确认结果：

```powershell
git status --short     # 确认没有多余文件、没有真实数据库或账单文件
git diff --check       # 确认没有空白符错误 / 冲突标记
git diff --stat        # 确认改动范围与预期一致
```

补充规则：

1. **禁止 `git reset --hard`**。它会不可逆地丢弃未提交的工作。
2. **禁止强制推送**（`git push --force` / `--force-with-lease`）。
   唯一的例外是仓库所有者**明确逐次授权**改写已发布历史（例如修正提交作者身份）。
   即便获授权，也必须：使用 `--force-with-lease` 而非 `--force`；
   改写前后逐一比对树对象哈希以证明**文件内容未变**；
   并在 `docs/PROGRESS_LOG.md` 中记录授权来源与核验结果。
   历史上仅发生过一次此类授权改写，已记录在 `docs/PROGRESS_LOG.md` 的 R1 小节。
3. **禁止在未获授权时修改远程**：不新增/删除远程、不改远程分支、不推送、不建/删 tag。默认只在本地提交。
4. **明确区分本地提交与已推送状态**：报告中必须写清"仅在本地提交，未推送"或"已推送到 `<remote>/<branch>`"，不得含糊表述为"已提交"就算完成同步。
5. 提交前必须已经跑过全量测试（见第 10 节），并在提交信息中说明"改了什么、为什么改、如何验证"。
6. 仓库当前状态提示（截至 2026-10-11）：`main` 已有 3 个提交（第一阶段骨架与文档），
   当前开发在审阅分支 `fix/stage1-review-memory-db-and-schema-version` 上，
   经 PR #1 审阅后合并。**不要直接向 `main` 推送**，改动请走分支 + PR。
   提交前务必用 `git status --short` 逐项确认纳入范围，尤其是 `docs/`、`tests/` 与 `src/`。
7. 每轮完成后必须更新 `docs/PROGRESS_LOG.md` 并同步 GitHub（见第 10.1 节）。

---

## 10. 完成定义（Definition of Done）

一个变更只有在下列全部条目成立时才算完成：

- [ ] 代码实现完成，且没有空实现、占位返回或假成功提示。
- [ ] 测试已编写并实际运行通过（不是"应该会通过"）。
- [ ] 文档已同步：涉及计算口径改 `docs/CALCULATION_SPEC.md`；涉及数据模型改 `docs/DATA_MODEL.md`；涉及流程与规则改本文档。
- [ ] 全量测试全绿。
- [ ] 无越界依赖（第 2 节规则全部满足）。
- [ ] 无假实现（第 8 节 B1/B2/B4 全部满足）。
- [ ] git 状态已核查（`git status --short`、`git diff --check`、`git diff --stat`）。
- [ ] **已在 `docs/PROGRESS_LOG.md` 追加本轮的完成结论记录，并同步到 GitHub**（见第 10.1 节）。

### 10.1 每轮必做：更新完成结论日志

**这是一项固定工作约定，不是可选项。** 每一轮开发或复核完成后，
必须在 `docs/PROGRESS_LOG.md` 追加一条结论记录，并推送到 GitHub，否则本轮不算完成。

操作步骤：

1. 实际运行测试与校验命令，记录**真实数字**（命令、通过数、失败数、跳过数）。
   禁止凭记忆或估算填写，也禁止把"代码已写"写成"已验证"。
2. 取 Git 事实：`git log --oneline`、`git status --short --branch`、`git rev-parse HEAD`、
   与远程的 `git rev-list --left-right --count origin/<branch>...HEAD`。
3. 明确列出**仍未验证**的能力，逐条写清；不允许省略或用"基本完成"模糊表述。
4. 在 `docs/PROGRESS_LOG.md` 的索引表格顶部插入一行，并在索引下方新增
   `## R<n> — <任务名>` 小节，沿用既有的九个小节结构：
   完成内容 / 缺陷或变更原因 / 关键设计决策与理由 / 测试结果（实测）/
   CI 实测 / 变更文件清单 / Git 状态 / 未完成事项 / 下一轮建议。
5. 若用例数量、版本号或验收日期发生变化，同步更新 `README.md`、
   `docs/TEST_PLAN.md`、`docs/ACCEPTANCE_CRITERIA.md`，
   避免各文件互相矛盾（文档与代码不一致视为未通过）。
6. 提交并推送，然后在记录中**如实写明**是"已推送到远程"还是"仅本地提交"。

轮次编号连续递增（`R1`、`R2`……）。同一轮内的多次补充提交不新开轮次，
直接补充该轮记录即可。

对应命令：

```powershell
# 1) 全量测试（唯一权威的"通过"依据，会输出 N passed 汇总行）
.venv\Scripts\python.exe -m pytest -p no:cacheprovider

# 2) 仅分层架构约束（改动 import 结构或界面时必须单独确认）
.venv\Scripts\python.exe -m pytest tests\unit\test_layering.py -q

# 3) 仅数据库与持久化
.venv\Scripts\python.exe -m pytest tests\integration -q

# 4) 用例数量（写入结论记录时使用真实收集结果）
.venv\Scripts\python.exe -m pytest --collect-only -q

# 5) git 状态核查
git status --short
git diff --check
git diff --stat
git rev-list --left-right --count origin/<branch>...HEAD
```

---

## 11. 环境与常用命令

**先决条件：必须避免 Microsoft Store 的 `python` 存根。** Windows 上直接输入 `python` 可能命中 `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe` 这个占位程序，它会打开应用商店而不是运行解释器。判断与规避方式：

```powershell
# 查看 python 实际解析到哪个可执行文件
Get-Command python -All | Select-Object Source

# 若出现 WindowsApps 路径，先看本机有哪些真实解释器，再按版本调用
py -0p
py -3.12 --version
```

本机现状示例（以实际 `py -0p` 输出为准）：当前仓库的 `.venv` 由 Python 3.14 创建；`py -0p` 也可能只列出 3.14 与 3.12。**不要凭记忆写死 `py -3.11`**，先执行 `py -0p` 选择本机真实存在的 ≥3.11 版本；仓库自身的 `requires-python` 为 `>=3.11`。

虚拟环境的解释器路径固定为 `.venv\Scripts\python.exe`；本手册中所有命令都显式使用该路径。

| 目的 | 命令 |
|---|---|
| 创建虚拟环境 | `py -3.12 -m venv .venv`（版本先用 `py -0p` 确认真实存在，需 ≥3.11） |
| 安装（含开发依赖） | `.venv\Scripts\python.exe -m pip install -e ".[dev]"` |
| 升级 pip | `.venv\Scripts\python.exe -m pip install --upgrade pip` |
| 运行全量测试 | `.venv\Scripts\python.exe -m pytest -q` |
| 运行单元测试 | `.venv\Scripts\python.exe -m pytest tests\unit -q` |
| 运行集成测试 | `.venv\Scripts\python.exe -m pytest tests\integration -q` |
| 运行 GUI 测试（无显示器） | `$env:QT_QPA_PLATFORM = "offscreen"; .venv\Scripts\python.exe -m pytest tests\unit\test_gui_main_window.py -q` |
| 带覆盖率 | `.venv\Scripts\python.exe -m pytest --cov=cenep --cov-report=term-missing` |
| 启动 GUI | `.venv\Scripts\python.exe -m cenep` |
| 启动 GUI（等价入口） | `.venv\Scripts\python.exe -m cenep.cli gui` |
| 查看版本与运行环境 | `.venv\Scripts\python.exe -m cenep.cli info` |
| 初始化数据库（幂等） | `.venv\Scripts\python.exe -m cenep.cli init-db` |
| 无界面验证核心计算（人类可读） | `.venv\Scripts\python.exe -m cenep.cli self-consumption --load 3,8,2 --pv 5,4,2 --interval 60` |
| 无界面验证核心计算（JSON，便于机器核对） | `.venv\Scripts\python.exe -m cenep.cli self-consumption --load 3,8,2 --pv 5,4,2 --interval 60 --json` |
| 使用临时数据库做实验（不碰真实库） | `.venv\Scripts\python.exe -m cenep.cli --db .\.tmp-check.db self-consumption --load 3,8,2 --pv 5,4,2` |

说明：

- 环境变量 `CENEP_DB_PATH` 可覆盖默认数据库路径（见 `.env.example` 与 `src/cenep/config.py`）；未设置时使用 `%LOCALAPPDATA%\CENEP\cenep.db`。
- 默认数据库**不在仓库目录内**，这是刻意的设计，用于避免真实项目数据被提交。
- CLI 退出码可用于自动化判断：`0` 成功；`2` 输入解析失败；`3` 计算输入校验失败；`4` 业务操作失败（见 `src/cenep/cli.py`）。
- 上述命令中的 `python -m cenep` 与 `python -m cenep.cli` 都指向同一套应用装配（`src/cenep/app.py`），不存在第二套实现。

---

## 12. 沟通与报告要求

AI 开发者向用户或上游智能体汇报时，必须遵守：

1. **不得把"代码已写"当作"功能已验证"**。只有实际执行过的命令与真实输出才能作为证据。
2. **不得编造测试结果**。不得写"测试已全部通过"而实际未运行。
3. **未验证事项必须显式标注**：写明未验证的内容、原因（如无显示器环境、缺依赖）、以及验证所需的具体命令。
4. **区分"已实现 / 未实现 / 部分实现"**，并说明各自的边界。不要用"基本完成""应该没问题"这类模糊表述代替事实。
5. **报告必须包含证据**：运行的命令、观测到的结果（如 `321 passed`）、改动的文件清单、以及 git 状态核查结论（本地提交还是已推送）。
6. **测试通过数量与耗时以实际输出为准**，不要凭记忆填写。
7. **遇到阻塞要直说**：明确指出是哪一条规则或哪一个测试挡住了进展，不要绕过规则实现"看起来能跑"的版本。
