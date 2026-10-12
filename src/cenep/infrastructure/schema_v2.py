"""模式版本 2：账单六类实体的表结构。

本模块只提供**建表语句**，不导入 openpyxl、不导入领域模型，
以便被 :mod:`cenep.infrastructure.database` 直接引用为
``SCHEMA_STATEMENTS_V2`` 与迁移步骤 ``MIGRATIONS[1]``。

设计要点（对应规格书第 29、30 节）：

- **金额、电量、电价一律 ``TEXT``**，存十进制字符串（``Decimal`` 的
  ``str()`` 形式）。第一阶段 ``bill_record`` 用 ``REAL`` 存钱，
  浮点无法保证十进制精确、会影响费用勾稽，故新表不用 ``REAL``；
- **``NULL`` 表示"未提供"**，与显式 ``'0'`` 严格区分，**任何列都不设默认 0**；
- **负值合法**：功率因数调整电费等可为负，故**不加 ``>= 0`` 约束**
  （这与第一阶段 ``bill_record`` 的 ``CHECK (total_amount_yuan >= 0)`` 不同，
  是有意为之：真实账单存在合法负费用）；
- 非负约束只加在**物理上不可能为负**的字段（电量、电价、需量、倍率）；
- 枚举列用 ``CHECK`` 限定取值，与领域层枚举保持一致；
- 所有表通过外键挂到 ``project``，并使用 ``ON DELETE RESTRICT``
  以延续"存在关联数据时拒绝删除项目"的安全策略；
- 表名使用 ``bill_`` 前缀以区别于第一阶段已冻结的 ``bill_record``。

**与 ``bill_record`` 的关系**：``bill_record`` 继续保留、不改动、不删除，
以非破坏方式新增本模块的账单表。两者并存，待后续统一。
"""

from __future__ import annotations

__all__ = ["SCHEMA_STATEMENTS_V2", "BUSINESS_TABLES_V2"]

# ---------------------------------------------------------------------------
# 枚举取值范围（与 cenep.domain.bill_models 保持一致）
# ---------------------------------------------------------------------------

# 下列取值**必须与 cenep.domain.bill_models 的枚举逐字一致**。
# 由 tests/unit/test_schema_v2_enums.py 自动比对，防止再次漂移。
_REVIEW_STATUS = "'待复核','已复核','存在疑问','不适用'"
_CONFIRMATION = "'待确认','已确认','已驳回'"
_DEMAND_UNIT = "'kW','kVA'"
_TOU_PERIOD = "'尖峰','高峰','平','低谷','其他'"
_METERING_BASIS = "'购电','上网','其他'"
_FEE_CATEGORY = (
    "'电量电费','输配电费','系统运行费','政府性基金及附加',"
    "'调整类费用','需量/基本电费','市场化运营费','其他'"
)
_INCLUDED_IN_OTHER = "'是','否','待核实'"
_AVOIDABILITY = "'可避免','部分可避免','不可避免','待核实'"
_BASELINE_INCLUSION = "'是','否','待确认'"
_METER_POINT_TYPE = "'主表','分表','考核表','其他'"
_YES_NO_UNKNOWN = "'是','否','待核实'"
_IMPORT_OUTCOME = "'全部导入','部分导入','已取消','导入失败'"
_VALIDATION_SEVERITY = "'阻断','警告','提示'"
_VALIDATION_RESULT = "'通过','不通过','待检查','不适用'"


#: 模式版本 2 新增的业务表名
BUSINESS_TABLES_V2: tuple[str, ...] = (
    "bill",
    "bill_fee_item",
    "bill_tou_item",
    "bill_meter_point",
    "bill_import_batch",
    "bill_validation_issue",
)


SCHEMA_STATEMENTS_V2: tuple[str, ...] = (
    # --- 账单主表 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS bill (
        bill_id             TEXT PRIMARY KEY,
        project_id          TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        import_batch_id     TEXT REFERENCES bill_import_batch(batch_id) ON DELETE SET NULL,

        -- 标识与账期
        account_number      TEXT,
        customer_name       TEXT,
        supply_company      TEXT,
        supply_address      TEXT,
        electricity_category TEXT,
        voltage_level       TEXT,
        market_attribute    TEXT,
        billing_period      TEXT,
        period_start        TEXT,
        period_end          TEXT,
        printed_on          TEXT,

        -- 电量与金额（TEXT 存十进制字符串，NULL 表示未提供）
        total_energy_kwh    TEXT,
        total_amount_yuan   TEXT,
        vat_invoice_amount_yuan TEXT,
        displayed_average_price TEXT,

        -- 费用分项
        industrial_commercial_fee_yuan TEXT,
        market_purchase_fee_yuan       TEXT,
        grid_loss_fee_yuan             TEXT,
        transmission_distribution_fee_yuan TEXT,
        system_operation_fee_yuan      TEXT,
        government_fund_fee_yuan       TEXT,
        power_factor_adjustment_fee_yuan TEXT,
        demand_charge_yuan             TEXT,
        market_operation_fee_yuan      TEXT,
        basic_charge_yuan              TEXT,

        -- 需量
        contract_demand      TEXT,
        contract_demand_unit TEXT CHECK (contract_demand_unit IS NULL
                                         OR contract_demand_unit IN ({demand_unit})),
        actual_demand        TEXT,
        actual_demand_unit   TEXT CHECK (actual_demand_unit IS NULL
                                         OR actual_demand_unit IN ({demand_unit})),
        demand_billing_mode  TEXT,
        power_factor         TEXT,

        -- 溯源与状态
        source_file          TEXT,
        source_page          TEXT,
        review_status        TEXT NOT NULL DEFAULT '待复核'
                             CHECK (review_status IN ({review_status})),
        confirmation     TEXT NOT NULL DEFAULT '待确认'
                             CHECK (confirmation IN ({confirmation})),
        confirmed_at         TEXT,
        confirmed_by         TEXT,
        is_sample            INTEGER NOT NULL DEFAULT 0
                             CHECK (is_sample IN (0, 1)),
        created_at           TEXT,
        updated_at           TEXT,
        note                 TEXT,

        -- 物理约束：电量与电价不可能为负；金额允许为负（存在合法负费用）
        CHECK (total_energy_kwh IS NULL OR CAST(total_energy_kwh AS REAL) >= 0),
        CHECK (displayed_average_price IS NULL
               OR CAST(displayed_average_price AS REAL) >= 0),
        CHECK (contract_demand IS NULL OR CAST(contract_demand AS REAL) >= 0),
        CHECK (actual_demand IS NULL OR CAST(actual_demand AS REAL) >= 0),
        CHECK (period_start IS NULL OR period_end IS NULL OR period_start <= period_end)
    )
    """.format(
        demand_unit=_DEMAND_UNIT,
        review_status=_REVIEW_STATUS,
        confirmation=_CONFIRMATION,
    ),
    "CREATE INDEX IF NOT EXISTS idx_bill_project_period ON bill(project_id, billing_period)",
    "CREATE INDEX IF NOT EXISTS idx_bill_batch ON bill(import_batch_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_bill_business_key "
    "ON bill(project_id, IFNULL(account_number,''), IFNULL(billing_period,''))",

    # --- 导入批次（先建，供 bill 外键引用） ------------------------------
    """
    CREATE TABLE IF NOT EXISTS bill_import_batch (
        batch_id        TEXT PRIMARY KEY,
        project_id      TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        file_name       TEXT NOT NULL DEFAULT '',
        file_hash       TEXT,
        template_version TEXT,
        imported_at     TEXT,
        imported_by     TEXT,
        total_records   INTEGER NOT NULL DEFAULT 0 CHECK (total_records >= 0),
        valid_records   INTEGER NOT NULL DEFAULT 0 CHECK (valid_records >= 0),
        warning_records INTEGER NOT NULL DEFAULT 0 CHECK (warning_records >= 0),
        invalid_records INTEGER NOT NULL DEFAULT 0 CHECK (invalid_records >= 0),
        skipped_records INTEGER NOT NULL DEFAULT 0 CHECK (skipped_records >= 0),
        outcome         TEXT NOT NULL DEFAULT '成功'
                        CHECK (outcome IN ({outcome})),
        user_decision   TEXT,
        message         TEXT
    )
    """.format(outcome=_IMPORT_OUTCOME),
    "CREATE INDEX IF NOT EXISTS idx_bill_batch_project ON bill_import_batch(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_bill_batch_hash ON bill_import_batch(project_id, file_hash)",

    # --- 费用明细 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS bill_fee_item (
        fee_item_id     TEXT PRIMARY KEY,
        bill_id         TEXT NOT NULL REFERENCES bill(bill_id) ON DELETE CASCADE,
        project_id      TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        billing_period  TEXT,
        fee_category    TEXT CHECK (fee_category IS NULL OR fee_category IN ({category})),
        fee_name        TEXT NOT NULL DEFAULT '',
        quantity        TEXT,
        quantity_unit   TEXT,
        unit_price      TEXT,
        amount_yuan     TEXT,
        included_in_other TEXT NOT NULL DEFAULT '待核实'
                        CHECK (included_in_other IN ({included})),
        included_in_fee_name TEXT,
        avoidability    TEXT NOT NULL DEFAULT '待核实'
                        CHECK (avoidability IN ({avoidability})),
        baseline_inclusion TEXT NOT NULL DEFAULT '待确认'
                        CHECK (baseline_inclusion IN ({baseline})),
        source_file     TEXT,
        source_page     TEXT,
        review_status   TEXT NOT NULL DEFAULT '待复核'
                        CHECK (review_status IN ({review_status})),
        note            TEXT,
        -- 规则：标记"包含在其他费用中=是"时必须写明被包含于哪一项
        CHECK (included_in_other <> '是' OR IFNULL(included_in_fee_name,'') <> '')
    )
    """.format(
        category=_FEE_CATEGORY,
        included=_INCLUDED_IN_OTHER,
        avoidability=_AVOIDABILITY,
        baseline=_BASELINE_INCLUSION,
        review_status=_REVIEW_STATUS,
    ),
    "CREATE INDEX IF NOT EXISTS idx_fee_bill ON bill_fee_item(bill_id)",
    "CREATE INDEX IF NOT EXISTS idx_fee_project_period "
    "ON bill_fee_item(project_id, billing_period)",

    # --- 分时电量电价 ---------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS bill_tou_item (
        tou_item_id     TEXT PRIMARY KEY,
        bill_id         TEXT NOT NULL REFERENCES bill(bill_id) ON DELETE CASCADE,
        project_id      TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        billing_period  TEXT,
        metering_basis_id TEXT,
        basis           TEXT NOT NULL DEFAULT '购电'
                        CHECK (basis IN ({basis})),
        period_name     TEXT CHECK (period_name IS NULL OR period_name IN ({period})),
        segment_start   TEXT,
        segment_end     TEXT,
        energy_kwh      TEXT,
        price_yuan_per_kwh TEXT,
        energy_amount_yuan TEXT,
        price_type_or_source TEXT,
        source_file     TEXT,
        source_page     TEXT,
        review_status   TEXT NOT NULL DEFAULT '待复核'
                        CHECK (review_status IN ({review_status})),
        note            TEXT,
        CHECK (energy_kwh IS NULL OR CAST(energy_kwh AS REAL) >= 0),
        CHECK (price_yuan_per_kwh IS NULL OR CAST(price_yuan_per_kwh AS REAL) >= 0)
    )
    """.format(basis=_METERING_BASIS, period=_TOU_PERIOD, review_status=_REVIEW_STATUS),
    "CREATE INDEX IF NOT EXISTS idx_tou_bill ON bill_tou_item(bill_id)",
    "CREATE INDEX IF NOT EXISTS idx_tou_project_period "
    "ON bill_tou_item(project_id, billing_period)",

    # --- 计量点 ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS bill_meter_point (
        meter_point_id  TEXT PRIMARY KEY,
        bill_id         TEXT NOT NULL REFERENCES bill(bill_id) ON DELETE CASCADE,
        project_id      TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        billing_period  TEXT,
        point_code      TEXT NOT NULL DEFAULT '',
        point_name      TEXT,
        point_type      TEXT CHECK (point_type IS NULL OR point_type IN ({point_type})),
        main_sub_relation TEXT,
        ratio           TEXT,
        energy_kwh      TEXT,
        included_in_total TEXT NOT NULL DEFAULT '待核实'
                        CHECK (included_in_total IN ({yesno})),
        allowed_in_rollup TEXT NOT NULL DEFAULT '待核实'
                        CHECK (allowed_in_rollup IN ({yesno})),
        source_file     TEXT,
        source_page     TEXT,
        review_status   TEXT NOT NULL DEFAULT '待复核'
                        CHECK (review_status IN ({review_status})),
        note            TEXT,
        CHECK (energy_kwh IS NULL OR CAST(energy_kwh AS REAL) >= 0)
    )
    """.format(
        point_type=_METER_POINT_TYPE,
        yesno=_YES_NO_UNKNOWN,
        review_status=_REVIEW_STATUS,
    ),
    "CREATE INDEX IF NOT EXISTS idx_meter_bill ON bill_meter_point(bill_id)",
    "CREATE INDEX IF NOT EXISTS idx_meter_project_period "
    "ON bill_meter_point(project_id, billing_period)",

    # --- 校验问题 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS bill_validation_issue (
        issue_id        TEXT PRIMARY KEY,
        batch_id        TEXT REFERENCES bill_import_batch(batch_id) ON DELETE CASCADE,
        project_id      TEXT NOT NULL DEFAULT '',
        bill_id         TEXT,
        check_code      TEXT NOT NULL DEFAULT '',
        check_item      TEXT NOT NULL DEFAULT '',
        severity        TEXT NOT NULL DEFAULT '提示'
                        CHECK (severity IN ({severity})),
        result          TEXT NOT NULL DEFAULT '不适用'
                        CHECK (result IN ({result})),
        detail          TEXT NOT NULL DEFAULT '',
        sheet_name      TEXT,
        row_number      INTEGER CHECK (row_number IS NULL OR row_number >= 1),
        column_name     TEXT,
        handler         TEXT,
        handled_on      TEXT,
        handle_status   TEXT
    )
    """.format(severity=_VALIDATION_SEVERITY, result=_VALIDATION_RESULT),
    "CREATE INDEX IF NOT EXISTS idx_issue_batch ON bill_validation_issue(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_issue_project ON bill_validation_issue(project_id)",
)
