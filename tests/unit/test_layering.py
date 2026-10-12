"""架构分层约束测试。

任务书第 5.2 节要求：

1. UI 不直接计算消纳率。
2. 数据库不决定业务计算规则。
3. 计算模块不读取界面控件。
4. 领域计算模块不得依赖 PySide6、SQLite 或 PDF 解析库。
5. 不允许把所有代码写在一个文件里。

本测试用 AST 静态分析 + 文本扫描自动检查这些约束，
避免"约定写在文档里、代码里没人管"。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "cenep"

#: 领域层与计算层禁止出现的第三方依赖前缀
FORBIDDEN_THIRD_PARTY = (
    "PySide6",
    "shiboken6",
    "sqlite3",
    "pandas",
    "numpy",
    "openpyxl",
    "pdfminer",
    "PyPDF2",
    "pypdf",
    "fitz",
    "requests",
)

#: 领域层与计算层禁止依赖的本项目其它分层
FORBIDDEN_INTERNAL_PREFIXES = (
    "cenep.ui",
    "cenep.infrastructure",
    "cenep.application",
)


def _iter_python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def _imported_modules(path: Path) -> list[tuple[str, int]]:
    """返回文件中所有 import 的目标模块名与行号。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # 相对导入在本项目内不会越过分层
            if node.module:
                modules.append((node.module, node.lineno))
    return modules


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


class TestLayerIsolation:
    @pytest.mark.parametrize("layer", ["domain", "calculations"])
    def test_domain_and_calculation_layers_have_no_forbidden_imports(self, layer: str) -> None:
        offenders: list[str] = []
        for path in _iter_python_files(SRC_DIR / layer):
            for module, lineno in _imported_modules(path):
                for forbidden in FORBIDDEN_THIRD_PARTY:
                    if _matches(module, forbidden):
                        offenders.append(f"{path.name}:{lineno} 导入了 {module}")
                for forbidden in FORBIDDEN_INTERNAL_PREFIXES:
                    if _matches(module, forbidden):
                        offenders.append(f"{path.name}:{lineno} 导入了 {module}")
        assert not offenders, "领域/计算层出现越界依赖：\n" + "\n".join(offenders)

    def test_domain_layer_does_not_import_infrastructure(self) -> None:
        for path in _iter_python_files(SRC_DIR / "domain"):
            for module, _ in _imported_modules(path):
                assert not _matches(module, "cenep.infrastructure"), f"{path.name} 非法依赖基础设施层"

    def test_calculations_do_not_import_ui(self) -> None:
        for path in _iter_python_files(SRC_DIR / "calculations"):
            for module, _ in _imported_modules(path):
                assert not _matches(module, "cenep.ui"), f"{path.name} 非法依赖界面层"

    def test_infrastructure_does_not_import_ui(self) -> None:
        for path in _iter_python_files(SRC_DIR / "infrastructure"):
            for module, _ in _imported_modules(path):
                assert not _matches(module, "cenep.ui"), f"{path.name} 非法依赖界面层"

    def test_pdf_libraries_only_allowed_in_infrastructure(self) -> None:
        """PDF 解析库只允许出现在基础设施层。

        第一阶段曾完全禁止 PDF 库；第二阶段 P0-1 引入 ``pypdf`` 后，
        规则收紧为"只在基础设施层允许"：

        - ``domain`` / ``calculations``：禁止（保持纯领域与纯计算）；
        - ``application``：禁止（只编排流程，不直接解析文件）；
        - ``ui``：禁止（界面不得直接操作 PDF，必须走应用服务）；
        - ``infrastructure``：允许（解析库是基础设施实现细节）。

        该约束保证未来替换解析库（例如换成 pdfplumber）不影响上层。
        """
        pdf_prefixes = ("pdfminer", "PyPDF2", "pypdf", "fitz", "pytesseract", "cv2", "PIL")
        allowed_layers = ("infrastructure",)
        offenders: list[str] = []

        for path in _iter_python_files(SRC_DIR):
            relative = path.relative_to(SRC_DIR)
            if relative.parts and relative.parts[0] in allowed_layers:
                continue
            for module, lineno in _imported_modules(path):
                for prefix in pdf_prefixes:
                    if _matches(module, prefix):
                        offenders.append(f"{relative}:{lineno} 导入了 {module}")

        assert not offenders, (
            "PDF/OCR 依赖只允许出现在基础设施层，以下位置越界：\n" + "\n".join(offenders)
        )

    def test_excel_libraries_only_allowed_in_data_and_infrastructure(self) -> None:
        """Excel 读写库只允许出现在 ``data`` 与 ``infrastructure`` 层。

        规则（`docs/ARCHITECTURE.md` 依赖方向规则第 5 条）：

        - ``data``：允许（Excel 读写、模板生成是本层职责）；
        - ``infrastructure``：允许（如需导出/持久化集成）；
        - ``domain`` / ``calculations``：禁止（保持纯领域与纯计算）；
        - ``application``：禁止（只编排流程，不直接操作表格）；
        - ``ui``：禁止（界面不得直接操作 Excel，必须走 ``data``）。

        该约束保证"Excel 读写逻辑不得直接散落在界面代码中"（规格书第 8 节）。
        """
        excel_prefixes = ("openpyxl", "xlsxwriter", "xlrd", "xlwt", "pandas")
        allowed_layers = ("data", "infrastructure")
        offenders: list[str] = []

        for path in _iter_python_files(SRC_DIR):
            relative = path.relative_to(SRC_DIR)
            if relative.parts and relative.parts[0] in allowed_layers:
                continue
            for module, lineno in _imported_modules(path):
                for prefix in excel_prefixes:
                    if _matches(module, prefix):
                        offenders.append(f"{relative}:{lineno} 导入了 {module}")

        assert not offenders, (
            "Excel 读写依赖只允许出现在 data / infrastructure 层，以下位置越界：\n"
            + "\n".join(offenders)
        )

    def test_data_layer_actually_uses_openpyxl(self) -> None:
        """反向检查：模板生成器确实通过 openpyxl 写出真实文件，而非空实现。"""
        writer = SRC_DIR / "data" / "template_writer.py"
        assert writer.exists(), "缺少模板生成器实现"
        modules = [module for module, _ in _imported_modules(writer)]
        assert any(_matches(module, "openpyxl") for module in modules), (
            "template_writer.py 应当导入 openpyxl 完成真实写文件"
        )

    def test_data_layer_does_not_depend_on_upper_layers(self) -> None:
        """``data`` 层只依赖 ``domain``：不得依赖 ui / application / infrastructure。"""
        for path in _iter_python_files(SRC_DIR / "data"):
            for module, lineno in _imported_modules(path):
                for forbidden in ("cenep.ui", "cenep.application", "cenep.infrastructure"):
                    assert not _matches(module, forbidden), (
                        f"{path.name}:{lineno} 非法依赖 {module}"
                    )

    def test_template_spec_is_free_of_excel_dependency(self) -> None:
        """模板**结构规范**必须是纯数据，不得依赖 openpyxl。"""
        spec = SRC_DIR / "data" / "bill_template_spec.py"
        assert spec.exists(), "缺少模板结构规范"
        for module, lineno in _imported_modules(spec):
            for prefix in ("openpyxl", "xlsxwriter", "pandas", "PySide6", "sqlite3"):
                assert not _matches(module, prefix), (
                    f"bill_template_spec.py:{lineno} 不应依赖 {module}（结构规范须为纯数据）"
                )

    def test_infrastructure_pdf_layer_actually_uses_pypdf(self) -> None:
        """反向检查：解析器确实通过 pypdf 实现，而不是自己造轮子或空实现。"""
        extractor = SRC_DIR / "infrastructure" / "pdf" / "extractor.py"
        assert extractor.exists(), "缺少 PDF 提取器实现"
        modules = [module for module, _ in _imported_modules(extractor)]
        assert any(_matches(module, "pypdf") for module in modules), (
            "extractor.py 应当导入 pypdf 完成真实解析"
        )

    def test_domain_pdf_model_has_no_pdf_dependency(self) -> None:
        """领域层的 PDF 模型必须与解析库彻底解耦。"""
        domain_model = SRC_DIR / "domain" / "pdf_extraction.py"
        assert domain_model.exists(), "缺少 PDF 领域模型"
        for module, lineno in _imported_modules(domain_model):
            for prefix in ("pypdf", "PyPDF2", "pdfminer", "fitz", "sqlite3", "PySide6", "shiboken6"):
                assert not _matches(module, prefix), (
                    f"{domain_model.name}:{lineno} 不应导入 {module}"
                )


class TestUIContainsNoBusinessFormulas:
    def test_self_consumption_rates_are_not_computed_in_ui(self) -> None:
        """界面层不得出现 min(/max( 形式的消纳公式或比例计算。"""
        ui_dir = SRC_DIR / "ui"
        suspicious: list[str] = []
        for path in _iter_python_files(ui_dir):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "min(" in stripped and "max(" in stripped:
                    suspicious.append(f"{path.name}:{lineno}: {stripped}")
                if "total_self_consumption" in stripped and "/" in stripped and "=" in stripped:
                    suspicious.append(f"{path.name}:{lineno}: {stripped}")
        assert not suspicious, "界面层疑似包含业务计算：\n" + "\n".join(suspicious)

    def test_ui_does_not_import_sqlite_or_run_sql(self) -> None:
        for path in _iter_python_files(SRC_DIR / "ui"):
            text = path.read_text(encoding="utf-8")
            for module, lineno in _imported_modules(path):
                assert not _matches(module, "sqlite3"), f"{path.name}:{lineno} 直接导入 sqlite3"
            lowered = text.lower()
            assert "select " not in lowered or "sql" not in lowered, f"{path.name} 疑似包含 SQL 语句"

    def test_ui_uses_application_service(self) -> None:
        """界面层必须通过应用服务访问业务能力。"""
        text = (SRC_DIR / "ui" / "main_window.py").read_text(encoding="utf-8")
        assert "ProjectService" in text
        assert "run_self_consumption" in text

    def test_service_does_not_contain_formulas(self) -> None:
        """应用服务层只组织流程，不得复制领域公式。"""
        text = (SRC_DIR / "application" / "project_service.py").read_text(encoding="utf-8")
        assert "min(" not in text
        assert "max(" not in text


class TestProjectStructure:
    def test_expected_modules_exist(self) -> None:
        expected = [
            "__init__.py",
            "__main__.py",
            "app.py",
            "cli.py",
            "config.py",
            "domain/__init__.py",
            "domain/models.py",
            "domain/validation.py",
            "domain/exceptions.py",
            "domain/bill_models.py",
            "calculations/__init__.py",
            "calculations/self_consumption.py",
            "application/__init__.py",
            "application/project_service.py",
            "application/bill_service.py",
            "infrastructure/__init__.py",
            "infrastructure/database.py",
            "infrastructure/schema_v2.py",
            "infrastructure/bill_repository.py",
            "data/__init__.py",
            "data/bill_template_spec.py",
            "data/template_writer.py",
            "data/template_reader.py",
            "data/template_mapping.py",
            "data/bill_validation.py",
            "data/bill_import_service.py",
            "data/report_data.py",
            "data/report_writer.py",
            "ui/__init__.py",
            "ui/main_window.py",
            "ui/bill_page.py",
        ]
        missing = [name for name in expected if not (SRC_DIR / name).exists()]
        assert not missing, f"缺少模块文件：{missing}"

    def test_no_oversized_single_file(self) -> None:
        """不允许把全部功能写在一个文件里：单文件不超过 1200 行。"""
        oversized = [
            f"{path.relative_to(SRC_DIR)}: {len(path.read_text(encoding='utf-8').splitlines())} 行"
            for path in _iter_python_files(SRC_DIR)
            if len(path.read_text(encoding="utf-8").splitlines()) > 1200
        ]
        assert not oversized, "存在过大的单文件：" + "; ".join(oversized)

    def test_module_count_reflects_layering(self) -> None:
        """分层目录都必须真实存在且包含实现文件。"""
        for layer in ("domain", "calculations", "application", "infrastructure", "data", "ui"):
            files = [path for path in _iter_python_files(SRC_DIR / layer) if path.name != "__init__.py"]
            assert files, f"{layer} 层没有任何实现文件"


class TestNoFakeImplementations:
    def test_no_not_implemented_placeholders_in_core_paths(self) -> None:
        """核心路径不得留下未实现占位。"""
        core_files = [
            SRC_DIR / "calculations" / "self_consumption.py",
            SRC_DIR / "domain" / "validation.py",
            SRC_DIR / "domain" / "models.py",
            SRC_DIR / "infrastructure" / "database.py",
            SRC_DIR / "application" / "project_service.py",
        ]
        offenders: list[str] = []
        for path in core_files:
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "NotImplementedError" in line or "raise NotImplementedError" in line:
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
        assert not offenders, "核心模块存在未实现占位：" + "; ".join(offenders)

    def test_no_functions_with_only_pass_body(self) -> None:
        """除 __init__.py 的包声明外，不应存在空实现函数。"""
        offenders: list[str] = []
        for path in _iter_python_files(SRC_DIR):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = [item for item in node.body if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant))]
                    if len(body) == 1 and isinstance(body[0], ast.Pass):
                        offenders.append(f"{path.relative_to(SRC_DIR)}:{node.lineno} {node.name}")
        assert not offenders, "存在空实现函数：" + "; ".join(offenders)

    def test_no_hardcoded_fake_success_results(self) -> None:
        """界面层不得硬编码"成功"文案来掩盖失败。

        覆盖 ``ui/`` 下**全部** Python 文件（不只主窗口）。
        只检查**会显示给用户/日志的字符串字面量**，
        排除模块与函数的文档字符串（``__doc__``）——因为文档里写
        "禁止出现某某文案"这类说明本身是正当的，否则会误判（实测踩坑）。
        """
        ui_files = sorted((SRC_DIR / "ui").glob("*.py"))
        assert ui_files, "未找到界面层文件"

        def _docstrings(tree: ast.AST) -> set[int]:
            """收集所有文档字符串节点所在行号。"""
            lines: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    body = getattr(node, "body", [])
                    if (
                        body
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)
                    ):
                        lines.add(body[0].value.lineno)
            return lines

        forbidden = ("保存成功", "导入成功", "操作成功")
        for path in ui_files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            doc_lines = _docstrings(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if node.lineno in doc_lines:
                    continue
                for phrase in forbidden:
                    assert phrase not in node.value, (
                        f"{path.name} 第 {node.lineno} 行出现硬编码成功文案：{phrase}"
                    )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in ui_files)
        assert "QMessageBox.critical" in combined, "界面层必须保留失败提示的报错出口"

    def test_ui_does_not_touch_excel_or_sql_directly(self) -> None:
        """界面层不得直接读写 Excel 或直接执行 SQL。"""
        for path in sorted((SRC_DIR / "ui").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            assert "openpyxl" not in text, f"{path.name} 不应直接使用 openpyxl"
            assert "sqlite3" not in text, f"{path.name} 不应直接使用 sqlite3"
            assert "INSERT INTO" not in text.upper(), f"{path.name} 不应包含 SQL 写入"

    def test_ui_uses_application_service_for_bills(self) -> None:
        """账单页面必须经应用服务访问业务能力，不得直接依赖 data/infrastructure。"""
        text = (SRC_DIR / "ui" / "bill_page.py").read_text(encoding="utf-8")
        assert "BillService" in text, "账单页面必须使用应用服务"
        assert "SqliteBillRepository" not in text, "界面层不得直接使用仓储"
        assert "cenep.infrastructure" not in text, "界面层不得直接依赖基础设施层"
