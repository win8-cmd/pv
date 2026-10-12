"""账单页面：人工录入 / Excel 导入 / 校验结果 / 人工确认。

界面层职责边界（规格书第 41 节）：

- **只调用** :class:`cenep.application.bill_service.BillService`，
  不直接访问数据库、仓储或 Excel 读写细节；
- **不含任何业务公式**：金额合计等由服务层汇总后返回，界面只做显示；
- **不虚报成功**：失败一律 ``QMessageBox.critical`` 报错，
  且**禁止**出现"保存成功"之类在未真正落库时就显示的文案；
- 关键结果必须显式展示"未确认不得用于正式测算"。

页面结构：

1. 顶部：项目选择 + 刷新；
2. 左：账单列表（账期、户号、电量、金额、复核状态、确认状态）；
3. 右：账单详情（关键字段 + 13 类校验结果）；
4. 底部：操作按钮（新增、编辑、复制上月、删除、确认、导入 Excel、下载模板）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cenep.application.bill_service import BillService, ManualBillInput
from cenep.data.bill_import_service import (
    DuplicateDecision,
    ImportDecision,
    ImportPreview,
)
from cenep.data.template_reader import TemplateReadError
from cenep.data.report_writer import default_report_name
from cenep.data.template_writer import default_template_path, write_template
from cenep.domain.bill_models import ElectricityBill, ReviewStatus
from cenep.domain.exceptions import CENEPError

__all__ = ["BillDialog", "BillPage", "ImportPreviewDialog"]

#: 列表列定义：``(标题, 取值函数)``
_LIST_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("账期", lambda bill: bill.billing_period or ""),
    ("户号", lambda bill: bill.account_number or ""),
    ("本期总电量_kWh", lambda bill: _num(bill.total_energy_kwh)),
    ("账单本期电费_元", lambda bill: _num(bill.total_amount_yuan)),
    ("复核状态", lambda bill: bill.review_status.value),
    ("确认状态", lambda bill: bill.confirmation.value),
    ("可用于测算", lambda bill: "是" if bill.is_usable_for_calculation else "否"),
    ("来源", lambda bill: bill.source_file or ""),
)

#: 需量单位可选值
_DEMAND_UNITS: tuple[str, ...] = ("", "kW", "kVA")

#: 复核状态可选值
_REVIEW_OPTIONS: tuple[str, ...] = tuple(item.value for item in ReviewStatus)


def _num(value: Any) -> str:
    """数值显示：未提供显示"未提供"，不显示 0。"""
    return "未提供" if value is None else str(value)


def _text_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


class BillDialog(QDialog):
    """账单录入 / 编辑对话框。只采集输入，不写库。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        bill: ElectricityBill | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增账单" if bill is None else "编辑账单")
        self.setMinimumWidth(560)

        self._period = QLineEdit()
        self._period.setPlaceholderText("YYYY-MM，例如 2025-09")
        self._period_start = QLineEdit()
        self._period_start.setPlaceholderText("YYYY-MM-DD")
        self._period_end = QLineEdit()
        self._period_end.setPlaceholderText("YYYY-MM-DD")
        self._account = QLineEdit()
        self._account.setPlaceholderText("用电户号")
        self._customer = QLineEdit()
        self._supply_company = QLineEdit()
        self._energy = QLineEdit()
        self._energy.setPlaceholderText("留空表示未提供，不会当作 0")
        self._amount = QLineEdit()
        self._amount.setPlaceholderText("留空表示未提供，不会当作 0")
        self._vat = QLineEdit()
        self._average_price = QLineEdit()
        self._power_factor_fee = QLineEdit()
        self._power_factor_fee.setPlaceholderText("可为负数")
        self._demand_charge = QLineEdit()
        self._actual_demand = QLineEdit()
        self._demand_unit = QComboBox()
        self._demand_unit.addItems(_DEMAND_UNITS)
        self._review = QComboBox()
        self._review.addItems(_REVIEW_OPTIONS)
        self._source_file = QLineEdit()
        self._source_page = QLineEdit()
        self._note = QTextEdit()
        self._note.setFixedHeight(60)

        form = QFormLayout()
        form.addRow("账期 *", self._period)
        form.addRow("账期开始 *", self._period_start)
        form.addRow("账期结束 *", self._period_end)
        form.addRow("户号", self._account)
        form.addRow("用户名称", self._customer)
        form.addRow("供电单位", self._supply_company)
        form.addRow("本期总电量 kWh *", self._energy)
        form.addRow("账单本期电费 元 *", self._amount)
        form.addRow("增值税专票金额 元", self._vat)
        form.addRow("账单展示平均电价 元/kWh", self._average_price)
        form.addRow("功率因数调整电费 元", self._power_factor_fee)
        form.addRow("需量电费 元", self._demand_charge)
        form.addRow("实际最大需量", self._actual_demand)
        form.addRow("需量单位", self._demand_unit)
        form.addRow("复核状态", self._review)
        form.addRow("来源文件", self._source_file)
        form.addRow("来源页码", self._source_page)
        form.addRow("备注", self._note)

        hint = QLabel(
            "说明：留空的金额/电量会保存为“未提供”，<b>不会当作 0</b>；"
            "功率因数调整电费等允许填负数。\n"
            "新增后账单为“待确认”，<b>未确认不得用于正式测算</b>。"
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        if bill is not None:
            self._period.setText(_text_or_empty(bill.billing_period))
            self._period_start.setText(
                bill.period_start.isoformat() if bill.period_start else ""
            )
            self._period_end.setText(bill.period_end.isoformat() if bill.period_end else "")
            self._account.setText(_text_or_empty(bill.account_number))
            self._customer.setText(_text_or_empty(bill.customer_name))
            self._supply_company.setText(_text_or_empty(bill.supply_company))
            # 未提供的字段显示为空，而不是 0
            self._energy.setText(
                "" if bill.total_energy_kwh is None else str(bill.total_energy_kwh)
            )
            self._amount.setText(
                "" if bill.total_amount_yuan is None else str(bill.total_amount_yuan)
            )
            self._vat.setText(
                "" if bill.vat_invoice_amount_yuan is None
                else str(bill.vat_invoice_amount_yuan)
            )
            self._average_price.setText(
                "" if bill.displayed_average_price is None
                else str(bill.displayed_average_price)
            )
            self._power_factor_fee.setText(
                "" if bill.power_factor_adjustment_fee_yuan is None
                else str(bill.power_factor_adjustment_fee_yuan)
            )
            self._demand_charge.setText(
                "" if bill.demand_charge_yuan is None else str(bill.demand_charge_yuan)
            )
            self._actual_demand.setText(
                "" if bill.actual_demand is None else str(bill.actual_demand)
            )
            index = self._demand_unit.findText(bill.actual_demand_unit or "")
            self._demand_unit.setCurrentIndex(index if index >= 0 else 0)
            review_index = self._review.findText(bill.review_status.value)
            self._review.setCurrentIndex(review_index if review_index >= 0 else 0)
            self._source_file.setText(_text_or_empty(bill.source_file))
            self._source_page.setText(_text_or_empty(bill.source_page))
            self._note.setPlainText(_text_or_empty(bill.note))

    def payload(self) -> ManualBillInput:
        """采集为服务层输入（空字符串表示未提供）。"""
        return ManualBillInput(
            billing_period=self._period.text(),
            period_start=self._period_start.text(),
            period_end=self._period_end.text(),
            account_number=self._account.text(),
            customer_name=self._customer.text(),
            supply_company=self._supply_company.text(),
            total_energy_kwh=self._energy.text(),
            total_amount_yuan=self._amount.text(),
            vat_invoice_amount_yuan=self._vat.text(),
            displayed_average_price=self._average_price.text(),
            power_factor_adjustment_fee_yuan=self._power_factor_fee.text(),
            demand_charge_yuan=self._demand_charge.text(),
            actual_demand=self._actual_demand.text(),
            actual_demand_unit=self._demand_unit.currentText(),
            review_status=self._review.currentText(),
            source_file=self._source_file.text(),
            source_page=self._source_page.text(),
            note=self._note.toPlainText(),
        )


class ImportPreviewDialog(QDialog):
    """导入预览对话框：展示计数、错误定位与重复项，由用户决定是否导入。

    **不自动导入**：用户必须显式选择决策。
    """

    def __init__(self, preview: ImportPreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"导入预览 — {preview.file_name}")
        self.setMinimumSize(760, 520)
        self._preview = preview
        self.decision: ImportDecision = ImportDecision.CANCEL
        self.duplicate_decision: DuplicateDecision | None = None

        counts = preview.counts
        summary = QLabel(
            f"<b>记录总数 {counts.total}</b>　"
            f"有效 <b>{counts.valid}</b>　警告 <b>{counts.warning}</b>　"
            f"无效 <b>{counts.invalid}</b><br>"
            f"模板版本：{preview.template_version or '未识别'}　"
            f"阻断级问题：<b>{'有' if preview.has_blocking_issues else '无'}</b>　"
            f"疑似重复：<b>{len(preview.duplicates)} 项</b>"
        )
        summary.setWordWrap(True)

        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(self._build_details(preview))

        duplicate_row = QHBoxLayout()
        duplicate_row.addWidget(QLabel("重复记录处理："))
        self._duplicate_combo = QComboBox()
        for item in DuplicateDecision:
            self._duplicate_combo.addItem(item.value, item.value)
        self._duplicate_combo.setEnabled(preview.has_duplicates)
        duplicate_row.addWidget(self._duplicate_combo)
        duplicate_row.addStretch(1)
        if not preview.has_duplicates:
            duplicate_row.addWidget(QLabel("（未检测到重复，无需选择）"))

        buttons = QDialogButtonBox()
        self._valid_only = buttons.addButton("仅导入有效记录", QDialogButtonBox.AcceptRole)
        self._import_all = buttons.addButton("导入全部记录", QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton("取消导入", QDialogButtonBox.RejectRole)
        self._import_all.setEnabled(not preview.has_blocking_issues)
        self._valid_only.clicked.connect(lambda: self._finish(ImportDecision.VALID_ONLY))
        self._import_all.clicked.connect(lambda: self._finish(ImportDecision.IMPORT_ALL))
        cancel.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(QLabel("问题明细（含工作表与行号）："))
        layout.addWidget(details)
        layout.addLayout(duplicate_row)
        layout.addWidget(buttons)

    @staticmethod
    def _build_details(preview: ImportPreview) -> str:
        lines: list[str] = []
        if preview.warnings:
            lines.append("== 提示 ==")
            lines.extend(f"  · {item}" for item in preview.warnings)
            lines.append("")
        if preview.duplicates:
            lines.append("== 疑似重复 ==")
            for item in preview.duplicates:
                lines.append(
                    f"  [{item.kind}] {item.sheet_name} 第 {item.row_number} 行：{item.message}"
                )
            lines.append("")
        if preview.issues_by_location:
            lines.append("== 逐行问题 ==")
            for (sheet, row), messages in sorted(preview.issues_by_location.items()):
                lines.append(f"  {sheet} 第 {row} 行：")
                lines.extend(f"      - {message}" for message in messages)
            lines.append("")
        for issue in preview.validation.issues:
            if issue.result.value == "不通过" and not preview.issues_by_location:
                lines.append(f"  {issue.check_code} {issue.check_item}：{issue.detail}")
        return "\n".join(lines) if lines else "未发现问题。"

    def _finish(self, decision: ImportDecision) -> None:
        self.decision = decision
        if self._preview.has_duplicates:
            self.duplicate_decision = DuplicateDecision(self._duplicate_combo.currentData())
        self.accept()


class BillPage(QWidget):
    """账单页面。"""

    def __init__(self, service: BillService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._project_id: str | None = None
        self._bills: list[ElectricityBill] = []
        self._build()

    # -- 构建 -----------------------------------------------------------
    def _build(self) -> None:
        self._project_combo = QComboBox()
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_projects)

        top = QHBoxLayout()
        top.addWidget(QLabel("项目："))
        top.addWidget(self._project_combo, 1)
        top.addWidget(refresh)

        self._table = QTableWidget(0, len(_LIST_COLUMNS))
        self._table.setHorizontalHeaderLabels([title for title, _ in _LIST_COLUMNS])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._table)
        detail_box = QGroupBox("账单详情与校验结果")
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.addWidget(self._detail)
        splitter.addWidget(detail_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._create_button = QPushButton("新增账单")
        self._edit_button = QPushButton("编辑")
        self._copy_button = QPushButton("复制上月")
        self._delete_button = QPushButton("删除")
        self._confirm_button = QPushButton("人工确认")
        self._import_button = QPushButton("导入 Excel 模板")
        self._template_button = QPushButton("生成模板文件")
        self._report_button = QPushButton("导出账单报告")

        self._create_button.clicked.connect(self.on_create)
        self._edit_button.clicked.connect(self.on_edit)
        self._copy_button.clicked.connect(self.on_copy)
        self._delete_button.clicked.connect(self.on_delete)
        self._confirm_button.clicked.connect(self.on_confirm)
        self._import_button.clicked.connect(self.on_import)
        self._template_button.clicked.connect(self.on_generate_template)
        self._report_button.clicked.connect(self.on_export_report)

        buttons = QHBoxLayout()
        for button in (
            self._create_button,
            self._edit_button,
            self._copy_button,
            self._delete_button,
            self._confirm_button,
            self._import_button,
            self._template_button,
            self._report_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)

        self._summary = QLabel("尚未选择项目。")
        self._summary.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._summary)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

    # -- 项目 -----------------------------------------------------------
    def refresh_projects(self, projects: list[Any] | None = None) -> None:
        """重新载入项目下拉框。

        Args:
            projects: 由主窗口传入的项目列表；为 ``None`` 时保持当前项。
        """
        if projects is None:
            return
        current = self._project_id
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        for project in projects:
            self._project_combo.addItem(project.name, project.project_id)
        self._project_combo.blockSignals(False)
        if current is not None:
            index = self._project_combo.findData(current)
            if index >= 0:
                self._project_combo.setCurrentIndex(index)
        self._on_project_changed()

    def set_project(self, project_id: str | None) -> None:
        self._project_id = project_id
        if project_id is not None:
            index = self._project_combo.findData(project_id)
            if index >= 0:
                self._project_combo.blockSignals(True)
                self._project_combo.setCurrentIndex(index)
                self._project_combo.blockSignals(False)
        self.refresh_bills()

    def _on_project_changed(self) -> None:
        self._project_id = self._project_combo.currentData()
        self.refresh_bills()

    # -- 数据刷新 -------------------------------------------------------
    def refresh_bills(self) -> None:
        project_id = self._project_id
        if not project_id:
            self._bills = []
            self._table.setRowCount(0)
            self._detail.setPlainText("尚未选择项目。")
            self._summary.setText("尚未选择项目。")
            self._update_buttons()
            return

        self._bills = self._service.list_bills(project_id)
        self._table.setRowCount(len(self._bills))
        for row, bill in enumerate(self._bills):
            for column, (_title, getter) in enumerate(_LIST_COLUMNS):
                self._table.setItem(row, column, QTableWidgetItem(str(getter(bill))))

        summary = self._service.summarize(project_id)
        self._summary.setText(
            f"账单数 <b>{summary.bill_count}</b>　"
            f"已确认 <b>{summary.confirmed_count}</b>　"
            f"待确认 <b>{summary.pending_confirmation_count}</b>　"
            f"账期：{'、'.join(summary.periods) if summary.periods else '（无）'}<br>"
            f"合计电量：{_num(summary.total_energy_kwh)} kWh　"
            f"合计电费：{_num(summary.total_amount_yuan)} 元<br>"
            f"<b>可用于正式测算的账单：{len(self._service.usable_bills(project_id))} 条</b>"
            "（未确认或存在疑问的账单不计入）"
        )
        self._update_buttons()
        if self._bills:
            self._table.selectRow(0)
        else:
            self._detail.setPlainText("该项目暂无账单。可“新增账单”或“导入 Excel 模板”。")

    def _update_buttons(self) -> None:
        bill = self._current_bill()
        has_project = bool(self._project_id)
        self._create_button.setEnabled(has_project)
        self._import_button.setEnabled(has_project)
        for button in (self._edit_button, self._copy_button, self._delete_button):
            button.setEnabled(bill is not None)
        self._confirm_button.setEnabled(bill is not None and not bill.is_confirmed)

    def _current_bill(self) -> ElectricityBill | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._bills):
            return None
        return self._bills[row]

    def _on_selection_changed(self) -> None:
        self._update_buttons()
        bill = self._current_bill()
        if bill is None:
            self._detail.setPlainText("未选择账单。")
            return
        self._detail.setPlainText(self._describe(bill))

    def _describe(self, bill: ElectricityBill) -> str:
        """展示账单详情与该项目 13 类校验结果。"""
        lines = [
            f"账期：{bill.billing_period or '未提供'}",
            f"账期起止：{_text_or_empty(bill.period_start)} ~ {_text_or_empty(bill.period_end)}",
            f"户号：{bill.account_number or '未提供'}",
            f"用户名称：{bill.customer_name or '未提供'}",
            f"本期总电量 kWh：{_num(bill.total_energy_kwh)}",
            f"账单本期电费 元：{_num(bill.total_amount_yuan)}",
            f"增值税专票金额 元：{_num(bill.vat_invoice_amount_yuan)}",
            f"账单展示平均电价 元/kWh：{_num(bill.displayed_average_price)}",
            f"功率因数调整电费 元：{_num(bill.power_factor_adjustment_fee_yuan)}",
            f"需量电费 元：{_num(bill.demand_charge_yuan)}",
            f"实际最大需量：{_num(bill.actual_demand)} {bill.actual_demand_unit or ''}",
            f"复核状态：{bill.review_status.value}",
            f"确认状态：{bill.confirmation.value}",
            f"样本数据：{'是' if bill.is_sample else '否'}",
            f"可用于正式测算：{'是' if bill.is_usable_for_calculation else '否'}",
            f"来源：{bill.source_file or '未提供'} 第 {bill.source_page or '未提供'} 页",
            f"备注：{bill.note or ''}",
            "",
            "提示：账单展示平均电价仅为统计值，不能作为光伏边际节省电价使用。",
        ]
        return "\n".join(lines)

    # -- 操作 -----------------------------------------------------------
    def on_create(self) -> None:
        project_id = self._project_id
        if not project_id:
            QMessageBox.critical(self, "无法新增", "请先选择项目。")
            return
        dialog = BillDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self._service.create_bill(project_id, dialog.payload())
        except (CENEPError, ValueError) as exc:
            QMessageBox.critical(self, "新增失败", f"账单未保存：{exc}")
            return
        self.refresh_bills()

    def on_edit(self) -> None:
        bill = self._current_bill()
        if bill is None:
            return
        dialog = BillDialog(self, bill)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self._service.update_bill(bill.bill_id, dialog.payload())
        except (CENEPError, ValueError) as exc:
            QMessageBox.critical(self, "修改失败", f"账单未保存：{exc}")
            return
        self.refresh_bills()

    def on_copy(self) -> None:
        bill = self._current_bill()
        if bill is None:
            return
        dialog = BillDialog(self, bill)
        dialog.setWindowTitle("复制上月 — 请填写新账期与本月金额")
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        try:
            self._service.copy_bill(
                bill.bill_id,
                billing_period=payload.billing_period or "",
                period_start=payload.period_start,
                period_end=payload.period_end,
                total_energy_kwh=payload.total_energy_kwh,
                total_amount_yuan=payload.total_amount_yuan,
            )
        except (CENEPError, ValueError) as exc:
            QMessageBox.critical(self, "复制失败", f"账单未保存：{exc}")
            return
        self.refresh_bills()

    def on_delete(self) -> None:
        bill = self._current_bill()
        if bill is None:
            return
        if bill.is_confirmed:
            answer = QMessageBox.question(
                self,
                "删除已确认账单",
                "该账单已确认。删除已确认数据属于高风险操作，确定继续？",
            )
            if answer != QMessageBox.Yes:
                return
            allow = True
        else:
            answer = QMessageBox.question(self, "删除账单", "确定删除该账单及其明细？")
            if answer != QMessageBox.Yes:
                return
            allow = False
        try:
            self._service.delete_bill(bill.bill_id, allow_confirmed=allow)
        except (CENEPError, ValueError) as exc:
            QMessageBox.critical(self, "删除失败", f"账单未删除：{exc}")
            return
        self.refresh_bills()

    def on_confirm(self) -> None:
        bill = self._current_bill()
        if bill is None:
            return
        try:
            self._service.confirm_bill(bill.bill_id)
        except (CENEPError, ValueError) as exc:
            QMessageBox.critical(self, "确认失败", f"账单未确认：{exc}")
            return
        self.refresh_bills()

    def on_generate_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存标准模板", default_template_path().name, "Excel 文件 (*.xlsx)"
        )
        if not path:
            return
        try:
            written = write_template(path)
        except OSError as exc:
            QMessageBox.critical(self, "模板生成失败", str(exc))
            return
        QMessageBox.information(
            self,
            "模板已生成",
            f"已生成：{written}\n\n"
            "工作表：使用说明、月度汇总、分时电量电价、费用明细、计量点、"
            "数据校验、样本参考_勿直接测算。\n"
            "样本参考表仅供字段对照，导入时默认忽略。",
        )

    def on_import(self) -> None:
        project_id = self._project_id
        if not project_id:
            QMessageBox.critical(self, "无法导入", "请先选择项目。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择账单 Excel 文件", "", "Excel 文件 (*.xlsx)"
        )
        if not path:
            return
        try:
            preview = self._service.preview_import(path, project_id=project_id)
        except TemplateReadError as exc:
            QMessageBox.critical(self, "无法读取文件", exc.format())
            return
        except (CENEPError, ValueError) as exc:
            QMessageBox.critical(self, "预览失败", str(exc))
            return

        dialog = ImportPreviewDialog(preview, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            result = self._service.apply_import(
                preview,
                decision=dialog.decision,
                duplicate_decision=dialog.duplicate_decision,
            )
        except (CENEPError, ValueError) as exc:
            QMessageBox.critical(self, "导入失败", f"未写入任何数据：{exc}")
            return

        QMessageBox.information(self, "导入结果", "\n".join(result.summary_lines()))
        self.refresh_bills()

    def on_export_report(self) -> None:
        """导出账单事实报告（Excel）。

        **不含经济性结论**：报告只呈现账单事实与数据质量。
        """
        project_id = self._project_id
        if not project_id:
            QMessageBox.critical(self, "无法导出", "请先选择项目。")
            return
        if not self._service.list_bills(project_id):
            QMessageBox.critical(self, "无法导出", "该项目暂无账单，导出为空报告无意义。")
            return

        suggested = default_report_name(self._project_combo.currentText())
        path, _ = QFileDialog.getSaveFileName(
            self, "导出账单报告", suggested, "Excel 文件 (*.xlsx)"
        )
        if not path:
            return
        try:
            written = self._service.export_report(
                project_id, path, project_name=self._project_combo.currentText()
            )
        except (CENEPError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "导出失败", f"报告未生成：{exc}")
            return
        QMessageBox.information(
            self,
            "报告已导出",
            f"已生成：{written}\n\n"
            "报告含 6 张工作表：报告说明、数据概览、数据完整性、账单事实、"
            "费用明细、分时与计量点。\n"
            "报告只呈现账单事实与数据质量，<b>不含收益率等经济性结论</b>；"
            "未提供的字段显示为“未提供”。",
        )
