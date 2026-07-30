"""券型与优惠计算（FR-015、FR-022、ADR-013）。

两种券型共用最低消费门槛，差异只在优惠金额的算法：

- CASH   满减券：满 min_order_amount 减 face_value，优惠额恒为 face_value
- DISCOUNT 折扣券：满 min_order_amount 打 discount_percent 折，
           优惠额 = 订单金额 × (100 - discount_percent) / 100，并受 max_discount_amount 封顶

封顶对折扣券是必填而非可选：无上限的折扣券在大额订单上会造成不可控的
营销成本，这是真实业务的硬约束。
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from ..models import Campaign

_CENT = Decimal("0.01")


def describe(campaign: Campaign) -> str:
    """券的面额描述，供列表与卡片展示。"""
    threshold = campaign.min_order_amount or Decimal(0)
    if campaign.coupon_type == "CASH":
        base = f"满 {_fmt(threshold)} 减 {_fmt(campaign.face_value or Decimal(0))}"
        return base if threshold > 0 else f"立减 {_fmt(campaign.face_value or Decimal(0))}"
    tenths = Decimal(campaign.discount_percent or 0) / Decimal(10)
    label = f"{_fmt(tenths)} 折"
    prefix = f"满 {_fmt(threshold)} 享" if threshold > 0 else "全单"
    return f"{prefix} {label}（最高减 {_fmt(campaign.max_discount_amount or Decimal(0))}）"


def _fmt(value: Decimal) -> str:
    """去掉无意义的小数尾零：20.00 → 20，8.50 → 8.5。

    不用 Decimal.normalize()：它会把 100 变成科学计数法 1E+2，
    而这个字符串会直接显示在用户界面上。
    """
    q = Decimal(value).quantize(_CENT)
    text = format(q, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def compute_discount(campaign: Campaign, order_amount: Decimal) -> Decimal:
    """按券型算出实际优惠金额。调用方须已校验门槛。

    结果向下取整到分：优惠额多算一分是商家吃亏，少算一分用户可接受，
    因此取 ROUND_DOWN 而不是四舍五入。
    """
    if campaign.coupon_type == "CASH":
        amount = Decimal(campaign.face_value or 0)
    else:
        percent_off = Decimal(100 - int(campaign.discount_percent or 0))
        amount = order_amount * percent_off / Decimal(100)
        cap = Decimal(campaign.max_discount_amount or 0)
        amount = min(amount, cap)
    # 优惠额不得超过订单金额本身
    amount = min(amount, order_amount)
    return amount.quantize(_CENT, rounding=ROUND_DOWN)


def meets_threshold(campaign: Campaign, order_amount: Decimal) -> bool:
    return order_amount >= Decimal(campaign.min_order_amount or 0)
