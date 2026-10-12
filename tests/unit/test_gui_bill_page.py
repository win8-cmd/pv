"""账单页面与主窗口标签页的界面测试。

任务书要求"GUI 入口实际启动成功，或明确说明未验证原因"。
本模块用 Qt 的 ``offscreen`` 平台插件在无显示器环境下**真实创建控件**：

- 真实构造 ``MainWindow(service, bill_service)`` 并断言出现"电费账单"标签页；
- 真实构造 ``BillPage``，真实触发录入 / 确认 / 复制逻辑并断言数据落入 SQLite；
- 断言失败时走 ``QMessageBox.critical``（用 monkeypatch 捕获，不弹真窗口）；
- 断言未提供字段在界面上显示"未提供"而不是 0。

若 PySide6 缺失或 Qt 平台插件无法初始化，测试会明确 skip 并给出原因，
而不是把"没验证"伪装成"通过"。
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.gui

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cenep.application.bill_service import BillService, ManualBillInput  # noqa: E402
from cenep.application.project_service import ProjectService  # noqa: E402
from cenep.domain.models import Project  # noqa: E402
from cenep.infrastructure.database import Database, ProjectRepository  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="未安装 PySide6，GUI 无法验证")


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def services(tmp_path):
    """同一数据库文件上的项目服务与账单服务。"""
    db = Database(tmp_path / "gui.db")
    db.initialize_schema()
    project = ProjectRepository(db).add(Project(name="界面测试项目"))
    yield ProjectService(db), BillService(db), project.project_id
    db.close()


@pytest.fixture
def page(qapp, services):
    from cenep.ui.bill_page import BillPage

    _, bill_service, project_id = services
    widget = BillPage(bill_service)
    projects = [Project(project_id=project_id, name="界面测试项目")]
    widget.refresh_projects(projects)
    widget.set_project(project_id)
    yield widget
    widget.deleteLater()
    qapp.processEvents()


class TestMainWindowTabs:
    def test_bill_tab_appears_when_service_injected(self, qapp, services) -> None:
        from cenep.ui.main_window import MainWindow

        project_service, bill_service, _ = services
        window = MainWindow(project_service, bill_service)
        try:
            tabs = window.centralWidget().findChildren(QtWidgets.QTabWidget)
            assert tabs, "注入账单服务后应使用标签页布局"
            titles = [tabs[0].tabText(index) for index in range(tabs[0].count())]
            assert "项目" in titles
            assert "电费账单" in titles
        finally:
            window.close()
            window.deleteLater()
            qapp.processEvents()

    def test_window_still_works_without_bill_service(self, qapp, services) -> None:
        """未注入账单服务时退化为单页模式，既有行为不变。"""
        from cenep.ui.main_window import MainWindow

        project_service, _, _ = services
        window = MainWindow(project_service)
        try:
            tabs = window.centralWidget().findChildren(QtWidgets.QTabWidget)
            assert not tabs, "未注入账单服务时不应出现标签页"
            texts = " ".join(
                label.text()
                for label in window.centralWidget().findChildren(QtWidgets.QLabel)
            )
            assert "尚未开放" in texts
        finally:
            window.close()
            window.deleteLater()
            qapp.processEvents()

    def test_cancelled_pdf_route_is_disclosed(self, qapp, services) -> None:
        """PDF 自动识别必须明确标注"已取消"，且不得再写"第二阶段"。"""
        from cenep.ui.main_window import NOT_IMPLEMENTED_FEATURES

        joined = " ".join(NOT_IMPLEMENTED_FEATURES)
        assert "已取消" in joined
        assert "Excel 模板导入" in joined
        assert not any("第二阶段" in item for item in NOT_IMPLEMENTED_FEATURES)


class TestBillPageRendering:
    def test_empty_project_shows_guidance(self, page) -> None:
        texts = " ".join(
            label.text() for label in page.findChildren(QtWidgets.QLabel)
        )
        assert "账单数" in texts or "暂无账单" in texts

    def test_buttons_disabled_without_selection(self, page) -> None:
        assert page._edit_button.isEnabled() is False
        assert page._copy_button.isEnabled() is False
        assert page._delete_button.isEnabled() is False
        assert page._confirm_button.isEnabled() is False
        assert page._create_button.isEnabled() is True

    def test_table_columns_match_spec(self, page) -> None:
        headers = [
            page._table.horizontalHeaderItem(index).text()
            for index in range(page._table.columnCount())
        ]
        assert "账期" in headers
        assert "本期总电量_kWh" in headers
        assert "账单本期电费_元" in headers
        assert "复核状态" in headers
        assert "确认状态" in headers
        assert "可用于测算" in headers


class TestBillPageWithData:
    def _add(self, services, page, **overrides):
        _, bill_service, project_id = services
        payload = dict(
            billing_period="2025-09",
            period_start="2025-09-01",
            period_end="2025-09-30",
            account_number="1234567890",
            total_energy_kwh="8780498",
            total_amount_yuan="6699241.94",
            source_file="2025-09账单.pdf",
            source_page="1",
            review_status="已复核",
        )
        payload.update(overrides)
        bill_service.create_bill(project_id, ManualBillInput(**payload))
        page.refresh_bills()
        return bill_service

    def test_bill_appears_in_table(self, services, page) -> None:
        self._add(services, page)
        assert page._table.rowCount() == 1
        assert page._table.item(0, 0).text() == "2025-09"

    def test_missing_value_shows_not_provided(self, services, page) -> None:
        """未提供的金额在界面上必须显示"未提供"，而不是 0。"""
        self._add(services, page, vat_invoice_amount_yuan=None)
        texts = " ".join(
            label.text() for label in page.findChildren(QtWidgets.QLabel)
        )
        assert "可用于正式测算" in texts
        # 详情里应显示未提供
        page._table.selectRow(0)
        detail = page._detail.toPlainText()
        assert "增值税专票金额 元：未提供" in detail
        assert "增值税专票金额 元：0" not in detail

    def test_new_bill_shows_not_confirmed(self, services, page) -> None:
        self._add(services, page)
        assert page._table.item(0, 5).text() == "待确认"
        assert page._table.item(0, 6).text() == "否", "未确认不得标记为可用于测算"

    def test_summary_shows_usable_count_zero(self, services, page) -> None:
        self._add(services, page)
        assert "可用于正式测算的账单：0 条" in page._summary.text()

    def test_confirm_enables_usable_count(self, services, page) -> None:
        self._add(services, page)
        page._table.selectRow(0)
        page.on_confirm()
        assert page._table.item(0, 5).text() == "已确认"
        assert page._table.item(0, 6).text() == "是"
        assert "可用于正式测算的账单：1 条" in page._summary.text()

    def test_detail_warns_about_average_price(self, services, page) -> None:
        """详情必须提示平均电价不能当作光伏边际节省电价。"""
        self._add(services, page)
        page._table.selectRow(0)
        assert "不能作为光伏边际节省电价" in page._detail.toPlainText()

    def test_delete_removes_row(self, services, page, monkeypatch) -> None:
        self._add(services, page)
        page._table.selectRow(0)
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "question", lambda *a, **k: QtWidgets.QMessageBox.Yes
        )
        page.on_delete()
        assert page._table.rowCount() == 0


class TestBillPageErrors:
    def test_invalid_input_shows_critical_not_silent(self, services, page, monkeypatch) -> None:
        """非法输入必须走 QMessageBox.critical，且不得产生数据。"""
        _, bill_service, project_id = services
        captured: list[tuple] = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "critical",
            lambda *args, **kwargs: captured.append(args),
        )

        class _Dialog:
            def exec(self):  # noqa: ANN201
                return QtWidgets.QDialog.Accepted

        monkeypatch.setattr(
            "cenep.ui.bill_page.BillDialog",
            lambda *a, **k: _FakeDialog(_Dialog(), bad=True),
        )
        page.on_create()
        assert captured, "非法输入必须弹出错误提示"
        assert bill_service.list_bills(project_id) == [], "失败时不得写入数据"

    def test_cancelled_dialog_writes_nothing(self, services, page, monkeypatch) -> None:
        _, bill_service, project_id = services
        monkeypatch.setattr(
            "cenep.ui.bill_page.BillDialog",
            lambda *a, **k: _FakeDialog(cancelled=True),
        )
        page.on_create()
        assert bill_service.list_bills(project_id) == []

    def test_confirm_failure_surfaces_error(self, services, page, monkeypatch) -> None:
        """样本账单不得确认：界面必须报错而不是静默成功。"""
        _, bill_service, project_id = services
        bill_service.create_bill(
            project_id,
            ManualBillInput(
                billing_period="2025-09",
                account_number="1",
                total_energy_kwh="1",
                total_amount_yuan="2",
            ),
            is_sample=True,
        )
        page.refresh_bills()
        page._table.selectRow(0)
        captured: list[tuple] = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "critical", lambda *a, **k: captured.append(a)
        )
        page.on_confirm()
        assert captured, "样本确认失败必须报错"
        assert "样本" in str(captured[0])


class TestReportExportFromGui:
    def test_report_button_exists(self, page) -> None:
        buttons = [b.text() for b in page.findChildren(QtWidgets.QPushButton)]
        assert "导出账单报告" in buttons

    def test_export_refuses_empty_project(self, page, monkeypatch) -> None:
        """无账单时不得导出空报告，必须报错。"""
        captured: list[tuple] = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "critical", lambda *a, **k: captured.append(a)
        )
        page.on_export_report()
        assert captured, "空项目导出必须报错"

    def test_export_writes_report(self, services, page, monkeypatch, tmp_path) -> None:
        """点击导出必须真实生成 6 张工作表的 xlsx。"""
        from openpyxl import load_workbook

        from cenep.data.report_writer import REPORT_SHEET_NAMES

        self._add(services, page)
        target = tmp_path / "gui_report.xlsx"
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getSaveFileName",
            lambda *a, **k: (str(target), "Excel 文件 (*.xlsx)"),
        )
        captured: list[tuple] = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "information", lambda *a, **k: captured.append(a)
        )

        page.on_export_report()

        assert target.exists(), "报告文件必须真实生成"
        workbook = load_workbook(target)
        assert tuple(workbook.sheetnames) == REPORT_SHEET_NAMES
        assert captured, "导出后应提示结果"

    def test_export_cancelled_writes_nothing(self, services, page, monkeypatch, tmp_path) -> None:
        self._add(services, page)
        monkeypatch.setattr(
            QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: ("", "")
        )
        page.on_export_report()
        assert list(tmp_path.glob("*.xlsx")) == [], "取消后不得生成文件"

    def test_export_failure_surfaces_error(
        self, services, page, monkeypatch, tmp_path
    ) -> None:
        """写入失败必须报错，不得静默。

        用"把普通文件当目录用"来构造必然失败的目标：
        该写法在 Windows 与 Linux 上都会抛 OSError，
        而 `"Z:/..."` 这类盘符路径在 Linux 上只是普通相对路径、会写入成功
        （跨平台陷阱，实测发现）。
        """
        self._add(services, page)
        blocker = tmp_path / "not_a_directory"
        blocker.write_text("占位文件，用于让同名目录创建失败", encoding="utf-8")
        bad_target = blocker / "r.xlsx"
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getSaveFileName",
            lambda *a, **k: (str(bad_target), ""),
        )
        captured: list[tuple] = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "critical", lambda *a, **k: captured.append(a)
        )
        page.on_export_report()
        assert captured, "导出失败必须报错"

    def _add(self, services, page, **overrides):
        _, bill_service, project_id = services
        payload = dict(
            billing_period="2025-09",
            period_start="2025-09-01",
            period_end="2025-09-30",
            account_number="1234567890",
            total_energy_kwh="8780498",
            total_amount_yuan="6699241.94",
            source_file="2025-09账单.pdf",
            source_page="1",
            review_status="已复核",
        )
        payload.update(overrides)
        bill_service.create_bill(project_id, ManualBillInput(**payload))
        page.refresh_bills()


class _FakeDialog:
    """替代 BillDialog 的测试替身（不弹真窗口）。"""

    def __init__(self, wrapped=None, *, bad: bool = False, cancelled: bool = False) -> None:
        self._wrapped = wrapped
        self._bad = bad
        self._cancelled = cancelled

    def setWindowTitle(self, _title: str) -> None:  # noqa: N802 - 模仿 Qt 命名
        return None

    def exec(self) -> int:  # noqa: N802
        if self._cancelled:
            return QtWidgets.QDialog.Rejected
        if self._wrapped is not None:
            return self._wrapped.exec()
        return QtWidgets.QDialog.Accepted

    def payload(self) -> ManualBillInput:
        if self._bad:
            # 电量填了非数值文本 → 服务层必须拒绝（数值解析失败）
            return ManualBillInput(
                billing_period="2025-09",
                account_number="123",
                total_energy_kwh="约八百八十万",
                total_amount_yuan="200",
            )
        return ManualBillInput(
            billing_period="2025-09",
            period_start="2025-09-01",
            period_end="2025-09-30",
            account_number="123",
            total_energy_kwh="100",
            total_amount_yuan="200",
        )
