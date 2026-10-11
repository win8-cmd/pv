"""表现层（PySide6 桌面界面）。

本层只负责显示与采集用户输入：

1. 不实现任何光伏消纳或财务公式 —— 一律调用 :mod:`cenep.application`。
2. 不直接访问 SQLite 或执行 SQL。
3. 不修改用户输入（不自动补 0、不丢弃非法行）。

PySide6 采用延迟导入：本模块可以在未安装 Qt 的环境中导入成功
（例如服务器上没有图形库时运行纯领域测试），只有真正创建窗口时才会要求 Qt。
"""

from __future__ import annotations

__all__: list[str] = []


def is_qt_available() -> bool:
    """检测当前环境能否导入 PySide6。"""
    try:
        import PySide6.QtWidgets  # noqa: F401
    except Exception:
        return False
    return True


def main() -> int:
    """启动桌面应用入口（``cenep-gui`` / ``python -m cenep``）。"""
    from cenep.app import main as _main

    return _main()
