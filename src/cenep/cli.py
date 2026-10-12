"""CENEP 命令行入口。

存在的意义：**没有图形界面也能验证领域计算与数据持久化**。
所有计算命令都直接调用 :mod:`cenep.application`，不复制任何公式。

用法示例::

    python -m cenep.cli init-db
    python -m cenep.cli project-add --name "示例项目" --location "湖北省武汉市"
    python -m cenep.cli project-list
    python -m cenep.cli self-consumption --load 3,8,2 --pv 5,4,2 --interval 60
    python -m cenep.cli self-consumption --load 3,8,2 --pv 5,4,2 --json
    python -m cenep.cli gui
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from cenep import APP_NAME, STAGE, __version__
from cenep.application.project_service import ProjectService
from cenep.domain.exceptions import CENEPError
from cenep.domain.models import Project, ProjectType


def _parse_series(text: str) -> list[float]:
    """解析逗号分隔的数值序列；非法输入直接抛 ``ValueError``，不做静默修正。"""
    cleaned = text.replace("，", ",").replace("、", ",").strip()
    if not cleaned:
        return []
    values: list[float] = []
    for index, token in enumerate(part.strip() for part in cleaned.split(",") if part.strip() != ""):
        try:
            values.append(float(token))
        except ValueError as exc:
            raise ValueError(f"第 {index + 1} 个数值无法解析：{token!r}") from exc
    return values


def _project_row(project: Project) -> dict[str, object]:
    return {
        "project_id": project.project_id,
        "name": project.name,
        "location": project.location,
        "customer_name": project.customer_name,
        "project_type": project.project_type.value,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "description": project.description,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cenep",
        description=f"{APP_NAME} {__version__} —— {STAGE}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", dest="db_path", default=None, help="数据库文件路径（默认使用用户数据目录）")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="初始化数据库与表结构（幂等）")

    add = subparsers.add_parser("project-add", help="新增项目")
    add.add_argument("--name", required=True, help="项目名称（必填）")
    add.add_argument("--location", default=None, help="项目地址")
    add.add_argument("--customer", default=None, help="业主/客户名称")
    add.add_argument(
        "--type",
        dest="project_type",
        default=ProjectType.INDUSTRIAL_COMMERCIAL.value,
        choices=[item.value for item in ProjectType],
        help="项目类型",
    )
    add.add_argument("--description", default=None, help="项目说明")

    subparsers.add_parser("project-list", help="列出全部项目")

    show = subparsers.add_parser("project-show", help="按主键查看项目")
    show.add_argument("project_id", help="项目主键")

    update = subparsers.add_parser("project-update", help="更新项目字段")
    update.add_argument("project_id", help="项目主键")
    update.add_argument("--name", default=None)
    update.add_argument("--location", default=None)
    update.add_argument("--customer", default=None)
    update.add_argument("--type", dest="project_type", default=None, choices=[item.value for item in ProjectType])
    update.add_argument("--description", default=None)

    delete = subparsers.add_parser("project-delete", help="删除项目（存在关联数据时会被拒绝）")
    delete.add_argument("project_id", help="项目主键")

    calc = subparsers.add_parser("self-consumption", help="计算光伏自发自用/余电上网/电网购电")
    calc.add_argument("--load", required=True, help="各时段用电量（kWh），逗号分隔；可为空字符串")
    calc.add_argument("--pv", required=True, help="各时段光伏发电量（kWh），逗号分隔；可为空字符串")
    calc.add_argument("--interval", type=int, default=None, help="时段长度（分钟），可选")
    calc.add_argument("--json", action="store_true", help="以 JSON 输出结构化结果")

    template = subparsers.add_parser(
        "bill-template",
        help="生成电费账单标准 Excel 导入模板（7 张工作表，不依赖宏）",
    )
    template.add_argument(
        "--out",
        dest="out_path",
        default=None,
        help="输出文件路径；默认为当前目录下的标准模板名",
    )
    template.add_argument(
        "--dir",
        dest="out_dir",
        default=None,
        help="输出目录；与 --out 同时提供时以 --out 为准",
    )

    subparsers.add_parser("gui", help="启动 PySide6 图形界面")

    subparsers.add_parser("info", help="显示版本、阶段与运行环境信息")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """命令行主入口。返回进程退出码。"""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "gui":
        from cenep.app import main as app_main

        return app_main()

    if args.command == "info":
        from cenep.app import describe_environment

        payload = describe_environment()
        payload["stage_name"] = STAGE
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "bill-template":
        from cenep.data.template_writer import default_template_path, write_template

        if args.out_path:
            target = Path(args.out_path).expanduser()
        elif args.out_dir:
            target = default_template_path(args.out_dir)
        else:
            target = default_template_path()
        try:
            written = write_template(target)
        except OSError as exc:
            print(f"模板生成失败：{exc}", file=sys.stderr)
            return 4
        print(f"模板已生成：{written}")
        print("工作表：使用说明、月度汇总、分时电量电价、费用明细、计量点、数据校验、样本参考_勿直接测算")
        print("提示：样本参考表仅供字段对照，导入时默认忽略；请勿作为生产数据使用。")
        return 0

    if args.command == "self-consumption":
        try:
            load = _parse_series(args.load)
            pv = _parse_series(args.pv)
        except ValueError as exc:
            print(f"输入解析失败：{exc}", file=sys.stderr)
            return 2
        service = ProjectService()
        try:
            result = service.run_self_consumption(load, pv, interval_minutes=args.interval)
        except CENEPError as exc:
            detail = getattr(exc, "format_issues", lambda: str(exc))()
            print(f"校验失败，未执行计算：\n{detail}", file=sys.stderr)
            return 3
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"计算规则版本：{result.calculation_version}　输入指纹：{result.input_fingerprint}")

            def ratio(value: float | None) -> str:
                return "未定义（零分母）" if value is None else f"{value:.6f}（{value * 100:.2f}%）"

            print(f"总用电量　　　　：{result.total_load_kwh:.6f} kWh")
            print(f"总光伏发电量　　：{result.total_pv_kwh:.6f} kWh")
            print(f"自用电量　　　　：{result.total_self_consumption_kwh:.6f} kWh")
            print(f"余电上网电量　　：{result.total_export_kwh:.6f} kWh")
            print(f"电网购电量　　　：{result.total_grid_import_kwh:.6f} kWh")
            print(f"自用率　　　　　：{ratio(result.self_consumption_rate)}")
            print(f"负荷覆盖率　　　：{ratio(result.load_coverage_rate)}")
            print(f"余电比例　　　　：{ratio(result.export_rate)}")
            print(f"状态　　　　　　：{result.status}")
            for note in result.notes:
                print(f"提示　　　　　　：{note.message}")
        return 0

    # 其余命令都需要数据库
    from cenep import config
    from cenep.infrastructure.database import Database

    db_path = config.ensure_parent_dir(config.resolve_database_path(args.db_path))
    service = ProjectService(Database(db_path))

    try:
        if args.command == "init-db":
            service.initialize()
            print(f"数据库已初始化：{db_path}")
            print(f"模式版本：{service.database.schema_version()}")
            print("数据表：" + ", ".join(service.database.table_names()))
            return 0

        if args.command == "project-add":
            project = service.create_project(
                name=args.name,
                location=args.location,
                customer_name=args.customer,
                project_type=args.project_type,
                description=args.description,
            )
            print(json.dumps(_project_row(project), ensure_ascii=False, indent=2))
            return 0

        if args.command == "project-list":
            projects = service.list_projects()
            if not projects:
                print("暂无项目。")
                return 0
            print(json.dumps([_project_row(item) for item in projects], ensure_ascii=False, indent=2))
            return 0

        if args.command == "project-show":
            print(json.dumps(_project_row(service.get_project(args.project_id)), ensure_ascii=False, indent=2))
            return 0

        if args.command == "project-update":
            project = service.update_project(
                args.project_id,
                name=args.name,
                location=args.location,
                customer_name=args.customer,
                project_type=args.project_type,
                description=args.description,
            )
            print(json.dumps(_project_row(project), ensure_ascii=False, indent=2))
            return 0

        if args.command == "project-delete":
            service.delete_project(args.project_id)
            print(f"已删除项目：{args.project_id}")
            return 0
    except CENEPError as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        return 4

    parser.error(f"未知命令：{args.command}")  # pragma: no cover
    return 1


if __name__ == "__main__":
    sys.exit(main())
