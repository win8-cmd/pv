# CENEP 系统架构说明书（ARCHITECTURE）

- 文档版本：`2026.02-stage1`
- 软件版本：`0.1.0`
- 对应代码：`src/cenep/`

---

## 1. 架构风格

CENEP 采用 **Python 模块化单体（modular monolith）** 架构，严格分层。
选择理由：

1. 项目为单机桌面工具，部署与维护成本必须低；
2. 但业务规则（消纳、电价、财务）必须能脱离界面独立测试与复用；
3. 后续将扩展到账单解析、发电量模拟、报告导出，若不分层会迅速失控；
4. 单体便于未来按层拆出服务或命令行批处理，不需要现在承担分布式复杂度。

技术栈：

| 用途 | 选型 | 说明 |
|---|---|---|
| 语言 | Python ≥ 3.11 | 开发与验收环境为 Python 3.14.7（Windows） |
| 桌面 GUI | PySide6 ≥ 6.6 | Qt for Python（LGPL） |
| 本地数据库 | SQLite（标准库 `sqlite3`） | 单文件、免部署 |
| 数据处理（后续） | pandas ≥ 2.0 | 第二阶段账单与负荷数据的表格处理基础 |
| Excel 导出（后续） | openpyxl ≥ 3.1 | 报告导出基础 |
| 测试 | pytest ≥ 7.4、pytest-cov | 单元 + 集成 |
| 发电量模拟（第四阶段） | pvlib | **本阶段未引入**，届时再添加 |

依赖数量在第一阶段刻意保持最小：只安装当前或紧邻阶段真正需要的库，
不为"技术栈清单完整"而预装无用依赖。

---

## 2. 分层与依赖方向

```text
┌──────────────────────────────────────────────────────────────┐
│ 表现层  cenep.ui                                             │
│   main_window.py  —— PySide6 窗口、对话框、结果渲染           │
│   职责：采集输入、展示结果、提示未开放功能                     │
│   禁止：写公式、执行 SQL、访问 sqlite3                         │
└───────────────────────────┬──────────────────────────────────┘
                            │ 只允许向下调用
┌───────────────────────────▼──────────────────────────────────┐
│ 应用服务层  cenep.application                                 │
│   project_service.py —— 用例编排：校验 → 计算 → 持久化         │
│   职责：组织业务流程、事务边界、装配依赖、产生追溯信息           │
│   禁止：复制领域公式、拼接 SQL                                 │
└───────┬───────────────────────────────────┬──────────────────┘
        │                                   │
┌───────▼───────────────────────┐  ┌────────▼──────────────────┐
│ 领域层  cenep.domain           │  │ 基础设施层                 │
│   models.py    数据模型与枚举   │  │  cenep.infrastructure      │
│   validation.py 校验规则        │  │   database.py              │
│   exceptions.py 业务异常        │  │   SQLite 模式/事务/仓储     │
│                                │  │                            │
│ 计算模块  cenep.calculations    │  │  后续：文件读取、报告导出   │
│   self_consumption.py 消纳计算  │  │                            │
│                                │  │                            │
│ 禁止：PySide6 / sqlite3 /       │  │ 可以：sqlite3、pandas、     │
│       pandas / PDF 库           │  │       openpyxl             │
└────────────────────────────────┘  └────────────────────────────┘
```

**依赖方向规则：**

1. `ui` → `application` → `domain` / `calculations`，单向，不得反向。
2. `application` 可以调用 `infrastructure`；`infrastructure` **不得**调用 `application` 或 `ui`。
3. `domain` 与 `calculations` **不得**导入 `PySide6`、`shiboken6`、`sqlite3`、
   `pandas`、`numpy`、`openpyxl`、任何 PDF 解析库，
   也不得导入 `cenep.ui`、`cenep.infrastructure`、`cenep.application`。
4. 同层内的模块可以互相引用（例如 `domain.validation` 引用 `domain.models`）。
5. `data`（Excel / CSV 读写、模板生成、列映射、数据质量检查）**只依赖 `domain`**；
   `application` / `ui` 通过 `data` 处理表格，**不得**在界面或应用代码中直接操作 Excel。
   Excel 读写库（`openpyxl`）只允许出现在 `data` 与 `infrastructure` 层。
6. 依赖方向汇总（只能向右依赖）：`ui` → `application` → `data` / `domain` / `calculations`；
   `data` 只依赖 `domain`；`infrastructure` 不依赖 `application` / `ui`。

### 2.1 依赖规则的自动化强制

规则不靠口头约定，由 AST 静态分析测试强制执行：

| 规则 | 强制测试 |
|---|---|
| 领域层与计算层无越界第三方依赖 | `tests/unit/test_layering.py::TestLayerIsolation::test_domain_and_calculation_layers_have_no_forbidden_imports` |
| 领域层不依赖基础设施层 | `...::test_domain_layer_does_not_import_infrastructure` |
| 计算层不依赖界面层 | `...::test_calculations_do_not_import_ui` |
| 基础设施层不依赖界面层 | `...::test_infrastructure_does_not_import_ui` |
| PDF 解析库只允许出现在基础设施层 | `...::test_pdf_libraries_only_allowed_in_infrastructure` |
| Excel 读写库只允许出现在 `data` / `infrastructure` 层 | `...::test_excel_libraries_only_allowed_in_data_and_infrastructure` |
| `data` 层只依赖 `domain` | `...::test_data_layer_does_not_depend_on_upper_layers` |
| 模板结构规范不含 Excel 依赖 | `...::test_template_spec_is_free_of_excel_dependency` |
| 界面层不含消纳公式 | `...::TestUIContainsNoBusinessFormulas::test_self_consumption_rates_are_not_computed_in_ui` |
| 应用服务层不含公式 | `...::test_service_does_not_contain_formulas` |
| 界面层不执行 SQL | `...::test_ui_does_not_import_sqlite_or_run_sql` |
| 界面层通过应用服务访问业务 | `...::test_ui_uses_application_service` |
| 不存在空实现函数 | `...::TestNoFakeImplementations::test_no_functions_with_only_pass_body` |
| 不存在未实现占位 | `...::test_no_not_implemented_placeholders_in_core_paths` |
| 不允许单文件巨型化 | `...::TestProjectStructure::test_no_oversized_single_file` |

---

## 3. 模块职责

### 3.1 `cenep/__init__.py`

导出 `APP_NAME`、`__version__`、`STAGE`。不导入任何子模块，保证包导入零副作用。

### 3.2 `cenep/config.py`

环境与路径解析。优先级：显式参数 → 环境变量 → 默认值。

| 配置项 | 环境变量 | 默认值 |
|---|---|---|
| 数据库路径 | `CENEP_DB_PATH` | `%LOCALAPPDATA%\CENEP\cenep.db` |
| 日志级别 | `CENEP_LOG_LEVEL` | `INFO` |

关键决策：**默认数据库放在用户数据目录，不放在仓库目录内**，
从根本上避免真实项目数据被提交到 Git。示例配置见 `.env.example`。

### 3.3 `cenep/domain/`

| 文件 | 职责 |
|---|---|
| `models.py` | 11 个实体数据类、全部枚举、`new_id()` / `utc_now_iso()`、`ASSUMPTIONS_VERSION`、`CALCULATION_ENGINE_VERSION` |
| `validation.py` | 电量序列校验、项目字段校验、`ValidationIssue` / `ValidationResult`、校验问题代码常量 |
| `exceptions.py` | `CENEPError` 及子类：`ValidationError`、`EntityNotFoundError`、`EntityAlreadyExistsError`、`PersistenceError`、`UnsupportedOperationError` |

领域层是纯 Python，无 IO、无第三方依赖，可被任何上层复用。

### 3.4 `cenep/calculations/`

纯计算模块。当前只有一个文件 `self_consumption.py`，实现第一阶段唯一业务计算。

模块级常量：

| 常量 | 值 | 含义 |
|---|---|---|
| `CALCULATION_VERSION` | `"0.1.0"` | 计算规则版本 |
| `ENERGY_TOLERANCE_KWH` | `1e-9` | 守恒自检容差 |
| `STATUS_OK` | `"ok"` | 计算正常 |
| `STATUS_UNDEFINED_RATIO` | `"undefined_ratio"` | 电量已算出但至少一个比例未定义 |

对外接口：

```python
calculate_self_consumption(load, pv, *, interval_minutes=None) -> SelfConsumptionResult
calculate_self_consumption_with_issues(load, pv, *, interval_minutes=None) \
    -> tuple[SelfConsumptionResult | None, ValidationIssue | None, tuple[ValidationIssue, ...]]
```

计算规则详见 `docs/CALCULATION_SPEC.md`。

### 3.5 `cenep/application/project_service.py`

`ProjectService` 是界面层唯一允许接触的业务入口。

| 方法组 | 方法 |
|---|---|
| 生命周期 | `initialize()`、`ensure_initialized()` |
| 项目用例 | `create_project()`、`get_project()`、`find_project()`、`list_projects()`、`update_project()`、`delete_project()`、`count_projects()` |
| 校验用例 | `validate_project_input()`、`check_self_consumption_input()` |
| 计算用例 | `run_self_consumption()` |
| 元信息 | `stage_info()`（静态） |

构造参数：`ProjectService(database=None, *, auto_initialize=True)`。
不传 `database` 时按 `config.resolve_database_path()` 打开默认库。

### 3.6 `cenep/infrastructure/database.py`

| 名称 | 职责 |
|---|---|
| `SCHEMA_STATEMENTS` | 全部建表与建索引语句（幂等，`CREATE TABLE IF NOT EXISTS`） |
| `BUSINESS_TABLES` | 11 张业务表名，供测试核对 |
| `SCHEMA_VERSION` | 模式版本号，写入 `schema_meta` |
| `MIGRATIONS` | 模式迁移注册表 `{起始版本: (SQL, ...)}`，当前为空（`SCHEMA_VERSION = 1`） |
| `MISSING_VERSION` | 哨兵：`schema_meta` 表存在但缺 `schema_version` 记录（与 `None` 区分） |
| `Database` | 连接、事务、模式初始化、元数据状态与版本校验、迁移、表名与版本查询、`exists()`、`close()` |
| `ProjectRepository` | `project` 表的完整 CRUD |
| `translate_integrity_error()` | 把驱动层 `IntegrityError` 分类为领域异常 |

#### 数据库连接模式

| 模式 | 用法 | 数据存活范围 |
|---|---|---|
| 文件数据库 | `Database(r"D:\data\cenep.db")` | 磁盘文件，跨进程、跨实例持久 |
| 内存数据库 | `Database("file:x?mode=memory&cache=shared", uri=True)`，或别名 `Database(":memory:")` | 由 `Database` 实例持有的**锚定连接**维持；`close()` 后消失 |

内存库必须使用**共享缓存**：SQLite 的普通内存库按连接隔离，而
`Database.transaction()` 每次新建并在结束时关闭连接，因此普通内存库会出现
"初始化建表后表消失、下一个事务报 `no such table`"。
故内存模式下本类持有一个常驻锚定连接，并为每个 `Database` 实例生成唯一库名，
保证不同实例之间互不可见。

#### 模式版本与元数据保护

`initialize_schema()` 先读取数据库的**模式元数据状态**，再决定动作：

| 数据库状态 | 行为 |
|---|---|
| **`schema_meta` 表不存在**（真正的空库） | 建表并写入 `SCHEMA_VERSION` |
| 版本等于 `SCHEMA_VERSION` | 幂等执行 `CREATE ... IF NOT EXISTS`，不改变版本号 |
| 版本高于 `SCHEMA_VERSION` | 抛 `SchemaVersionError`，**保持原版本号不变**，拒绝读写 |
| 版本低于 `SCHEMA_VERSION` 且有迁移步骤 | 按版本阶梯执行迁移 SQL，每步之后更新版本号 |
| 版本低于 `SCHEMA_VERSION` 且无迁移步骤 | 抛 `SchemaVersionError`，拒绝自动升级 |
| **`schema_meta` 表存在但缺 `schema_version` 记录** | 抛 `SchemaVersionError`：**不写版本号、不补齐缺失表、不接纳未知结构** |

关键规则：**只有"元数据表不存在"才允许按新数据库初始化。**

"表不存在"与"表存在但缺版本记录"必须严格区分，两者都返回"没有版本"会导致
后者被当作空库，进而把当前版本号写入一个结构未知的库——这是静默的数据破坏。
因此 `Database._read_schema_state()` 返回 `(元数据表是否存在, 版本或哨兵)`，
由 `MISSING_VERSION` 哨兵表达"表在但版本缺失"，与 `None`（表不存在）区分。

对照场景：版本号**有效且等于当前版本**、但某张表被外部删掉时，
属于"缺表"而非"缺版本"，允许用 `CREATE ... IF NOT EXISTS` 幂等补齐。

设计目的：

1. 绝不静默降级由更新版本程序创建的数据库；
2. 绝不做"只改版本号而不迁移真实表结构"的假升级；
3. 绝不把元数据不完整的库当作新库接纳。

`Database.transaction()` 语义：

- 进入时 `BEGIN IMMEDIATE`；
- 正常退出 `COMMIT`；
- `sqlite3.Error` → 回滚并抛 `PersistenceError`；
- `sqlite3.IntegrityError` → 回滚并**放行原始异常**，由仓储层携带实体主键
  翻译为 `EntityAlreadyExistsError` / `ValidationError` / `PersistenceError`；
- 其他异常 → 回滚后原样上抛（业务异常不被吞掉）；
- 每次连接都执行 `PRAGMA foreign_keys = ON`，文件库额外启用 WAL。

### 3.6.1 `cenep/domain/pdf_extraction.py` 与 `cenep/infrastructure/pdf/`

第二阶段 P0-1 引入的 PDF 文本提取，刻意拆成两层：

| 模块 | 层 | 依赖 | 职责 |
|---|---|---|---|
| `domain/pdf_extraction.py` | 领域层 | **纯 Python**（无 pypdf/Qt/sqlite3） | `PdfExtractionStatus`、`PdfPage`、`PdfExtractionResult`、文本规范化 |
| `infrastructure/pdf/extractor.py` | 基础设施层 | `pypdf` | 打开 PDF、逐页提取、SHA-256、文本层判定、异常映射 |

**为什么这样拆**：解析库是"实现细节"，而"一页文本、一次提取的状态"是领域语言。
界面与业务只依赖领域模型，未来把 `pypdf` 换成 `pdfplumber` 不需要改动上层。

约束（由 `tests/unit/test_layering.py` 强制）：

- PDF 解析库**只允许**出现在 `infrastructure`；
  `domain`、`calculations`、`application`、`ui` 一律禁止导入。
- `domain/pdf_extraction.py` 不得导入 `pypdf`、`sqlite3`、`PySide6`。

状态语义（**四个状态必须互不混淆**）：

| 状态 | 场景 | 文本处理要求 | `text_layer_available` | `is_complete` |
|---|---|---|---|---|
| `success` | 全部页面提取成功且文本可用 | 保留全部页面文本 | `True` | `True` |
| `partial` | **部分页面提取失败，但其他页面有可用文本** | 保留成功页面文本 + 失败页错误信息 | `True` | `False` |
| `needs_ocr` | 整份文档没有获得可用文本 | 明确说明无法直接取得可用文本 | `False` | `False` |
| `failed` | 文件缺失/为空/非 PDF/损坏 | 不产生页面，只保留错误 | `False` | `False` |
| `duplicate` | 内容哈希与已登记文件相同 | 需数据库参与，**由应用服务层判定，提取器不产生** | — | — |

> **为什么必须区分 `partial` 与 `needs_ocr`**：二者曾共用 `needs_ocr`，导致
> 「部分页面读取失败（数据不完整但可用）」与「整份扫描件没有文本层（根本没有文本）」
> 无法区分。前者应进入人工复核或重新提取并保留已取到的文本，
> 后者需要完全不同的后续处理（OCR）。混为一谈会误导账单导入流程。

**两个维度必须分开看**：

- `text_layer_available` 表示「**文档里有没有可用文本**」，
  **不表示**「所有页面都提取成功」。`partial` 时它可以为 `True`。
- `is_complete`（等价于 `status == success`）表示「**提取结果是否完整**」。
  账单导入必须用它判断能否当作完整账单，**不得**用 `text_layer_available` 代替。

`needs_ocr` 的两种子情形由 `error_code` 区分：
`no_text_layer`（页面本身没有文本，疑似扫描件）与
`page_extraction_failed`（所有页面提取均失败）。

领域模型在类型层面拒绝自相矛盾的组合：`success` 带错误、
`partial` 无文本层、`partial` 无错误、`failed` 却含页面。

工程约定：不使用临时文件（因此无清理问题）；原始 PDF 只读；
失败通过结果对象表达，只有"参数非法"这类编程错误才抛 `PdfExtractionError`。

### 3.7 `cenep/ui/main_window.py`

| 类/函数 | 职责 |
|---|---|
| `MainWindow` | 主窗口：项目列表、新建/编辑/删除、消纳计算演示区、阶段状态区 |
| `ProjectDialog` | 项目创建/编辑对话框，只采集输入 |
| `_parse_series()` | 文本 → 数值序列；无法解析直接报错，不静默丢弃 |
| `_format_result()` | 结构化结果 → 可读文本；只展示，不做二次计算 |
| `NOT_IMPLEMENTED_FEATURES` | 未开放功能清单，界面必须显式展示 |

`cenep/ui/__init__.py` 提供 `is_qt_available()` 与 `main()`；
PySide6 在 `ui/main_window.py` 中直接导入，而 `ui/__init__.py` 不导入 Qt，
使包导入在无 Qt 环境下仍然成功。

### 3.8 `cenep/app.py`、`cenep/__main__.py`、`cenep/cli.py`

| 入口 | 命令 | 说明 |
|---|---|---|
| GUI | `python -m cenep`、`cenep-gui`、`python -m cenep.cli gui` | 三者共用 `cenep.app.main()` |
| CLI | `python -m cenep.cli <子命令>` | 无 GUI 也能验证计算与持久化 |

CLI 子命令：`init-db`、`project-add`、`project-list`、`project-show`、
`project-update`、`project-delete`、`self-consumption`、`gui`、`info`。
CLI 中的数值解析与应用服务调用与 GUI 完全一致，**不复制公式**。

---

## 4. 核心数据流

### 4.1 消纳计算流（界面路径）

```text
用户在输入框键入 "3, 8, 2" / "5, 4, 2"
        │
        ▼
ui.main_window._parse_series()      仅做文本→数值转换；非法 token 立即报错
        │
        ▼
ui.main_window.MainWindow.on_calculate_self_consumption()
        │  不含公式
        ▼
application.ProjectService.run_self_consumption(load, pv, interval_minutes)
        │  不含公式
        ▼
calculations.self_consumption.calculate_self_consumption()
        │
        ├─ domain.validation.require_valid_energy_series()  非法即抛 ValidationError
        │
        ├─ 逐时段 min / max 计算 + 汇总 + 比例指标（零分母 → None）
        │
        ├─ 内部 check_energy_balance() 自检守恒
        │
        ▼
SelfConsumptionResult（结构化数据）
        │
        ▼
ui.main_window._format_result()     纯展示，比例 → 百分比
```

### 4.2 项目落库流

```text
ProjectDialog 采集输入
        │
        ▼
ProjectService.create_project(...)   类型规范化（字符串 → 枚举）、去除名称首尾空白
        │
        ▼
ProjectRepository.add(project)
        │
        ├─ domain.validation.require_valid_project()  字段级校验
        │
        ▼
Database.transaction() → 参数化 INSERT
        │
        ├─ 主键重复 → EntityAlreadyExistsError
        ├─ CHECK / NOT NULL 违反 → ValidationError
        ├─ 外键违反 → PersistenceError
        ▼
COMMIT → MainWindow.refresh_projects() 重新自数据库加载（不用内存缓存）
```

### 4.3 结果追溯链

任何计算结果必须能够回答"用了什么输入、按哪一版规则算的"：

```text
CalculationRun.calculation_version  ← CALCULATION_VERSION（如 "0.1.0"）
CalculationRun.input_snapshot       ← 输入摘要（JSON）
SelfConsumptionResult.input_fingerprint ← 输入序列的 SHA-256 指纹（前 16 位）
PVModel.assumptions_version         ← ASSUMPTIONS_VERSION（如 "2026.02-stage1"）
TariffModel.source_reference/effective_from ← 电价来源与生效日期
```

---

## 5. 错误处理策略

### 5.1 异常层次

```text
CENEPError
├── ValidationError              用户数据不合法（携带 issues 结构化清单）
├── EntityNotFoundError          按主键查询不到
├── EntityAlreadyExistsError     主键重复
├── PersistenceError             连接/事务/SQL 失败、外键 RESTRICT 拒绝
│   └── SchemaVersionError       数据库模式版本与本程序不兼容（拒绝静默降级）
└── UnsupportedOperationError    调用了尚未实现的能力
```

### 5.2 各层职责

| 层 | 责任 |
|---|---|
| 领域层 | 用 `ValidationIssue` 表达"哪里不对、为什么不对"；不负责呈现 |
| 计算层 | 非法输入抛 `ValidationError`，**绝不静默修正数据** |
| 基础设施层 | 把 `sqlite3.*` 异常包装为 `PersistenceError` 或分类为更精确的领域异常，保留 `__cause__` |
| 应用服务层 | 事务边界；把业务结果与追溯信息组装返回 |
| 表现层 | 捕获 `CENEPError`，展示 `format_issues()` 的逐条说明，不崩溃 |

### 5.3 三条硬规则

1. **未定义 ≠ 0。** 零分母的比例指标一律用 `None` / `NULL` 表达。
2. **非法输入 ≠ 被修正的输入。** 不截断、不补齐、不取绝对值、不丢弃行。
3. **未实现 ≠ 已完成。** 未实现的能力抛 `UnsupportedOperationError`
   或在界面显式标注"尚未开放"，禁止返回占位成功结果。

---

## 6. 数据隔离

| 隔离维度 | 机制 |
|---|---|
| 项目之间 | 所有业务表均带 `project_id`；查询一律按 `project_id` 过滤 |
| 测试与真实数据 | `tests/conftest.py` 的自动夹具把 `CENEP_DB_PATH` 重定向到临时目录；测试全部使用 `tmp_path` |
| 数据库与仓库 | 默认库位于 `%LOCALAPPDATA%\CENEP\`；`.gitignore` 排除 `*.db`、`*.sqlite*` 与 `data/` 下的账单文件 |
| 学校/客户敏感信息 | 账单原始文件、导出目录均被 `.gitignore` 排除 |

---

## 7. 扩展方式

### 7.1 新增一个计算（例如分时电价收益）

1. 在 `cenep/calculations/` 新建模块，写纯函数 + 结构化结果 `dataclass`。
2. 结果对象提供 `to_dict()` 与 `to_metric_rows()`，字段名与 `MetricName` 对齐。
3. 定义该模块的 `CALCULATION_VERSION`。
4. 在 `cenep/application/` 增加用例方法，由它调用计算模块。
5. 在 `cenep/ui/` 只增加输入采集与结果展示。
6. 在 `docs/CALCULATION_SPEC.md` 补充公式、单位、边界与零分母规则。
7. 在 `tests/unit/` 增加单元测试（含边界与守恒）。

### 7.2 新增一个数据实体

按 `docs/DATA_MODEL.md` 第 7 节的顺序执行：模型 → 建表语句 → 提升 `SCHEMA_VERSION`
→ 迁移方案 → 文档 → 集成测试。

### 7.3 引入新依赖

只有当前阶段真正需要才引入。引入前必须确认：

1. 该库不会出现在 `domain` / `calculations` 的导入列表中；
2. 许可证与项目兼容；
3. Windows 上可通过 pip 安装；
4. `pyproject.toml` 的 `dependencies` 或 `[project.optional-dependencies].dev` 中登记。

### 7.4 拆分为服务或批处理

由于 `application` 层已与 `ui` 解耦、`domain` / `calculations` 已与 IO 解耦，
后续可以把 `application` 暴露为 HTTP/RPC 接口或批处理入口，
无需改动领域与计算代码。这是当前分层设计的主要收益。

---

## 8. 架构层面的已知限制

1. **迁移框架只有骨架。** 迁移注册表 `MIGRATIONS` 与阶梯执行逻辑已实现并有测试覆盖
   （含真实 `ALTER TABLE` 与"缺步骤即停止"场景），但当前 `SCHEMA_VERSION = 1`
   没有历史版本，注册表为空。提升版本号时必须登记真实结构变更。
2. **单用户单库。** 无并发写保护策略，仅依赖 SQLite 的事务与 WAL；
   内存库由单实例持有锚定连接，未验证多线程并发访问。
3. **内存库不能跨实例共享。** 内存库唯一名由 `Database` 实例生成，
   实例销毁或 `close()` 后数据即消失；需要持久化请使用文件数据库。
4. **仓储覆盖不全。** 仅 `Project` 有仓储；其余实体的读写将在后续阶段按需实现。
5. **无日志与可观测性配置。** `config.log_level()` 已提供读取入口，但尚未接入日志系统。
6. **无依赖注入容器。** 依赖通过构造函数传入，界面层在装配处创建服务，
   在当前规模下够用；若对象图继续增长，需要引入显式容器。
