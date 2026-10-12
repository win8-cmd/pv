"""电费账单标准 Excel 模板的**结构规范**（纯数据，不含 Excel 依赖）。

本模块只描述"模板长什么样"：工作表、字段、单位、枚举、必填性、说明。
**不导入 `openpyxl`**，因此可被领域层与测试直接引用；
实际写文件由 :mod:`cenep.data.template_writer` 完成。

依据：《CENEP 工商业电费账单模板整合执行规格书 V1.0》
第五部分第 19–28 节。

设计约束（规格书第 21、30 节）：

- 电量统一 `kWh`；电价统一 `元/kWh`；金额统一 `元`；
- 账期用 `YYYY-MM`，日期用 `YYYY-MM-DD`；
- 空值与 0 必须区分：未提供留空，明确为 0 才写 0；
- 负费用合法（如功率因数调整电费）；
- 总电量不得因费用调整而为负。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ALL_SHEETS",
    "BUSINESS_SHEETS",
    "EXCLUDED_SHEETS",
    "SAMPLE_MARKER_TEXT",
    "SAMPLE_TEMPLATE_ROWS",
    "SHEET_DATA_VALIDATION",
    "SHEET_FEE_ITEMS",
    "SHEET_INSTRUCTIONS",
    "SHEET_METER_POINTS",
    "SHEET_MONTHLY_SUMMARY",
    "SHEET_SAMPLE_REFERENCE",
    "SHEET_TIME_OF_USE",
    "DailyRow",
    "ColumnSpec",
    "SheetSpec",
    "TEMPLATE_NAME",
    "TEMPLATE_VERSION",
    "ValidationSeverity",
    "ValidationResult",
    "columns_of",
    "get_sheet",
    "headers_of",
]


#: 模板文件名（规格书第 19 节建议名）
TEMPLATE_NAME = "CENEP_工商业电费账单标准导入模板_V1.0.xlsx"

#: 模板结构版本。字段增删或语义变化时提升，并在 `使用说明` 中记录变更规则。
TEMPLATE_VERSION = "1.0"

# 工作表名称（规格书第 20 节：名称必须保持稳定）
SHEET_INSTRUCTIONS = "使用说明"
SHEET_MONTHLY_SUMMARY = "月度汇总"
SHEET_TIME_OF_USE = "分时电量电价"
SHEET_FEE_ITEMS = "费用明细"
SHEET_METER_POINTS = "计量点"
SHEET_DATA_VALIDATION = "数据校验"
SHEET_SAMPLE_REFERENCE = "样本参考_勿直接测算"

#: 正式业务数据所在工作表（导入器只从这些表读取账单数据）
BUSINESS_SHEETS: tuple[str, ...] = (
    SHEET_MONTHLY_SUMMARY,
    SHEET_TIME_OF_USE,
    SHEET_FEE_ITEMS,
    SHEET_METER_POINTS,
)

#: 导入器**默认排除**的工作表（规格书第 20、31 节）
EXCLUDED_SHEETS: tuple[str, ...] = (
    SHEET_INSTRUCTIONS,
    SHEET_DATA_VALIDATION,
    SHEET_SAMPLE_REFERENCE,
)

#: 样本参考表必须在显著位置显示的警示（规格书第 28 节）
SAMPLE_MARKER_TEXT = (
    "样本初始值，仅用于模板字段对照与回归测试。"
    "正式使用前必须与原始 PDF 逐项核实。"
    "导入器默认忽略本工作表，不得作为生产项目账单自动导入。"
)


class ValidationSeverity(str, Enum):
    """校验问题的严重程度（规格书第 27 节）。"""

    BLOCKING = "阻断"
    WARNING = "警告"
    INFO = "提示"


class ValidationResult(str, Enum):
    """校验结果（规格书第 27 节）。"""

    PASS = "通过"
    FAIL = "不通过"
    PENDING = "待检查"
    NOT_APPLICABLE = "不适用"


class ReviewStatus(str, Enum):
    """数据复核状态（规格书第 23.5 节）。"""

    PENDING = "待复核"
    REVIEWED = "已复核"
    QUESTIONABLE = "存在疑问"
    NOT_APPLICABLE = "不适用"


class DemandUnit(str, Enum):
    """需量单位。**必须显式区分 kW 与 kVA**（规格书第 21、23.5 节）。"""

    KW = "kW"
    KVA = "kVA"


class DemandBillingMode(str, Enum):
    """需量计费方式。"""

    ACTUAL_DEMAND = "按实际最大需量"
    CONTRACT_DEMAND = "按合同最大需量"
    CAPACITY = "按变压器容量"
    NOT_APPLICABLE = "不适用"


class TimeOfUsePeriod(str, Enum):
    """时段名称（规格书第 24 节）。"""

    SHARP_PEAK = "尖峰"
    PEAK = "高峰"
    FLAT = "平"
    VALLEY = "低谷"
    OTHER = "其他"


class MeteringBasis(str, Enum):
    """电量类型（规格书第 24 节）。**必须区分购电、上网及其他口径**。"""

    PURCHASE = "购电"
    EXPORT = "上网"
    OTHER = "其他"


class FeeCategory(str, Enum):
    """费用大类（规格书第 25 节）。"""

    ENERGY = "电量电费"
    TRANSMISSION = "输配电费"
    SYSTEM = "系统运行费"
    GOVERNMENT = "政府性基金及附加"
    ADJUSTMENT = "调整类费用"
    DEMAND = "需量/基本电费"
    MARKET = "市场化运营费"
    OTHER = "其他"


class IncludedInOther(str, Enum):
    """`是否包含在其他费用中`（规格书第 25 节）。"""

    YES = "是"
    NO = "否"
    TO_VERIFY = "待核实"


class Avoidability(str, Enum):
    """`光伏测算可避免性`（规格书第 25 节）。

    **仅作数据管理标记**，不得在缺乏明确业务规则时直接决定最终收益。
    """

    AVOIDABLE = "可避免"
    PARTIALLY_AVOIDABLE = "部分可避免"
    UNAVOIDABLE = "不可避免"
    TO_VERIFY = "待核实"


class BaselineInclusion(str, Enum):
    """`是否纳入基准电费`（规格书第 25 节）。"""

    YES = "是"
    NO = "否"
    TO_CONFIRM = "待确认"


class MeterPointType(str, Enum):
    """计量点类型（规格书第 26 节）。"""

    MAIN = "主表"
    SUB = "分表"
    CHECK = "考核表"
    OTHER = "其他"


class YesNoUnknown(str, Enum):
    """通用三态（规格书第 26 节）。"""

    YES = "是"
    NO = "否"
    TO_VERIFY = "待核实"


@dataclass(frozen=True)
class ColumnSpec:
    """一个字段（列）的完整定义。"""

    name: str
    unit: str | None = None
    required: bool = False
    description: str = ""
    choices: tuple[str, ...] = ()
    number_format: str | None = None

    @property
    def header(self) -> str:
        """工作表首行使用的字段标题（即字段名本身，规格书第 21 节）。"""
        return self.name


@dataclass(frozen=True)
class DailyRow:
    """`使用说明` 表中的一条说明记录。"""

    topic: str
    content: str


@dataclass(frozen=True)
class SheetSpec:
    """一张工作表的完整定义。"""

    name: str
    purpose: str
    """工作表用途（写入 `使用说明`）。"""
    granularity: str
    """记录粒度（写入 `使用说明`）。"""
    columns: tuple[ColumnSpec, ...]
    is_business: bool
    freeze_header: bool = True
    enable_filter: bool = True
    note: str = ""


def _col(
    name: str,
    unit: str | None = None,
    *,
    required: bool = False,
    description: str = "",
    choices: tuple[str, ...] = (),
    number_format: str | None = None,
) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        unit=unit,
        required=required,
        description=description,
        choices=choices,
        number_format=number_format,
    )


# ---------------------------------------------------------------------------
# 共用字段组
# ---------------------------------------------------------------------------

_PROJECT_KEY_COLUMNS: tuple[ColumnSpec, ...] = (
    _col("项目编号", required=True, description="项目唯一编号，需与软件内项目一致。必填。"),
    _col("户号", description="供电户号。一个项目可有多个户号。"),
    _col("账期", required=True, description="账期月份，格式 YYYY-MM。必填，用于重复账单识别。"),
)

_SOURCE_COLUMNS: tuple[ColumnSpec, ...] = (
    _col("来源文件", description="账单来源文件名。建议填写以便追溯；缺失时校验会提示。"),
    _col("来源页码", description="字段在来源文件中的页码。"),
    _col(
        "复核状态",
        choices=tuple(item.value for item in ReviewStatus),
        description="待复核 / 已复核 / 存在疑问 / 不适用。**未复核数据不得用于正式测算**。",
    ),
    _col("备注", description="自由说明。"),
)

_MONTHLY_SUMMARY_COLUMNS: tuple[ColumnSpec, ...] = (
    # 23.1 基本信息
    _col("项目编号", required=True, description="项目唯一编号。必填。"),
    _col("用户名称", description="用电户名称。"),
    _col("户号", description="供电户号。"),
    _col("供电单位", description="供电公司名称。"),
    _col("用电地址", description="用电地址。**含客户信息，请勿提交到公开仓库。**"),
    _col(
        "用电类别",
        description="如：大工业用电 / 一般工商业。",
    ),
    _col("电压等级", description="如：交流110kV。"),
    _col("市场化属性", description="如：市场化直购客户。"),
    # 23.2 账期信息
    _col("账期", required=True, description="账期月份，格式 YYYY-MM。必填。"),
    _col(
        "账期开始日期",
        required=True,
        number_format="yyyy-mm-dd",
        description="账期开始日，格式 YYYY-MM-DD。必填。",
    ),
    _col(
        "账期结束日期",
        required=True,
        number_format="yyyy-mm-dd",
        description="账期结束日，格式 YYYY-MM-DD；不得早于开始日。必填。",
    ),
    _col("账单打印日期", number_format="yyyy-mm-dd", description="格式 YYYY-MM-DD。"),
    # 23.3 总量与金额
    _col("本期总电量_kWh", "kWh", required=True, description="账单明确标注的权威总电量。**不得由计量点或分时电量求和推导**。不得为负。"),
    _col("账单本期电费_元", "元", required=True, description="账单本期电费（合计）金额。**与发票金额口径不同，必须分别保存**。"),
    _col("增值税专票金额_元", "元", description="增值税专用发票金额。与账单总金额口径不同。"),
    _col("账单展示平均电价_元每kWh", "元/kWh", description="账单展示的平均电价。**仅为统计值，不得当作光伏边际节省电价**。"),
    # 23.4 主要费用
    _col("工商业电费_元", "元", description="账单口径的工商业电费。与账单总金额口径不同。"),
    _col("市场化购电电费_元", "元", description="(1) 市场化购电电费。"),
    _col("上网环节线损费用_元", "元", description="(2) 上网环节线损费用。"),
    _col("输配电费_元", "元", description="(3) 输配电费。"),
    _col("系统运行费_元", "元", description="(4) 系统运行费。"),
    _col("政府性基金及附加_元", "元", description="(5) 政府性基金及附加。"),
    _col("功率因数调整电费_元", "元", description="力调电费。**可为负数**（减免），必须保留负号。"),
    _col("需量电费_元", "元", description="需（容）量电费。**具有独立计费机制，不得默认随光伏发电量同比例节省**。"),
    _col("市场化运营费合计_元", "元", description="市场运营费合计。**可能已包含在其他费用中，核实后方可参与合计**。"),
    _col("基本电费_元", "元", description="基本电费（如与需量电费并存，须核实口径避免重复计入）。"),
    # 23.5 需量与来源
    _col("合同最大需量", description="合同最大需量数值。"),
    _col(
        "合同最大需量单位",
        choices=tuple(item.value for item in DemandUnit),
        description="kW 或 kVA。**必须显式填写，不得混淆**。",
    ),
    _col("实际最大需量", description="实际最大需量数值。"),
    _col(
        "实际最大需量单位",
        choices=tuple(item.value for item in DemandUnit),
        description="kW 或 kVA。**必须显式填写，不得混淆**。",
    ),
    _col(
        "需量计费方式",
        choices=tuple(item.value for item in DemandBillingMode),
        description="需量/容量的计费方式，影响可避免性判断。",
    ),
    _col("功率因数", description="本期实际功率因数。"),
    *_SOURCE_COLUMNS,
)

_TIME_OF_USE_COLUMNS: tuple[ColumnSpec, ...] = (
    _col("项目编号", required=True, description="项目唯一编号。必填。"),
    _col("户号", description="供电户号。"),
    _col("账期", required=True, description="账期月份，格式 YYYY-MM。必填。"),
    _col(
        "计量口径/计量点编号",
        required=True,
        description="本条电量所属的计量口径或计量点。**不同口径不得直接求和**。必填。",
    ),
    _col(
        "电量类型",
        choices=tuple(item.value for item in MeteringBasis),
        description="购电 / 上网 / 其他。**必须区分口径**。",
    ),
    _col(
        "时段名称",
        choices=tuple(item.value for item in TimeOfUsePeriod),
        description="尖峰 / 高峰 / 平 / 低谷 / 其他。",
    ),
    _col("时段开始", description="时段起，如 08:00。账单提供 24 小时数据时按实际时段逐行记录。"),
    _col("时段结束", description="时段止，如 09:00。"),
    _col("电量_kWh", "kWh", description="该时段电量。**未提供的时段留空，不得补 0**。"),
    _col("购电电价_元每kWh", "元/kWh", description="该时段电价。**不得把某时段电价复制到其他时段**。"),
    _col("电量电费_元", "元", description="该时段电量电费。"),
    _col("电价类型/来源", description="如：市场化购电 / 目录电价 / 账单标注。"),
    *_SOURCE_COLUMNS,
)

_FEE_ITEM_COLUMNS: tuple[ColumnSpec, ...] = (
    _col("项目编号", required=True, description="项目唯一编号。必填。"),
    _col("户号", description="供电户号。"),
    _col("账期", required=True, description="账期月份，格式 YYYY-MM。必填。"),
    _col(
        "费用大类",
        choices=tuple(item.value for item in FeeCategory),
        description="费用归类，用于分组展示与分析。",
    ),
    _col("费用项目名称", required=True, description="费用项名称，如“市场化购电电费”。必填。"),
    _col("计费数量", description="计费数量数值。"),
    _col("计费数量单位", description="计费数量单位，如 kWh、kW、kVA、月。"),
    _col("单价_元每单位", "元/单位", description="单价。"),
    _col("金额_元", "元", required=True, description="该项金额。**可为负数**。必填。"),
    _col(
        "是否包含在其他费用中",
        choices=tuple(item.value for item in IncludedInOther),
        description="是 / 否 / 待核实。**用于防止重复汇总**。",
    ),
    _col("被包含于/关联费用", description="若已包含在其他费用中，填写被包含于哪一项。"),
    _col(
        "光伏测算可避免性",
        choices=tuple(item.value for item in Avoidability),
        description="可避免 / 部分可避免 / 不可避免 / 待核实。**仅作管理标记，不直接决定收益**。",
    ),
    _col(
        "是否纳入基准电费",
        choices=tuple(item.value for item in BaselineInclusion),
        description="是 / 否 / 待确认。",
    ),
    *_SOURCE_COLUMNS,
)

_METER_POINT_COLUMNS: tuple[ColumnSpec, ...] = (
    _col("项目编号", required=True, description="项目唯一编号。必填。"),
    _col("户号", description="供电户号。"),
    _col("账期", required=True, description="账期月份，格式 YYYY-MM。必填。"),
    _col("计量点编号", required=True, description="计量点编号。必填。"),
    _col("计量点名称/位置", description="计量点名称或安装位置。"),
    _col(
        "计量点类型",
        choices=tuple(item.value for item in MeterPointType),
        description="主表 / 分表 / 考核表 / 其他。",
    ),
    _col("主/分表关系", description="主分表隶属关系说明。**未核实前不得自动汇总**。"),
    _col("倍率/定比", description="综合倍率或定比。"),
    _col("电量_kWh", "kWh", description="该计量点电量。"),
    _col(
        "是否已计入首页总电量",
        choices=tuple(item.value for item in YesNoUnknown),
        description="是 / 否 / 待核实。**决定该点电量能否与首页总量比较**。",
    ),
    _col(
        "是否允许纳入汇总",
        choices=tuple(item.value for item in YesNoUnknown),
        description="是 / 否 / 待核实。**未核实主分表关系时不得自动汇总所有计量点电量**。",
    ),
    *_SOURCE_COLUMNS,
)

_VALIDATION_COLUMNS: tuple[ColumnSpec, ...] = (
    _col("校验编号", required=True, description="校验项编号，如 V01。"),
    _col("校验项目", required=True, description="校验项名称。"),
    _col("校验规则/检查方法", description="该检查的判定规则说明。"),
    _col(
        "严重程度",
        choices=tuple(item.value for item in ValidationSeverity),
        description="阻断 / 警告 / 提示。",
    ),
    _col(
        "结果",
        choices=tuple(item.value for item in ValidationResult),
        description="通过 / 不通过 / 待检查 / 不适用。",
    ),
    _col("差异值/异常说明", description="差异数值或异常描述。"),
    _col("处理状态", description="复核处理进展。"),
    _col("处理人", description="处理人。"),
    _col("处理日期", number_format="yyyy-mm-dd", description="格式 YYYY-MM-DD。"),
)

#: 规格书第 27 节要求的 13 类校验项（模板 `数据校验` 表的预置行）
VALIDATION_CHECK_ITEMS: tuple[tuple[str, str, str, ValidationSeverity], ...] = (
    ("V01", "账期完整性", "账期与账期起止日期齐全，且结束日不早于开始日", ValidationSeverity.BLOCKING),
    ("V02", "总电量有效性", "本期总电量为非负数且已提供", ValidationSeverity.BLOCKING),
    ("V03", "账单金额有效性", "账单本期电费已提供；金额允许为负的项目须核实", ValidationSeverity.BLOCKING),
    ("V04", "首页总量与分时电量口径冲突", "仅在账期、计量范围、电量类型一致时比较总电量与分时电量之和", ValidationSeverity.WARNING),
    ("V05", "计量点是否重复计入", "是否已计入首页总电量与是否允许纳入汇总须明确", ValidationSeverity.WARNING),
    ("V06", "费用是否重复计入", "是否包含在其他费用中须核实，防止重复汇总", ValidationSeverity.BLOCKING),
    ("V07", "费用分项与账单总金额勾稽", "费用层级与包含关系明确后比较；差异只提示不改数", ValidationSeverity.WARNING),
    ("V08", "分时电量与总量勾稽", "电量差 = 总电量 − 同口径分时电量合计；未提供时段视为未知而非 0", ValidationSeverity.WARNING),
    ("V09", "电价单位检查", "电价单位为元/kWh；出现元/MWh 须显式换算并记录原始单位", ValidationSeverity.BLOCKING),
    ("V10", "需量单位与计费方式检查", "需量单位须为 kW 或 kVA，两者不得混淆", ValidationSeverity.BLOCKING),
    ("V11", "关键字段复核状态", "关键字段复核状态不得为空白；未复核数据不得用于正式测算", ValidationSeverity.WARNING),
    ("V12", "来源文件与页码可追溯性", "关键字段应能追溯到来源文件与页码", ValidationSeverity.INFO),
    ("V13", "是否具备光伏消纳测算所需数据", "是否具备可用于消纳测算的电量与时段数据", ValidationSeverity.INFO),
)

_INSTRUCTION_ROWS: tuple[DailyRow, ...] = (
    ("模板用途", f"本模板用于把工商业电费账单整理为 CENEP 可导入的结构化数据。模板版本 {TEMPLATE_VERSION}。"),
    ("工作表用途", "使用说明（本表，不导入）；月度汇总；分时电量电价；费用明细；计量点；数据校验；样本参考_勿直接测算。"),
    (
        "记录粒度",
        "月度汇总：每个 户号 + 账期 一行；分时电量电价：每个 账期 + 计量口径 + 时段/小时 一行；"
        "费用明细：每个费用项目一行；计量点：每个计量点一行。",
    ),
    ("必填字段", "各表已用“必填”标注；未标注的为可选。缺必填项将被校验拦截。"),
    ("单位约定", "电量 kWh；电价 元/kWh；金额 元；需量 kW 或 kVA（必须显式选择）。"),
    ("日期格式", "账期 YYYY-MM；日期 YYYY-MM-DD。"),
    (
        "空值与零值",
        "未提供的数据必须留空，**不得填 0**；只有账单明确为 0 时才写 0。"
        "空值表示“未知”，0 表示“确为零”，两者在测算中的处理完全不同。",
    ),
    (
        "来源与复核",
        "关键字段须填写来源文件、来源页码与复核状态。"
        "复核状态：待复核 / 已复核 / 存在疑问 / 不适用。未复核数据不得用于正式测算。",
    ),
    (
        "总电量与分项关系",
        "本期总电量必须取账单明确标注的权威字段，"
        "**不得由计量点电量或分时电量求和推导**。",
    ),
    (
        "总电费口径区别",
        "账单本期电费、工商业电费、市场化购电电费、增值税专票金额口径各不相同，"
        "必须分别保存，**不得为凑平总额而修改原始数据**。",
    ),
    (
        "费用重复计入风险",
        "部分费用可能已包含在其他费用中（如市场运营费）。"
        "必须通过“是否包含在其他费用中 / 被包含于”标记核实，**不得把所有分项简单相加**。",
    ),
    (
        "需量电费的特殊性",
        "需量电费与基本电费具有独立计费机制，"
        "**不得默认按光伏发电量同比例节省**，须按计费方式单独判断可避免性。",
    ),
    (
        "自用率计算前提",
        "只有月度账单无法精确计算光伏自发自用率；"
        "需结合负荷曲线数据，且估算负荷得出的结果必须标注为估算。",
    ),
    (
        "样本数据警告",
        f"`{SHEET_SAMPLE_REFERENCE}` 表仅为字段对照与回归测试使用，"
        "导入器默认忽略该表，**不得作为生产项目数据**。",
    ),
    (
        "模板版本变更规则",
        "字段增删或语义变化时提升模板版本号，并在本表记录变更；"
        "旧版本文件导入时若结构不兼容须给出明确提示，不得静默导入。",
    ),
)


#: `样本参考_勿直接测算` 的预置样本行。
#: 数值取自规格书第 28 节；**这些是初始提取值，不是已逐项复核的正式数据**，
#: 复核状态一律标注为"待复核"。
SAMPLE_TEMPLATE_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    ("本期总电量_kWh", "8780498", "7479418", "kWh", "权威总电量；待复核"),
    ("账单本期电费_元", "6699241.94", "5471334.24", "元", "账单合计；待复核"),
    ("增值税专票金额_元", "6534168.58", "5330721.18", "元", "与总金额口径不同；待复核"),
    ("账单展示平均电价_元每kWh", "0.76297", "0.73152", "元/kWh", "仅统计值，非边际节省电价"),
    ("工商业电费_元", "6708448.31", "5509070.05", "元", "与总金额口径不同；待复核"),
    ("市场化购电电费_元", "3840051.76", "2912242.44", "元", "(1)；待复核"),
    ("上网环节线损费用_元", "179343.47", "145362.52", "元", "(2)；待复核"),
    ("输配电费_元", "2000662.04", "1787644.30", "元", "(3)；待复核"),
    ("系统运行费_元", "291512.53", "325751.10", "元", "(4)；待复核"),
    ("政府性基金及附加_元", "396878.51", "338069.69", "元", "(5)；待复核"),
    ("功率因数调整电费_元", "-9206.37", "-37735.81", "元", "负费用合法，保留负号"),
    ("需量电费_元", "1202916.00", "1108107.00", "元", "独立计费机制，不得按电量同比例节省"),
    (
        "市场化运营费合计_元",
        "-141770.00",
        "-295720.67",
        "元",
        "可能已包含在其他费用中，核实后方可参与合计",
    ),
)


# ---------------------------------------------------------------------------
# 工作表规范
# ---------------------------------------------------------------------------

_INSTRUCTIONS_SHEET = SheetSpec(
    name=SHEET_INSTRUCTIONS,
    purpose="说明模板用途、各表用途与填写规则。",
    granularity="每条说明一行",
    columns=(
        _col("项目", required=True, description="说明主题。"),
        _col("内容", description="说明正文。"),
    ),
    is_business=False,
    freeze_header=False,
    enable_filter=False,
    note="本表仅供阅读，导入器默认忽略。",
)

_MONTHLY_SUMMARY_SHEET = SheetSpec(
    name=SHEET_MONTHLY_SUMMARY,
    purpose="保存每月每户的账单主记录（总量、金额、主要费用、需量、来源）。",
    granularity="每个 项目编号 + 户号 + 账期 一行",
    columns=_MONTHLY_SUMMARY_COLUMNS,
    is_business=True,
)

_TIME_OF_USE_SHEET = SheetSpec(
    name=SHEET_TIME_OF_USE,
    purpose="保存分时或逐小时的电量与电价。",
    granularity="每个 账期 + 计量口径 + 时段（或小时）一行",
    columns=_TIME_OF_USE_COLUMNS,
    is_business=True,
    note="未提供的时段必须留空，不得补 0。",
)

_FEE_ITEMS_SHEET = SheetSpec(
    name=SHEET_FEE_ITEMS,
    purpose="保存费用明细、包含关系与可避免性标记。",
    granularity="每个费用项目一行",
    columns=_FEE_ITEM_COLUMNS,
    is_business=True,
    note="费用包含关系须核实，防止重复汇总。",
)

_METER_POINTS_SHEET = SheetSpec(
    name=SHEET_METER_POINTS,
    purpose="保存计量点信息、主分表关系与倍率。",
    granularity="每个计量点一行",
    columns=_METER_POINT_COLUMNS,
    is_business=True,
    note="未核实主分表关系时不得自动汇总所有计量点电量。",
)

_DATA_VALIDATION_SHEET = SheetSpec(
    name=SHEET_DATA_VALIDATION,
    purpose="记录 13 类数据校验项及其结果与处理状态。",
    granularity="每个校验项一行",
    columns=_VALIDATION_COLUMNS,
    is_business=False,
    note="本表用于记录校验结果，导入器默认忽略。",
)

_SAMPLE_REFERENCE_SHEET = SheetSpec(
    name=SHEET_SAMPLE_REFERENCE,
    purpose="提供两个月的字段对照样本，仅供模板字段对照与回归测试。",
    granularity="每个字段一行（字段名 + 各月数值）",
    columns=(
        _col("字段", required=True, description="字段名称。"),
        _col("2025-09", description="2025 年 9 月样本值。"),
        _col("2025-10", description="2025 年 10 月样本值。"),
        _col("单位", description="该字段单位。"),
        _col("说明", description="字段口径说明或复核提示。"),
    ),
    is_business=False,
    note=SAMPLE_MARKER_TEXT,
)


ALL_SHEETS: tuple[SheetSpec, ...] = (
    _INSTRUCTIONS_SHEET,
    _MONTHLY_SUMMARY_SHEET,
    _TIME_OF_USE_SHEET,
    _FEE_ITEMS_SHEET,
    _METER_POINTS_SHEET,
    _DATA_VALIDATION_SHEET,
    _SAMPLE_REFERENCE_SHEET,
)

_BY_NAME: dict[str, SheetSpec] = {sheet.name: sheet for sheet in ALL_SHEETS}


def get_sheet(name: str) -> SheetSpec:
    """按名称取工作表规范。

    Raises:
        KeyError: 名称不存在（附可用名称，便于定位拼写错误）。
    """
    try:
        return _BY_NAME[name]
    except KeyError:  # pragma: no cover - 错误路径，由测试覆盖
        available = "、".join(_BY_NAME)
        raise KeyError(f"未知工作表 {name!r}；可用工作表：{available}") from None


def columns_of(name: str) -> tuple[ColumnSpec, ...]:
    """返回某工作表的全部字段规范。"""
    return get_sheet(name).columns


def headers_of(name: str) -> tuple[str, ...]:
    """返回某工作表的首行字段标题（顺序即列顺序）。"""
    return tuple(column.header for column in columns_of(name))


def column_by_name(sheet_name: str, column_name: str) -> ColumnSpec:
    """按字段名取字段规范。

    Raises:
        KeyError: 字段不存在。
    """
    for column in columns_of(sheet_name):
        if column.name == column_name:
            return column
    available = "、".join(column.name for column in columns_of(sheet_name))
    raise KeyError(f"工作表 {sheet_name!r} 中无字段 {column_name!r}；可用字段：{available}")


def instruction_rows() -> tuple[DailyRow, ...]:
    """返回 `使用说明` 表的预置说明行（已转为 :class:`DailyRow`）。"""
    return tuple(DailyRow(topic=topic, content=content) for topic, content in _INSTRUCTION_ROWS)


def validation_check_items() -> tuple[tuple[str, str, str, ValidationSeverity], ...]:
    """返回 13 类校验项的预置定义。"""
    return VALIDATION_CHECK_ITEMS
