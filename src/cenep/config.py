"""项目级配置：路径解析、常量与运行期开关。

本模块只做**配置读取**，不含业务计算，也不导入 PySide6。

优先级（高 → 低）：

1. 显式函数参数
2. 环境变量（见 ``.env.example``）
3. 默认值

默认数据库位置为 ``%LOCALAPPDATA%\\CENEP\\cenep.db``，
即用户级应用数据目录，**不放在仓库目录内**，避免把真实项目数据提交到 Git。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "CENEP"
APP_VERSION = "0.1.0"
STAGE_NAME = "第一阶段：工程骨架与核心规则冻结"

#: 默认数据库文件名
DEFAULT_DB_FILENAME = "cenep.db"

#: 仓库内文档目录（相对包文件向上回溯）
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent

#: 日志级别（第一阶段仅记录到标准输出/文件，不做复杂配置）
DEFAULT_LOG_LEVEL = "INFO"


def user_data_dir() -> Path:
    """返回用户级数据目录。

    Windows: ``%LOCALAPPDATA%\\CENEP``；
    其他平台: ``~/.local/share/CENEP``（保证非 Windows 环境也能运行测试）。
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def default_database_path() -> Path:
    """返回默认数据库文件路径（不保证父目录已存在）。"""
    return user_data_dir() / DEFAULT_DB_FILENAME


def resolve_database_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """解析最终使用的数据库路径。

    Args:
        explicit: 显式指定路径，优先级最高。

    Returns:
        数据库文件 :class:`pathlib.Path`。
    """
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get("CENEP_DB_PATH", "").strip()
    if env_value:
        return Path(env_value)
    return default_database_path()


def ensure_parent_dir(path: Path) -> Path:
    """确保数据库文件的父目录存在，返回原路径。"""
    parent = path.parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
    return path


def log_level() -> str:
    """读取日志级别环境变量。"""
    return os.environ.get("CENEP_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper() or DEFAULT_LOG_LEVEL


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "DEFAULT_DB_FILENAME",
    "DEFAULT_LOG_LEVEL",
    "PACKAGE_DIR",
    "PROJECT_ROOT",
    "STAGE_NAME",
    "default_database_path",
    "ensure_parent_dir",
    "log_level",
    "resolve_database_path",
    "user_data_dir",
]
