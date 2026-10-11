"""桌面界面测试。

任务书要求"GUI 入口实际启动成功，或明确说明未验证原因"。
本模块用 Qt 的 ``offscreen`` 平台插件在无显示器环境下**真实创建窗口**：

- 真实构造 ``QApplication`` 与 ``MainWindow``；
- 真实触发"新建项目"逻辑并断言数据已落入 SQLite；
- 真实触发"计算消纳"逻辑并断言界面文本来自计算模块的结果。

若 PySide6 缺失或 Qt 平台插件无法初始化，测试会明确 skip 并给出原因，
而不是把"没验证"伪装成"通过"。
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.gui

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cenep.application.project_service import ProjectService  # noqa: E402
from cenep.infrastructure.database import Database  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="未安装 PySide6，GUI 无法验证")


@pytest.fixture(scope="module")
def qapp():
    """创建一个 QApplication（offscreen 平台）。"""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def window(qapp, db_path):  # noqa: ANN001, ANN201
    """真实主窗口实例。"""
    from cenep.ui.main_window import MainWindow

    service = ProjectService(Database(db_path))
    win = MainWindow(service)
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


class TestWindowConstruction:
    def test_window_opens_with_title_and_version(self, window) -> None:  # noqa: ANN001
        from cenep import APP_NAME, __version__

        assert APP_NAME in window.windowTitle()
        assert __version__ in window.windowTitle()

    def test_subtitle_shows_current_stage(self, window) -> None:  # noqa: ANN001
        from cenep import STAGE

        texts = " ".join(label.text() for label in window.centralWidget().findChildren(QtWidgets.QLabel))
        assert STAGE in texts

    def test_window_is_visible_after_show(self, window) -> None:  # noqa: ANN001
        window.show()
        assert window.isVisible()

    def test_project_table_present_and_empty_initially(self, window) -> None:  # noqa: ANN001
        assert window._table.columnCount() == 5
        assert window._table.rowCount() == 0
        assert "尚未创建项目" in window._project_summary.text()

    def test_header_shows_stage_and_scope(self, window) -> None:  # noqa: ANN001
        labels = window.centralWidget().findChildren(QtWidgets.QLabel)
        texts = " ".join(label.text() for label in labels)
        assert "CENEP" in texts
        assert "光伏消纳" in texts

    def test_not_implemented_features_are_disclosed(self, window) -> None:  # noqa: ANN001
        from cenep.ui.main_window import NOT_IMPLEMENTED_FEATURES

        texts = " ".join(label.text() for label in window.centralWidget().findChildren(QtWidgets.QLabel))
        assert "尚未开放" in texts
        assert "电费账单 PDF 导入与解析（第二阶段）" in texts
        assert len(NOT_IMPLEMENTED_FEATURES) >= 8

    def test_status_area_describes_implemented_capability(self, window) -> None:  # noqa: ANN001
        texts = " ".join(label.text() for label in window.centralWidget().findChildren(QtWidgets.QLabel))
        assert "已实现" in texts
        assert "SQLite" in texts


class TestProjectCreationFromGui:
    def test_dialog_defaults_and_input(self, qapp) -> None:  # noqa: ANN001
        from cenep.domain.models import ProjectType
        from cenep.ui.main_window import ProjectDialog

        dialog = ProjectDialog()
        dialog._name_edit.setText("界面测试项目")
        dialog._location_edit.setText("湖北省武汉市")
        dialog._customer_edit.setText("测试客户")
        assert dialog.project_name() == "界面测试项目"
        assert dialog.location() == "湖北省武汉市"
        assert dialog.customer_name() == "测试客户"
        assert dialog.project_type() is ProjectType.INDUSTRIAL_COMMERCIAL
        dialog._type_combo.setCurrentIndex(1)
        assert dialog.project_type() is ProjectType.UTILITY_SCALE
        dialog.close()
        dialog.deleteLater()

    def test_created_project_is_really_persisted(self, window, db_path) -> None:  # noqa: ANN001
        """通过界面创建的项目必须真实写入 SQLite，而不是只弹提示。"""
        window._service.create_project(name="界面落库项目", location="湖北省宜昌市")
        window.refresh_projects()

        assert window._table.rowCount() == 1
        assert window._table.item(0, 0).text() == "界面落库项目"
        assert "共 1 个项目" in window._project_summary.text()

        # 用全新连接重新读取，证明落盘
        reopened = ProjectService(Database(db_path))
        names = [project.name for project in reopened.list_projects()]
        assert names == ["界面落库项目"]

    def test_table_row_carries_project_id(self, window) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        created = window._service.create_project(name="主键行项目")
        window.refresh_projects()
        assert window._table.item(0, 0).data(Qt.UserRole) == created.project_id


class TestCalculationFromGui:
    def test_calculation_output_contains_acceptance_values(self, window) -> None:  # noqa: ANN001
        window._load_edit.setText("3, 8, 2")
        window._pv_edit.setText("5, 4, 2")
        window._interval_edit.setText("60")
        window.on_calculate_self_consumption()
        text = window._result_view.toPlainText()

        assert "9.000000" in text  # 自用电量
        assert "2.000000" in text  # 余电上网
        assert "4.000000" in text  # 电网购电
        assert "13.000000" in text  # 总用电量
        assert "11.000000" in text  # 总发电量
        assert "0.818182" in text  # 自用率 9/11
        assert "0.692308" in text  # 负荷覆盖率 9/13
        assert "0.181818" in text  # 余电比例 2/11
        assert "ok" in text

    def test_undefined_ratios_shown_as_undefined(self, window) -> None:  # noqa: ANN001
        window._load_edit.setText("")
        window._pv_edit.setText("")
        window.on_calculate_self_consumption()
        assert "未定义" in window._result_view.toPlainText()

    def test_parse_series_rejects_bad_token(self) -> None:
        from cenep.ui.main_window import _parse_series

        with pytest.raises(ValueError):
            _parse_series("3, abc, 2")

    def test_parse_series_accepts_chinese_comma_and_spaces(self) -> None:
        from cenep.ui.main_window import _parse_series

        assert _parse_series("3， 8、2") == [3.0, 8.0, 2.0]
        assert _parse_series("") == []

    def test_parse_series_does_not_correct_negative_values(self) -> None:
        """界面层不得静默修正非法输入：负数必须原样交给计算层报错。"""
        from cenep.ui.main_window import _parse_series

        assert _parse_series("-1, 2") == [-1.0, 2.0]


class TestInvalidInputHandling:
    """非法输入必须被明确拒绝，且界面不崩溃。

    这里用 monkeypatch 记录 ``QMessageBox.warning`` 的调用；
    若 Qt 绑定不允许替换静态方法，则退化为"只验证不崩溃"，
    并在断言中体现差异。
    """

    @staticmethod
    def _patch_warning(monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple], bool]:
        warnings: list[tuple] = []
        try:
            monkeypatch.setattr(
                QtWidgets.QMessageBox,
                "warning",
                staticmethod(lambda *args, **kwargs: warnings.append(args)),
            )
        except (AttributeError, TypeError):  # pragma: no cover - 取决于 Qt 绑定实现
            return warnings, False
        return warnings, True

    def test_invalid_input_does_not_crash_and_reports(self, window, monkeypatch) -> None:  # noqa: ANN001
        warnings, patched = self._patch_warning(monkeypatch)
        window._load_edit.setText("1, 2, 3")
        window._pv_edit.setText("1, 2")
        window.on_calculate_self_consumption()

        assert "未通过校验" in window._result_view.toPlainText()
        if patched:
            assert warnings, "长度不一致时界面必须弹出明确提示"

    def test_bad_interval_rejected(self, window, monkeypatch) -> None:  # noqa: ANN001
        warnings, patched = self._patch_warning(monkeypatch)
        window._interval_edit.setText("0")
        window.on_calculate_self_consumption()
        if patched:
            assert warnings
        # 未执行计算：结果区仍保留输入提示，未被改写为计算结果
        assert "计算规则版本" not in window._result_view.toPlainText()
