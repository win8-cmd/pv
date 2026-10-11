"""CENEP 应用装配与启动。

``cenep.app.main`` 是 GUI 的统一入口，被以下三种方式复用：

- ``python -m cenep``
- 安装后的 ``cenep-gui`` 脚本
- ``python -m cenep.cli gui``

装配顺序严格遵循依赖方向：界面 ← 应用服务 ← 领域层。
"""

from __future__ import annotations

import sys
from typing import Sequence

from cenep import APP_NAME, STAGE, __version__
from cenep.application.project_service import ProjectService


def build_service(database_path: str | None = None) -> ProjectService:
    """构造应用服务（同时确保数据库与表结构就绪）。"""
    from cenep import config
    from cenep.infrastructure.database import Database

    path = config.ensure_parent_dir(config.resolve_database_path(database_path))
    return ProjectService(Database(path))


def main(argv: Sequence[str] | None = None) -> int:
    """启动桌面主窗口。

    Returns:
        进程退出码。0 表示正常退出。

    Raises:
        SystemExit: PySide6 未安装时以明确的错误信息退出，而不是静默失败。
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        print(
            f"[{APP_NAME}] 未检测到 PySide6，无法启动图形界面。\n"
            f"原因：{exc}\n"
            "请先安装依赖：python -m pip install -e \".[dev]\"\n"
            "无图形界面时仍可使用命令行验证核心计算：python -m cenep.cli self-consumption --help",
            file=sys.stderr,
        )
        return 2

    from cenep.ui.main_window import MainWindow

    arguments = list(argv) if argv is not None else sys.argv
    app = QApplication(arguments)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)

    service = build_service()
    window = MainWindow(service)
    window.show()
    return app.exec()


def describe_environment() -> dict[str, object]:
    """返回运行环境摘要，供界面"当前阶段状态"区域与报告使用。"""
    from cenep.ui import is_qt_available

    return {
        "app_name": APP_NAME,
        "version": __version__,
        "stage": STAGE,
        "python_version": sys.version.split()[0],
        "qt_available": is_qt_available(),
    }


__all__ = ["build_service", "describe_environment", "main"]
