# CENEP 数据模型说明书（DATA_MODEL）

- 文档版本：`2026.02-stage1`
- 模式版本：`SCHEMA_VERSION = 1`（见 `src/cenep/infrastructure/database.py`）
- 对应代码：`src/cenep/domain/models.py`（领域模型）、
  `src/cenep/infrastructure/database.py`（`SCHEMA_STATEMENTS` 建表语句）

本文件与建表语句**逐字段一致**。任何字段、类型、约束或索引的改动，必须同时修改
`models.py`、`database.py` 与本文件，并提升 `SCHEMA_VERSION`。

---

## 1. 总体约定

| 项目 | 约定 |
|---|---|
| 主键 | UUID4 十六进制字符串（32 位小写，无连字符），由 `cenep.domain.models.new_id()` 生成。不使用自增整数，避免多库合并与导入导出时主键冲突 |
| 时间戳 | UTC 的 ISO 8601 字符串，秒精度，格式 `YYYY-MM-DDTHH:MM:SSZ`，由 `utc_now_iso()` 生成 |
| 日期 | `YYYY-MM-DD` 字符串 |
| 电量单位 | kWh（字段名一律以 `_kwh` 结尾） |
| 功率单位 | kW（字段名以 `_kw` 结尾）；装机容量用 kWp（`_kwp`） |
| 金额单位 | 元（字段名以 `_yuan` 结尾） |
| 比例单位 | 内部使用 `0 ~ 1` 比值，字段名以 `_rate` 结尾；界面展示时才转百分比 |
| 布尔 | 仅使用 `TEXT` / `REAL` / `INTEGER`，不使用 `BOOLEAN` |
| 缺失值 | 用 `NULL` / Python `None` 表达。**禁止**用 0 或估算值冒充实测值 |
| 枚举 | 以字符串存储，并由数据库 `CHECK` 约束枚举取值；Python 侧对应 `str` 枚举 |
| 字符编码 | UTF-8 |

### 1.1 时段电量与瞬时功率的区别（必须严格遵守）

- **时段电量**：某一时间区间内累计的电能，单位 kWh。
  存储字段为 `load_profile.energy_kwh`，类型 `REAL`，非负。
- **瞬时功率**：某一时刻的功率，单位 kW。
  **本项目第一阶段不存储瞬时功率**；如需表达，必须新增 `power_kw` 字段，
  不得复用 `energy_kwh`。

换算关系为：

```text
energy_kwh = power_kw × interval_minutes / 60
```

把功率数值写入 `energy_kwh` 属于数据错误，数据库层面无法识别，
必须在数据导入环节拦截并记录校验问题。

### 1.2 删除策略

| 关系 | 策略 | 后果 |
|---|---|---|
| `project` ← `document` / `bill_record` / `load_profile` / `pv_model` / `scenario` / `report` | `ON DELETE RESTRICT` | 项目存在关联数据时，删除被数据库拒绝，转为 `PersistenceError`。防止误删客户原始台账 |
| `calculation_run` ← `result_record` | `ON DELETE CASCADE` | 删除一次计算运行记录时，连带删除其指标结果（同一计算产物，无独立价值） |
| `project` ← `validation_issue` | `ON DELETE CASCADE` | 校验问题记录随项目一起清理 |
| `document` ← `bill_record.source_document_id` | `ON DELETE SET NULL` | 原始文件被移除时保留账单记录，仅解除来源引用 |
| `pv_model` / `tariff_model` / `scenario` 被 `scenario` / `report` 引用 | `ON DELETE SET NULL` | 保留测算与报告记录，仅置空引用 |

所有连接均执行 `PRAGMA foreign_keys = ON`，外键约束真实生效
（由 `tests/integration/test_database.py` 验证）。

---

## 2. 实体关系总览

```text
project (项目)  ── 全部业务数据的隔离边界
  ├──1:N── document (原始文件)
  ├──1:N── bill_record (月度电费账单) ──N:1── document
  ├──1:N── load_profile (时段负荷)
  ├──1:N── pv_model (光伏方案)
  ├──1:N── scenario (测算方案) ──N:1── pv_model
  │                            └──N:1── tariff_model
  ├──1:N── report (报告输出) ──N:1── scenario
  └──1:N── validation_issue (校验问题)

tariff_model (电价方案)  ── 独立于项目（可跨项目复用）

scenario ──1:N── calculation_run (计算运行记录) ──1:N── result_record (计算结果)
```

---

## 3. 表定义

### 3.1 `schema_meta` — 模式元数据

| 字段 | 类型 | 可空 | 键/约束 | 说明 |
|---|---|---|---|---|
| `key` | TEXT | 否 | 主键 | 元数据键，当前仅 `schema_version` |
| `value` | TEXT | 否 | — | 元数据值 |

用途：记录数据库模式版本，供后续迁移判断。

### 3.2 `project` — 项目

**第一阶段具备完整 CRUD。**

| 字段 | 类型 | 可空 | 键/约束 | 单位 | 说明 |
|---|---|---|---|---|---|
| `project_id` | TEXT | 否 | 主键 | — | UUID4 十六进制 |
| `name` | TEXT | 否 | `CHECK (length(trim(name)) BETWEEN 1 AND 200)` | — | 项目名称 |
| `location` | TEXT | 是 | — | — | 项目地址（省/市/区） |
| `customer_name` | TEXT | 是 | — | — | 业主或客户名称 |
| `project_type` | TEXT | 否 | `CHECK IN ('industrial_commercial','utility_scale','other')`，默认 `industrial_commercial` | — | 项目类型 |
| `created_at` | TEXT | 否 | — | — | 创建时间（UTC ISO 8601） |
| `updated_at` | TEXT | 否 | — | — | 最后更新时间 |
| `description` | TEXT | 是 | — | — | 项目说明 |

索引：

- `idx_project_name` on `(name)`
- `idx_project_updated_at` on `(updated_at DESC)`

对应 Python 类：`cenep.domain.models.Project`；
对应枚举：`ProjectType`。

### 3.3 `document` — 文件

| 字段 | 类型 | 可空 | 键/约束 | 说明 |
|---|---|---|---|---|
| `document_id` | TEXT | 否 | 主键 | UUID4 |
| `project_id` | TEXT | 否 | 外键 → `project.project_id`，`ON DELETE RESTRICT` | 所属项目 |
| `filename` | TEXT | 否 | — | 原始文件名（仅名称，不含目录） |
| `document_type` | TEXT | 否 | `CHECK IN ('electricity_bill','load_profile','tariff_document','other')`，默认 `other` | 文件类型 |
| `file_path` | TEXT | 是 | — | 本地文件路径（元数据，与解析结果分离） |
| `imported_at` | TEXT | 否 | — | 导入时间 |
| `processing_status` | TEXT | 否 | `CHECK IN ('pending','parsed','failed','manual_review')`，默认 `pending` | 处理状态 |

索引：`idx_document_project` on `(project_id)`。

对应 Python 类：`Document`；枚举：`DocumentType`、`ProcessingStatus`。

**设计要求：原始文件路径与解析结果分开管理。** 第一阶段只登记文件元数据，
不实现解析。

### 3.4 `bill_record` — 电费账单记录

| 字段 | 类型 | 可空 | 键/约束 | 单位 | 说明 |
|---|---|---|---|---|---|
| `bill_id` | TEXT | 否 | 主键 | — | UUID4 |
| `project_id` | TEXT | 否 | 外键 → `project`，`ON DELETE RESTRICT` | — | 所属项目 |
| `billing_period_start` | TEXT | 是 | — | — | 账期起（`YYYY-MM-DD`） |
| `billing_period_end` | TEXT | 是 | — | — | 账期止（`YYYY-MM-DD`） |
| `total_energy_kwh` | REAL | 是 | `CHECK (IS NULL OR >= 0)` | kWh | 账期总用电量 |
| `total_amount_yuan` | REAL | 是 | `CHECK (IS NULL OR >= 0)` | 元 | 账期总电费 |
| `validation_status` | TEXT | 否 | `CHECK IN ('unvalidated','valid','invalid','warning')`，默认 `unvalidated` | — | 校验状态 |
| `source_document_id` | TEXT | 是 | 外键 → `document`，`ON DELETE SET NULL` | — | 来源文件 |

表级约束：`billing_period_start <= billing_period_end`（任一为空时不做限制）。

索引：`idx_bill_project_period` on `(project_id, billing_period_start)`。

对应 Python 类：`BillRecord`；枚举：`ValidationStatus`。

**设计要求：必须保留来源与校验状态。** 缺失的电量或电费一律保持 `NULL`，
不得填入看似合理的数值。

### 3.5 `load_profile` — 负荷曲线

| 字段 | 类型 | 可空 | 键/约束 | 单位 | 说明 |
|---|---|---|---|---|---|
| `profile_id` | TEXT | 否 | 主键 | — | UUID4 |
| `project_id` | TEXT | 否 | 外键 → `project`，`ON DELETE RESTRICT` | — | 所属项目 |
| `timestamp` | TEXT | 否 | — | — | 时段起点（UTC ISO 8601） |
| `energy_kwh` | REAL | 否 | `CHECK (>= 0)` | kWh | **该时段电量**（非瞬时功率） |
| `interval_minutes` | INTEGER | 否 | `CHECK (> 0)` | 分钟 | 时段长度 |
| `source_type` | TEXT | 否 | `CHECK IN ('meter_interval','bill_allocated','synthetic','manual')`，默认 `manual` | — | 数据来源类型 |

唯一约束：`UNIQUE (project_id, timestamp, interval_minutes)`
——同一项目、同一时段起点、同一粒度不允许重复记录。

索引：`idx_load_profile_project_ts` on `(project_id, timestamp)`。

对应 Python 类：`LoadProfile`；枚举：`SourceType`。

`source_type` 的含义直接决定数据可信度：

| 取值 | 含义 | 可信度 |
|---|---|---|
| `meter_interval` | 电表分时计量数据 | 实测数据 |
| `bill_allocated` | 由月度账单按典型曲线分摊 | 估算数据，必须标注 |
| `synthetic` | 模拟/假设生成 | 假设数据 |
| `manual` | 人工录入 | 取决于录入依据 |

### 3.6 `tariff_model` — 电价方案

| 字段 | 类型 | 可空 | 键/约束 | 说明 |
|---|---|---|---|---|
| `tariff_id` | TEXT | 否 | 主键 | UUID4 |
| `name` | TEXT | 否 | — | 方案名称 |
| `region` | TEXT | 是 | — | 适用地区 |
| `effective_from` | TEXT | 是 | — | 生效日期（`YYYY-MM-DD`） |
| `effective_to` | TEXT | 是 | — | 失效日期；`NULL` 表示长期有效 |
| `tariff_type` | TEXT | 否 | `CHECK IN ('tou_industrial','flat','demand','market','other')`，默认 `tou_industrial` | 电价类型 |
| `source_reference` | TEXT | 是 | — | 来源说明（文件名/文号/URL） |
| `status` | TEXT | 否 | `CHECK IN ('draft','active','archived')`，默认 `draft` | 状态 |

表级约束：`effective_from <= effective_to`（任一为空时不做限制）。

对应 Python 类：`TariffModel`；枚举：`TariffType`、`EntityStatus`。

**设计要求：** 电价方案独立于项目存储，可被多个项目复用。
正式电价数据必须填写 `source_reference` 与 `effective_from`；
`source_reference` 为空的记录不得将 `status` 置为 `active`
（见 `CALCULATION_SPEC.md` 第 10 条第 8、9 项）。
本项目当前**不包含**任何已核实的全国电价数据。

### 3.7 `pv_model` — 光伏方案

| 字段 | 类型 | 可空 | 键/约束 | 单位 | 说明 |
|---|---|---|---|---|---|
| `pv_model_id` | TEXT | 否 | 主键 | — | UUID4 |
| `project_id` | TEXT | 否 | 外键 → `project`，`ON DELETE RESTRICT` | — | 所属项目 |
| `installed_capacity_kwp` | REAL | 否 | `CHECK (>= 0)` | kWp | 装机容量 |
| `annual_generation_kwh` | REAL | 是 | `CHECK (IS NULL OR >= 0)` | kWh | 年发电量；第一阶段不做模拟，缺失时为 `NULL` |
| `generation_profile_reference` | TEXT | 是 | — | — | 发电量曲线来源引用 |
| `assumptions_version` | TEXT | 否 | — | — | 假设口径版本，取自 `ASSUMPTIONS_VERSION` |

索引：`idx_pv_model_project` on `(project_id)`。

对应 Python 类：`PVModel`。

### 3.8 `scenario` — 测算方案

| 字段 | 类型 | 可空 | 键/约束 | 说明 |
|---|---|---|---|---|
| `scenario_id` | TEXT | 否 | 主键 | UUID4 |
| `project_id` | TEXT | 否 | 外键 → `project`，`ON DELETE RESTRICT` | 所属项目 |
| `name` | TEXT | 否 | — | 方案名称 |
| `pv_model_id` | TEXT | 是 | 外键 → `pv_model`，`ON DELETE SET NULL` | 采用的光伏方案 |
| `tariff_id` | TEXT | 是 | 外键 → `tariff_model`，`ON DELETE SET NULL` | 采用的电价方案 |
| `assumptions` | TEXT | 是 | — | 方案假设说明（JSON 文本或备注） |
| `created_at` | TEXT | 否 | — | 创建时间 |

索引：`idx_scenario_project` on `(project_id)`。

对应 Python 类：`Scenario`。

### 3.9 `calculation_run` — 计算运行记录

| 字段 | 类型 | 可空 | 键/约束 | 说明 |
|---|---|---|---|---|
| `calculation_run_id` | TEXT | 否 | 主键 | UUID4 |
| `scenario_id` | TEXT | 是 | 外键 → `scenario`，`ON DELETE SET NULL` | 所属方案 |
| `calculation_type` | TEXT | 否 | 默认 `self_consumption` | 计算类型 |
| `calculation_version` | TEXT | 否 | — | 计算规则版本，取自 `CALCULATION_VERSION` |
| `input_snapshot` | TEXT | 是 | — | 输入快照（JSON 文本） |
| `status` | TEXT | 否 | `CHECK IN ('pending','running','succeeded','failed')`，默认 `pending` | 运行状态 |
| `started_at` | TEXT | 否 | — | 开始时间 |
| `completed_at` | TEXT | 是 | — | 完成时间 |

索引：`idx_calc_run_scenario` on `(scenario_id)`。

对应 Python 类：`CalculationRun`；枚举：`CalculationStatus`、`CalculationType`。

**设计要求：** `input_snapshot` + `calculation_version` 共同保证计算结果可追溯、
可复现。任何计算结果都必须能回答"用了什么输入、按哪一版规则算的"。

### 3.10 `result_record` — 计算结果

| 字段 | 类型 | 可空 | 键/约束 | 单位 | 说明 |
|---|---|---|---|---|---|
| `result_id` | TEXT | 否 | 主键 | — | UUID4 |
| `calculation_run_id` | TEXT | 否 | 外键 → `calculation_run`，`ON DELETE CASCADE` | — | 所属计算运行 |
| `metric_name` | TEXT | 否 | — | — | 指标名，取值见 `MetricName` |
| `value` | REAL | 是 | — | 视指标而定 | 指标数值；未定义时 `NULL` |
| `unit` | TEXT | 是 | — | — | `kWh` 或 `ratio` |
| `period` | TEXT | 是 | — | — | 统计期间 |
| `status` | TEXT | 否 | 默认 `ok` | — | `ok` 或 `undefined` |

唯一约束：`UNIQUE (calculation_run_id, metric_name, period)`。

索引：`idx_result_run` on `(calculation_run_id)`。

对应 Python 类：`ResultRecord`；指标名枚举：`MetricName`。

**设计要求：** 一条记录一个指标。比例类指标未定义时，
`value` 必须为 `NULL` 且 `status = 'undefined'`，**禁止写入 0**。

`MetricName` 取值与消纳计算输出字段一一对应：

| `metric_name` | 单位 | 说明 |
|---|---|---|
| `total_load_kwh` | kWh | 总用电量 |
| `total_pv_kwh` | kWh | 总光伏发电量 |
| `total_self_consumption_kwh` | kWh | 自用电量 |
| `total_export_kwh` | kWh | 余电上网电量 |
| `total_grid_import_kwh` | kWh | 电网购电量 |
| `self_consumption_rate` | ratio | 自用率 |
| `load_coverage_rate` | ratio | 负荷覆盖率 |
| `export_rate` | ratio | 余电比例 |

### 3.11 `validation_issue` — 校验问题

| 字段 | 类型 | 可空 | 键/约束 | 说明 |
|---|---|---|---|---|
| `issue_id` | TEXT | 否 | 主键 | UUID4 |
| `project_id` | TEXT | 是 | 外键 → `project`，`ON DELETE CASCADE` | 所属项目；无项目上下文的校验可为空 |
| `related_object_type` | TEXT | 是 | — | 关联对象类型，如 `bill_record` |
| `related_object_id` | TEXT | 是 | — | 关联对象主键 |
| `field_name` | TEXT | 否 | — | 问题字段 |
| `issue_code` | TEXT | 否 | — | 稳定问题代码 |
| `severity` | TEXT | 否 | `CHECK IN ('error','warning','info')`，默认 `error` | 严重程度 |
| `message` | TEXT | 否 | — | 面向用户的说明 |

索引：`idx_validation_issue_project` on `(project_id)`。

对应 Python 类：`ValidationIssueRecord`；
运行期对象为 `cenep.domain.validation.ValidationIssue`；枚举：`ValidationIssueSeverity`。

### 3.12 `report` — 报告

| 字段 | 类型 | 可空 | 键/约束 | 说明 |
|---|---|---|---|---|
| `report_id` | TEXT | 否 | 主键 | UUID4 |
| `project_id` | TEXT | 否 | 外键 → `project`，`ON DELETE RESTRICT` | 所属项目 |
| `scenario_id` | TEXT | 是 | 外键 → `scenario`，`ON DELETE SET NULL` | 关联方案 |
| `report_type` | TEXT | 否 | `CHECK IN ('feasibility','comparison','data_quality','other')`，默认 `other` | 报告类型 |
| `file_path` | TEXT | 是 | — | 生成的文件路径 |
| `generated_at` | TEXT | 是 | — | 生成时间 |
| `status` | TEXT | 否 | `CHECK IN ('pending','generated','failed')`，默认 `pending` | 生成状态 |

索引：`idx_report_project` on `(project_id)`。

对应 Python 类：`Report`；枚举：`ReportType`。

**第一阶段不实现报告生成**，本表仅冻结结构。

---

## 4. 枚举取值汇总

| 枚举 | 取值 | 对应列 |
|---|---|---|
| `ProjectType` | `industrial_commercial` / `utility_scale` / `other` | `project.project_type` |
| `DocumentType` | `electricity_bill` / `load_profile` / `tariff_document` / `other` | `document.document_type` |
| `ProcessingStatus` | `pending` / `parsed` / `failed` / `manual_review` | `document.processing_status` |
| `ValidationStatus` | `unvalidated` / `valid` / `invalid` / `warning` | `bill_record.validation_status` |
| `SourceType` | `meter_interval` / `bill_allocated` / `synthetic` / `manual` | `load_profile.source_type` |
| `TariffType` | `tou_industrial` / `flat` / `demand` / `market` / `other` | `tariff_model.tariff_type` |
| `EntityStatus` | `draft` / `active` / `archived` | `tariff_model.status` |
| `ValidationIssueSeverity` | `error` / `warning` / `info` | `validation_issue.severity` |
| `CalculationStatus` | `pending` / `running` / `succeeded` / `failed` | `calculation_run.status` |
| `ReportType` | `feasibility` / `comparison` / `data_quality` / `other` | `report.report_type` |
| 报告状态（字面量） | `pending` / `generated` / `failed` | `report.status` |
| 结果状态（字面量） | `ok` / `undefined` | `result_record.status` |

Python 侧所有枚举均继承 `str`，`.value` 即数据库存储值。

---

## 5. 第一阶段实现范围

| 表 | 建表 | CRUD | 说明 |
|---|---|---|---|
| `schema_meta` | 已实现 | 读写模式版本 | — |
| `project` | 已实现 | **完整 CRUD 已实现并测试** | `ProjectRepository` |
| 其余 10 张业务表 | 已实现 | 仅结构冻结 | 后续阶段按版本逐步开放 |

`project` 表的读接口（`ProjectRepository`）：

| 方法 | 说明 |
|---|---|
| `add(project)` | 新增；重复主键抛 `EntityAlreadyExistsError` |
| `update(project, touch_updated_at=True)` | 整体更新；不存在抛 `EntityNotFoundError` |
| `delete(project_id)` | 删除；存在关联数据抛 `PersistenceError`；不存在抛 `EntityNotFoundError` |
| `get(project_id)` | 返回 `Project` 或 `None` |
| `get_or_raise(project_id)` | 不存在抛 `EntityNotFoundError` |
| `list_all(order_by=...)` | 排序白名单：`"updated_at DESC"` / `"created_at DESC"` / `"name ASC"` |
| `find_by_name(name)` | 参数化精确查询 |
| `count()` | 项目总数 |

全部 SQL 使用 `?` 参数化占位符；排序子句仅接受白名单取值。

---

## 6. 数据完整性校验层次

| 层次 | 位置 | 负责内容 | 失败表现 |
|---|---|---|---|
| 领域校验 | `cenep.domain.validation` | 必填、长度、枚举取值、时间戳格式、电量序列合法性 | `ValidationError`（携带结构化问题清单） |
| 数据库约束 | 建表语句 | `NOT NULL`、`CHECK`、`UNIQUE`、`FOREIGN KEY` | 由 `translate_integrity_error()` 分类为 `EntityAlreadyExistsError` / `ValidationError` / `PersistenceError` |
| 数据模型文档 | 本文件 | 字段语义、单位、可信度等级 | 人工评审与代码审查 |

---

## 7. 模式变更流程

当前项目**尚无迁移框架**，`SCHEMA_VERSION = 1`。后续变更必须按以下顺序执行：

1. 修改 `src/cenep/domain/models.py` 中对应数据类。
2. 修改 `src/cenep/infrastructure/database.py` 的 `SCHEMA_STATEMENTS`。
3. 提升 `SCHEMA_VERSION`。
4. 编写并执行数据迁移方案，保证已有用户数据库不被破坏性重建。
5. 同步修改本文件对应章节。
6. 在 `tests/integration/test_database.py` 中补充覆盖新字段/新约束的测试。

禁止的做法：直接删除用户的 `.db` 文件重建、静默丢弃列、
在不提升版本号的情况下改变列语义。
