"""P0-2 测试夹具：脱敏后的真实账单文本片段。

**来源与脱敏说明**

- 片段取自用户提供的**已脱敏**真实电费账单
  （户名、户号、用电地址已在源文件中擦除）。
- 本文件**只保留与字段识别相关的标签行与数值行**，
  并已删除：户名、户号、用电地址、供电服务单位、受电点、电能表编号、
  二维码说明、抄表日期等客户标识与无关信息。
- 本文件**不含**任何账单 PDF 二进制；真实账单文件不在仓库中。

**为什么保留"难看"的排版**

片段**故意保留**真实账单的排版缺陷（标签与数值跨行、标签内含
`-110`/`-35` 电压等级、数量与金额同行、小数点与小数位被切开等），
否则测试就测不出真实解析难点。

`tests/unit/test_bill_field_recognition.py` 中有一条用例会扫描本文件，
断言其中不含客户标识关键词。
"""

from __future__ import annotations

from decimal import Decimal

__all__ = [
    "BILL_2025_09_SNIPPET",
    "BILL_2025_10_SNIPPET",
    "CUSTOMER_IDENTIFIER_KEYWORDS",
    "EXPECTED_2025_09",
    "EXPECTED_2025_10",
    "FIVE_ITEM_KEYS",
]

#: 客户标识关键词：夹具中不得出现（供脱敏自查测试使用）
CUSTOMER_IDENTIFIER_KEYWORDS: tuple[str, ...] = (
    "户名：",
    "户号：",
    "用电地址：",
    "受电点",
    "电能表编号",
    "供电服务单位：",
    "增值税专用发票号",
)

#: 2025 年 9 月账单片段（脱敏、保留真实排版）
BILL_2025_09_SNIPPET = """电 费 账 单
账单周期
2025-09-01
至
2025-09-30
 本期电量
 8780498千瓦时
 本期电费
 6699241.94元
 其中增值税专用发票金
额
 6534168.58元
工商业电费：用电户-110千伏-大工业用电-工商业两部制、用电户-35千伏-非居民照明-工商业单一制
8780498 6708448.31
其中：(1)市场化购电电费 3840051.76
(2)上网环节线损费用 179343.47
(3)输配电费 2000662.04
电量电费 797746.04
输配需量电费 30844 1202916
(4)系统运行费 291512.53
(5)政府性基金及附加 396878.51
功率因数调整电费 -9206.37
 合计 ￥6699241.94
 本期您的需（容）量电费为1202916元
本期您的平均电价0.76297元/千瓦时
"""

#: 2025 年 10 月账单片段（脱敏、保留真实排版；含"小数点与小数位被切开"）
BILL_2025_10_SNIPPET = """电 费 账 单
账单周期
2025-10-01
至
2025-10-31
 本期电量
 7479418千瓦时
 本期电费
 5471334.24元
 其中增值税专用发票金
额
 5330721.18元
工商业电费：用电户-110千伏-大工业用电-工商业两部制、用电户-35千伏-非居民照明-工商业单一制
7479418 5509070.05
其中：(1)市场化购电电费 2912242.44
(2)上网环节线损费用 145362.52
(3)输配电费 1787644.
3
(4)系统运行费 325751.1
(5)政府性基金及附加 338069.69
功率因数调整电费 -37735.81
 合计 ￥5471334.24
 本期您的需（容）量电费为1108107元
本期您的平均电价0.73152元/千瓦时
"""

#: "五项之和"的标签（顺序与账单 (1)~(5) 一致）
FIVE_ITEM_KEYS: tuple[str, ...] = (
    "(1)市场化购电电费",
    "(2)上网环节线损费用",
    "(3)输配电费",
    "(4)系统运行费",
    "(5)政府性基金及附加",
)

#: 2025-09 期望值（来自 P0_2_REGRESSION_BASELINE.md，已与原始 PDF 逐项核验）
EXPECTED_2025_09: dict[str, Decimal | str] = {
    "billing_period_start": "2025-09-01",
    "billing_period_end": "2025-09-30",
    "total_consumption": Decimal("8780498"),
    "bill_total_amount": Decimal("6699241.94"),
    "vat_invoice_amount": Decimal("6534168.58"),
    "displayed_average_price": Decimal("0.76297"),
    "industrial_commercial_fee": Decimal("6708448.31"),
    "market_purchase_fee": Decimal("3840051.76"),
    "grid_loss_fee": Decimal("179343.47"),
    "transmission_distribution_fee": Decimal("2000662.04"),
    "system_operation_fee": Decimal("291512.53"),
    "government_fund_fee": Decimal("396878.51"),
    "power_factor_adjustment_fee": Decimal("-9206.37"),
    "demand_charge": Decimal("1202916"),
}

#: 2025-10 期望值
EXPECTED_2025_10: dict[str, Decimal | str] = {
    "billing_period_start": "2025-10-01",
    "billing_period_end": "2025-10-31",
    "total_consumption": Decimal("7479418"),
    "bill_total_amount": Decimal("5471334.24"),
    "vat_invoice_amount": Decimal("5330721.18"),
    "displayed_average_price": Decimal("0.73152"),
    "industrial_commercial_fee": Decimal("5509070.05"),
    "market_purchase_fee": Decimal("2912242.44"),
    "grid_loss_fee": Decimal("145362.52"),
    "transmission_distribution_fee": Decimal("1787644.30"),
    "system_operation_fee": Decimal("325751.10"),
    "government_fund_fee": Decimal("338069.69"),
    "power_factor_adjustment_fee": Decimal("-37735.81"),
    "demand_charge": Decimal("1108107"),
}
