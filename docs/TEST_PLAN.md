# CENEP 测试计划（TEST PLAN）

- 文档版本：`2026.10-phase2-p0-1`
- 软件版本：`0.1.0`
- 对应测试目录：`tests/`
- 当前基线：**321 个用例，全部通过**（实测结果见 `docs/ACCEPTANCE_CRITERIA.md`）
- 最近一次实测：2026-10-11，Python 3.14.7，Windows 11，`321 passed`

按文件分布（实测 `pytest --collect-only -q` 输出）：

| 测试文件 | 用例数 | 层次 |
|---|---:|---|
| `tests/integration/test_database.py` | 51 | 集成 |
| `tests/integration/test_database_memory_and_schema_version.py` | 45 | 集成（内存库与模式版本保护） |
| `tests/unit/test_gui_main_window.py` | 17 | 界面（标记 gui） |
| `tests/unit/test_layering.py` | 18 | 单元（架构约束） |
| `tests/unit/test_package_import.py` | 21 | 单元 / 应用验证 |
| `tests/unit/test_pdf_extraction.py` | 75 | 单元（P0-1 PDF 提取与状态语义） |
| `tests/unit/test_self_consumption.py` | 42 | 单元 |
| `tests/unit/test_validation.py` | 52 | 单元 |
| **合计** | **321** | |

小计：单元与界面测试 225 个，集成测试 96 个。

> 用例数量随缺陷修复与功能增加而变化。判断质量的标准是
> **`0 failed`、`0 error`、`0 skipped`**，而不是数量本身。
> 每次修改后必须重新运行并同步本表。

---

## 1. 测试目标

第一阶段测试要证明的不是"代码写完了"，而是下面四件事：

1. **核心消纳公式正确**——标准案例逐项数值正确，边界情况行为明确。
2. **非法输入被拒绝而不是被修正**——原始数据在任何失败路径下都不被改写。
3. **数据真的落盘并可重新读取**——不是内存假象、不是界面自报成功。
4. **架构规则被真实遵守**——分层依赖、界面无公式、无空实现，由自动化检查保证。

---

## 2. 测试层次与分工

| 层次 | 目录 | 关注点 | 允许依赖 |
|---|---|---|---|
| 单元测试 | `tests/unit/` | 领域规则、计算公式、校验、架构约束 | 纯 Python，不使用真实数据库文件 |
| 集成测试 | `tests/integration/` | SQLite 建表、CRUD、事务、约束、异常分类 | 使用 `tmp_path` 临时数据库文件 |
| 界面测试 | `tests/unit/test_gui_main_window.py` | 窗口可创建、界面操作真实落库、结果来自计算模块 | Qt `offscreen` 平台，临时数据库 |

---

## 3. 测试夹具与数据隔离

`tests/conftest.py` 提供：

| 夹具 | 作用域 | 说明 |
|---|---|---|
| `_isolate_default_database` | function（`autouse=True`） | 把 `CENEP_DB_PATH` 重定向到 `tmp_path_factory` 下的临时文件。**即使被测代码走默认路径分支，也不会触碰用户真实数据库** |
| `db_path` | function | 临时 `.db` 文件路径 |
| `database` | function | 已建表的临时文件数据库 |
| `memory_database` | function | 已建表的内存数据库 |
| `repository` | function | 绑定临时库的 `ProjectRepository` |
| `project_service` | function | 绑定临时库的 `ProjectService` |
| `sample_project` | function | 标准示例项目 |

同时 `conftest.py` 把 `src/` 插入 `sys.path`，使未执行 `pip install -e .` 时也可运行测试。

**强制规则：测试代码不得出现指向 `%LOCALAPPDATA%\CENEP\cenep.db` 的路径。**
该规则由 `tests/integration/test_database.py::TestRealDatabaseSafety` 显式断言。

---

## 4. 单元测试明细

### 4.1 `tests/unit/test_validation.py`（52 个用例）

| 测试类 | 覆盖内容 |
|---|---|
| `TestEnergySeriesValidation` | 合法序列；空数组合法；全零合法；长度不一致（3 组参数）；非数值元素（6 组参数：`None`/字符串/对象/列表/字典/`bool`）；`NaN`；`inf`/`-inf`；负荷负数；光伏负数；非序列（4 组参数）；非法时间粒度（5 组参数）；合法时间粒度；多问题全部上报不截断；问题默认严重度为 ERROR；问题可序列化 |
| `TestRequireValidEnergySeries` | 合法返回结果；非法抛 `ValidationError` 且携带问题代码；异常携带全部问题；**校验不修改输入数据** |
| `TestClassifyEnergySeries` | 空数组提示；全零提示；无光伏提示；无负荷提示；正常场景无提示 |
| `TestProjectValidation` | 合法项目；空白名称；空名称；超长名称；边界长度 200 通过；非法项目类型；非法主键；非法时间戳；`require_valid_project` 抛错；全部 3 种项目类型合法 |

### 4.2 `tests/unit/test_self_consumption.py`（42 个用例）

| 测试类 | 覆盖内容 |
|---|---|
| 标准案例 | `test_acceptance_case_all_metrics`：逐项断言 13/11/9/2/4 kWh 与 9/11、9/13、2/11；`test_acceptance_case_period_values`：逐时段复核 |
| 守恒关系 | `test_energy_conservation_relations` + 9 组参数的 `test_conservation_holds_for_many_inputs`（含 1e-6 与 1e6 量级） |
| `TestBoundaryCases` | 空数组；全零；只有负荷；只有光伏；光伏等于负荷；光伏恒小于负荷；光伏恒大于负荷；单时段；部分时段零负荷 |
| `TestInvalidInputRaises` | 长度不一致；负数；`NaN`；`inf`/`-inf`；非数值；非法粒度；**非法输入不被静默修正** |
| `TestResultStructure` | 返回结构化 dataclass；`to_dict()` 含全部必需字段；未定义比例在字典中保持 `None`；比例为 0~1 比值；负荷覆盖率不超过 1；`to_metric_rows()` 标记 `undefined`；正常比例标记 `ok` 且共 8 行；输入指纹稳定且对输入敏感；守恒自检能发现人为构造的违例 |
| `TestNonRaisingEntryPoint` | 成功路径；失败路径返回问题而不返回结果；仅有警告时仍返回结果 |

### 4.3 `tests/unit/test_layering.py`（18 个用例）

| 测试类 | 覆盖内容 |
|---|---|
| `TestLayerIsolation` | 领域层与计算层无越界第三方依赖（参数化 2 组）；领域层不依赖基础设施层；计算层不依赖界面层；基础设施层不依赖界面层；PDF 解析库只允许出现在基础设施层 |
| `TestUIContainsNoBusinessFormulas` | 界面层无 `min(`/`max(` 消纳公式；界面层不导入 `sqlite3` 且疑似无 SQL；界面层使用应用服务；应用服务层无公式 |
| `TestProjectStructure` | 17 个必需模块文件存在；单文件不超过 1200 行；5 个分层目录都有实现文件 |
| `TestNoFakeImplementations` | 核心路径无 `NotImplementedError` 占位；无"只有 `pass` 的函数体"；界面层无硬编码"保存成功"文案且保留 `QMessageBox.critical` |

### 4.4 `tests/unit/test_package_import.py`（21 个用例）

| 测试类 | 覆盖内容 |
|---|---|
| `TestPackageMetadata` | 包可导入；`pyproject.toml` 元数据与包版本一致；`pip install -e .` 后 `importlib.metadata` 版本一致（未安装则 skip）；所有子模块可导入；`py.typed` 存在 |
| `TestCoreModulesRunWithoutGui` | 计算不依赖数据库；经应用服务得到验收数值；`stage_info()` 版本信息；`describe_environment()` 不启动 GUI；`is_qt_available()` 返回布尔 |
| `TestCommandLineInterface` | 人类可读输出；JSON 输出；非法输入返回非零退出码；空数组被接受；项目全生命周期（初始化→新增→列表→查看→更新→删除→空列表）；不存在的项目返回错误；空白名称被拒绝；`info` 命令；**真实子进程端到端验证** |
| `TestPersistenceRoundTrip` | 新服务实例重新读取同一文件；多项目互不干扰 |

### 4.5 `tests/unit/test_gui_main_window.py`（17 个用例，标记 `gui`）

使用 `QT_QPA_PLATFORM=offscreen`，**真实创建 `QApplication` 与 `MainWindow`**。

| 测试类 | 覆盖内容 |
|---|---|
| `TestWindowConstruction` | 标题含软件名与版本；副标题含当前阶段；`show()` 后真实可见；项目表 5 列且初始为空；界面含"CENEP"与"光伏消纳"；未开放功能被显式展示；已实现能力被说明 |
| `TestProjectCreationFromGui` | 对话框取值与类型枚举还原；**界面创建的项目真实落库**（用全新连接验证）；表格行携带项目主键 |
| `TestCalculationFromGui` | 界面计算结果含 9/2/4/13/11 kWh 与 0.818182、0.692308、0.181818；空输入的"未定义"提示；`_parse_series` 拒绝非法 token；接受中文逗号与顿号；**负数原样传递不修正** |
| `TestInvalidInputHandling` | 长度不一致时给出明确提示且界面不崩溃；非法时间粒度被拒绝且不产生计算结果 |

### 4.6 `tests/unit/test_pdf_extraction.py`（75 个用例）

对应第二阶段 P0-1。测试样本全部由 `tests/unit/pdf_fixtures.py` 在运行时生成，
仓库内不保存任何 PDF 二进制，也不使用真实客户账单。

| 测试类 | 覆盖内容 |
|---|---|
| `TestSinglePagePdf` | 单页成功；文本提取；文件元数据（哈希/大小/名称）；文件名不泄露目录 |
| `TestMultipagePdf` | 多页页数与顺序；**多页文本不合并、不串页**；中文多页 |
| `TestChineseText` | 中文字符完整提取；中文标点与数字；字符数一致 |
| `TestEmptyFile` | 空文件报失败而非成功；空文件哈希仍计算 |
| `TestCorruptPdf` | 截断 PDF；仅含文件头；损坏不抛异常；**损坏与无文本层状态不同** |
| `TestNotAPdf` | 文本文件冒充 PDF；二进制非 PDF；目录；文件不存在 |
| `TestNoTextLayer` | 空白 PDF 判为 `needs_ocr` 而非成功；空白页仍如实反映页数；纯空白不算文本层；领域模型阻止"非成功却声称有文本层" |
| `TestFileHash` | 与 hashlib 一致；跨调用与跨路径稳定；内容变化则变化；**同一内容不同文件名同哈希**；缺失文件抛错 |
| `TestPageNumberMapping` | 页码从 1 连续；每页映射自身文本；越界抛错；领域模型拒绝页码不一致与页数不匹配 |
| `TestExplicitFailureStates` | 每种失败都有错误码与信息；失败不声称有页；`None` 路径抛编程错误；摘要不含完整文本 |
| `TestNoLeftoverFiles` | 提取不产生额外文件；无 `.tmp/.part` 残留 |
| `TestSourceFileUntouched` | 内容与 mtime 不变；重复提取结果稳定 |
| `TestNormalizePageText` | `None`→空串；换行统一；仅去行尾空白；**内部内容（数字换行截断、汉字插空格）原样保留**；非字符串抛错 |
| `TestPdfPageModel` | 页码必须为正；字符数派生；摘要压缩空白；可序列化 |
| `TestResultSerialization` | 必需字段齐备；失败时保持 `None` 不补 0 |
| `TestParserMetadata` | 解析器名为 pypdf；版本取自实际安装库而非硬编码 |
| `TestStatusSemantics` | **状态语义回归（测试 A/B/C/D）**：全部成功→`success`；单页失败（首/中/末页）→`partial` 且 `text_layer_available=True`、成功页文本与页码保留、失败页错误含页码；空白 PDF 与「全部页失败」→`needs_ocr`，且错误码区分 `no_text_layer` 与 `page_extraction_failed`；失败页不覆盖成功页诊断信息；`to_dict()`/`summarize()` 同时暴露 `is_complete` 与 `text_layer_available` |
| `TestPartialStatusModelConstraints` | `partial` 必须满足：有文本层、有错误、至少一页有文本；`success` 不得带错误且必须有文本层；`failed` 不得含页面；`status` 必须是枚举；合法 `partial` 可正常构造 |

---

## 5. 集成测试明细

### 5.1 `tests/integration/test_database.py`（51 个用例）

| 测试类 | 覆盖内容 |
|---|---|
| `TestSchemaInitialization` | 11 张业务表 + `schema_meta` 全部创建；模式版本写入；重复初始化幂等；重复初始化不丢数据；未初始化时无版本；真实生成文件；每个连接都启用外键；外键违反被拒绝且回滚；`translate_integrity_error` 三类分类正确 |
| `TestProjectCrud` | 新增并读取（含全部字段与枚举往返）；查询不存在返回 `None`；`get_or_raise` 抛错；空列表；列出全部；排序白名单拒绝注入；按名称查询；更新字段；`touch_updated_at` 行为；更新不存在项目；非法名称更新被拒且旧值保留；删除；删除不存在；重复删除；**重复主键**；**存在关联文档时删除被 RESTRICT 拒绝**；写入前校验拦截非法项目；**参数化 SQL 抗注入**；可空字段往返；3 种项目类型往返；项目间数据隔离 |
| `TestTransactionsAndErrors` | 数据库错误导致整体回滚；非 SQL 业务异常上抛并回滚；非法路径抛 `PersistenceError`；绕过领域校验时数据库 CHECK 约束仍拦截非法数据 |
| `TestServiceAndPersistence` | 经服务创建后**用全新连接与新服务实例重新读取**；名称去空白；空白名称被拒；非法类型被拒；字符串类型可接受；经服务更新；经服务删除；输入校验返回问题；消纳输入校验（合法/非法）；`auto_initialize=False` 后手动初始化；异常继承关系 |
| `TestRealDatabaseSafety` | 默认库路径在测试中被重定向；临时库不在用户数据目录内；`sqlite3.Row` 行工厂可用 |

### 5.2 `tests/integration/test_database_memory_and_schema_version.py`（45 个用例）

| 测试类 | 覆盖内容 |
|---|---|
| `TestMemoryDatabaseLifecycle` | `:memory:` 与内存 URI 两种形式的建表跨事务可见；写入后新事务可读；完整 CRUD；回滚隔离；外键强制；`schema_meta` 表存在性；实例间互相不可见；`close()` 语义与上下文管理器 |
| `TestSchemaVersionProtection` | 当前版本幂等与数据保留；未来版本拒绝且**不改写版本号**；被拒后不改动表结构；旧版本无迁移步骤拒绝；迁移注册表为空；已登记迁移真实执行 `ALTER TABLE`；缺步骤停止升级；异常层次 |
| `TestMissingVersionRecordIsNotTreatedAsNewDatabase` | **元数据表存在但缺版本记录**时：查询与初始化都报错；不写当前版本号；不补齐缺失表；不接纳未知结构；既有业务数据保留；NULL 版本值同样视为元数据不完整；空 `schema_meta` 表被拒绝；只有 `schema_meta` 表的半成品库被拒绝；对照组——真正空库仍可初始化、版本有效时缺表可修复 |
| `TestFileDatabaseUnaffected` | 文件库跨实例持久；WAL 与外键；`is_memory=False`；`uri` 参数不影响文件路径；`close()` 不影响文件库 |

---

---

## 6. 边界测试清单（第一阶段必须全部覆盖）

| 编号 | 边界情况 | 覆盖位置 | 期望 |
|---|---|---|---|
| B1 | 负荷与光伏全为零 | 单元 | 电量全 0，比例全 `None` |
| B2 | 只有负荷、没有光伏 | 单元 | 购电 = 总负荷，自用率/余电比例 `None` |
| B3 | 只有光伏、没有负荷 | 单元 | 上网 = 总发电，负荷覆盖率 `None` |
| B4 | 光伏与负荷完全相等 | 单元 | 自用率 = 覆盖率 = 1，上网 = 购电 = 0 |
| B5 | 光伏恒小于负荷 | 单元 | 上网 = 0，余电比例 = 0 |
| B6 | 光伏恒大于负荷 | 单元 | 购电 = 0，覆盖率 = 1 |
| B7 | 空数组 | 单元 + 集成 + 界面 + CLI | 全 0 电量，比例未定义，`status = undefined_ratio` |
| B8 | 长度不一致 | 单元 + 集成 + 界面 + CLI | 抛 `ValidationError`，问题代码 `length_mismatch` |
| B9 | 负数 | 单元 + 集成 | 抛 `ValidationError`，问题代码 `negative_value` |
| B10 | `NaN` | 单元 | 抛 `ValidationError`，问题代码 `nan_value` |
| B11 | 无穷值 | 单元 | 抛 `ValidationError`，问题代码 `infinite_value` |
| B12 | 非数值输入 | 单元 + 界面 | 抛 `ValidationError` / 界面报格式错误 |
| B13 | 能量守恒 | 单元（9 组参数 + 自检） | 两条等式在 `1e-9` 容差内成立 |
| B14 | 项目名称空白 | 单元 + 集成 + CLI | 拒绝写入 |
| B15 | 项目名称 200/201 字符 | 单元 | 200 通过，201 拒绝 |
| B16 | 重复项目主键 | 集成 | `EntityAlreadyExistsError` |
| B17 | 删除有关联数据的项目 | 集成 | 被 RESTRICT 拒绝，项目保留 |
| B18 | SQL 注入字符串作为项目名 | 集成 | 仅作为数据存储，表结构不变 |

---

## 7. 界面验证方案

| 项目 | 方案 |
|---|---|
| 无显示器环境 | 设置 `QT_QPA_PLATFORM=offscreen`，真实创建 `QApplication` 与 `MainWindow` |
| 可自动化验证 | 窗口标题/版本/阶段文案、项目表结构、界面创建项目真实落库、界面计算结果数值、非法输入提示 |
| 无法自动化验证 | 人眼可见的布局美观度、鼠标点击的真实交互手感、真实显示器上的字体渲染 |
| 未安装 PySide6 时 | `pytest.importorskip` 明确 skip 并给出原因，**不伪装成通过** |

---

## 8. 回归测试方案

每次提交前必须执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

只跑某一层时：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit
.\.venv\Scripts\python.exe -m pytest -q tests/integration
.\.venv\Scripts\python.exe -m pytest -q -m gui
```

带覆盖率时：

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=cenep --cov-report=term-missing
```

回归门槛：**全部用例通过，无失败、无错误**。任何失败必须先定位原因，
不允许通过跳过、删除用例或放宽断言来"转绿"。

---

## 9. 后续阶段需要补充的测试

| 阶段 | 需要新增的测试 |
|---|---|
| 第二阶段（账单导入） | 真实账单样本的解析回归、版式变化容错、缺失字段不填假值、导入幂等 |
| 第三阶段（负荷与电价） | 时段粒度归一化、分时时段映射、月度分摊标注为估算、电价来源缺失时拒绝启用 |
| 第四阶段（发电量模拟） | 气象数据缺失处理、倾角/朝向假设版本变更、与年度发电量目标的偏差检查 |
| 第五阶段（经济评价） | 现金流逐年闭合、折现率边界、`NPV`/`IRR`/回收期的独立算法交叉验证、基本电费不随电量同比减少 |
| 第六阶段（报告输出） | 报告数值与计算结果逐项一致、导出失败不产生半成品文件 |

---

## 10. 测试环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（本机开发与验收环境）；CI 另在 Ubuntu 上运行 |
| Python | ≥ 3.11（本机 3.14.7；CI 实测 3.14.8 与 3.11.17 均全部通过） |
| 依赖 | `python -m pip install -e ".[dev]"` |
| Qt 平台 | 无显示器时 `QT_QPA_PLATFORM=offscreen` |
| 数据库 | 仅使用临时文件或内存库 |
| 网络 | 运行测试不需要网络 |
