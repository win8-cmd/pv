"""业务异常定义。

设计原则：

1. 所有业务异常继承 :class:`CENEPError`，便于应用服务层统一捕获。
2. 输入校验失败必须给出**结构化**的问题清单，而不是一句拼接文本，
   这样界面层可以逐条展示，测试层可以按 ``code`` 精确断言。
3. 基础设施异常（如 sqlite3.Error）在基础设施层被包装为
   :class:`PersistenceError`，避免上层直接依赖 sqlite3。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，避免运行期循环导入
    from cenep.domain.validation import ValidationIssue


class CENEPError(Exception):
    """CENEP 全部业务异常的基类。"""

    #: 机器可读的错误代码，便于界面层与测试层判断
    code: str = "cenep_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def __str__(self) -> str:  # pragma: no cover - 简单委托
        return self.message


class ValidationError(CENEPError):
    """输入数据未通过校验规则。

    与"数据类型写错"这类编程错误不同，本异常表示**用户数据**不合法，
    属于可预期、可向用户展示的失败。

    Attributes:
        issues: 结构化校验问题清单，至少含一条。
    """

    code = "validation_error"

    def __init__(
        self,
        message: str,
        issues: Sequence["ValidationIssue"] = (),
    ) -> None:
        super().__init__(message)
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)

    def issue_codes(self) -> tuple[str, ...]:
        """返回全部问题的 ``issue_code``，便于测试断言。"""
        return tuple(issue.issue_code for issue in self.issues)

    def format_issues(self) -> str:
        """把问题清单渲染为多行文本，供界面或命令行展示。"""
        if not self.issues:
            return self.message
        lines = [self.message]
        for issue in self.issues:
            severity = getattr(issue.severity, "value", issue.severity)
            lines.append(f"  - [{severity}] {issue.field_name}: {issue.message}")
        return "\n".join(lines)


class EntityNotFoundError(CENEPError):
    """按主键查询的实体不存在。"""

    code = "entity_not_found"

    def __init__(self, entity: str, entity_id: str) -> None:
        super().__init__(f"{entity} 不存在：{entity_id}")
        self.entity = entity
        self.entity_id = entity_id


class EntityAlreadyExistsError(CENEPError):
    """写入的实体主键已存在（重复主键）。"""

    code = "entity_already_exists"

    def __init__(self, entity: str, entity_id: str) -> None:
        super().__init__(f"{entity} 已存在，主键重复：{entity_id}")
        self.entity = entity
        self.entity_id = entity_id


class PersistenceError(CENEPError):
    """持久化操作失败（连接、事务、SQL 执行等）。

    基础设施层负责把底层驱动异常（如 ``sqlite3.Error``）包装成本异常，
    并在 ``__cause__`` 中保留原始异常。
    """

    code = "persistence_error"

    def __init__(self, message: str, *, operation: str | None = None) -> None:
        super().__init__(message)
        self.operation = operation


class SchemaVersionError(PersistenceError):
    """数据库模式版本与本程序不兼容。

    典型场景：数据库由**更新版本**的 CENEP 创建，当前程序无法安全读写它。
    此时必须拒绝初始化，而不是把版本号改写成旧值——后者会造成静默降级，
    使新版本写入的数据被旧程序误读甚至破坏。
    """

    code = "schema_version_incompatible"

    def __init__(
        self,
        message: str,
        *,
        found_version: int | None = None,
        supported_version: int | None = None,
    ) -> None:
        super().__init__(message, operation="initialize_schema")
        self.found_version = found_version
        self.supported_version = supported_version


class UnsupportedOperationError(CENEPError):
    """调用了本阶段尚未实现的能力。

    用于明确区分"还没做"和"做完了"。任何尚未实现的业务能力都必须抛出
    本异常，禁止返回看似成功的占位结果。
    """

    code = "unsupported_operation"


def summarize_issues(issues: Iterable["ValidationIssue"]) -> str:
    """把若干校验问题压成一行摘要，用于异常消息。"""
    parts = [f"{issue.field_name}({issue.issue_code})" for issue in issues]
    return ", ".join(parts) if parts else "无"
