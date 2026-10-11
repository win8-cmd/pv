"""SQLite 集成测试。

覆盖：初始化建表、模式版本、项目新增/查询/更新/删除、重复主键、
非法字段约束、外键 RESTRICT 删除策略、事务回滚、参数化 SQL 防注入，
以及"测试绝不触碰真实数据库"的显式断言。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cenep.application.project_service import ProjectService
from cenep.domain.exceptions import (
    CENEPError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    PersistenceError,
    ValidationError,
)
from cenep.domain.models import (
    Document,
    DocumentType,
    Project,
    ProjectType,
    new_id,
    utc_now_iso,
)
from cenep.infrastructure.database import (
    BUSINESS_TABLES,
    SCHEMA_VERSION,
    Database,
    ProjectRepository,
)


class TestSchemaInitialization:
    def test_initialize_creates_all_tables(self, database: Database) -> None:
        tables = set(database.table_names())
        for table in BUSINESS_TABLES:
            assert table in tables, f"缺少数据表：{table}"
        assert "schema_meta" in tables

    def test_schema_version_recorded(self, database: Database) -> None:
        assert database.schema_version() == SCHEMA_VERSION

    def test_initialize_is_idempotent(self, database: Database) -> None:
        database.initialize_schema()
        database.initialize_schema()
        assert database.schema_version() == SCHEMA_VERSION

    def test_initialize_preserves_existing_data(self, database: Database, sample_project: Project) -> None:
        repo = ProjectRepository(database)
        repo.add(sample_project)
        database.initialize_schema()
        assert repo.count() == 1

    def test_uninitialized_database_has_no_schema_version(self, db_path: Path) -> None:
        assert Database(db_path).schema_version() is None

    def test_creates_real_file_on_disk(self, database: Database, db_path: Path) -> None:
        assert db_path.exists()

    def test_foreign_keys_enforced_on_every_connection(self, database: Database) -> None:
        with database.transaction() as conn:
            enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert enabled == 1

    def test_foreign_key_violation_rejected_by_database(self, database: Database) -> None:
        """外键约束由数据库强制；事务层回滚并放行原始完整性错误。"""
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            with database.transaction() as conn:
                conn.execute(
                    "INSERT INTO document (document_id, project_id, filename, document_type, imported_at, "
                    "processing_status) VALUES (?, ?, ?, 'other', ?, 'pending')",
                    (new_id(), "nonexistent-project", "a.pdf", utc_now_iso()),
                )
        assert "FOREIGN KEY" in str(excinfo.value).upper()
        with database.transaction() as conn:
            assert conn.execute("SELECT COUNT(*) AS n FROM document").fetchone()["n"] == 0

    def test_translate_integrity_error_classifies_driver_errors(self) -> None:
        """驱动层完整性错误必须被分类为明确的领域异常。"""
        from cenep.infrastructure.database import translate_integrity_error

        unique_error = translate_integrity_error(
            sqlite3.IntegrityError("UNIQUE constraint failed: project.project_id"),
            entity_id="abc123",
        )
        assert isinstance(unique_error, EntityAlreadyExistsError)
        assert unique_error.entity_id == "abc123"

        foreign_key_error = translate_integrity_error(sqlite3.IntegrityError("FOREIGN KEY constraint failed"))
        assert isinstance(foreign_key_error, PersistenceError)
        assert foreign_key_error.operation == "delete"

        check_error = translate_integrity_error(sqlite3.IntegrityError("CHECK constraint failed: project"))
        assert isinstance(check_error, ValidationError)


class TestProjectCrud:
    def test_add_and_get(self, repository: ProjectRepository, sample_project: Project) -> None:
        repository.add(sample_project)
        loaded = repository.get(sample_project.project_id)
        assert loaded is not None
        assert loaded.project_id == sample_project.project_id
        assert loaded.name == sample_project.name
        assert loaded.location == sample_project.location
        assert loaded.customer_name == sample_project.customer_name
        assert loaded.project_type is ProjectType.INDUSTRIAL_COMMERCIAL
        assert loaded.description == sample_project.description
        assert loaded.created_at == sample_project.created_at

    def test_get_missing_returns_none(self, repository: ProjectRepository) -> None:
        assert repository.get(new_id()) is None

    def test_get_or_raise_missing(self, repository: ProjectRepository) -> None:
        missing = new_id()
        with pytest.raises(EntityNotFoundError) as excinfo:
            repository.get_or_raise(missing)
        assert excinfo.value.entity_id == missing

    def test_list_all_empty(self, repository: ProjectRepository) -> None:
        assert repository.list_all() == []

    def test_list_all_returns_all_projects(self, repository: ProjectRepository) -> None:
        for index in range(3):
            repository.add(Project(name=f"项目 {index}"))
        assert len(repository.list_all()) == 3
        assert repository.count() == 3

    def test_list_all_rejects_unknown_order_by(self, repository: ProjectRepository) -> None:
        """排序子句使用白名单，防止 SQL 注入。"""
        with pytest.raises(ValueError):
            repository.list_all(order_by="name; DROP TABLE project")

    def test_find_by_name(self, repository: ProjectRepository) -> None:
        repository.add(Project(name="同名项目"))
        repository.add(Project(name="同名项目"))
        repository.add(Project(name="另一个项目"))
        assert len(repository.find_by_name("同名项目")) == 2

    def test_update_changes_fields_and_timestamp(self, repository: ProjectRepository, sample_project: Project) -> None:
        repository.add(sample_project)
        original_updated_at = sample_project.updated_at

        sample_project.name = "更新后的项目名称"
        sample_project.location = "湖北省黄石市"
        repository.update(sample_project, touch_updated_at=False)
        loaded = repository.get(sample_project.project_id)

        assert loaded is not None
        assert loaded.name == "更新后的项目名称"
        assert loaded.location == "湖北省黄石市"
        assert loaded.updated_at == original_updated_at

    def test_update_touch_updated_at_sets_new_value(self, repository: ProjectRepository) -> None:
        project = Project(name="项目", updated_at="2000-01-01T00:00:00Z")
        repository.add(project)
        repository.update(project)
        loaded = repository.get(project.project_id)
        assert loaded is not None
        assert loaded.updated_at != "2000-01-01T00:00:00Z"

    def test_update_missing_project(self, repository: ProjectRepository) -> None:
        ghost = Project(name="不存在的项目")
        with pytest.raises(EntityNotFoundError):
            repository.update(ghost)

    def test_update_with_invalid_name_rejected(self, repository: ProjectRepository, sample_project: Project) -> None:
        repository.add(sample_project)
        sample_project.name = "   "
        with pytest.raises(ValidationError):
            repository.update(sample_project)
        loaded = repository.get(sample_project.project_id)
        assert loaded is not None and loaded.name == "示例：某汽车零部件厂屋顶光伏"

    def test_delete_removes_project(self, repository: ProjectRepository, sample_project: Project) -> None:
        repository.add(sample_project)
        repository.delete(sample_project.project_id)
        assert repository.get(sample_project.project_id) is None
        assert repository.count() == 0

    def test_delete_missing_project(self, repository: ProjectRepository) -> None:
        with pytest.raises(EntityNotFoundError):
            repository.delete(new_id())

    def test_delete_twice_second_call_fails(self, repository: ProjectRepository, sample_project: Project) -> None:
        repository.add(sample_project)
        repository.delete(sample_project.project_id)
        with pytest.raises(EntityNotFoundError):
            repository.delete(sample_project.project_id)

    def test_add_duplicate_primary_key(self, repository: ProjectRepository, sample_project: Project) -> None:
        repository.add(sample_project)
        duplicate = Project(
            project_id=sample_project.project_id,
            name="重复主键项目",
        )
        with pytest.raises(EntityAlreadyExistsError) as excinfo:
            repository.add(duplicate)
        assert excinfo.value.entity_id == sample_project.project_id
        assert repository.count() == 1

    def test_delete_restricted_when_related_data_exists(
        self, database: Database, repository: ProjectRepository, sample_project: Project
    ) -> None:
        """安全删除策略：存在关联文档时必须拒绝删除，而不是级联删除客户台账。"""
        repository.add(sample_project)
        document = Document(
            project_id=sample_project.project_id,
            filename="2026-01 电费账单.pdf",
            document_type=DocumentType.ELECTRICITY_BILL,
        )
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO document (document_id, project_id, filename, document_type, "
                "imported_at, processing_status) VALUES (?, ?, ?, 'electricity_bill', ?, 'pending')",
                (document.document_id, document.project_id, document.filename, document.imported_at),
            )
        with pytest.raises(PersistenceError):
            repository.delete(sample_project.project_id)
        assert repository.get(sample_project.project_id) is not None

    def test_add_invalid_project_rejected_before_sql(self, repository: ProjectRepository) -> None:
        with pytest.raises(ValidationError):
            repository.add(Project(name=""))
        assert repository.count() == 0

    def test_parameterized_sql_resists_injection(self, repository: ProjectRepository) -> None:
        """恶意字符串只能作为数据存储，不能改变 SQL 结构。"""
        attack = "Robert'); DROP TABLE project;--"
        repository.add(Project(name=attack))
        assert repository.count() == 1
        loaded = repository.find_by_name(attack)
        assert len(loaded) == 1
        assert loaded[0].name == attack
        # 表仍然存在且可继续写入
        repository.add(Project(name="正常项目"))
        assert repository.count() == 2

    def test_project_description_and_nulls_roundtrip(self, repository: ProjectRepository) -> None:
        project = Project(name="最小项目")
        repository.add(project)
        loaded = repository.get(project.project_id)
        assert loaded is not None
        assert loaded.location is None
        assert loaded.customer_name is None
        assert loaded.description is None

    @pytest.mark.parametrize("project_type", list(ProjectType))
    def test_all_project_types_roundtrip(
        self, repository: ProjectRepository, project_type: ProjectType
    ) -> None:
        project = Project(name=f"项目-{project_type.value}", project_type=project_type)
        repository.add(project)
        loaded = repository.get(project.project_id)
        assert loaded is not None
        assert loaded.project_type is project_type

    def test_data_isolated_between_projects(self, repository: ProjectRepository) -> None:
        first = repository.add(Project(name="项目A", location="武汉市"))
        second = repository.add(Project(name="项目B", location="黄石市"))
        assert first.project_id != second.project_id
        assert repository.get(first.project_id).location == "武汉市"  # type: ignore[union-attr]
        assert repository.get(second.project_id).location == "黄石市"  # type: ignore[union-attr]


class TestTransactionsAndErrors:
    def test_transaction_rolls_back_on_error(self, database: Database) -> None:
        """事务内发生数据库错误时必须整体回滚，已写入的行不得留存。"""
        with pytest.raises(PersistenceError):
            with database.transaction() as conn:
                conn.execute(
                    "INSERT INTO project (project_id, name, project_type, created_at, updated_at) "
                    "VALUES (?, ?, 'other', ?, ?)",
                    (new_id(), "回滚测试", utc_now_iso(), utc_now_iso()),
                )
                conn.execute("SELECT * FROM table_that_does_not_exist")
        assert ProjectRepository(database).count() == 0

    def test_non_sql_exception_propagates_and_rolls_back(self, database: Database) -> None:
        class CustomError(RuntimeError):
            pass

        with pytest.raises(CustomError):
            with database.transaction() as conn:
                conn.execute(
                    "INSERT INTO project (project_id, name, project_type, created_at, updated_at) "
                    "VALUES (?, ?, 'other', ?, ?)",
                    (new_id(), "业务异常回滚", utc_now_iso(), utc_now_iso()),
                )
                raise CustomError("模拟业务异常")
        assert ProjectRepository(database).count() == 0

    def test_invalid_path_raises_persistence_error(self) -> None:
        # 指向一个不存在的目录，打开时必须失败
        blocked = Database(Path("Z:/definitely/not/exists/cenep.db"))
        with pytest.raises(PersistenceError) as excinfo:
            blocked.connect()
        assert excinfo.value.operation == "connect"

    def test_constraint_violation_rejected_and_rolled_back(self, database: Database) -> None:
        """绕过领域校验直接写库时，数据库 CHECK 约束仍然拦住非法数据。"""
        repo = ProjectRepository(database)
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as conn:
                conn.execute(
                    "INSERT INTO project (project_id, name, project_type, created_at, updated_at) "
                    "VALUES (?, ?, 'other', ?, ?)",
                    (new_id(), "   ", utc_now_iso(), utc_now_iso()),
                )
        assert repo.count() == 0


class TestServiceAndPersistence:
    def test_create_project_persists_and_reloads(self, database: Database, db_path: Path) -> None:
        """真实保存并重新读取：使用全新连接与全新服务实例验证。"""
        service = ProjectService(database)
        project = service.create_project(
            name="重载验证项目",
            location="湖北省宜昌市",
            customer_name="重载客户",
            description="验证落盘",
        )

        reopened = ProjectService(Database(db_path))
        loaded = reopened.get_project(project.project_id)
        assert loaded.name == "重载验证项目"
        assert loaded.location == "湖北省宜昌市"
        assert loaded.customer_name == "重载客户"
        assert loaded.description == "验证落盘"

    def test_create_project_strips_name(self, project_service: ProjectService) -> None:
        project = project_service.create_project(name="  带空格项目  ")
        assert project.name == "带空格项目"

    def test_create_project_blank_name_raises(self, project_service: ProjectService) -> None:
        with pytest.raises(ValidationError):
            project_service.create_project(name="   ")
        assert project_service.count_projects() == 0

    def test_create_project_invalid_type_raises(self, project_service: ProjectService) -> None:
        with pytest.raises(ValidationError):
            project_service.create_project(name="项目", project_type="bad-type")

    def test_create_project_accepts_string_type(self, project_service: ProjectService) -> None:
        project = project_service.create_project(name="项目", project_type="utility_scale")
        assert project.project_type is ProjectType.UTILITY_SCALE

    def test_update_project_via_service(self, project_service: ProjectService) -> None:
        project = project_service.create_project(name="原名称")
        updated = project_service.update_project(project.project_id, name="新名称", location="武汉市")
        assert updated.name == "新名称"
        assert updated.location == "武汉市"
        assert project_service.get_project(project.project_id).name == "新名称"

    def test_delete_project_via_service(self, project_service: ProjectService) -> None:
        project = project_service.create_project(name="待删除项目")
        project_service.delete_project(project.project_id)
        assert project_service.list_projects() == []

    def test_service_validate_input_reports_issues(self, project_service: ProjectService) -> None:
        issues = project_service.validate_project_input(name="   ")
        assert issues
        assert issues[0].issue_code == "project_name_required"

    def test_service_check_self_consumption_input(self, project_service: ProjectService) -> None:
        payload = project_service.check_self_consumption_input([3, 8, 2], [5, 4, 2])
        assert payload["is_valid"] is True
        assert payload["status"] == "valid"

    def test_service_check_self_consumption_input_invalid(self, project_service: ProjectService) -> None:
        payload = project_service.check_self_consumption_input([1, 2, 3], [1, 2])
        assert payload["is_valid"] is False
        assert payload["status"] == "invalid"
        assert payload["issues"]

    def test_auto_initialize_false_then_initialize(self, db_path: Path) -> None:
        service = ProjectService(Database(db_path), auto_initialize=False)
        assert service.database.schema_version() is None
        service.initialize()
        assert service.database.schema_version() == SCHEMA_VERSION

    def test_exceptions_are_cenep_errors(self) -> None:
        for exc_type in (EntityNotFoundError, EntityAlreadyExistsError, PersistenceError, ValidationError):
            assert issubclass(exc_type, CENEPError)


class TestRealDatabaseSafety:
    def test_default_database_path_is_redirected_in_tests(self) -> None:
        """conftest 必须把默认数据库重定向到临时目录，避免误触真实数据。"""
        from cenep import config

        resolved = config.resolve_database_path()
        assert "cenep-default-db" in str(resolved)
        assert resolved != config.default_database_path()

    def test_temp_database_is_not_inside_user_data_dir(self, db_path: Path) -> None:
        from cenep import config

        assert config.user_data_dir() not in db_path.parents

    def test_sqlite_row_factory_returns_mapping(self, database: Database) -> None:
        with database.transaction() as conn:
            row = conn.execute("SELECT 1 AS value").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert row["value"] == 1
