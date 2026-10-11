"""包安装与应用可运行性测试。

覆盖任务书第 14.C 节"应用验证"中可在无 GUI 条件下自动化的部分：

- 项目已可安装（``cenep`` 可导入、``pyproject.toml`` 元数据正确）。
- Python 包全部模块可导入。
- 核心模块可独立运行（不启动 GUI）。
- 命令行入口可执行。
- 项目可以真实保存并重新读取。
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import cenep
from cenep import APP_NAME, __version__
from cenep.application.project_service import ProjectService
from cenep.calculations.self_consumption import calculate_self_consumption
from cenep.infrastructure.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestPackageMetadata:
    def test_package_importable(self) -> None:
        assert cenep.APP_NAME == "CENEP"
        assert cenep.__version__
        assert cenep.STAGE

    def test_pyproject_metadata_matches_package(self) -> None:
        text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "cenep"' in text
        assert f'version = "{__version__}"' in text
        assert 'requires-python = ">=3.11"' in text
        assert "PySide6" in text
        assert "pytest" in text
        assert "[tool.pytest.ini_options]" in text

    def test_installable_metadata_via_importlib(self) -> None:
        from importlib.metadata import PackageNotFoundError, version

        try:
            installed = version("cenep")
        except PackageNotFoundError:  # pragma: no cover - 未安装时的兜底
            pytest.skip("cenep 未以发行版形式安装（未执行 pip install -e .）")
        assert installed == __version__

    def test_all_submodules_import(self) -> None:
        failures: list[str] = []
        for module_info in pkgutil.walk_packages(cenep.__path__, prefix="cenep."):
            name = module_info.name
            if name.endswith(".__main__"):
                continue
            try:
                importlib.import_module(name)
            except Exception as exc:  # pragma: no cover - 失败时收集信息
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
        assert not failures, "以下模块无法导入：\n" + "\n".join(failures)

    def test_py_typed_marker_present(self) -> None:
        assert (PROJECT_ROOT / "src" / "cenep" / "py.typed").exists()


class TestCoreModulesRunWithoutGui:
    def test_calculation_runs_without_any_database(self) -> None:
        """核心计算不依赖数据库、不依赖 GUI。"""
        result = calculate_self_consumption([3, 8, 2], [5, 4, 2])
        assert result.total_self_consumption_kwh == pytest.approx(9.0)

    def test_service_calculation_returns_acceptance_values(self, database: Database) -> None:
        service = ProjectService(database)
        result = service.run_self_consumption([3, 8, 2], [5, 4, 2], interval_minutes=60)
        assert result.total_load_kwh == pytest.approx(13.0)
        assert result.total_pv_kwh == pytest.approx(11.0)
        assert result.total_self_consumption_kwh == pytest.approx(9.0)
        assert result.total_export_kwh == pytest.approx(2.0)
        assert result.total_grid_import_kwh == pytest.approx(4.0)

    def test_stage_info_reports_versions(self, database: Database) -> None:
        info = ProjectService.stage_info()
        assert info["calculation_engine_version"]
        assert info["assumptions_version"]
        assert info["calculation_type"] == "self_consumption"

    def test_describe_environment_does_not_launch_gui(self) -> None:
        from cenep.app import describe_environment

        payload = describe_environment()
        assert payload["app_name"] == APP_NAME
        assert payload["version"] == __version__
        assert isinstance(payload["qt_available"], bool)

    def test_gui_availability_helper_is_boolean(self) -> None:
        from cenep.ui import is_qt_available

        assert isinstance(is_qt_available(), bool)


class TestCommandLineInterface:
    def test_cli_main_self_consumption_human_readable(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        exit_code = cli.main(["--db", str(tmp_path / "cli.db"), "self-consumption", "--load", "3,8,2", "--pv", "5,4,2"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "自用电量" in captured.out
        assert "9.000000" in captured.out

    def test_cli_main_self_consumption_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        exit_code = cli.main(
            ["--db", str(tmp_path / "cli.db"), "self-consumption", "--load", "3,8,2", "--pv", "5,4,2", "--json"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["total_self_consumption_kwh"] == pytest.approx(9.0)
        assert payload["self_consumption_rate"] == pytest.approx(9 / 11)

    def test_cli_invalid_input_returns_nonzero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        exit_code = cli.main(["--db", str(tmp_path / "cli.db"), "self-consumption", "--load", "3,8,2", "--pv", "5,4"])
        captured = capsys.readouterr()
        assert exit_code == 3
        assert "校验失败" in captured.err

    def test_cli_empty_series_is_accepted(self, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        exit_code = cli.main(["self-consumption", "--load", "", "--pv", "", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["status"] == "undefined_ratio"
        assert payload["self_consumption_rate"] is None

    def test_cli_project_lifecycle(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        db = str(tmp_path / "cli_project.db")

        assert cli.main(["--db", db, "init-db"]) == 0
        assert "数据库已初始化" in capsys.readouterr().out

        assert cli.main(["--db", db, "project-add", "--name", "CLI 项目", "--location", "湖北省武汉市"]) == 0
        created = json.loads(capsys.readouterr().out)
        project_id = created["project_id"]
        assert created["name"] == "CLI 项目"

        assert cli.main(["--db", db, "project-list"]) == 0
        listed = json.loads(capsys.readouterr().out)
        assert len(listed) == 1

        assert cli.main(["--db", db, "project-show", project_id]) == 0
        shown = json.loads(capsys.readouterr().out)
        assert shown["project_id"] == project_id

        assert cli.main(["--db", db, "project-update", project_id, "--name", "改名后"]) == 0
        updated = json.loads(capsys.readouterr().out)
        assert updated["name"] == "改名后"

        assert cli.main(["--db", db, "project-delete", project_id]) == 0
        assert "已删除项目" in capsys.readouterr().out

        assert cli.main(["--db", db, "project-list"]) == 0
        assert "暂无项目" in capsys.readouterr().out

    def test_cli_missing_project_returns_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        exit_code = cli.main(["--db", str(tmp_path / "cli_missing.db"), "project-show", "0" * 32])
        assert exit_code == 4
        assert "操作失败" in capsys.readouterr().err

    def test_cli_blank_name_rejected(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        exit_code = cli.main(["--db", str(tmp_path / "cli_blank.db"), "project-add", "--name", "   "])
        assert exit_code == 4
        assert "操作失败" in capsys.readouterr().err

    def test_cli_info_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        from cenep import cli

        assert cli.main(["info"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["app_name"] == APP_NAME
        assert payload["stage_name"]

    def test_cli_runs_as_real_subprocess(self, tmp_path: Path) -> None:
        """真实子进程端到端验证（证明模块可执行、退出码正确）。"""
        import os

        env = dict(os.environ)
        # 强制子进程使用 UTF-8 标准输出，避免 Windows 默认控制台代码页造成的乱码
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "cenep.cli",
                "--db",
                str(tmp_path / "subprocess.db"),
                "project-add",
                "--name",
                "子进程项目",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["name"] == "子进程项目"
        assert (tmp_path / "subprocess.db").exists()


class TestPersistenceRoundTrip:
    def test_project_saved_and_reread_by_new_service(self, db_path: Path) -> None:
        first = ProjectService(Database(db_path))
        created = first.create_project(name="落盘验证项目", location="湖北省襄阳市")

        second = ProjectService(Database(db_path))
        loaded = second.get_project(created.project_id)
        assert loaded.name == "落盘验证项目"
        assert loaded.location == "湖北省襄阳市"

    def test_multiple_projects_isolated_on_disk(self, db_path: Path) -> None:
        service = ProjectService(Database(db_path))
        service.create_project(name="A")
        service.create_project(name="B")
        reopened = ProjectService(Database(db_path))
        names = sorted(project.name for project in reopened.list_projects())
        assert names == ["A", "B"]
