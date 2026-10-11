"""项目应用服务。

职责边界：

- **做**：组织业务流程（校验 → 落库 → 返回结果）、装配依赖、
  产生可追溯的校验留痕、给界面层提供粒度合适的用例方法。
- **不做**：不写 SQL（交给仓储）、不做电量/财务公式（交给 calculations）、
  不碰 Qt 控件。

界面层只允许调用本服务，不允许直接访问仓储或数据库。
"""

from __future__ import annotations

from typing import Any, Sequence

from cenep.calculations.self_consumption import (
    SelfConsumptionResult,
    calculate_self_consumption,
)
from cenep.domain.exceptions import (
    CENEPError,
    EntityNotFoundError,
    PersistenceError,
    ValidationError,
)
from cenep.domain.models import (
    ASSUMPTIONS_VERSION,
    CALCULATION_ENGINE_VERSION,
    CalculationType,
    Project,
    ProjectType,
)
from cenep.domain.validation import (
    ValidationIssue,
    classify_energy_series,
    validate_project,
)
from cenep.infrastructure.database import Database, ProjectRepository


class ProjectService:
    """项目相关用例的应用服务。

    Args:
        database: 数据库对象；不传则使用默认路径
            （``%LOCALAPPDATA%\\CENEP\\cenep.db`` 或 ``CENEP_DB_PATH``）。
        auto_initialize: 为 ``True`` 时在首次操作前自动建表（幂等）。
    """

    def __init__(
        self,
        database: Database | None = None,
        *,
        auto_initialize: bool = True,
    ) -> None:
        if database is None:
            from cenep import config

            database = Database(config.ensure_parent_dir(config.resolve_database_path()))
        self._db = database
        self._projects = ProjectRepository(database)
        self._initialized = False
        if auto_initialize:
            self.initialize()

    # -- 生命周期 -------------------------------------------------------
    @property
    def database(self) -> Database:
        """底层数据库对象（仅供组装使用，界面层不应直接使用）。"""
        return self._db

    def initialize(self) -> None:
        """建库建表（幂等）。"""
        self._db.initialize_schema()
        self._initialized = True

    def ensure_initialized(self) -> None:
        """确保表结构已就绪。

        若数据库文件尚不存在，只做只读操作时不会因为"读一个不存在的库"
        而凭空创建空数据库文件；一旦需要落库，:meth:`create_project`
        与 :meth:`update_project` 会显式调用 :meth:`initialize`。
        """
        if self._initialized:
            return
        if self._db.exists():
            self._db.initialize_schema()
        self._initialized = True

    # -- 项目用例 -------------------------------------------------------
    def create_project(
        self,
        *,
        name: str,
        location: str | None = None,
        customer_name: str | None = None,
        project_type: ProjectType | str = ProjectType.INDUSTRIAL_COMMERCIAL,
        description: str | None = None,
    ) -> Project:
        """创建项目并真实写入数据库。

        Raises:
            ValidationError: 名称等字段不合法，或项目类型非法。
            EntityAlreadyExistsError: 主键重复（自动生成主键时不会发生）。
            PersistenceError: 数据库写入失败。
        """
        self.ensure_initialized()
        if isinstance(project_type, str) and not isinstance(project_type, ProjectType):
            try:
                project_type = ProjectType(project_type)
            except ValueError as exc:
                raise ValidationError(
                    f"项目类型非法：{project_type!r}；允许值为 {[item.value for item in ProjectType]}。",
                    issues=(
                        ValidationIssue(
                            issue_code="project_type_invalid",
                            field_name="project_type",
                            message=f"项目类型非法：{project_type!r}。",
                            value=project_type,
                        ),
                    ),
                ) from exc

        project = Project(
            name=name.strip() if isinstance(name, str) else name,
            location=location,
            customer_name=customer_name,
            project_type=project_type,
            description=description,
        )
        return self._projects.add(project)

    def get_project(self, project_id: str) -> Project:
        """按主键读取项目。

        Raises:
            EntityNotFoundError: 项目不存在。
        """
        self.ensure_initialized()
        return self._projects.get_or_raise(project_id)

    def find_project(self, project_id: str) -> Project | None:
        """按主键读取项目；不存在返回 ``None``。"""
        self.ensure_initialized()
        return self._projects.get(project_id)

    def list_projects(self) -> list[Project]:
        """列出全部项目（按更新时间倒序）。"""
        self.ensure_initialized()
        return self._projects.list_all()

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        location: str | None = None,
        customer_name: str | None = None,
        project_type: ProjectType | str | None = None,
        description: str | None = None,
    ) -> Project:
        """更新项目字段（只覆盖显式传入的字段）。

        Raises:
            EntityNotFoundError: 项目不存在。
            ValidationError: 更新后字段不合法。
        """
        self.ensure_initialized()
        project = self._projects.get_or_raise(project_id)
        if name is not None:
            project.name = name.strip()
        if location is not None:
            project.location = location
        if customer_name is not None:
            project.customer_name = customer_name
        if project_type is not None:
            project.project_type = ProjectType(project_type) if isinstance(project_type, str) else project_type
        if description is not None:
            project.description = description
        return self._projects.update(project)

    def delete_project(self, project_id: str) -> None:
        """删除项目（RESTRICT 策略，存在关联数据时拒绝）。

        Raises:
            EntityNotFoundError: 项目不存在。
            PersistenceError: 仍有关联数据或其他数据库异常。
        """
        self.ensure_initialized()
        self._projects.delete(project_id)

    def count_projects(self) -> int:
        """返回项目总数。"""
        self.ensure_initialized()
        return self._projects.count()

    # -- 校验用例 -------------------------------------------------------
    def validate_project_input(
        self,
        *,
        name: str,
        project_type: ProjectType | str = ProjectType.INDUSTRIAL_COMMERCIAL,
    ) -> list[ValidationIssue]:
        """在写入前校验项目输入，返回问题清单（不抛异常，供界面提示）。"""
        candidate = Project(
            name=name.strip() if isinstance(name, str) else name,
            project_type=project_type if isinstance(project_type, ProjectType) else ProjectType(project_type),
        )
        return validate_project(candidate).errors

    # -- 计算用例 -------------------------------------------------------
    def run_self_consumption(
        self,
        load: Sequence[float],
        pv: Sequence[float],
        *,
        interval_minutes: int | None = None,
    ) -> SelfConsumptionResult:
        """执行消纳计算。

        本方法只做"调用领域计算并附带上下文"，不复制任何公式。

        Raises:
            ValidationError: 输入不合法。
        """
        return calculate_self_consumption(load, pv, interval_minutes=interval_minutes)

    def check_self_consumption_input(
        self,
        load: Sequence[float],
        pv: Sequence[float],
        *,
        interval_minutes: int | None = None,
    ) -> dict[str, Any]:
        """仅校验输入并给出业务提示，不执行计算。"""
        from cenep.domain.validation import check_energy_series

        result = check_energy_series(load, pv, interval_minutes=interval_minutes)
        combined: list[ValidationIssue] = list(result.issues)
        if result.is_valid:
            combined.extend(classify_energy_series(list(load), list(pv)))
        return {
            "status": result.status,
            "is_valid": result.is_valid,
            "issues": [issue.to_dict() for issue in combined],
        }

    # -- 元信息 ---------------------------------------------------------
    @staticmethod
    def stage_info() -> dict[str, str]:
        """返回当前阶段的版本与口径信息，供界面与报告展示。"""
        return {
            "calculation_engine_version": CALCULATION_ENGINE_VERSION,
            "assumptions_version": ASSUMPTIONS_VERSION,
            "calculation_type": CalculationType.SELF_CONSUMPTION.value,
        }


__all__ = ["ProjectService", "CENEPError", "EntityNotFoundError", "PersistenceError", "ValidationError"]
