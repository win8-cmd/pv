"""SQLite 持久化：模式定义、连接/事务管理与项目仓储。

第一阶段实现范围：

- 建库与建表（全部实体表一次性冻结，字段与 ``docs/DATA_MODEL.md`` 一致）。
- :class:`ProjectRepository` 的完整基础 CRUD。
- 重复主键、外键约束与数据库异常的明确处理。
- 全部 SQL 使用参数化占位符，绝不拼接用户数据。

安全约束：

1. 连接默认开启 ``PRAGMA foreign_keys = ON``，保证跨表引用完整性。
2. 删除项目采用 **RESTRICT** 策略：只要存在关联文档/账单/负荷数据，
   删除就被数据库拒绝并转为 :class:`PersistenceError`，
   避免"删项目顺手删掉客户原始台账"这类不可逆事故。
   如确需级联删除，必须由应用层显式调用专用方法（本阶段未提供）。
3. 事务由 :meth:`Database.transaction` 显式管理；异常时回滚。
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Iterator, Sequence

from cenep.domain.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    PersistenceError,
    SchemaVersionError,
    ValidationError,
)
from cenep.domain.models import Project, utc_now_iso
from cenep.domain.validation import require_valid_project

# ---------------------------------------------------------------------------
# 模式定义
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
"""数据库模式版本，写入 ``schema_meta`` 表。"""

#: 迁移步骤注册表：``{起始版本: (迁移 SQL, ...)}``。
#:
#: 键为**升级前**的版本号，值为把该版本升级到 ``键 + 1`` 所需的 SQL 语句序列。
#: :meth:`Database.initialize_schema` 会按版本阶梯依次执行，并在每一步之后
#: 更新 ``schema_meta`` 中的版本号。
#:
#: **当前为空**：``SCHEMA_VERSION == 1`` 尚无历史版本需要迁移。
#: 一旦把 ``SCHEMA_VERSION`` 提升到 2，必须在此登记从 1 到 2 的**真实表结构变更**
#: （例如 ``ALTER TABLE ... ADD COLUMN``）。禁止只改版本号而不迁移结构。
MIGRATIONS: dict[int, tuple[str, ...]] = {}

_PROJECT_TYPE_VALUES = "'industrial_commercial','utility_scale','other'"
_DOCUMENT_TYPE_VALUES = "'electricity_bill','load_profile','tariff_document','other'"
_PROCESSING_STATUS_VALUES = "'pending','parsed','failed','manual_review'"
_VALIDATION_STATUS_VALUES = "'unvalidated','valid','invalid','warning'"
_SOURCE_TYPE_VALUES = "'meter_interval','bill_allocated','synthetic','manual'"
_TARIFF_TYPE_VALUES = "'tou_industrial','flat','demand','market','other'"
_ENTITY_STATUS_VALUES = "'draft','active','archived'"
_ISSUE_SEVERITY_VALUES = "'error','warning','info'"
_CALC_STATUS_VALUES = "'pending','running','succeeded','failed'"
_REPORT_TYPE_VALUES = "'feasibility','comparison','data_quality','other'"
_REPORT_STATUS_VALUES = "'pending','generated','failed'"

SCHEMA_STATEMENTS: tuple[str, ...] = (
    # --- 元数据 ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL
    )
    """,
    # --- 项目 -----------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS project (
        project_id      TEXT PRIMARY KEY,
        name            TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 200),
        location        TEXT,
        customer_name   TEXT,
        project_type    TEXT NOT NULL DEFAULT 'industrial_commercial'
                        CHECK (project_type IN ({project_type})),
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        description     TEXT
    )
    """.format(project_type=_PROJECT_TYPE_VALUES),
    "CREATE INDEX IF NOT EXISTS idx_project_name ON project(name)",
    "CREATE INDEX IF NOT EXISTS idx_project_updated_at ON project(updated_at DESC)",
    # --- 文件 -----------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS document (
        document_id       TEXT PRIMARY KEY,
        project_id        TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        filename          TEXT NOT NULL,
        document_type     TEXT NOT NULL DEFAULT 'other'
                          CHECK (document_type IN ({document_type})),
        file_path         TEXT,
        imported_at       TEXT NOT NULL,
        processing_status TEXT NOT NULL DEFAULT 'pending'
                          CHECK (processing_status IN ({processing_status}))
    )
    """.format(
        document_type=_DOCUMENT_TYPE_VALUES,
        processing_status=_PROCESSING_STATUS_VALUES,
    ),
    "CREATE INDEX IF NOT EXISTS idx_document_project ON document(project_id)",
    # --- 电费账单 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS bill_record (
        bill_id             TEXT PRIMARY KEY,
        project_id          TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        billing_period_start TEXT,
        billing_period_end   TEXT,
        total_energy_kwh    REAL CHECK (total_energy_kwh IS NULL OR total_energy_kwh >= 0),
        total_amount_yuan   REAL CHECK (total_amount_yuan IS NULL OR total_amount_yuan >= 0),
        validation_status   TEXT NOT NULL DEFAULT 'unvalidated'
                            CHECK (validation_status IN ({validation_status})),
        source_document_id  TEXT REFERENCES document(document_id) ON DELETE SET NULL,
        CHECK (
            billing_period_start IS NULL
            OR billing_period_end IS NULL
            OR billing_period_start <= billing_period_end
        )
    )
    """.format(validation_status=_VALIDATION_STATUS_VALUES),
    "CREATE INDEX IF NOT EXISTS idx_bill_project_period ON bill_record(project_id, billing_period_start)",
    # --- 负荷曲线 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS load_profile (
        profile_id       TEXT PRIMARY KEY,
        project_id       TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        timestamp        TEXT NOT NULL,
        energy_kwh       REAL NOT NULL CHECK (energy_kwh >= 0),
        interval_minutes INTEGER NOT NULL CHECK (interval_minutes > 0),
        source_type      TEXT NOT NULL DEFAULT 'manual'
                         CHECK (source_type IN ({source_type})),
        UNIQUE (project_id, timestamp, interval_minutes)
    )
    """.format(source_type=_SOURCE_TYPE_VALUES),
    "CREATE INDEX IF NOT EXISTS idx_load_profile_project_ts ON load_profile(project_id, timestamp)",
    # --- 电价方案 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS tariff_model (
        tariff_id        TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        region           TEXT,
        effective_from   TEXT,
        effective_to     TEXT,
        tariff_type      TEXT NOT NULL DEFAULT 'tou_industrial'
                         CHECK (tariff_type IN ({tariff_type})),
        source_reference TEXT,
        status           TEXT NOT NULL DEFAULT 'draft'
                         CHECK (status IN ({status})),
        CHECK (
            effective_from IS NULL
            OR effective_to IS NULL
            OR effective_from <= effective_to
        )
    )
    """.format(tariff_type=_TARIFF_TYPE_VALUES, status=_ENTITY_STATUS_VALUES),
    # --- 光伏方案 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS pv_model (
        pv_model_id                  TEXT PRIMARY KEY,
        project_id                   TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        installed_capacity_kwp       REAL NOT NULL CHECK (installed_capacity_kwp >= 0),
        annual_generation_kwh        REAL CHECK (annual_generation_kwh IS NULL OR annual_generation_kwh >= 0),
        generation_profile_reference TEXT,
        assumptions_version          TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pv_model_project ON pv_model(project_id)",
    # --- 测算方案 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS scenario (
        scenario_id  TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        name         TEXT NOT NULL,
        pv_model_id  TEXT REFERENCES pv_model(pv_model_id) ON DELETE SET NULL,
        tariff_id    TEXT REFERENCES tariff_model(tariff_id) ON DELETE SET NULL,
        assumptions  TEXT,
        created_at   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scenario_project ON scenario(project_id)",
    # --- 计算运行记录 ---------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS calculation_run (
        calculation_run_id   TEXT PRIMARY KEY,
        scenario_id          TEXT REFERENCES scenario(scenario_id) ON DELETE SET NULL,
        calculation_type     TEXT NOT NULL DEFAULT 'self_consumption',
        calculation_version  TEXT NOT NULL,
        input_snapshot       TEXT,
        status               TEXT NOT NULL DEFAULT 'pending'
                             CHECK (status IN ({status})),
        started_at           TEXT NOT NULL,
        completed_at         TEXT
    )
    """.format(status=_CALC_STATUS_VALUES),
    "CREATE INDEX IF NOT EXISTS idx_calc_run_scenario ON calculation_run(scenario_id)",
    # --- 计算结果 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS result_record (
        result_id          TEXT PRIMARY KEY,
        calculation_run_id TEXT NOT NULL REFERENCES calculation_run(calculation_run_id) ON DELETE CASCADE,
        metric_name        TEXT NOT NULL,
        value              REAL,
        unit               TEXT,
        period             TEXT,
        status             TEXT NOT NULL DEFAULT 'ok',
        UNIQUE (calculation_run_id, metric_name, period)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_result_run ON result_record(calculation_run_id)",
    # --- 校验问题 -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS validation_issue (
        issue_id             TEXT PRIMARY KEY,
        project_id           TEXT REFERENCES project(project_id) ON DELETE CASCADE,
        related_object_type  TEXT,
        related_object_id    TEXT,
        field_name           TEXT NOT NULL,
        issue_code           TEXT NOT NULL,
        severity             TEXT NOT NULL DEFAULT 'error'
                             CHECK (severity IN ({severity})),
        message              TEXT NOT NULL
    )
    """.format(severity=_ISSUE_SEVERITY_VALUES),
    "CREATE INDEX IF NOT EXISTS idx_validation_issue_project ON validation_issue(project_id)",
    # --- 报告 -----------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS report (
        report_id    TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
        scenario_id  TEXT REFERENCES scenario(scenario_id) ON DELETE SET NULL,
        report_type  TEXT NOT NULL DEFAULT 'other'
                     CHECK (report_type IN ({report_type})),
        file_path    TEXT,
        generated_at TEXT,
        status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ({status}))
    )
    """.format(report_type=_REPORT_TYPE_VALUES, status=_REPORT_STATUS_VALUES),
    "CREATE INDEX IF NOT EXISTS idx_report_project ON report(project_id)",
)

#: 全部业务表名（不含 ``schema_meta``），供测试与文档核对。
BUSINESS_TABLES: tuple[str, ...] = (
    "project",
    "document",
    "bill_record",
    "load_profile",
    "tariff_model",
    "pv_model",
    "scenario",
    "calculation_run",
    "result_record",
    "validation_issue",
    "report",
)


# ---------------------------------------------------------------------------
# 连接与事务
# ---------------------------------------------------------------------------


class Database:
    """SQLite 数据库连接与模式管理。

    支持两种模式：

    **文件数据库**（默认）::

        db = Database(r"D:\\data\\cenep.db")
        db.initialize_schema()
        with db.transaction() as conn:
            ...

    **内存数据库**（URI 形式，推荐显式写法）::

        db = Database("file:cenep?mode=memory&cache=shared", uri=True)

    也接受便捷别名 ``Database(":memory:")``，内部转换为**共享缓存**内存库。

    内存库为何必须用共享缓存
    ------------------------
    SQLite 的普通内存库（``mode=memory`` 且不共享）**按连接隔离**，
    连接一旦关闭，其中的数据立即消失。而本类的 :meth:`transaction`
    每次都会新建连接、结束即关闭，因此"普通内存库"在本设计中根本不可用：
    初始化建表后连接关闭 → 表随之消失 → 下一个事务报
    ``no such table``。

    共享缓存内存库（``cache=shared``）的生命周期由**仍处于打开状态的连接**
    决定。本类因此持有一个常驻的"锚定连接"（anchor connection），
    只要 ``Database`` 实例存活且未被关闭，内存库及其中的表和数据就持续可见。

    使用约定：

    1. 内存库必须由创建它的同一个 ``Database`` 实例使用；
       跨实例共享同一内存库名有风险（实例销毁后库即消失）。
    2. 不再使用时应调用 :meth:`close`（或使用 ``with`` 语句）释放锚定连接。
    3. 内存库不支持 WAL；``PRAGMA foreign_keys`` 在所有模式下一律开启。

    模式版本保护
    ------------
    :meth:`initialize_schema` 会先读取数据库中的模式版本：

    - 空数据库（无 ``schema_meta`` 表）→ 正常建表并写入当前版本；
    - 版本等于当前支持版本 → 幂等执行，不重复变更；
    - 版本**高于**当前支持版本 → 抛 :class:`SchemaVersionError`，
      拒绝读写由更新版本程序创建的数据库（防止静默降级）；
    - 版本**低于**当前支持版本 → 抛 :class:`SchemaVersionError`，
      并要求显式迁移（见 :data:`MIGRATIONS`），不做部分升级。
    """

    #: 便捷别名：映射到共享缓存内存库的 URI 模板（``{name}`` 为实例唯一名）
    MEMORY_ALIASES: ClassVar[dict[str, str]] = {":memory:": "file:{name}?mode=memory&cache=shared"}

    def __init__(self, path: str | Path, *, uri: bool = False) -> None:
        # 每个实例一个唯一的内存库名，保证不同实例互不可见
        self._memory_name = f"cenep_mem_{uuid.uuid4().hex}"

        raw_path = str(path)
        alias_template = self.MEMORY_ALIASES.get(raw_path) if not uri else None
        if alias_template is not None:
            # 便捷别名（如 ":memory:"）→ 实例唯一的共享缓存内存库
            self.path = alias_template.format(name=self._memory_name)
            self.uri = True
            self.is_memory = True
        else:
            self.path = raw_path
            # 内存 URI（含 mode=memory）必须走 uri 模式，即使调用方未显式声明，
            # 否则 sqlite3 会把它当成普通文件名。
            self.uri = uri or self._detect_memory_uri(raw_path)
            self.is_memory = self.uri and self._detect_memory_uri(raw_path)

        # 锚定连接：使共享缓存内存库在整个实例生命周期内存活
        self._anchor: sqlite3.Connection | None = None
        self._closed = False
        self._lock = threading.RLock()

    # -- 路径与生命周期 -------------------------------------------------
    @staticmethod
    def _detect_memory_uri(path: str) -> bool:
        """判断 URI 形式的路径是否为内存库。"""
        lowered = path.lower()
        return lowered.startswith("file::memory:") or "mode=memory" in lowered

    @staticmethod
    def _display_path(path: str) -> str:
        """返回便于阅读与日志记录的路径（隐藏内存库内部实现细节）。"""
        lowered = path.lower()
        if lowered.startswith("file:") and ("mode=memory" in lowered or lowered.startswith("file::memory:")):
            return ":memory:"
        return path

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - 依赖垃圾回收时机
        try:
            self.close()
        except Exception:
            pass

    def close(self) -> None:
        """释放锚定连接（内存库的数据随之消失）。幂等。

        文件数据库无需关闭任何常驻资源，调用本方法只标记实例已关闭。
        """
        with self._lock:
            anchor, self._anchor = self._anchor, None
            self._closed = True
        if anchor is not None:
            try:
                anchor.close()
            except sqlite3.Error:  # pragma: no cover - 关闭失败不影响后续
                pass

    def _require_open(self) -> None:
        if self._closed:
            raise PersistenceError(
                "数据库连接已关闭，无法继续使用该实例。",
                operation="connect",
            )

    # -- 连接 -----------------------------------------------------------
    def exists(self) -> bool:
        """数据库是否存在（内存库视为存在）。

        用于区分"新建库"与"打开已有库"：只读操作不应凭空创建空库文件。
        """
        if self.is_memory:
            return True
        return Path(self.path).exists()

    def _ensure_anchor(self) -> None:
        """确保共享缓存内存库的锚定连接存在。"""
        if self._anchor is not None:
            return
        with self._lock:
            if self._anchor is not None:
                return
            if self.uri:
                uri = self._shared_memory_uri()
            else:
                # 第一次打开内存库时按共享缓存模式创建它
                uri = f"file:{self._memory_name}?mode=memory&cache=shared"
            conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._anchor = conn

    def _shared_memory_uri(self) -> str:
        """把用户提供的 URI 改写为共享缓存形式。

        用户无需记住 ``cache=shared``；若其 URI 使用 ``mode=memory`` 却未声明
        共享缓存，本方法会自动补上，否则数据将按连接隔离而无法跨事务读取。
        """
        if "cache=" in self.path:
            return self.path
        separator = "&" if "?" in self.path else "?"
        return f"{self.path}{separator}cache=shared"

    def connect(self) -> sqlite3.Connection:
        """新建一个已配置好的连接（调用方负责关闭）。

        Raises:
            PersistenceError: 无法打开数据库或配置连接。
        """
        self._require_open()
        try:
            if self.is_memory:
                self._ensure_anchor()
                conn = sqlite3.connect(
                    self._shared_memory_uri(),
                    uri=True,
                    isolation_level=None,
                    timeout=10.0,
                )
            else:
                conn = sqlite3.connect(self.path, isolation_level=None, timeout=10.0)
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"无法打开数据库：{self._display_path(self.path)}（{exc}）",
                operation="connect",
            ) from exc

        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if not self.is_memory:
                # WAL 提升并发读性能；内存库不支持。
                conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error as exc:  # pragma: no cover - 取决于驱动状态
            conn.close()
            raise PersistenceError(f"数据库 PRAGMA 配置失败：{exc}", operation="configure") from exc
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文：正常退出提交，异常回滚并包装为领域异常。"""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
        except sqlite3.IntegrityError as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover - 回滚失败时保留原始异常
                pass
            # 保留原始驱动异常，交由调用方（仓储层携带实体主键）翻译为领域异常。
            raise
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover - 回滚失败时保留原始异常
                pass
            raise PersistenceError(f"数据库操作失败：{exc}", operation="transaction") from exc
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover
                pass
            raise
        else:
            conn.execute("COMMIT")
        finally:
            conn.close()

    # -- 模式 -----------------------------------------------------------
    @staticmethod
    def _meta_table_exists(conn: sqlite3.Connection) -> bool:
        """``schema_meta`` 表是否已存在。"""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
        ).fetchone()
        if row is not None:
            return True
        # 兼容大小写差异（SQLite 对象名不区分大小写）
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND lower(name) = 'schema_meta'"
        ).fetchone()
        return row is not None

    @staticmethod
    def _read_schema_version(conn: sqlite3.Connection) -> int | None:
        """读取已写入的模式版本。

        Returns:
            - ``None``：``schema_meta`` 表不存在（空数据库）或版本记录缺失；
            - 非负整数：已记录的模式版本。

        Raises:
            PersistenceError: 版本值存在但不是整数（数据库被外部破坏）。
        """
        if not Database._meta_table_exists(conn):
            return None
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            return None
        value = row["value"]
        try:
            version = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise PersistenceError(
                f"数据库模式版本记录非法（期望整数）：{value!r}",
                operation="initialize_schema",
            ) from exc
        if version < 0:
            raise PersistenceError(
                f"数据库模式版本记录非法（不允许负数）：{version}",
                operation="initialize_schema",
            )
        return version

    @property
    def supported_schema_version(self) -> int:
        """本程序当前支持的模式版本。"""
        return SCHEMA_VERSION

    def _check_schema_version(self, stored: int | None) -> None:
        """校验数据库模式版本是否可被本程序安全使用。

        Raises:
            SchemaVersionError: 版本高于或低于当前支持版本。
        """
        if stored is None or stored == SCHEMA_VERSION:
            return
        if stored > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"数据库模式版本（{stored}）高于本程序支持的版本（{SCHEMA_VERSION}），"
                "已拒绝打开以避免破坏数据。该数据库可能由更新版本的 CENEP 创建，"
                "请升级本程序后再使用。",
                found_version=stored,
                supported_version=SCHEMA_VERSION,
            )
        # stored < SCHEMA_VERSION
        if stored in MIGRATIONS:
            return
        raise SchemaVersionError(
            f"数据库模式版本（{stored}）低于本程序支持的版本（{SCHEMA_VERSION}），"
            "且没有可用的迁移步骤，已拒绝自动升级。"
            "仅修改版本号而不迁移真实表结构会导致数据损坏，因此本程序不做静默升级；"
            "请先备份数据并使用与本数据库版本匹配的程序，或提供显式迁移脚本。",
            found_version=stored,
            supported_version=SCHEMA_VERSION,
        )

    def _apply_schema(self, conn: sqlite3.Connection) -> None:
        """建表建索引并写入当前模式版本。"""
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )

    def _apply_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        """按阶梯顺序执行迁移步骤，真实迁移表结构后再更新版本号。"""
        version = from_version
        while version < SCHEMA_VERSION:
            steps = MIGRATIONS.get(version)
            if not steps:
                raise SchemaVersionError(
                    f"缺少从模式版本 {version} 升级到 {version + 1} 的迁移步骤，"
                    "已停止升级以避免仅改版本号而不迁移表结构。",
                    found_version=from_version,
                    supported_version=SCHEMA_VERSION,
                )
            for statement in steps:
                conn.execute(statement)
            version += 1
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(version),),
            )

    def initialize_schema(self) -> None:
        """创建或校验数据表结构，并按需执行迁移。

        幂等：重复调用不会报错，也不会删除已有数据。

        Raises:
            SchemaVersionError: 数据库模式版本与本程序不兼容（见类文档）。
            PersistenceError: 数据库无法打开或写入。
        """
        self._require_open()
        with self.transaction() as conn:
            stored = self._read_schema_version(conn)
            self._check_schema_version(stored)

            if stored == SCHEMA_VERSION:
                # 幂等路径：表结构已是最新，仍执行一次 CREATE IF NOT EXISTS，
                # 以修复被外部删掉的索引或缺表（不改变版本号语义）。
                for statement in SCHEMA_STATEMENTS:
                    conn.execute(statement)
                return

            if stored is None:
                # 空数据库：正常初始化
                self._apply_schema(conn)
                return

            # stored < SCHEMA_VERSION 且存在迁移步骤：先迁移，再补齐缺失结构
            self._apply_migrations(conn, stored)
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)

    def table_names(self) -> tuple[str, ...]:
        """返回当前库中全部用户表名（已排序）。"""
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return tuple(row["name"] for row in rows)

    def schema_version(self) -> int | None:
        """返回已写入的模式版本；表或记录不存在时返回 ``None``。

        Note:
            表不存在属于"尚未初始化"的正常情况，返回 ``None``；
            但版本值本身非法时会抛 :class:`PersistenceError`，不会静默吞掉。
        """
        with self.transaction() as conn:
            return self._read_schema_version(conn)


# ---------------------------------------------------------------------------
# 项目仓储
# ---------------------------------------------------------------------------

_PROJECT_COLUMNS = (
    "project_id",
    "name",
    "location",
    "customer_name",
    "project_type",
    "created_at",
    "updated_at",
    "description",
)

_PROJECT_INSERT_SQL = (
    f"INSERT INTO project ({', '.join(_PROJECT_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _PROJECT_COLUMNS)})"
)

_PROJECT_SELECT_SQL = f"SELECT {', '.join(_PROJECT_COLUMNS)} FROM project"


def translate_integrity_error(exc: sqlite3.IntegrityError, *, entity_id: str = "") -> Exception:
    """把 sqlite 完整性错误细分为明确的领域异常。

    只做异常分类，不改动任何数据。

    - 主键/唯一约束 → :class:`EntityAlreadyExistsError`
    - 外键约束 → :class:`PersistenceError`（安全删除策略被触发）
    - ``CHECK`` 约束 → :class:`ValidationError`（字段值违反数据模型约束）
    - 其他完整性错误 → 保持 :class:`PersistenceError`
    """
    message = str(exc)
    upper = message.upper()
    if "UNIQUE CONSTRAINT FAILED" in upper or "PRIMARY KEY" in upper:
        return EntityAlreadyExistsError("项目", entity_id or "未知主键")
    if "FOREIGN KEY CONSTRAINT FAILED" in upper:
        return PersistenceError(
            f"存在关联数据，已按安全删除策略拒绝该操作：{entity_id or '未知主键'}",
            operation="delete",
        )
    if "CHECK CONSTRAINT FAILED" in upper or "NOT NULL CONSTRAINT FAILED" in upper:
        return ValidationError(
            f"数据违反数据库约束，已拒绝写入：{message}",
            issues=(),
        )
    return PersistenceError(f"数据库完整性错误：{message}", operation="constraint")


class ProjectRepository:
    """项目仓储：第一阶段的完整基础 CRUD。"""

    ENTITY_NAME = "项目"

    def __init__(self, database: Database) -> None:
        self._db = database

    # -- 写 -------------------------------------------------------------
    def add(self, project: Project) -> Project:
        """新增项目。

        Raises:
            ValidationError: 项目字段不合法。
            EntityAlreadyExistsError: 主键重复。
            PersistenceError: 其他数据库异常（如名称约束冲突）。
        """
        require_valid_project(project)
        data = project.to_dict()
        try:
            with self._db.transaction() as conn:
                conn.execute(_PROJECT_INSERT_SQL, tuple(data[column] for column in _PROJECT_COLUMNS))
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, entity_id=project.project_id) from exc
        return project

    def update(self, project: Project, *, touch_updated_at: bool = True) -> Project:
        """按主键整体更新项目。

        Args:
            project: 待更新项目，``project_id`` 必须已存在。
            touch_updated_at: 为 ``True`` 时把 ``updated_at`` 刷新为当前 UTC 时间。

        Raises:
            ValidationError: 项目字段不合法。
            EntityNotFoundError: 主键不存在。
            PersistenceError: 其他数据库异常。
        """
        require_valid_project(project)
        data = project.to_dict()
        if touch_updated_at:
            data["updated_at"] = utc_now_iso()
            project.updated_at = data["updated_at"]

        assignments = ", ".join(f"{column} = ?" for column in _PROJECT_COLUMNS if column != "project_id")
        values = [data[column] for column in _PROJECT_COLUMNS if column != "project_id"]
        values.append(project.project_id)
        sql = f"UPDATE project SET {assignments} WHERE project_id = ?"

        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(sql, tuple(values))
                if cursor.rowcount == 0:
                    raise EntityNotFoundError(self.ENTITY_NAME, project.project_id)
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, entity_id=project.project_id) from exc
        return project

    def delete(self, project_id: str) -> None:
        """删除项目（RESTRICT 策略）。

        Raises:
            EntityNotFoundError: 主键不存在。
            PersistenceError: 项目仍有关联数据（外键 RESTRICT）或其他数据库异常。
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute("DELETE FROM project WHERE project_id = ?", (project_id,))
                if cursor.rowcount == 0:
                    raise EntityNotFoundError(self.ENTITY_NAME, project_id)
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, entity_id=project_id) from exc

    # -- 读 -------------------------------------------------------------
    def get(self, project_id: str) -> Project | None:
        """按主键查询项目；不存在返回 ``None``。"""
        with self._db.transaction() as conn:
            row = conn.execute(f"{_PROJECT_SELECT_SQL} WHERE project_id = ?", (project_id,)).fetchone()
        return Project.from_row(dict(row)) if row else None

    def get_or_raise(self, project_id: str) -> Project:
        """按主键查询项目；不存在抛 :class:`EntityNotFoundError`。"""
        project = self.get(project_id)
        if project is None:
            raise EntityNotFoundError(self.ENTITY_NAME, project_id)
        return project

    def list_all(self, *, order_by: str = "updated_at DESC") -> list[Project]:
        """列出全部项目。

        Args:
            order_by: 排序子句。仅允许白名单内的固定取值，
                防止把外部输入拼进 SQL。
        """
        allowed = {
            "updated_at DESC": "updated_at DESC, project_id ASC",
            "created_at DESC": "created_at DESC, project_id ASC",
            "name ASC": "name ASC, project_id ASC",
        }
        if order_by not in allowed:
            raise ValueError(f"不支持的排序方式：{order_by!r}；允许值：{sorted(allowed)}")
        sql = f"{_PROJECT_SELECT_SQL} ORDER BY {allowed[order_by]}"
        with self._db.transaction() as conn:
            rows = conn.execute(sql).fetchall()
        return [Project.from_row(dict(row)) for row in rows]

    def find_by_name(self, name: str) -> list[Project]:
        """按名称精确查询（参数化，不拼接）。"""
        with self._db.transaction() as conn:
            rows = conn.execute(f"{_PROJECT_SELECT_SQL} WHERE name = ? ORDER BY created_at ASC", (name,)).fetchall()
        return [Project.from_row(dict(row)) for row in rows]

    def count(self) -> int:
        """返回项目总数。"""
        with self._db.transaction() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM project").fetchone()
        return int(row["n"])

    # -- 辅助 -----------------------------------------------------------
    # 完整性错误的分类统一由模块级 :func:`translate_integrity_error` 完成，
    # 仓储方法在调用处捕获 ``sqlite3.IntegrityError`` 并传入实体主键。


__all__ = [
    "BUSINESS_TABLES",
    "MIGRATIONS",
    "Database",
    "ProjectRepository",
    "SCHEMA_STATEMENTS",
    "SCHEMA_VERSION",
    "translate_integrity_error",
]
