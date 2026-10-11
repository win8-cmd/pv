"""内存数据库与模式版本保护的集成测试。

覆盖两项复核缺陷的回归：

1. **内存数据库跨事务持久性**——修复前 ``Database(":memory:")`` 的每个事务
   都新建连接，初始化建表后连接关闭、表随之消失，下一个事务报
   ``no such table``。现在必须保证建表后数据跨事务持续可见。
2. **模式版本保护**——修复前 ``initialize_schema()`` 无条件把版本写回当前值，
   会把"未来版本"数据库静默降级为旧版本。现在必须拒绝并给出明确错误。

同时确保文件数据库行为不受影响。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cenep.domain.exceptions import (
    CENEPError,
    PersistenceError,
    SchemaVersionError,
)
from cenep.domain.models import Project, new_id, utc_now_iso
from cenep.infrastructure.database import (
    BUSINESS_TABLES,
    MIGRATIONS,
    SCHEMA_VERSION,
    Database,
    ProjectRepository,
)

MEMORY_ALIAS = ":memory:"
MEMORY_URI = "file:cenep?mode=memory&cache=shared"


# ---------------------------------------------------------------------------
# 缺陷 1：内存数据库
# ---------------------------------------------------------------------------


class TestMemoryDatabaseLifecycle:
    """内存库必须跨事务持续可见。"""

    @pytest.mark.parametrize("memory_spec,use_uri", [(MEMORY_ALIAS, False), (MEMORY_URI, True)])
    def test_schema_survives_across_transactions(self, memory_spec: str, use_uri: bool) -> None:
        """建表 → 结束事务 → 重新开启事务 → 表仍然存在。"""
        db = Database(memory_spec, uri=use_uri)
        try:
            db.initialize_schema()
            # 每次访问都会开启并关闭一个新连接
            assert db.schema_version() == SCHEMA_VERSION
            for _ in range(3):
                with db.transaction() as conn:
                    tables = {
                        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                for table in BUSINESS_TABLES:
                    assert table in tables, f"重新开启事务后表丢失：{table}"
        finally:
            db.close()

    @pytest.mark.parametrize("memory_spec,use_uri", [(MEMORY_ALIAS, False), (MEMORY_URI, True)])
    def test_write_then_read_in_separate_transactions(self, memory_spec: str, use_uri: bool) -> None:
        """写入 → 提交结束事务 → 新事务读取 → 数据仍在。"""
        db = Database(memory_spec, uri=use_uri)
        try:
            db.initialize_schema()
            repository = ProjectRepository(db)
            project = Project(name="内存库跨事务项目", location="湖北省武汉市")
            repository.add(project)

            # 完全独立的新事务（新连接）读取
            with db.transaction() as conn:
                row = conn.execute(
                    "SELECT name, location FROM project WHERE project_id = ?",
                    (project.project_id,),
                ).fetchone()
            assert row is not None
            assert row["name"] == "内存库跨事务项目"
            assert row["location"] == "湖北省武汉市"
            assert repository.count() == 1
        finally:
            db.close()

    def test_full_repository_crud_on_memory_database(self) -> None:
        """内存库必须支持与文件库相同的完整 CRUD。"""
        with Database(MEMORY_ALIAS) as db:
            db.initialize_schema()
            repository = ProjectRepository(db)

            project = repository.add(Project(name="原始名称"))
            assert repository.get(project.project_id) is not None

            project.name = "更新后名称"
            repository.update(project, touch_updated_at=False)
            assert repository.get(project.project_id).name == "更新后名称"

            assert len(repository.list_all()) == 1
            assert repository.count() == 1

            repository.delete(project.project_id)
            assert repository.get(project.project_id) is None
            assert repository.count() == 0

    def test_rollback_is_isolated_to_its_own_transaction(self) -> None:
        """一个事务回滚，不影响之前已提交的数据。"""
        with Database(MEMORY_ALIAS) as db:
            db.initialize_schema()
            repository = ProjectRepository(db)
            repository.add(Project(name="已提交项目"))

            with pytest.raises(PersistenceError):
                with db.transaction() as conn:
                    conn.execute(
                        "INSERT INTO project (project_id, name, project_type, created_at, updated_at) "
                        "VALUES (?, ?, 'other', ?, ?)",
                        (new_id(), "将被回滚", utc_now_iso(), utc_now_iso()),
                    )
                    conn.execute("SELECT * FROM table_that_does_not_exist")

            assert repository.count() == 1
            assert repository.find_by_name("已提交项目")
            assert repository.find_by_name("将被回滚") == []

    def test_foreign_keys_enforced_on_memory_database(self) -> None:
        with Database(MEMORY_ALIAS) as db:
            db.initialize_schema()
            with db.transaction() as conn:
                assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError):
                with db.transaction() as conn:
                    conn.execute(
                        "INSERT INTO document (document_id, project_id, filename, document_type, "
                        "imported_at, processing_status) VALUES (?, ?, ?, 'other', ?, 'pending')",
                        (new_id(), "no-such-project", "a.pdf", utc_now_iso()),
                    )

    def test_alias_is_translated_to_shared_cache_uri(self) -> None:
        """``:memory:`` 别名必须解析为共享缓存 URI，否则数据按连接隔离。"""
        db = Database(MEMORY_ALIAS)
        try:
            assert db.is_memory is True
            assert db.uri is True
            assert "mode=memory" in db.path
            assert "cache=shared" in db.path
        finally:
            db.close()

    def test_user_uri_without_shared_cache_gets_it_added(self) -> None:
        """用户写成 mode=memory 但漏了 cache=shared 时必须自动补上。"""
        db = Database("file:my_mem?mode=memory")
        try:
            assert db.is_memory is True
            conn = db.connect()
            try:
                assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
            finally:
                conn.close()
            db.initialize_schema()
            assert db.schema_version() == SCHEMA_VERSION
            ProjectRepository(db).add(Project(name="未声明共享缓存的内存库"))
            assert ProjectRepository(db).count() == 1
        finally:
            db.close()

    def test_two_memory_databases_are_isolated_from_each_other(self) -> None:
        """两个内存库实例不得互相看到对方的数据。"""
        with Database(MEMORY_ALIAS) as first, Database(MEMORY_ALIAS) as second:
            first.initialize_schema()
            second.initialize_schema()
            ProjectRepository(first).add(Project(name="只在第一个库"))
            assert ProjectRepository(first).count() == 1
            assert ProjectRepository(second).count() == 0

    def test_close_releases_memory_database(self) -> None:
        """close() 之后实例不可再用，且不会崩溃。"""
        db = Database(MEMORY_ALIAS)
        db.initialize_schema()
        db.close()
        db.close()  # 幂等
        with pytest.raises(PersistenceError):
            with db.transaction():
                pass

    def test_context_manager_closes_database(self) -> None:
        with Database(MEMORY_ALIAS) as db:
            db.initialize_schema()
            assert db.schema_version() == SCHEMA_VERSION
        with pytest.raises(PersistenceError):
            db.table_names()

    def test_memory_database_reports_exists(self) -> None:
        with Database(MEMORY_ALIAS) as db:
            assert db.exists() is True


# ---------------------------------------------------------------------------
# 缺陷 2：模式版本保护
# ---------------------------------------------------------------------------


def _write_schema_version(db: Database, value: str) -> None:
    """把数据库中的模式版本改写为指定字符串（用于构造异常场景）。"""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (value,),
        )


class TestSchemaVersionProtection:
    def test_current_version_is_idempotent(self, db_path: Path) -> None:
        db = Database(db_path)
        db.initialize_schema()
        db.initialize_schema()
        assert db.schema_version() == SCHEMA_VERSION
        assert set(BUSINESS_TABLES).issubset(set(db.table_names()))

    def test_current_version_preserves_existing_data(self, db_path: Path) -> None:
        db = Database(db_path)
        db.initialize_schema()
        ProjectRepository(db).add(Project(name="版本幂等保留项目"))
        db.initialize_schema()
        assert ProjectRepository(db).count() == 1

    def test_future_version_is_rejected(self, db_path: Path) -> None:
        """版本高于本程序时必须停止初始化。"""
        db = Database(db_path)
        db.initialize_schema()
        _write_schema_version(db, str(SCHEMA_VERSION + 1))

        reopened = Database(db_path)
        with pytest.raises(SchemaVersionError) as excinfo:
            reopened.initialize_schema()

        error = excinfo.value
        assert error.found_version == SCHEMA_VERSION + 1
        assert error.supported_version == SCHEMA_VERSION
        assert "高于本程序支持的版本" in str(error)
        assert error.operation == "initialize_schema"

    def test_future_version_is_not_silently_downgraded(self, db_path: Path) -> None:
        """核心回归：失败后版本号必须保持原值，不得被改写成当前版本。"""
        db = Database(db_path)
        db.initialize_schema()
        _write_schema_version(db, "99")

        reopened = Database(db_path)
        with pytest.raises(SchemaVersionError):
            reopened.initialize_schema()

        # 直接读原始记录，确认没有被写入 1
        with reopened.transaction() as conn:
            stored = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()["value"]
        assert stored == "99"
        assert reopened.schema_version() == 99

    def test_future_version_rejected_before_any_write(self, db_path: Path) -> None:
        """拒绝必须发生在任何建表/写入之前：不能先改结构再报错。"""
        db = Database(db_path)
        db.initialize_schema()
        # 记录当前库中表集合，并额外删除一张表观察是否被"顺手补齐"
        with db.transaction() as conn:
            conn.execute("DROP TABLE report")
        baseline = set(db.table_names())
        assert "report" not in baseline
        _write_schema_version(db, str(SCHEMA_VERSION + 5))

        reopened = Database(db_path)
        with pytest.raises(SchemaVersionError):
            reopened.initialize_schema()
        assert set(reopened.table_names()) == baseline, "被拒绝的初始化不应改动任何表结构"

    def test_older_version_without_migration_is_rejected(self, db_path: Path) -> None:
        """版本低于本程序且没有迁移步骤时必须拒绝，不得仅改版本号。"""
        db = Database(db_path)
        db.initialize_schema()
        _write_schema_version(db, "0")

        reopened = Database(db_path)
        with pytest.raises(SchemaVersionError) as excinfo:
            reopened.initialize_schema()
        assert excinfo.value.found_version == 0
        assert "低于本程序支持的版本" in str(excinfo.value)
        assert reopened.schema_version() == 0

    def test_migration_registry_is_empty_for_stage_one(self) -> None:
        """第一阶段没有历史版本，迁移注册表必须为空（有迁移步骤时必须登记）。"""
        assert SCHEMA_VERSION == 1
        assert MIGRATIONS == {}

    def test_registered_migration_upgrades_real_structure(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """迁移机制必须真的执行 SQL 并更新版本号，而不是只改版本。"""
        db = Database(db_path)
        db.initialize_schema()
        _write_schema_version(db, "0")

        monkeypatch.setitem(
            MIGRATIONS,
            0,
            ("ALTER TABLE project ADD COLUMN legacy_note TEXT",),
        )
        reopened = Database(db_path)
        reopened.initialize_schema()

        assert reopened.schema_version() == SCHEMA_VERSION
        with reopened.transaction() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(project)")}
        assert "legacy_note" in columns, "迁移必须真的改变表结构"

    def test_missing_migration_step_stops_upgrade(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """登记了起始版本但缺少后续步骤时，必须停止而不是跳过。"""
        db = Database(db_path)
        db.initialize_schema()
        _write_schema_version(db, "0")

        monkeypatch.setattr("cenep.infrastructure.database.SCHEMA_VERSION", 3)
        monkeypatch.setitem(MIGRATIONS, 0, ("ALTER TABLE project ADD COLUMN step_one TEXT",))
        # 缺少从 1 到 2、从 2 到 3 的步骤
        reopened = Database(db_path)
        with pytest.raises(SchemaVersionError) as excinfo:
            reopened.initialize_schema()
        assert "缺少从模式版本" in str(excinfo.value)

    @pytest.mark.parametrize("bad_value", ["abc", "", "1.5", "None"])
    def test_invalid_version_record_is_reported_not_swallowed(self, db_path: Path, bad_value: str) -> None:
        """版本记录不是整数时必须明确报错，不能静默当作"未初始化"。"""
        db = Database(db_path)
        db.initialize_schema()
        _write_schema_version(db, bad_value)
        with pytest.raises(PersistenceError) as excinfo:
            db.schema_version()
        assert "模式版本记录非法" in str(excinfo.value)

    def test_negative_version_is_rejected(self, db_path: Path) -> None:
        db = Database(db_path)
        db.initialize_schema()
        _write_schema_version(db, "-1")
        with pytest.raises(PersistenceError):
            db.schema_version()

    def test_schema_version_none_before_initialization(self, db_path: Path) -> None:
        """未初始化的空库返回 None（表示尚未初始化），而不是抛异常。"""
        assert Database(db_path).schema_version() is None

    def test_schema_version_error_is_persistence_error(self) -> None:
        """异常层次：SchemaVersionError 必须可被 PersistenceError/CENEPError 捕获。"""
        assert issubclass(SchemaVersionError, PersistenceError)
        assert issubclass(SchemaVersionError, CENEPError)

    def test_missing_version_row_in_existing_meta_table(self, db_path: Path) -> None:
        """schema_meta 存在但缺版本记录时，视为待初始化并写入当前版本。"""
        db = Database(db_path)
        db.initialize_schema()
        with db.transaction() as conn:
            conn.execute("DELETE FROM schema_meta WHERE key = 'schema_version'")
        assert db.schema_version() is None
        db.initialize_schema()
        assert db.schema_version() == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 文件数据库不受影响
# ---------------------------------------------------------------------------


class TestFileDatabaseUnaffected:
    def test_file_database_still_persists_across_instances(self, db_path: Path) -> None:
        first = Database(db_path)
        first.initialize_schema()
        ProjectRepository(first).add(Project(name="文件库跨实例项目"))

        second = Database(db_path)
        second.initialize_schema()
        assert ProjectRepository(second).count() == 1
        assert db_path.exists()

    def test_file_database_uses_wal_and_foreign_keys(self, db_path: Path) -> None:
        db = Database(db_path)
        db.initialize_schema()
        with db.transaction() as conn:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

    def test_file_database_is_not_memory(self, db_path: Path) -> None:
        db = Database(db_path)
        assert db.is_memory is False
        assert db.uri is False
        assert db.exists() is False  # 尚未创建
        db.initialize_schema()
        assert db.exists() is True

    def test_uri_flag_does_not_break_file_paths(self, db_path: Path) -> None:
        """显式 uri=True 传普通文件路径时，仍应作为文件库处理。"""
        db = Database(str(db_path), uri=False)
        db.initialize_schema()
        assert db.is_memory is False
        assert db.schema_version() == SCHEMA_VERSION
        assert db_path.exists()

    def test_close_on_file_database_is_harmless(self, db_path: Path) -> None:
        db = Database(db_path)
        db.initialize_schema()
        db.close()
        # 文件库不依赖锚定连接，关闭后仍可重新打开使用
        reopened = Database(db_path)
        assert reopened.schema_version() == SCHEMA_VERSION
