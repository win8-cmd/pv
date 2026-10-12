"""CENEP 主窗口（PySide6）。

界面职责（严格遵守架构规则）：

- 采集用户输入、调用应用服务、展示结果。
- **不**包含任何消纳或财务公式：消纳结果全部来自
  :meth:`cenep.application.project_service.ProjectService.run_self_consumption`。
- **不**直接执行 SQL。
- 项目创建成功后，数据已真实写入 SQLite；界面刷新自数据库，而不是自内存假数据。

第一阶段刻意保持界面简单：不追求美观，但必须能启动、能操作、能保存、能退出。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cenep import APP_NAME, STAGE, __version__
from cenep.application.bill_service import BillService
from cenep.application.project_service import ProjectService
from cenep.domain.exceptions import CENEPError
from cenep.domain.models import Project, ProjectType
from cenep.ui.bill_page import BillPage

#: 尚未开放的功能（界面必须显式提示，避免用户误以为已可用）
NOT_IMPLEMENTED_FEATURES: tuple[str, ...] = (
    "电费账单 PDF 自动识别与解析（**该路线已取消**；改用人工录入 + Excel 模板导入）",
    "OCR 与复杂版式识别（**已取消**）",
    "全国电价政策自动获取",
    "光伏发电量模拟（pvlib）",
    "完整财务现金流、税务与 IRR/NPV 模型",
    "屋面识别、自动排板与三维展示",
    "储能充放电优化与电力市场交易",
    "Excel / PDF 报告导出",
    "用户权限与云端多用户协同",
)

_PROJECT_TYPE_LABELS: tuple[tuple[ProjectType, str], ...] = (
    (ProjectType.INDUSTRIAL_COMMERCIAL, "工商业分布式"),
    (ProjectType.UTILITY_SCALE, "集中式地面电站"),
    (ProjectType.OTHER, "其他"),
)


class ProjectDialog(QDialog):
    """项目创建 / 编辑对话框。只采集输入，不写库。"""

    def __init__(self, parent: QWidget | None = None, project: Project | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("项目信息" if project is None else "编辑项目")
        self.setMinimumWidth(460)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("必填，例如：某汽车零部件厂 1.2MW 屋顶光伏")
        self._location_edit = QLineEdit()
        self._location_edit.setPlaceholderText("省 / 市 / 区，例如：湖北省武汉市")
        self._customer_edit = QLineEdit()
        self._customer_edit.setPlaceholderText("业主或客户名称")
        self._type_combo = QComboBox()
        for project_type, label in _PROJECT_TYPE_LABELS:
            # 注意：ProjectType 继承自 str，Qt 的 setData 会把枚举转成普通字符串，
            # 因此这里统一以枚举的字符串值作为 USER 数据，取值时再还原为枚举。
            self._type_combo.addItem(label, project_type.value)
        self._description_edit = QTextEdit()
        self._description_edit.setPlaceholderText("项目说明（可空）")
        self._description_edit.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("项目名称 *", self._name_edit)
        form.addRow("项目地址", self._location_edit)
        form.addRow("业主/客户", self._customer_edit)
        form.addRow("项目类型", self._type_combo)
        form.addRow("项目说明", self._description_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if project is not None:
            self._name_edit.setText(project.name)
            self._location_edit.setText(project.location or "")
            self._customer_edit.setText(project.customer_name or "")
            self._description_edit.setPlainText(project.description or "")
            index = self._type_combo.findData(project.project_type.value)
            if index >= 0:
                self._type_combo.setCurrentIndex(index)

    # -- 取值 -----------------------------------------------------------
    def project_name(self) -> str:
        return self._name_edit.text()

    def location(self) -> str | None:
        value = self._location_edit.text().strip()
        return value or None

    def customer_name(self) -> str | None:
        value = self._customer_edit.text().strip()
        return value or None

    def project_type(self) -> ProjectType:
        """返回选中的项目类型枚举（Qt 会存字符串，这里显式还原）。"""
        return ProjectType(self._type_combo.currentData())

    def description(self) -> str | None:
        value = self._description_edit.toPlainText().strip()
        return value or None

    def accept(self) -> None:  # noqa: D102 - 覆写 Qt 方法
        if not self.project_name().strip():
            QMessageBox.warning(self, "输入不完整", "项目名称必填，不能为空白。")
            self._name_edit.setFocus()
            return
        super().accept()


class MainWindow(QMainWindow):
    """CENEP 主窗口。

    Args:
        service: 应用服务；界面只通过它访问业务与数据。
    """

    def __init__(
        self,
        service: ProjectService,
        bill_service: "BillService | None" = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._bill_service = bill_service

        self.setWindowTitle(f"{APP_NAME} {__version__} —— 工商业分布式光伏经济评价")
        self.resize(1080, 760)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addWidget(self._build_header())

        if bill_service is None:
            # 未注入账单服务时退化为单页模式（保持既有行为与测试兼容）
            root.addWidget(self._build_project_group())
            root.addWidget(self._build_calculation_group())
            root.addWidget(self._build_status_group())
        else:
            self._tabs = QTabWidget()
            self._tabs.addTab(self._build_project_tab(), "项目")
            self._bill_page = BillPage(bill_service)
            self._tabs.addTab(self._bill_page, "电费账单")
            self._tabs.addTab(self._build_status_group(), "未开放功能")
            root.addWidget(self._tabs, 1)

        self.refresh_projects()

    def _build_project_tab(self) -> QWidget:
        """项目页：原有项目与消纳计算区域，外加未开放功能提示。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._build_project_group())
        layout.addWidget(self._build_calculation_group())
        layout.addStretch(1)
        return page

    # -- 区域构建 -------------------------------------------------------
    def _build_header(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(f"{APP_NAME} 工商业分布式光伏经济评价软件")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        subtitle = QLabel(
            f"版本 {__version__}　|　当前阶段：{STAGE}　|　"
            "本阶段仅提供工程骨架、项目基础信息管理和光伏消纳计算"
        )
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return box

    def _build_project_group(self) -> QWidget:
        group = QGroupBox("项目基础信息")
        layout = QVBoxLayout(group)

        button_row = QHBoxLayout()
        self._new_button = QPushButton("新建项目")
        self._new_button.clicked.connect(self.on_create_project)
        self._edit_button = QPushButton("编辑选中项目")
        self._edit_button.clicked.connect(self.on_edit_project)
        self._delete_button = QPushButton("删除选中项目")
        self._delete_button.clicked.connect(self.on_delete_project)
        self._refresh_button = QPushButton("刷新列表")
        self._refresh_button.clicked.connect(self.refresh_projects)
        for button in (self._new_button, self._edit_button, self._delete_button, self._refresh_button):
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["项目名称", "项目地址", "业主/客户", "项目类型", "更新时间"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self._table)

        self._project_summary = QLabel("尚未创建项目。")
        layout.addWidget(self._project_summary)
        return group

    def _build_calculation_group(self) -> QWidget:
        group = QGroupBox("光伏消纳计算（核心规则验证，输入为时段电量 kWh）")
        layout = QVBoxLayout(group)

        input_row = QHBoxLayout()
        self._load_edit = QLineEdit("3, 8, 2")
        self._load_edit.setPlaceholderText("各时段用电量，逗号分隔，例如：3, 8, 2")
        self._pv_edit = QLineEdit("5, 4, 2")
        self._pv_edit.setPlaceholderText("各时段光伏发电量，逗号分隔，例如：5, 4, 2")
        self._interval_edit = QLineEdit("60")
        self._interval_edit.setFixedWidth(70)
        input_row.addWidget(QLabel("用电量 kWh"))
        input_row.addWidget(self._load_edit)
        input_row.addWidget(QLabel("光伏发电量 kWh"))
        input_row.addWidget(self._pv_edit)
        input_row.addWidget(QLabel("时段长度/分钟"))
        input_row.addWidget(self._interval_edit)
        layout.addLayout(input_row)

        action_row = QHBoxLayout()
        self._calculate_button = QPushButton("计算消纳")
        self._calculate_button.clicked.connect(self.on_calculate_self_consumption)
        action_row.addWidget(self._calculate_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self._result_view = QTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setFixedHeight(170)
        self._result_view.setPlainText(
            "点击“计算消纳”查看结果。默认示例即验收标准案例：用电量 [3, 8, 2]，发电量 [5, 4, 2]。\n"
            "自用电量 9 kWh，余电上网 2 kWh，电网购电 4 kWh，自用率 9/11，负荷覆盖率 9/13。"
        )
        layout.addWidget(self._result_view)
        return group

    def _build_status_group(self) -> QWidget:
        group = QGroupBox("当前阶段状态与未开放功能")
        layout = QVBoxLayout(group)

        info = QLabel(
            "已实现：项目基础信息新增/查询/修改/删除（SQLite 真实持久化）、"
            "光伏自发自用与余电上网消纳计算、输入校验与错误提示机制。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        not_ready = QLabel("尚未开放（本阶段不提供，点击无效属预期行为）：\n　· " + "\n　· ".join(NOT_IMPLEMENTED_FEATURES))
        not_ready.setWordWrap(True)
        layout.addWidget(not_ready)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)
        return group

    # -- 项目操作 -------------------------------------------------------
    def refresh_projects(self) -> None:
        """自数据库重新加载项目列表（不使用缓存或假数据）。"""
        try:
            projects = self._service.list_projects()
        except CENEPError as exc:
            QMessageBox.critical(self, "读取失败", f"读取项目列表失败：\n{exc}")
            return

        self._table.setRowCount(0)
        for project in projects:
            row = self._table.rowCount()
            self._table.insertRow(row)
            type_label = dict(_PROJECT_TYPE_LABELS).get(project.project_type, project.project_type.value)
            values = (
                project.name,
                project.location or "",
                project.customer_name or "",
                type_label,
                project.updated_at,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, project.project_id)
                self._table.setItem(row, column, item)

        count = len(projects)
        self._project_summary.setText(
            f"共 {count} 个项目（数据来自本地 SQLite：{self._service.database.path}）"
            if count
            else "尚未创建项目。点击“新建项目”创建，数据会真实写入本地 SQLite。"
        )

        # 账单页与项目列表保持同步
        bill_page = getattr(self, "_bill_page", None)
        if bill_page is not None:
            bill_page.refresh_projects(projects)
            bill_page.set_project(self._selected_project_id())

    def _selected_project_id(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def on_create_project(self) -> None:
        dialog = ProjectDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            project = self._service.create_project(
                name=dialog.project_name(),
                location=dialog.location(),
                customer_name=dialog.customer_name(),
                project_type=dialog.project_type(),
                description=dialog.description(),
            )
        except CENEPError as exc:
            QMessageBox.critical(self, "保存失败", f"项目保存失败：\n{exc}")
            return
        self.refresh_projects()
        self._status_label.setText(f"已保存项目：{project.name}（project_id={project.project_id}）")

    def on_edit_project(self) -> None:
        project_id = self._selected_project_id()
        if project_id is None:
            QMessageBox.information(self, "未选择项目", "请先在列表中选择一个项目。")
            return
        try:
            project = self._service.get_project(project_id)
        except CENEPError as exc:
            QMessageBox.critical(self, "读取失败", str(exc))
            return
        dialog = ProjectDialog(self, project=project)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self._service.update_project(
                project_id,
                name=dialog.project_name(),
                location=dialog.location(),
                customer_name=dialog.customer_name(),
                project_type=dialog.project_type(),
                description=dialog.description(),
            )
        except CENEPError as exc:
            QMessageBox.critical(self, "更新失败", f"项目更新失败：\n{exc}")
            return
        self.refresh_projects()
        self._status_label.setText(f"已更新项目：{dialog.project_name()}")

    def on_delete_project(self) -> None:
        project_id = self._selected_project_id()
        if project_id is None:
            QMessageBox.information(self, "未选择项目", "请先在列表中选择一个项目。")
            return
        answer = QMessageBox.question(
            self,
            "确认删除",
            "确认删除选中项目？如该项目已有关联数据，删除会被安全策略拒绝。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._service.delete_project(project_id)
        except CENEPError as exc:
            QMessageBox.critical(self, "删除失败", f"项目删除失败：\n{exc}")
            return
        self.refresh_projects()
        self._status_label.setText("已删除选中项目。")

    # -- 消纳计算 -------------------------------------------------------
    def on_calculate_self_consumption(self) -> None:
        """解析输入 → 调用应用服务计算 → 展示结构化结果。界面不含公式。"""
        try:
            load = _parse_series(self._load_edit.text())
            pv = _parse_series(self._pv_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "输入格式错误", str(exc))
            return

        interval_text = self._interval_edit.text().strip()
        interval: int | None = None
        if interval_text:
            if not interval_text.isdigit() or int(interval_text) <= 0:
                QMessageBox.warning(self, "输入格式错误", "时段长度必须为正整数（分钟）。")
                return
            interval = int(interval_text)

        try:
            result = self._service.run_self_consumption(load, pv, interval_minutes=interval)
        except CENEPError as exc:
            detail = getattr(exc, "format_issues", lambda: str(exc))()
            QMessageBox.warning(self, "输入校验未通过", detail)
            self._result_view.setPlainText(f"计算被拒绝（原始数据未被修改）：\n{detail}")
            return

        self._result_view.setPlainText(_format_result(result))
        self._status_label.setText(f"消纳计算完成，计算规则版本 {result.calculation_version}。")

    def closeEvent(self, event) -> None:  # noqa: D102 - 覆写 Qt 方法
        event.accept()


def _parse_series(text: str) -> list[float]:
    """把逗号/空格分隔的文本解析为数值序列。

    **不做业务修正**：无法解析的输入直接报错，绝不静默丢弃或补 0。
    空文本视为空数组（合法输入）。
    """
    cleaned = text.replace("，", ",").replace("、", ",").strip()
    if not cleaned:
        return []
    values: list[float] = []
    for index, token in enumerate(part for part in cleaned.replace(" ", ",").split(",") if part != ""):
        try:
            values.append(float(token))
        except ValueError as exc:
            raise ValueError(
                f"第 {index + 1} 个数值无法解析：{token!r}。请使用逗号分隔的数值，例如：3, 8, 2。"
            ) from exc
    return values


def _format_result(result) -> str:  # noqa: ANN001 - 避免在界面层导入计算结果类型
    """把结构化计算结果渲染为可读文本（只做展示，不做二次计算）。"""

    def ratio(value: float | None) -> str:
        return "未定义（零分母）" if value is None else f"{value:.6f}（{value * 100:.2f}%）"

    lines = [
        f"计算规则版本：{result.calculation_version}　　时段数：{result.periods}　　"
        f"时间粒度：{result.interval_minutes if result.interval_minutes else '未指定'} 分钟",
        f"输入指纹：{result.input_fingerprint}",
        "",
        f"总用电量　　　　：{result.total_load_kwh:.6f} kWh",
        f"总光伏发电量　　：{result.total_pv_kwh:.6f} kWh",
        f"自用电量　　　　：{result.total_self_consumption_kwh:.6f} kWh",
        f"余电上网电量　　：{result.total_export_kwh:.6f} kWh",
        f"电网购电量　　　：{result.total_grid_import_kwh:.6f} kWh",
        "",
        f"自用率　　　　　：{ratio(result.self_consumption_rate)}",
        f"负荷覆盖率　　　：{ratio(result.load_coverage_rate)}",
        f"余电比例　　　　：{ratio(result.export_rate)}",
        f"状态　　　　　　：{result.status}",
    ]
    if result.notes:
        lines.append("")
        lines.append("提示：")
        lines.extend(f"　· {note.message}" for note in result.notes)
    return "\n".join(lines)


def main() -> int:
    """``cenep-gui`` 脚本入口。"""
    from cenep.app import main as app_main

    return app_main()


__all__ = ["MainWindow", "NOT_IMPLEMENTED_FEATURES", "ProjectDialog", "main"]
