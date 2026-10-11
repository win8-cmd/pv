"""CENEP —— 中国工商业分布式光伏项目经济评价软件。

本包采用分层架构：

- :mod:`cenep.domain`          领域层：数据模型、校验规则、业务异常
- :mod:`cenep.calculations`    领域层：纯计算模块（不依赖 GUI / 数据库）
- :mod:`cenep.application`     应用服务层：组织业务流程
- :mod:`cenep.infrastructure`  基础设施层：SQLite、后续文件读取与报表导出
- :mod:`cenep.ui`              表现层：PySide6 桌面界面

依赖方向严格为：表现层 → 应用服务层 → 领域层。
领域层与计算层不得导入 PySide6、sqlite3 或任何 PDF 解析库。
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "STAGE"]

APP_NAME = "CENEP"
"""软件名称。"""

__version__ = "0.1.0"
"""当前版本号。"""

STAGE = "第一阶段：工程骨架与核心规则冻结"
"""当前开发阶段说明。"""
