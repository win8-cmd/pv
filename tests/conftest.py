"""pytest 全局夹具。

关键约定：**所有测试使用临时数据库**。
:func:`db_path` 基于 ``tmp_path``，绝不可能指向用户真实的
``%LOCALAPPDATA%\\CENEP\\cenep.db``；并且本文件显式把 ``CENEP_DB_PATH``
环境变量重定向到临时目录，即使被测代码走了默认路径分支也不会碰真实库。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest

# 保证以源码树直接运行 pytest 时也能导入 cenep（无需先 pip install -e）
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cenep.domain.models import Project, ProjectType  # noqa: E402
from cenep.infrastructure.database import Database, ProjectRepository  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_default_database(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """把所有测试的默认数据库路径重定向到临时目录。"""
    isolated = tmp_path_factory.mktemp("cenep-default-db") / "cenep.db"
    monkeypatch.setenv("CENEP_DB_PATH", str(isolated))


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """临时数据库文件路径。"""
    return tmp_path / "test_cenep.db"


@pytest.fixture
def database(db_path: Path) -> Iterator[Database]:
    """已建表的临时数据库。"""
    db = Database(db_path)
    db.initialize_schema()
    yield db


@pytest.fixture
def memory_database() -> Iterator[Database]:
    """内存数据库（同样已建表）。

    ``Database(":memory:")`` 已实现为**共享缓存**内存库，由实例持有锚定连接
    维持其存活，因此可以跨事务读写（回归测试见
    ``tests/integration/test_database_memory_and_schema_version.py``）。
    注意：内存库不能跨 ``Database`` 实例共享，且实例 ``close()`` 后数据消失。
    """
    db = Database(":memory:")
    db.initialize_schema()
    yield db
    db.close()


@pytest.fixture
def repository(database: Database) -> ProjectRepository:
    """绑定临时数据库的项目仓储。"""
    return ProjectRepository(database)


@pytest.fixture
def sample_project() -> Project:
    """标准示例项目。"""
    return Project(
        name="示例：某汽车零部件厂屋顶光伏",
        location="湖北省武汉市",
        customer_name="示例客户有限公司",
        project_type=ProjectType.INDUSTRIAL_COMMERCIAL,
        description="第一阶段测试用示例项目",
    )


@pytest.fixture
def project_service(database: Database):
    """绑定临时数据库的应用服务。"""
    from cenep.application.project_service import ProjectService

    return ProjectService(database)
