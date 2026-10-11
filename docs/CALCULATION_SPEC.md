# CENEP 计算规则说明书（CALCULATION_SPEC）

- 文档版本：`2026.02-stage1`
- 计算引擎版本：`CALCULATION_VERSION = "0.1.0"`（见 `src/cenep/calculations/self_consumption.py`）
- 假设版本：`ASSUMPTIONS_VERSION = "2026.02-stage1"`（见 `src/cenep/domain/models.py`）
- 对应代码：`src/cenep/calculations/self_consumption.py`、`src/cenep/domain/validation.py`

> **注意三个版本常量的分工，不要混淆：**
>
> | 常量 | 定义位置 | 值 | 用途 |
> |---|---|---|---|
> | `CALCULATION_VERSION` | `calculations/self_consumption.py` | `0.1.0` | 消纳计算规则版本，写入 `SelfConsumptionResult.calculation_version`；公式变化时必须提升 |
> | `CALCULATION_ENGINE_VERSION` | `domain/models.py` | `0.1.0` | 计算运行记录的默认版本，写入 `CalculationRun.calculation_version` |
> | `ASSUMPTIONS_VERSION` | `domain/models.py` | `2026.02-stage1` | 假设口径版本，写入 `PVModel.assumptions_version` |
>
> `CALCULATION_VERSION` 与 `CALCULATION_ENGINE_VERSION` 是两个不同的常量，
> 当前取值恰好相同。

本文件是计算口径的唯一权威说明。**代码与此文件必须保持一致**；任何公式、分母含义、
单位或边界处理的变化，都必须同时提升 `CALCULATION_VERSION` 并修订本文件。

---

## 1. 本阶段范围

本阶段（第一阶段）**只实现**光伏消纳计算，即逐时段的"自发自用 / 余电上网 / 电网购电"
电量拆分与三个比例指标。

本阶段**不实现**：光伏发电量模拟、分时电价与收益测算、初始投资与运维费用、
现金流与折现、净现值 / 内部收益率 / 投资回收期、税务模型、储能充放电、
电力交易优化。这些内容在后续版本实现前，不得以估算公式替代。

---

## 2. 输入定义

计算函数签名：

```python
calculate_self_consumption(
    load: Sequence[float],
    pv: Sequence[float],
    *,
    interval_minutes: int | None = None,
) -> SelfConsumptionResult
```

| 参数 | 类型 | 单位 | 含义 | 可空 |
|---|---|---|---|---|
| `load` | 非负数值序列 | kWh | 每个**时段**的用电量 | 否（可为空数组） |
| `pv` | 非负数值序列 | kWh | 与 `load` 相同时间粒度的光伏**时段发电量** | 否（可为空数组） |
| `interval_minutes` | 正整数或 `None` | 分钟 | 调用方声明的时段长度；程序**不推断也不换算**粒度 | 是 |

### 2.1 单位与粒度的一致性前提

1. `load` 与 `pv` 必须**长度一致**，即同一时段序号一一对应。
2. 两个序列必须具有**相同的时间粒度**（例如同为 15 分钟、同为 1 小时）。
3. 两个序列必须具有**相同的计量边界**（同一并网点、同一计量口径）。
4. `interval_minutes` 是**声明值**，函数不会用它做任何换算。若两个序列粒度不同，
   必须由调用方先归一到同一粒度后再调用，程序不做隐式重采样。
5. 输入必须是**时段电量（kWh）**，不是瞬时功率（kW）。
   两者关系为 `energy_kwh = power_kw × interval_minutes / 60`。
   把功率数值直接当作电量传入属于数据错误，程序无法自动识别，必须在数据导入阶段拦截。

### 2.2 输入合法性规则（`src/cenep/domain/validation.py`）

| 序号 | 规则 | 违反时的行为 | 问题代码 |
|---|---|---|---|
| 1 | `load`、`pv` 必须是数值序列（`list` / `tuple` / `Sequence`） | 校验失败 | `not_a_sequence` |
| 2 | 两者长度必须一致 | 校验失败 | `length_mismatch` |
| 3 | 元素必须是 `int` / `float`，不接受 `bool`、字符串、`None` | 校验失败 | `not_a_number` |
| 4 | 不允许 `NaN` | 校验失败 | `nan_value` |
| 5 | 不允许 `inf` / `-inf` | 校验失败 | `infinite_value` |
| 6 | 不允许负数 | 校验失败 | `negative_value` |
| 7 | `interval_minutes` 若给出，必须为正整数（`bool` 不算） | 校验失败 | `interval_minutes_invalid` |
| 8 | 空数组 | **合法**，见 4.2 节 | — |

**校验失败必须抛出 `ValidationError`，异常对象携带全部问题的结构化清单；
程序不得静默修正原始数据**——不截断、不补齐、不取绝对值、不把 `NaN` 当 0。
`ValidationError.issues` 中每条问题都包含 `issue_code`、`field_name`、`message`、`severity`、`value`。

校验与计算使用同一套规则实现（`require_valid_energy_series` 内部调用
`check_energy_series`），因此不存在"校验通过但计算报错"的不一致。

---

## 3. 逐时段计算公式

对每个时段 `t`：

```python
self_consumption_t = min(load_t, pv_t)      # 光伏自用电量
export_t           = max(pv_t - load_t, 0)  # 余电上网电量
grid_import_t      = max(load_t - pv_t, 0)  # 电网购电电量
```

物理含义：光伏出力优先满足同时段负荷，不足部分由电网补充，盈余部分上网。

---

## 4. 汇总与指标

### 4.1 电量汇总

```python
total_load            = sum(load)
total_pv              = sum(pv)
total_self_consumption = sum(self_consumption_t)
total_export          = sum(export_t)
total_grid_import     = sum(grid_import_t)
```

实现使用 `math.fsum` 对 `load` / `pv` 求和以提高浮点精度；
三个分项按累加求和。

| 输出字段 | 单位 | 含义 |
|---|---|---|
| `total_load_kwh` | kWh | 时段用电量合计 |
| `total_pv_kwh` | kWh | 时段光伏发电量合计 |
| `total_self_consumption_kwh` | kWh | 光伏自用电量合计 |
| `total_export_kwh` | kWh | 余电上网电量合计 |
| `total_grid_import_kwh` | kWh | 电网购电量合计 |

### 4.2 比例指标与零分母处理

```python
self_consumption_rate = total_self_consumption / total_pv   if total_pv  > 0 else None
load_coverage_rate    = total_self_consumption / total_load if total_load > 0 else None
export_rate           = total_export / total_pv             if total_pv  > 0 else None
```

| 指标 | 定义 | 取值范围 | 零分母条件 | 零分母结果 |
|---|---|---|---|---|
| `self_consumption_rate` | 自用电量 / 光伏发电量 | `[0, 1]` | `total_pv == 0` | `None` |
| `load_coverage_rate` | 自用电量 / 用电量 | `[0, 1]` | `total_load == 0` | `None` |
| `export_rate` | 余电上网电量 / 光伏发电量 | `[0, 1]` | `total_pv == 0` | `None` |

**关键规则：**

1. 比例在内部一律使用 `0 ~ 1` 的比值表示，**只有界面展示时才转换为百分比**。
2. 零分母时返回 `None`（JSON `null`），**绝不返回 0**。
   返回 0 会让"未定义"与"真实为零"无法区分，是禁止的实现方式。
3. `load_coverage_rate` 的分子是自用电量、分母是用电量。由于
   `self_consumption_t = min(load_t, pv_t) ≤ load_t`，逐时段求和后必有
   `total_self_consumption ≤ total_load`，故该指标**不会超过 1**。
4. 三个指标中只要有一个为 `None`，`status` 即为 `undefined_ratio`；否则为 `ok`。

### 4.3 空数组与全零输入

空数组 `load == pv == []` 是**合法输入**（例如接口先建结构后填数据），行为：

- 五个电量指标全部为 `0.0`；
- 三个比例指标全部为 `None`；
- `status == "undefined_ratio"`；
- `periods == 0`；
- 附带 `empty_series` 提示（`severity = warning`）。

`load` 与 `pv` 全部为零但长度非零时行为相同（提示代码为 `all_zero_energy`）。

---

## 5. 返回值结构

`SelfConsumptionResult` 是冻结的 `dataclass`，字段如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `total_load_kwh` | `float` | 见 4.1 |
| `total_pv_kwh` | `float` | 见 4.1 |
| `total_self_consumption_kwh` | `float` | 见 4.1 |
| `total_export_kwh` | `float` | 见 4.1 |
| `total_grid_import_kwh` | `float` | 见 4.1 |
| `self_consumption_rate` | `float \| None` | 见 4.2 |
| `load_coverage_rate` | `float \| None` | 见 4.2 |
| `export_rate` | `float \| None` | 见 4.2 |
| `status` | `str` | `ok` 或 `undefined_ratio` |
| `interval_minutes` | `int \| None` | 回显调用方声明的时间粒度 |
| `energy_unit` | `str` | 固定 `"kWh"` |
| `periods` | `int` | 时段数 |
| `calculation_version` | `str` | 计算规则版本，用于追溯 |
| `input_fingerprint` | `str` | 输入数据的 SHA-256 指纹（前 16 位） |
| `notes` | `tuple[ValidationIssue, ...]` | 业务提示，不影响数值 |

返回值是**结构化数据对象**，不是格式化文本。文本渲染只发生在界面层
（`src/cenep/ui/main_window.py::_format_result`）与命令行层（`src/cenep/cli.py`）。

结果同时支持：

- `to_dict()`：转为可 JSON 序列化的字典，`None` 保持为 `None`；
- `to_metric_rows()`：转为 `ResultRecord` 形态的指标行，
  未定义的比例指标其 `status` 记为 `undefined`、`value` 为 `None`；
- `check_energy_balance()`：自检 6.1 节两条守恒关系，不满足即抛 `AssertionError`。

---

## 6. 必须成立的守恒关系与精度处理

### 6.1 守恒关系

```python
total_pv   == total_self_consumption + total_export
total_load == total_self_consumption + total_grid_import
```

### 6.2 浮点精度处理

- 生产代码在计算完成后**内部自检**守恒关系，容差为
  `ENERGY_TOLERANCE_KWH = 1e-9` kWh；超出容差说明实现缺陷，直接抛错。
- 测试中使用 `pytest.approx` 做近似比较，不使用 `==` 直接比较浮点数。
- 容差仅用于浮点误差校验，**不允许**用来掩盖真实的数据或口径错误。

---

## 7. 标准验收案例

输入：

```python
load = [3, 8, 2]
pv   = [5, 4, 2]
```

逐时段：

| 时段 | load | pv | 自用 | 上网 | 购电 |
|---|---:|---:|---:|---:|---:|
| 1 | 3 | 5 | 3 | 2 | 0 |
| 2 | 8 | 4 | 4 | 0 | 4 |
| 3 | 2 | 2 | 2 | 0 | 0 |
| 合计 | 13 | 11 | 9 | 2 | 4 |

预期结果：

| 指标 | 预期值 |
|---|---:|
| 总负荷 | 13 kWh |
| 总发电 | 11 kWh |
| 自用电量 | 9 kWh |
| 余电上网 | 2 kWh |
| 电网购电 | 4 kWh |
| 自用率 | 9 / 11 ≈ 0.818182 |
| 负荷覆盖率 | 9 / 13 ≈ 0.692308 |
| 余电比例 | 2 / 11 ≈ 0.181818 |
| status | `ok` |

该案例由 `tests/unit/test_self_consumption.py::test_acceptance_case_all_metrics` 逐项断言。

---

## 8. 必须覆盖的边界情况

| 场景 | 期望行为 |
|---|---|
| 负荷与光伏全为零 | 电量全 0，三个比例均为 `None`，`status = undefined_ratio` |
| 只有负荷、没有光伏 | 自用 0、上网 0、购电 = 总负荷；`self_consumption_rate = None`、`export_rate = None`、`load_coverage_rate = 0.0` |
| 只有光伏、没有负荷 | 自用 0、购电 0、上网 = 总发电；`load_coverage_rate = None`、`self_consumption_rate = 0.0`、`export_rate = 1.0` |
| 光伏与负荷完全相等 | 自用率 = 负荷覆盖率 = 1.0，上网 = 购电 = 0 |
| 光伏始终小于负荷 | 上网 = 0，`export_rate = 0.0`，自用率 = 1.0 |
| 光伏始终大于负荷 | 购电 = 0，`load_coverage_rate = 1.0`，自用率 + 余电比例 = 1 |
| 空数组 | 见 4.3 节 |
| 长度不一致 | 抛 `ValidationError`（`length_mismatch`） |
| 负数 | 抛 `ValidationError`（`negative_value`） |
| `NaN` | 抛 `ValidationError`（`nan_value`） |
| `inf` / `-inf` | 抛 `ValidationError`（`infinite_value`） |
| 非数值输入 | 抛 `ValidationError`（`not_a_number` / `not_a_sequence`） |
| 能量守恒 | 两条等式在容差内成立 |

---

## 9. 非抛异常调用入口

界面层需要"逐条提示"而不是异常时，使用：

```python
calculate_self_consumption_with_issues(load, pv, interval_minutes=None)
    -> tuple[SelfConsumptionResult | None, ValidationIssue | None, tuple[ValidationIssue, ...]]
```

该函数内部**调用同一个** `calculate_self_consumption`，只改变错误呈现方式，
不复制公式、不改变判定结果。

---

## 10. 电量、电价与经济收益的规则边界（本阶段仅冻结规则）

以下 10 条为项目级计算口径纪律。第一条至第六条在当前版本**尚未实现对应计算**，
此处先行冻结，用以约束后续版本的实现方式。

1. **月度电量不等于逐时负荷曲线。** 月度账单的用电量是整月累计值，
   不包含时段分布信息，不能当作逐时曲线使用。
2. **月度估算与逐时消纳必须区分。** 二者是不同精度的数据产品，
   结果必须标注数据来源与精度等级，不得混用同一指标名称。
3. **逐时消纳计算的输入前提。** 负荷与光伏发电数据必须在相同时间粒度、
   相同计量边界下一一对应（见 2.1 节）。
4. **不能仅凭年度总用电量与年度总发电量得出可靠自用率。**
   年度总量抹掉了时序匹配关系，由此得到的自用率只能作为粗略上下界参考，
   且必须在结果中标注为估算值。
5. **光伏自用电量的收益按可避免的购电边际成本测算。**
   自用每 kWh 的价值等于该时段原本需要从电网购电的边际电费，
   而不是平均电价，也不是上网电价。
6. **基本电费、需量电费、功率因数调整及其他固定或惩罚性费用，
   不得默认按用电量同比减少。** 光伏只能减少电量电费中的对应部分；
   容量/需量类费用是否变化取决于实际需量曲线与合同约定，需单独判断。
7. **峰谷电价必须考虑时段对应关系。** 必须把光伏出力时段与电价时段对齐后
   逐段计算，禁止用简单年平均电价替代所有时段场景。
8. **电价数据必须具备地区、生效日期、适用用户类型和来源信息。**
   缺少任一要素的电价数据只能作为草稿，不得用于正式测算
   （对应 `TariffModel` 的 `region`、`effective_from`/`effective_to`、
   `tariff_type`、`source_reference`、`status` 字段）。
9. **未经正式来源核实的湖北电价数据，不得标记为已核实正式电价。**
   `source_reference` 为空的数据其 `status` 不得为 `active`。
   本项目当前**不包含**任何已核实的全国电价数据。
10. **缺失数据、估算数据和正式数据必须区分。** 分别对应
    `ValidationStatus` 的 `unvalidated` / `warning` / `valid`
    与 `LoadProfile.source_type` 的 `meter_interval` / `bill_allocated` /
    `synthetic` / `manual`。缺失值以 `None` 表达，禁止填 0 或填估算值冒充实测值。

---

## 11. 变更管理

任何涉及本文件的改动必须同时完成：

1. 修改 `src/cenep/calculations/self_consumption.py`（或相应计算模块）；
2. 提升该模块的 `CALCULATION_VERSION`；
3. 若涉及口径假设变化，提升 `ASSUMPTIONS_VERSION`；
4. 修订本文件对应章节；
5. 在 `tests/` 中补充或更新测试，并实际运行 `python -m pytest -q`；
6. 说明本次变化对历史计算结果解释的影响——历史结果按当时的
   `calculation_version` 解释，不得用新口径重新解释旧结果。
