# CENEP —— 中国工商业分布式光伏项目经济评价软件

- 软件版本：**0.1.0**
- 当前阶段：**第一阶段：工程骨架与核心规则冻结**
- 仓库：https://github.com/win8-cmd/pv
- 开发分支：`main`
- 当前状态：第一阶段已完成，**正在 PR #1 审阅中，尚未合并到 `main`**
  （审阅分支 `fix/stage1-review-memory-db-and-schema-version`；PR:
  https://github.com/win8-cmd/pv/pull/1 ）

---

## 1. 软件定位与适用范围

CENEP 是一款面向**中国工商业分布式光伏项目**的经济评价桌面软件，
目标是帮助项目开发人员、工商业业主能源管理人员、咨询与设计院技术人员
把电费账单、负荷数据、装机方案与电价方案整理成口径正确、可追溯的经济指标，
用于项目可行性判断与方案对比。

**适用范围：**

- 工商业屋顶分布式光伏项目（自发自用、余电上网）。
- 以电费账单与计量数据为基础的电量与电价分析。
- 多方案（不同装机容量、不同电价方案）的经济性对比。

**不适用范围（本软件不做，也不打算做）：**

- 电气设计与施工图输出（属设计软件职责）。
- 实时运行监控与远程运维（属监控平台职责）。
- 电网调度与电力市场报价执行。
- 财务记账与税务申报。
- 代替使用者判定"项目是否可行"——软件只给出**口径正确、可追溯**的指标。

---

## 2. 当前版本已实现的功能

以下功能**已实现且有自动化测试覆盖**（302 个用例全部通过）：

| 功能 | 说明 |
|---|---|
| 项目基础信息完整 CRUD | 新增、查询、修改、删除，数据**真实写入 SQLite**，可用新连接读回 |
| 安全删除策略 | 项目存在关联数据（文档、账单、负荷、方案、报告）时，删除被数据库 `RESTRICT` 拒绝，避免误删客户原始台账 |
| 光伏消纳计算 | 逐时段计算自用电量、余电上网电量、电网购电量，以及自用率、负荷覆盖率、余电比例三个指标 |
| 零分母语义 | 比例指标在分母为零时返回"未定义"（`None`），**不返回 0**，避免把"未定义"误读为"真实为零" |
| 能量守恒自检 | 计算完成后自动校验 `总光伏 = 自用 + 上网`、`总负荷 = 自用 + 购电`，容差 `1e-9` kWh |
| 输入校验与错误定位 | 长度不一致、负数、`NaN`、无穷、非数值、非法时间粒度均抛出结构化问题清单，**不静默修正用户数据** |
| 数据质量提示 | 空数组、全零、无光伏、无负荷四类业务提示（不影响数值） |
| 结果可追溯 | 结果携带计算规则版本、输入指纹（SHA-256 前 16 位）、时间粒度、时段数 |
| 11 个实体的数据契约 | 全部业务表结构一次性冻结（含字段类型、可空性、`CHECK` 约束、外键、索引） |
| SQLite 基础能力 | 建库建表（幂等）、事务与回滚、参数化 SQL、外键约束、重复主键与约束异常的明确分类 |
| 最小桌面界面 | PySide6 主窗口：项目列表与增删改、消纳计算输入与结果展示、当前阶段状态、未开放功能声明 |
| 命令行入口 | `python -m cenep.cli`，无图形界面时也能验证核心计算与持久化 |
| 分层架构守卫 | 自动化测试强制：领域/计算层不依赖 PySide6、SQLite、pandas、PDF 库；界面层不含业务公式；核心路径无空实现 |

### 2.1 标准验算案例

输入 `load = [3, 8, 2]`、`pv = [5, 4, 2]`（单位 kWh，逐时段）：

| 指标 | 结果 |
|---|---:|
| 总用电量 | 13 kWh |
| 总光伏发电量 | 11 kWh |
| 自用电量 | 9 kWh |
| 余电上网电量 | 2 kWh |
| 电网购电量 | 4 kWh |
| 自用率 | 9 / 11 ≈ 0.818182 |
| 负荷覆盖率 | 9 / 13 ≈ 0.692308 |
| 余电比例 | 2 / 11 ≈ 0.181818 |
| 状态 | `ok` |

---

## 3. 当前版本**未实现**的功能

以下能力在**当前版本中不存在**，界面已显式标注"尚未开放"：

- 电费账单 PDF / 图片 / Excel 导入与解析（第二阶段）。
- OCR 与复杂版式识别。
- 全国电价政策自动获取（本项目**不包含任何已核实的电价数据**）。
- 负荷曲线导入与来源精度管理。
- 分时电价模型与光伏自用收益测算。
- 光伏发电量模拟（`pvlib` **尚未引入**）。
- 完整财务现金流、税务模型、净现值、内部收益率、投资回收期。
- 屋面识别、自动排板与三维展示。
- 储能充放电优化。
- 电力市场交易优化。
- 用户权限系统与云端多用户协同。
- Excel / PDF 报告导出。
- 安装包制作与正式发布。

数据表结构已为其中部分能力预留字段，但**没有对应实现**，
不存在用占位返回值冒充已完成功能的情况。

---

## 4. 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11（开发与验收环境为 Windows 11 专业版 10.0.22621） |
| Python | **≥ 3.11**（实际开发与测试使用 Python 3.14.7） |
| 依赖管理 | pip（标准库 `venv` 创建虚拟环境） |
| 磁盘 | 依赖完整安装约需 400 MB（PySide6 占主要部分） |
| 网络 | 仅在安装依赖时需要；软件运行与测试不需要联网 |

> **Windows 重要提示：** 直接在终端输入 `python` 可能命中 Microsoft Store 的
> 应用商店存根程序（`...\WindowsApps\python.exe`），它不会运行解释器。
> 请先确认真实的 Python：
>
> ```powershell
> py -0p                # 列出本机已安装的 Python 版本与路径
> py -3.14 --version    # 用 py 启动器指定版本（按实际版本号替换）
> ```
>
> 若 `py` 不可用，请安装 Python 3.11+ 并勾选"Add python.exe to PATH"。

---

## 5. Windows 环境安装方法

在 **PowerShell** 中执行（在仓库根目录，即本 `README.md` 所在目录）：

```powershell
# 1) 进入仓库目录（按实际路径替换）
cd D:\CENEP

# 2) 创建虚拟环境
py -3.14 -m venv .venv

# 3) 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 4) 升级 pip
python -m pip install --upgrade pip

# 5) 以可编辑方式安装本项目及开发依赖
python -m pip install -e ".[dev]"
```

若第 3 步报"禁止运行脚本"，可改用当前会话临时放行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

若不激活虚拟环境，也可以在后续所有命令中直接使用虚拟环境解释器，
两种写法等价：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m cenep
```

### 5.1 运行依赖

| 依赖 | 版本 | 当前用途 |
|---|---|---|
| `PySide6` | ≥ 6.6 | 桌面界面 |
| `pandas` | ≥ 2.0 | 为第二阶段的账单与负荷数据处理准备 |
| `openpyxl` | ≥ 3.1 | 为后续 Excel 报表导出准备 |

### 5.2 开发依赖

| 依赖 | 版本 | 用途 |
|---|---|---|
| `pytest` | ≥ 7.4 | 单元与集成测试 |
| `pytest-cov` | ≥ 4.1 | 覆盖率统计（可选） |

开发依赖通过 `python -m pip install -e ".[dev]"` 一次装好。

---

## 6. 启动应用的方法

### 6.1 启动桌面界面

任选一种方式（三者等价，均进入同一个主窗口）：

```powershell
# 方式一：以模块方式启动
.\.venv\Scripts\python.exe -m cenep

# 方式二：使用安装时生成的 GUI 脚本
.\.venv\Scripts\cenep-gui.exe

# 方式三：通过命令行入口启动
.\.venv\Scripts\python.exe -m cenep.cli gui
```

主窗口提供：

- 软件名称与版本号；
- "项目基础信息"区域：项目列表 + 新建 / 编辑 / 删除 / 刷新；
- "光伏消纳计算"区域：输入各时段用电量与发电量，查看结构化结果；
- "当前阶段状态与未开放功能"区域：说明已实现能力与尚未开放的功能。

界面创建的项目会**真实写入**本地 SQLite 数据库；
下次启动界面时会从数据库重新加载，而不是依赖内存缓存。

### 6.2 不启动界面时验证核心计算（推荐用于快速自检）

```powershell
# 标准验收案例
.\.venv\Scripts\python.exe -m cenep.cli self-consumption --load 3,8,2 --pv 5,4,2 --interval 60

# 以 JSON 输出结构化结果
.\.venv\Scripts\python.exe -m cenep.cli self-consumption --load 3,8,2 --pv 5,4,2 --json

# 空数组（合法输入：电量为 0，比例未定义）
# 注意：PowerShell 会把裸 "" 当作空参数丢弃，必须写成 --load='' 形式
.\.venv\Scripts\python.exe -m cenep.cli self-consumption --load='' --pv='' --json

# 非法输入（长度不一致）：以非零退出码结束并给出问题清单
.\.venv\Scripts\python.exe -m cenep.cli self-consumption --load 3,8,2 --pv 5,4
# 输出：校验失败，未执行计算：load/pv(length_mismatch) ... 退出码 3
```

### 6.3 命令行项目管理

```powershell
.\.venv\Scripts\python.exe -m cenep.cli init-db
.\.venv\Scripts\python.exe -m cenep.cli project-add --name "示例项目" --location "湖北省武汉市"
.\.venv\Scripts\python.exe -m cenep.cli project-list
.\.venv\Scripts\python.exe -m cenep.cli project-show <project_id>
.\.venv\Scripts\python.exe -m cenep.cli project-update <project_id> --name "新名称"
.\.venv\Scripts\python.exe -m cenep.cli project-delete <project_id>
.\.venv\Scripts\python.exe -m cenep.cli info
```

用 `--db <路径>` 可指定数据库文件，例如把演示数据放到临时目录：

```powershell
.\.venv\Scripts\python.exe -m cenep.cli --db D:\temp\demo.db project-list
```

---

## 7. 运行测试的方法

```powershell
# 全量测试（推荐，提交前必须执行）
.\.venv\Scripts\python.exe -m pytest -q

# 分层次运行
.\.venv\Scripts\python.exe -m pytest -q tests\unit
.\.venv\Scripts\python.exe -m pytest -q tests\integration

# 只运行界面测试
.\.venv\Scripts\python.exe -m pytest -q -m gui

# 带覆盖率
.\.venv\Scripts\python.exe -m pytest --cov=cenep --cov-report=term-missing
```

**预期结果：** `302 passed`（0 失败、0 错误、0 跳过）。

用例分布：单元与界面测试 206 个（校验 52、消纳计算 42、架构约束 18、包与命令行 21、界面 17、PDF 提取 56），
集成测试 96 个（SQLite 建表、CRUD、事务、约束与异常分类 51；内存库、模式版本保护与元数据完整性 45）。

界面测试使用 Qt 的 `offscreen` 平台，在无显示器的环境中也能真实创建窗口：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q -m gui
```

测试安全约定：所有测试使用临时数据库，`tests/conftest.py` 会自动把
`CENEP_DB_PATH` 重定向到临时目录，**任何自动化测试都不会触碰你的真实项目数据库**。

---

## 8. 项目目录结构

```text
pv/  (仓库根目录)
├── README.md                     本文件
├── pyproject.toml                项目元数据、依赖、pytest 配置
├── .gitignore                    排除虚拟环境、缓存、数据库、账单、密钥
├── .env.example                  环境配置示例（复制为 .env 后使用）
├── docs/                         项目文档
│   ├── PRD.md                    产品需求文档
│   ├── ARCHITECTURE.md           系统架构说明
│   ├── DATA_MODEL.md             数据模型说明（字段、约束、索引）
│   ├── CALCULATION_SPEC.md       计算规则说明（公式与边界）
│   ├── ROADMAP.md                开发路线图
│   ├── TEST_PLAN.md              测试计划
│   ├── ACCEPTANCE_CRITERIA.md    第一阶段验收标准
│   └── AI_DEVELOPMENT_GUIDE.md   后续开发（含 AI 开发）操作手册
├── src/cenep/                    源码包
│   ├── __init__.py               软件名、版本、阶段常量
│   ├── __main__.py               python -m cenep 入口
│   ├── app.py                    GUI 应用装配与启动
│   ├── cli.py                    命令行入口（无界面验证路径）
│   ├── config.py                 路径与环境配置
│   ├── domain/                   领域层：模型、校验、异常（禁止 IO 与 GUI）
│   │   ├── models.py
│   │   ├── validation.py
│   │   └── exceptions.py
│   ├── calculations/             计算层：纯计算（禁止 IO 与 GUI）
│   │   └── self_consumption.py
│   ├── application/              应用服务层：用例编排
│   │   └── project_service.py
│   ├── infrastructure/           基础设施层：SQLite 等
│   │   └── database.py
│   └── ui/                       表现层：PySide6 界面
│       └── main_window.py
└── tests/                        测试
    ├── conftest.py               夹具与数据库隔离
    ├── unit/                     单元测试
    │   ├── test_validation.py
    │   ├── test_self_consumption.py
    │   ├── test_layering.py
    │   ├── test_package_import.py
    │   └── test_gui_main_window.py
    └── integration/              集成测试
        ├── test_database.py
        └── test_database_memory_and_schema_version.py
```

顶层另含 `.github/workflows/tests.yml`：推送到 `main` 或提交 Pull Request 时自动运行测试。

### 8.1 分层依赖方向

```text
表现层 cenep.ui
    ↓  （只允许向下调用）
应用服务层 cenep.application  ──→  基础设施层 cenep.infrastructure
    ↓
领域层 cenep.domain / 计算层 cenep.calculations
```

规则：领域层与计算层**不得**导入 PySide6、sqlite3、pandas、PDF 解析库，
也不得导入界面层或基础设施层。该规则由 `tests/unit/test_layering.py` 自动检查。

### 8.2 数据存放位置

| 数据 | 位置 | 是否提交到 Git |
|---|---|---|
| 默认项目数据库 | `%LOCALAPPDATA%\CENEP\cenep.db` | 否（仓库外） |
| 自定义数据库 | 由 `CENEP_DB_PATH` 或 `--db` 指定 | 否（`.gitignore` 排除 `*.db`） |
| 电费账单原始文件 | 建议放在 `data/bills/` | 否（`.gitignore` 排除） |
| 报告导出 | 建议放在 `data/exports/` | 否（`.gitignore` 排除） |

---

## 9. 后续开发路线

| 阶段 | 目标 | 状态 |
|---|---|---|
| 第一阶段 | 工程骨架、数据契约、核心消纳计算、基础持久化与测试 | **已完成** |
| 第二阶段 | 电费账单导入与关键字段提取（含校验与人工复核流程） | 未开始 |
| 第三阶段 | 负荷曲线与来源精度管理、分时电价模型、自用收益测算 | 未开始 |
| 第四阶段 | 光伏发电量模拟（引入 `pvlib`）与装机方案管理 | 未开始 |
| 第五阶段 | 完整财务模型：初始投资、运维费用、现金流、NPV、IRR、回收期 | 未开始 |
| 第六阶段 | 多方案对比与 Excel / PDF 报告输出 | 未开始 |
| 第七阶段及以后 | 屋面识别与三维展示、储能优化、电力交易、多用户协同 | 未开始 |

每个阶段的目标、前置条件、交付物与验收门槛见 [docs/ROADMAP.md](docs/ROADMAP.md)。

**本仓库当前状态：第一阶段完成，第二阶段尚未开始。**

---

## 10. 已知问题与技术限制

1. **迁移框架仅具骨架。** 迁移注册表 `MIGRATIONS` 与阶梯执行逻辑已实现并通过测试
   （含真实 `ALTER TABLE` 场景），但当前 `SCHEMA_VERSION = 1` 没有历史版本，
   注册表为空。提升模式版本时必须在该表中登记真实的表结构变更，
   **禁止只改版本号**。
2. **仅 `project` 表具备完整 CRUD。** 其余 10 张业务表只冻结了结构，
   尚无仓储与用例实现。
3. **内存数据库为共享缓存实现，不支持跨实例共享。** `Database(":memory:")`
   等价于 `file:<唯一名>?mode=memory&cache=shared`，由实例持有锚定连接维持其存活；
   实例 `close()` 后数据消失。需要持久数据请使用文件数据库。
4. **第一阶段不引入 `pvlib`。** 发电量需由外部提供，光伏方案表中
   `annual_generation_kwh` 为可空字段。
5. **无任何已核实的电价数据。** 电价方案表仅定义结构；
   未经正式来源核实的数据不得标记为已核实。
6. **单用户单库，无并发写保护策略。** 未做多进程并发写压力测试，
   内存库的多线程并发访问亦未验证。
7. **界面功能刻意保持最小。** 不追求美观，无菜单栏、无快捷键、
   无项目搜索与分页；界面自动化验证在 Qt `offscreen` 平台完成，
   未在物理显示器上人工确认布局观感。
8. **未提供打包与安装程序。** 仅支持源码方式安装（`pip install -e`）。
9. **Windows 上直接调用 `python` 可能命中 Microsoft Store 存根程序。**
   请使用 `.\.venv\Scripts\python.exe` 或 `py` 启动器。

> **CI 状态：** `.github/workflows/tests.yml` 已在 GitHub Actions 上实际运行通过，
> Python 3.14 与 3.11 两个作业均为 `302 passed`，无跳过用例。详见
> [docs/ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md) 第 5.2 节。

## 11. 文档索引

| 文档 | 内容 |
|---|---|
| [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md) | **完成结论日志**：每轮完成后追加的结论记录（最新在最上面） |
| [docs/PRD.md](docs/PRD.md) | 产品目标、用户角色、使用流程、功能边界与优先级 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层设计、模块职责、依赖方向、数据流、错误处理、扩展方式 |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | 实体、字段、类型、主键、外键、单位、约束与索引 |
| [docs/CALCULATION_SPEC.md](docs/CALCULATION_SPEC.md) | 消纳计算公式、输入条件、输出字段、边界情况与口径边界 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 各阶段目标、前置条件、交付物与验收门槛 |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | 单元、集成、边界、界面与回归测试方案 |
| [docs/ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md) | 第一阶段逐项验收标准与未验证事项 |
| [docs/AI_DEVELOPMENT_GUIDE.md](docs/AI_DEVELOPMENT_GUIDE.md) | 后续开发者的改码、加模块、改模型、写测试与提交规范 |

> **工作约定：** 每一轮开发或复核完成后，必须在
> [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md) 追加一条结论记录并同步到 GitHub，
> 内容包括实际的测试数字、CI 结果、Git 状态与未验证事项。
> 具体维护步骤见该文件第 3 节。

---

## 12. 许可与数据合规提醒

- 本项目当前未声明开源许可证，默认保留全部权利。
- 电费账单、负荷数据与客户信息属于**商业敏感数据**：
  不得提交到 Git 仓库，不得放入任何公开渠道。
  `.gitignore` 已排除常见账单与数据库文件，但这不能替代使用者的自查。
- 本项目**不附带**任何电价政策数据；使用者需自行依据当地正式发布的
  电价文件录入，并在 `source_reference` 字段中记录来源。
