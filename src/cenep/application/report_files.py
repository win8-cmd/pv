"""模板与报告文件的生成入口（应用层）。

**为什么需要本模块**：界面层不得直接调用 ``cenep.data`` 的生成器
（``template_writer`` / ``report_writer``）——那会绕过应用层。
本模块提供与界面无关的薄封装，使：

- 界面层只依赖 ``cenep.application``；
- 命令行（``cli.py``）与应用服务复用同一入口，避免"能生成模板"的路径出现两份实现。

本模块不含业务计算，只做"默认文件名 + 落盘"的组织。
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "default_report_file_name",
    "default_template_directory",
    "default_template_file_name",
    "write_report_file",
    "write_template_file",
]


def default_template_directory() -> Path:
    """模板默认输出目录（当前工作目录）。"""
    from cenep.data.template_writer import default_template_path

    return default_template_path().parent


def default_template_file_name() -> str:
    """模板默认文件名。"""
    from cenep.data.template_writer import default_template_path

    return default_template_path().name


def write_template_file(path: str | Path | None = None, *, directory: str | Path | None = None) -> Path:
    """生成标准 Excel 导入模板并返回实际路径。

    Args:
        path: 明确的目标文件路径；给出时忽略 ``directory``。
        directory: 目标目录；未给出 ``path`` 时使用。

    Returns:
        实际写入的路径。

    Raises:
        OSError: 写入失败。
    """
    from cenep.data.template_writer import default_template_path, write_template

    if path is not None:
        target = Path(path).expanduser()
    elif directory is not None:
        target = default_template_path(directory)
    else:
        target = default_template_path()
    return write_template(target)


def default_report_file_name(project_name: str, *, generated_on: str | None = None) -> str:
    """账单报告默认文件名。"""
    from cenep.data.report_writer import default_report_name

    return default_report_name(project_name, generated_on=generated_on)


def write_report_file(bundle, path: str | Path) -> Path:
    """把报告数据写入 Excel 文件。"""
    from cenep.data.report_writer import write_report

    return write_report(bundle, path)
