"""模式 v2 的枚举约束必须与领域枚举逐字一致。

**为什么需要这个测试**：建库语句里的 ``CHECK (... IN (...))`` 是手写的字符串，
很容易与 ``cenep.domain.bill_models`` 的枚举取值漂移。实测中确实发生过：

- ``ImportOutcome`` 领域值是 ``全部导入/部分导入/已取消/导入失败``，
  而初稿 DDL 写的是 ``成功/部分导入/已取消/失败``；
- ``MeteringBasis`` 领域值是 ``购电/上网/其他``，DDL 写的是 ``购电/上网/发电``；
- ``TimeOfUsePeriod`` 领域值是 ``尖峰/高峰/平/低谷/其他``，
  DDL 写的是 ``尖/峰/平/谷/深谷/其它``。

这类漂移会导致**写入被数据库拒绝**（运行时才暴露）。本测试在建库阶段就拦住它。
"""

from __future__ import annotations

import re
import sqlite3

import pytest

import cenep.domain.bill_models as models
from cenep.infrastructure.schema_v2 import SCHEMA_STATEMENTS_V2
import cenep.infrastructure.schema_v2 as schema_v2


def _ddl() -> str:
    return "\n".join(SCHEMA_STATEMENTS_V2)


def _quoted_values(raw: str) -> set[str]:
    """把 ``'a','b','c'`` 形式的常量解析为集合。"""
    return set(re.findall(r"'([^']*)'", raw))


#: DDL 常量名 → 领域枚举类
ENUM_BINDINGS: tuple[tuple[str, str], ...] = (
    ("_REVIEW_STATUS", "ReviewStatus"),
    ("_CONFIRMATION", "BillConfirmationState"),
    ("_TOU_PERIOD", "TimeOfUsePeriod"),
    ("_METERING_BASIS", "MeteringBasis"),
    ("_FEE_CATEGORY", "FeeCategory"),
    ("_INCLUDED_IN_OTHER", "IncludedInOtherFee"),
    ("_AVOIDABILITY", "Avoidability"),
    ("_BASELINE_INCLUSION", "BaselineInclusion"),
    ("_METER_POINT_TYPE", "MeterPointType"),
    ("_YES_NO_UNKNOWN", "YesNoUnknown"),
    ("_IMPORT_OUTCOME", "ImportOutcome"),
    ("_VALIDATION_SEVERITY", "ValidationSeverityLevel"),
    ("_VALIDATION_RESULT", "ValidationResultState"),
)


class TestSchemaEnumsMatchDomain:
    @pytest.mark.parametrize("constant, enum_name", ENUM_BINDINGS)
    def test_ddl_constant_matches_domain_enum(self, constant: str, enum_name: str) -> None:
        enum_cls = getattr(models, enum_name)
        expected = {member.value for member in enum_cls}
        actual = _quoted_values(getattr(schema_v2, constant))
        assert actual == expected, (
            f"{constant} 与 {enum_name} 不一致：\n"
            f"  DDL 多出：{sorted(actual - expected)}\n"
            f"  DDL 缺少：{sorted(expected - actual)}"
        )

    def test_demand_unit_matches_domain(self) -> None:
        """需量单位在领域层是字面量校验，模板规范里是枚举，两者必须一致。"""
        from cenep.data.bill_template_spec import DemandUnit

        expected = {member.value for member in DemandUnit}
        actual = _quoted_values(schema_v2._DEMAND_UNIT)
        assert actual == expected
        # 领域层的校验也必须是同一组取值
        assert expected == {"kW", "kVA"}

    @pytest.mark.parametrize("constant, enum_name", ENUM_BINDINGS)
    def test_constant_is_used_in_ddl(self, constant: str, enum_name: str) -> None:
        """常量必须真的被拼进建表语句，而不是定义了却没用。"""
        ddl = _ddl()
        for value in _quoted_values(getattr(schema_v2, constant)):
            assert f"'{value}'" in ddl, f"{constant} 的取值 {value!r} 未出现在建表语句中"


class TestEnumConstraintsAreEnforced:
    """枚举约束必须真的生效（用内存库实测，不只看字符串）。"""

    @pytest.fixture
    def conn(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        # 建一个最小的 project 表以满足外键
        connection.execute(
            "CREATE TABLE project (project_id TEXT PRIMARY KEY)"
        )
        for statement in SCHEMA_STATEMENTS_V2:
            connection.execute(statement)
        connection.execute("INSERT INTO project(project_id) VALUES('p1')")
        yield connection
        connection.close()

    def test_valid_import_outcome_is_accepted(self, conn) -> None:
        for outcome in (member.value for member in models.ImportOutcome):
            conn.execute(
                "INSERT INTO bill_import_batch(batch_id, project_id, outcome) VALUES(?,?,?)",
                (f"b-{outcome}", "p1", outcome),
            )

    def test_invalid_import_outcome_is_rejected(self, conn) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bill_import_batch(batch_id, project_id, outcome) VALUES('b','p1','成功')"
            )

    def test_valid_review_status_is_accepted(self, conn) -> None:
        """所有复核状态都必须被接受。

        注意：业务键唯一索引是 ``(项目, 户号, 账期)``，
        因此每条要**用不同账期**才能同时存在。
        """
        for index, status in enumerate(models.ReviewStatus):
            conn.execute(
                "INSERT INTO bill(bill_id, project_id, review_status, billing_period) "
                "VALUES(?,?,?,?)",
                (f"bill-{index}", "p1", status.value, f"2025-{index + 1:02d}"),
            )
        stored = {
            row[0] for row in conn.execute("SELECT review_status FROM bill")
        }
        assert stored == {member.value for member in models.ReviewStatus}

    def test_invalid_review_status_is_rejected(self, conn) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bill(bill_id, project_id, review_status) VALUES('b','p1','随便')"
            )

    def test_valid_metering_basis_is_accepted(self, conn) -> None:
        conn.execute("INSERT INTO bill(bill_id, project_id) VALUES('bl','p1')")
        for basis in (member.value for member in models.MeteringBasis):
            conn.execute(
                "INSERT INTO bill_tou_item(tou_item_id, bill_id, project_id, basis) "
                "VALUES(?,?,?,?)",
                (f"t-{basis}", "bl", "p1", basis),
            )

    def test_valid_fee_category_is_accepted(self, conn) -> None:
        conn.execute("INSERT INTO bill(bill_id, project_id) VALUES('bl','p1')")
        for index, category in enumerate(models.FeeCategory):
            conn.execute(
                "INSERT INTO bill_fee_item(fee_item_id, bill_id, project_id, fee_category) "
                "VALUES(?,?,?,?)",
                (f"f-{index}", "bl", "p1", category.value),
            )

    def test_valid_meter_point_type_is_accepted(self, conn) -> None:
        conn.execute("INSERT INTO bill(bill_id, project_id) VALUES('bl','p1')")
        for index, point_type in enumerate(models.MeterPointType):
            conn.execute(
                "INSERT INTO bill_meter_point(meter_point_id, bill_id, project_id, "
                "point_code, point_type) VALUES(?,?,?,?,?)",
                (f"m-{index}", "bl", "p1", "M1", point_type.value),
            )

    def test_valid_validation_severity_and_result(self, conn) -> None:
        for index, severity in enumerate(models.ValidationSeverityLevel):
            for jndex, result in enumerate(models.ValidationResultState):
                conn.execute(
                    "INSERT INTO bill_validation_issue(issue_id, severity, result) "
                    "VALUES(?,?,?)",
                    (f"i-{index}-{jndex}", severity.value, result.value),
                )
