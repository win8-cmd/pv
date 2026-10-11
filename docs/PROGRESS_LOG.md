# CENEP 完成结论日志（PROGRESS LOG）

- 文件用途：**每一轮开发或复核完成后，在本文件追加一条结论记录，并同步到 GitHub。**
- 记录原则：只写实际执行过的内容与实测数字；未验证事项必须显式列出，不得省略。
- 最新记录在最上面（倒序），便于快速查看当前状态。

---

## 1. 完成轮次索引

| 轮次 | 日期 | 任务 | 分支 | 结论 | 用例数 | CI |
|---|---|---|---|---:|---|
| R6 | 2026-10-11 | 记录本轮 CI 实测结论 | `fix/stage1-review-memory-db-and-schema-version` | 通过（待授权合并） | 244 | 全绿（见 R6） |
| R5 | 2026-10-11 | 合并前最终复核与文档版本同步 | `fix/stage1-review-memory-db-and-schema-version` | 通过（本地证据） | 244 | 结果见 R6 |
| R4 | 2026-10-11 | 元数据完整性修复与测试数量统一 | `fix/stage1-review-memory-db-and-schema-version` | 通过（待审阅合并） | 244 | 全绿 |
| R3 | 2026-10-11 | 建立完成结论日志与每轮更新约定 | `fix/stage1-review-memory-db-and-schema-version` | 完成（待随 PR #1 合并） | 234 | 全绿 |
| R2 | 2026-10-11 | 第一阶段代码复核与缺陷修复 | `fix/stage1-review-memory-db-and-schema-version` | 通过（待审阅合并） | 234 | 全绿 |
| R1 | 2026-10-11 | 第一阶段工程骨架与核心规则冻结 | `main` | 通过（已合并至 main） | 199 | 无（当时尚未配置） |

---

## 2. R5 — 合并前最终复核与文档版本同步

- 完成日期：2026-10-11
- 任务来源：第一阶段最终修正与合并前验收执行任务书
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- 结论：**通过**（等待仓库所有者授权合并，本轮未合并 PR）

### 2.1 执行前的远程状态核对

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

### 2.2 实际修改的文件及原因

本轮**未修改任何代码与测试**（元数据保护逻辑经复核已完整，见 2.3），
仅修正文档的当前状态描述：

| 文件 | 修改内容 | 原因 |
|---|---|---|
| `docs/TEST_PLAN.md` | 文档版本 `2026.10-stage1-r3` → `r4` | 内容已记录 R4 的实测结果，但版本标识未跟上，与 `PROGRESS_LOG` 记录的轮次不一致 |
| `docs/ACCEPTANCE_CRITERIA.md` | 文档版本 `2026.10-stage1-r2` → `2026.10-stage1-r4`（标题改为"第 4 版：合并前最终复核"）；补充 4 个版本的对照表与"文档版本命名口径"说明 | 文档内容早已覆盖 R3/R4（含新增 A17），但版本号仍停留在 r2，属自相矛盾 |
| `README.md` | 顶部补充"当前状态：第一阶段已完成，正在 PR #1 审阅中，尚未合并到 `main`"，并给出审阅分支与 PR 链接 | 原文只写"开发分支 main"，易被误认为代码已在 main，与实际不符 |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 第 9 节第 6 条由"`main` 分支尚无任何提交"改为当前真实状态（main 已有 3 个提交、改动走分支 + PR）；第 2 条补充强制推送的**唯一例外条件**及其核验要求 | 前者是过期陈述；后者与 R1 中"经授权改写作者身份"的史实冲突，未说明例外会让后续开发者无法解释既有历史 |

**未改动**：`src/`、`tests/` 下任何文件。

### 2.3 数据库元数据保护逻辑复核结论

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

### 2.4 测试收集命令与数量

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

### 2.5 完整测试的真实结果

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

### 2.6 git diff --check

```powershell
git diff --check
```

无输出，退出码 **0**（无空白字符错误、无补丁格式问题）。

### 2.7 CI 三项守卫的本地复现

不能仅凭本地测试宣称远程 CI 通过，但也需确认守卫逻辑本身有效：

| 守卫 | 本地复现结果 |
|---|---|
| 架构分层检查 | `tests/unit/test_layering.py` 16 个用例全部通过 |
| 跳过用例门禁 | 按 CI 同一正则解析真实输出：`parsed passed=244`、`parsed skipped=0` → 门禁 PASS |
| 工作树洁净检查 | `git status --porcelain` 为空 → PASS（测试未污染仓库） |

### 2.8 提交与推送

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

### 2.9 最新 GitHub Actions

本轮提交推送后触发的新运行结果见 **R6**（待该运行结束后据实记录）。
本地已复现 CI 的三项守卫（见 2.7），但**本地通过不等于远程 CI 通过**，
因此本节不预先声称 CI 结论。

### 2.10 PR 当前状态

| 项目 | 值 |
|---|---|
| PR | [#1](https://github.com/win8-cmd/pv/pull/1) |
| 状态 | **open（未合并，未授权合并）** |
| 合并前要求 | 仓库所有者复核 |

### 2.11 仍未验证的项目

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

### 2.12 后续建议

1. 由仓库所有者复核并**授权合并** PR #1；合并后本轮文档与修复进入 `main`。
2. （可选）把"文档数量与 `pytest --collect-only` 一致"固化为自动化测试，
   闭合 2.11 第 9 项。
3. （可选）演练首个真实迁移（`SCHEMA_VERSION` 提升到 2 并登记真实 `ALTER TABLE`），
   闭合 2.11 第 5 项。
4. 以上闭合后再评估是否进入第二阶段（电费账单导入与数据提取）。
   **本轮未开始第二阶段。**

---

## 3. R4 — 元数据完整性修复与测试数量统一

- 完成日期：2026-10-11
- 任务来源：复核意见（PR #1 的两项问题）
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- 结论：**完成**（等待复核，未合并）

### 3.1 完成内容

| 编号 | 问题 | 状态 | 实际做法 |
|---|---|---|---|
| 1 | `_read_schema_version()` 未区分"元数据表不存在"与"表存在但缺版本记录" | 完成 | 新增 `_read_schema_state()` 返回 `(表是否存在, 版本或 MISSING_VERSION)`；后者改为抛 `SchemaVersionError` |
| 2 | `TEST_PLAN.md` 分布表与明细分节数量不一致 | 完成 | 以 `pytest --collect-only -q` 实际输出为准重写分布表与各小节数量；补齐新增文件的明细小节 |

### 3.2 缺陷原因与修复

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

### 3.3 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 用独立哨兵而非 `-1` 或空字符串表示"表在但缺版本" | `-1` 会被误当版本号参与比较；哨兵可与 `None` 明确区分且为假值 |
| "表在但缺版本记录"一律拒绝，不做结构推断 | 推断"结构看起来像当前版本"会把猜测变成写入依据；拒绝可由人工修元数据后恢复，猜错则可能破坏数据 |
| 拒绝时不改动任何东西（不写、不补表、不建索引） | 拒绝必须是"无所作为"，否则仍会对结构未知的库产生副作用 |
| 保留"版本有效但缺表可幂等补齐" | 该场景结构版本明确，属正常修复，与元数据损坏性质不同 |
| 重写而非删除错误用例 | 该用例固化了错误语义；直接删除会丢失"这里曾有分歧"的信息，重写为对照组更有价值 |
| R1/R2 的历史数字不追溯改写 | 结论日志的生命力在于如实；追溯改写会让"当时实测是什么"无从考证 |

### 3.4 测试结果（实测）

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

### 3.5 CI 实测

| 运行 | 触发提交 | Python 3.14 | Python 3.11 |
|---|---|---|---|
| [run 38121815648](https://github.com/win8-cmd/pv/actions/runs/38121815648) | `c45e63d` | success（`244 passed in 1.26s`） | success（`244 passed in 1.79s`） |

跳过用例门禁输出"无跳过用例，全部用例已真实执行（passed=244）"，
架构分层检查与工作树洁净检查均通过。

### 3.6 变更文件清单

| 文件 | 变更 |
|---|---|
| `src/cenep/infrastructure/database.py` | `_read_schema_state()`、`MISSING_VERSION` 哨兵、初始化与查询的元数据校验 |
| `tests/integration/test_database_memory_and_schema_version.py` | 替换错误语义用例，新增 10 个用例 |
| `docs/TEST_PLAN.md` | 分布表与明细小节数量按实测重写，新增 5.2 |
| `docs/ACCEPTANCE_CRITERIA.md` | 新增验收项 A17、缺陷对照行、CI 运行表 |
| `docs/ARCHITECTURE.md` | 元数据保护规则与 `MISSING_VERSION` 说明 |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 第 5 节新增"元数据完整性红线" |
| `README.md`、`docs/PRD.md`、`docs/ROADMAP.md` | 数量同步为 244 |

### 3.7 Git 状态

| 项目 | 值 |
|---|---|
| 提交 | `c45e63d` fix: 区分"元数据表不存在"与"缺版本记录"，并统一测试数量 |
| 推送状态 | 已推送至 `origin/fix/stage1-review-memory-db-and-schema-version` |
| 强制推送 | 未使用 |
| PR | PR #1 保持 open，**未合并**（按要求等待复核） |

### 3.8 未完成事项（如实披露）

1. **PR #1 仍为 open**，本轮修复未合并到 main。
2. 元数据修复属**代码评审发现的缺陷**，非运行中故障；除新增用例覆盖的场景外，
   未穷举所有可能的元数据损坏形态（例如 `schema_meta` 表结构被改成别的列）。
3. 内存库多线程并发、真实显示器观感、真实账单与电价数据、
   多进程并发写、打包发布、覆盖率数值——继承 R2 第 3.8 节，仍未验证。
4. 结论日志与文档数量目前靠人工同步，**无自动化校验**（可将
   `--collect-only` 结果与文档比对做成测试）。

### 3.9 下一轮建议

1. 复核本轮修复与 PR #1，合并后使日志与修复进入 main。
2. （可选）增加"文档数量与实测一致"的自动化校验，闭合第 2.8 节第 4 项。
3. 三项缺陷（内存库、版本降级、元数据完整性）闭合后，再考虑进入第二阶段。

---

## 4. R3 — 建立完成结论日志与每轮更新约定

- 完成日期：2026-10-11
- 任务来源：用户要求"生成本轮已完成的结论文件同步到 GitHub，后续每次完成后执行此类操作"
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- 结论：**完成**

### 4.1 完成内容

| 编号 | 要求 | 状态 | 实际做法 |
|---|---|---|---|
| 1 | 生成本轮已完成的结论文件 | 完成 | 新增 `docs/PROGRESS_LOG.md`；补录 R1、R2 两轮完整结论 |
| 2 | 同步到 GitHub | 完成 | 提交并推送到 PR #1 分支；已用 GitHub API 校验文件确实可从远程取回 |
| 3 | 后续每次完成后执行此类操作 | 完成 | 写入制度而非仅口头约定：`docs/AI_DEVELOPMENT_GUIDE.md` 完成定义新增条目并新增第 10.1 节操作步骤；`README.md` 文档索引与工作约定同步标注 |

### 4.2 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 采用单一累计文件而非每轮一个文件 | 一个位置即可看到全部历史与当前状态；避免文件分散、索引失同步 |
| 最新记录在最上面（倒序） | 查看"当前状态"是最高频需求 |
| 固定九节模板（完成内容 / 缺陷或变更原因 / 关键设计决策 / 测试结果 / CI 实测 / 变更文件清单 / Git 状态 / 未完成事项 / 下一轮建议） | 模板固定才能跨轮次横向对比，也避免遗漏"未完成事项"这一最易被省略的部分 |
| 同时补录 R1 与 R2 | 只记录最新一轮会让上一轮结论无从追溯；R1 的自我纠正记录尤其值得留痕 |
| 把约定写进 AI_DEVELOPMENT_GUIDE 的完成定义并列为完成条件 | 仅写进日志本身容易被后续开发者忽略；纳入 DoD 才有约束力 |
| 本轮也单独记为 R3 | 轮次记录应自洽——新增约定后第一件应用它的事就是记录本轮自身 |

### 4.3 测试结果（实测）

本机：Windows 11 专业版 10.0.22621 / Python 3.14.7

| 命令 | 结果 |
|---|---|
| `python -m pytest -p no:cacheprovider` | **234 passed**（0 failed / 0 error / 0 skipped） |
| `python -m pytest --collect-only -q` | 收集正常，合计 234 |
| `git diff --check` | 通过（退出码 0） |

本轮为纯文档变更，未改动任何代码或测试，用例数与 R2 相同（234）。

### 4.4 CI 实测

| 运行 | 触发提交 | 结果 |
|---|---|---|
| [run 38121391733](https://github.com/win8-cmd/pv/actions/runs/38121391733) | `67145e4`（新增 PROGRESS_LOG） | Python 3.14 与 3.11 均 success |

### 4.5 变更文件清单

| 文件 | 变更 |
|---|---|
| `docs/PROGRESS_LOG.md` | 新增（本文件，含 R1–R3 记录与维护规则） |
| `docs/AI_DEVELOPMENT_GUIDE.md` | 完成定义新增条目；新增第 10.1 节每轮更新步骤与命令 |
| `README.md` | 文档索引加入 PROGRESS_LOG；标注每轮更新约定 |

### 4.6 Git 状态

| 项目 | 值 |
|---|---|
| 提交 | `67145e4` docs: 新增完成结论日志 PROGRESS_LOG，并确立每轮更新约定 |
| 推送状态 | 已推送至 `origin/fix/stage1-review-memory-db-and-schema-version` |
| 强制推送 | 未使用 |

### 4.7 未完成事项（如实披露）

1. **R3 与 PR #1 的其余变更尚未合并到 main**：PR #1 仍为 open；因此
   `docs/PROGRESS_LOG.md` 目前只存在于 PR 分支，合并后才出现在 main。
2. 本文件仍由人工按约定维护，**没有自动化校验**（例如校验索引表与各轮小节一致、
   或校验记录中的用例数与 `pytest --collect-only` 实际数量一致）。
3. 其余未验证事项继承 R2 第 3.8 节，本轮未涉及。

### 4.8 下一轮建议

1. 审阅并合并 PR #1，使结论日志进入 main。
2. （可选）为 PROGRESS_LOG 增加一致性校验测试，闭合第 2.7 节第 2 项。
3. 之后按约定执行：每轮完成时先更新本文件，再推送。

---

## 5. R2 — 第一阶段代码复核与缺陷修复

- 完成日期：2026-10-11
- 任务来源：第一阶段代码复核与缺陷修复任务书
- 分支：`fix/stage1-review-memory-db-and-schema-version`
- Pull Request：[PR #1](https://github.com/win8-cmd/pv/pull/1)（open，mergeable: clean）
- 结论：**通过**（复核新增验收项 A14–A16 全部通过；等待审阅合并）

### 5.1 完成内容

| 编号 | 任务书要求 | 状态 | 实际做法与证据 |
|---|---|---|---|
| 1 | 修复内存数据库问题 | 完成 | 采用共享缓存内存库 + 实例级锚定连接；新增 14 个用例覆盖建表→写入→结束事务→重开事务→读取 |
| 2 | 增强模式版本保护 | 完成 | 初始化前读取现有版本并分类处理；未来/旧版本抛 `SchemaVersionError`，**版本号保持原值**；新增迁移注册表与阶梯执行 |
| 3 | 修正文档测试统计和日期 | 完成 | 验收日期 `2026-02-01` → `2026-10-11`（实测）；各文件用例数统一为 234；文档版本 → `2026.10-stage1-r2` |
| 4 | 增加自动化测试工作流 | 完成 | `.github/workflows/tests.yml`；已在 GitHub 真实运行 3 轮，均 success |
| 5 | 完整回归测试 | 完成 | 安装 + 全量 pytest + collect-only + `git diff --check`，实测数字见 1.4 |
| 6 | Git 要求 | 完成 | 开发前工作树干净；提交到独立分支并创建 PR；**全程未使用强制推送** |
| 7 | 最终交付 | 完成 | 本轮报告已提交给用户；本文件为持久化结论 |

### 5.2 缺陷原因与修复

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

### 5.3 关键设计决策与理由

| 决策 | 理由 |
|---|---|
| 保留内存数据库，而非取消支持 | 任务书允许二选一；内存库便于后续测试，且共享缓存方案只需一个锚定连接即可保持"每次事务新建连接"的既有并发模型 |
| 每实例生成唯一内存库名 | 避免不同 `Database` 实例意外看到同一内存库（该问题在开发中被隔离测试发现并修正） |
| 旧版本无迁移步骤时**拒绝**而非部分升级 | 部分升级会造成"版本号前进但结构未迁移"的假升级，风险高于拒绝启动 |
| 迁移 SQL 执行成功后才推进版本号 | 保证结构与版本号原子一致 |
| 新增 `SchemaVersionError` 而非复用 `PersistenceError` | 调用方可精确区分"版本不兼容"与一般持久化故障；同时继承 `PersistenceError` 保持兼容 |
| CI 增加独立的"跳过用例门禁" | 任务书明确禁止以跳过测试获得绿色结果；仅靠"没有失败"无法证明没有跳过 |

### 5.4 测试结果（实测）

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

### 5.5 CI 实测（GitHub Actions，非本地推定）

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

### 5.6 变更文件清单

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

### 5.7 Git 状态

| 项目 | 值 |
|---|---|
| 开发前工作树 | 干净，无用户未提交修改 |
| 提交 1 | `6afa5af` fix: 修复内存数据库跨事务失效与模式版本静默降级 |
| 提交 2 | `7f90a75` ci: 测试汇总行可靠输出，并新增跳过用例门禁 |
| 提交 3 | `3f2519d` docs: 记录 CI 实测结果，消除两项未验证事项 |
| 推送状态 | 已推送至 `origin/fix/stage1-review-memory-db-and-schema-version`（`0 0` 同步） |
| 强制推送 | **未使用** |
| 敏感文件 | 未提交数据库、账单、密钥、缓存 |

### 5.8 未完成事项（如实披露）

1. **CI 与代码变更尚未合并到 main**：PR #1 仍为 open，等待审阅。
2. **内存库多线程并发访问**未验证（仅单实例单线程）。
3. **真实显示器界面观感与真实鼠标点击回放**未验证（自动化在 Qt `offscreen`）。
4. **真实电费账单数据与真实电价数据**未提供（本阶段明确不含）。
5. **多进程并发写压力测试**未做。
6. **迁移框架仅具骨架**：机制经真实 `ALTER TABLE` 与"缺步骤即停止"测试验证，但 `SCHEMA_VERSION` 仍为 1，注册表为空。
7. **打包与安装程序**未实现。
8. **覆盖率数值**未采集为验收指标。

### 5.9 下一轮建议

1. 审阅并合并 PR #1。
2. （可选）演练首个真实迁移：把 `SCHEMA_VERSION` 提升到 2 并登记一条真实 `ALTER TABLE`，验证迁移路径在真实场景下可用。
3. （可选）为内存库补多线程并发测试，闭合 1.8 第 2 项。
4. 上述闭合后再进入第二阶段：电费账单导入与数据提取。**本轮未开始第二阶段。**

---

## 6. R1 — 第一阶段工程骨架与核心规则冻结

- 完成日期：2026-10-11
- 任务来源：第一阶段工程骨架与核心规则冻结任务书
- 分支：`main`
- 结论：**通过**（13 项验收项全部通过）

### 6.1 完成内容

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

### 6.2 核心计算结果（标准验收案例）

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

### 6.3 测试结果（实测）

| 命令 | 结果 |
|---|---|
| `python -m pytest` | **199 passed**（0 failed / 0 error / 0 skipped） |
| `git diff --check` | 通过 |
| GUI 真实启动 | 事件循环启动并正常退出（退出码 0），界面计算结果正确 |
| 推送后复核 | 重新克隆仓库，以克隆自身 `src/` 运行测试 → 199 passed |

界面启动实测输出：`GUI_VISIBLE=True`、`GUI_EXIT_CODE=0`、界面计算结果含 `9.000000` 等验收数值。

### 6.4 Git 状态

| 项目 | 值 |
|---|---|
| 开发前仓库 | 空仓库（无提交、无工作树内容），未覆盖任何既有内容 |
| 提交 | `613b6fc` feat → `9a494a5` docs → `5494436` docs |
| 作者 | `Sterling--Q <335395661+win8-cmd@users.noreply.github.com>` |
| 推送状态 | 已推送至 `origin/main`（`0 0` 同步） |
| 强制推送 | 使用过一次（经仓库所有者明确授权），用于把占位作者 `CENEP Developer` 修正为真实身份；改写前后树对象哈希逐一比对，**内容完全一致** |

### 6.5 本轮的自我纠正记录（留痕）

开发过程中由真实执行发现并修复的问题：Qt `setData` 把 `str` 枚举降级为普通字符串；异常文本泄漏枚举类名（`[Severity.ERROR]`）；`SelfConsumptionResult` docstring 声称负荷覆盖率"可以大于 1"（与公式矛盾的文档缺陷）；`pyproject.toml` 声明 `readme = "README.md"` 而该文件当时不存在；工作区 Windows 文件权限故障阻塞沙箱写入（已按权限诊断流程修复）。

### 6.6 未完成事项（R1 结束时）

真实显示器界面观感、鼠标点击回放、真实账单与电价数据、多文件库并发写、迁移框架、打包安装程序、覆盖率数值。

### 6.7 下一轮建议（R1 结束时）

进入第二阶段账单导入与数据提取。实际下一轮执行的是**代码复核与缺陷修复（R2）**，
即任务书要求的先复核、再推进下一阶段。

---

## 7. 本文件的维护规则（后续每轮必读）

每一轮完成后，按以下步骤操作，**不要跳过第 3、5 步**：

1. **收集证据**：实际运行测试与校验命令，记录真实数字（命令、通过数、失败数、跳过数）。禁止凭记忆或估算填写。
2. **取 Git 事实**：`git log --oneline`、`git status --short --branch`、`git rev-parse HEAD`、与远程的 `rev-list --left-right --count`。
3. **确认未验证事项**：把本轮仍未验证的能力写清，不允许省略或用"基本完成"模糊表述。
4. **追加记录**：在 `## 1. 完成轮次索引` 表格顶部插入一行，并在索引下方插入新的 `## R<n> — <任务名>` 小节，沿用 R2 的九个小节结构（完成内容 / 缺陷或变更原因 / 关键设计决策 / 测试结果 / CI 实测 / 变更文件清单 / Git 状态 / 未完成事项 / 下一轮建议）。
5. **同步文档一致性**：若用例数量、版本号或验收日期变化，同步更新 `README.md`、`docs/TEST_PLAN.md`、`docs/ACCEPTANCE_CRITERIA.md`，避免本文件与它们互相矛盾。
6. **提交并推送**：按当轮约定提交到 PR 分支或 main，并确认远程同步状态；在记录中如实写明是"已推送"还是"仅本地提交"。

轮次编号规则：`R1`、`R2`…… 连续递增；同一轮内的多次补充提交不新开轮次，直接补充该轮记录。
