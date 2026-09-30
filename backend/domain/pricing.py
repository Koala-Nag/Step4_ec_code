# -*- coding: utf-8 -*-
"""金額の計算（要件定義書 BR-09〜BR-15）。

★このモジュールは repository も external も import しない（設計 2.2）。
  DBを立てずに単体で確かめられるようにするため。

★金額はサーバが決める。画面から送らせない（N-35）。
  リクエストの本文に unit_price があっても、ここには渡さない。単価はマスタから引く。

★式は要件定義書が正。設計仕様書には写していない（設計 6.7。二重管理になるため）。
  BR-10  計算順序：明細金額 → 商品合計 → 割引 → 送料判定 → 送料加算 → 消費税額
  BR-11  明細金額＝税込単価 × 数量
  BR-12  割引は商品合計に適用。商品合計が上限
  BR-13  送料は全国一律。★送料無料の判定は「割引適用後の商品合計」で行う
  BR-14  店舗受取は送料0
  BR-15  消費税額は支払総額から逆算。丸めは注文単位で1回・円未満切り捨て
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

# F-301。1明細の数量の上限（販売可能数と、この値の小さい方）
MAX_QTY_PER_LINE = 99
# F-301。カート明細の件数の上限
MAX_LINES = 20


class DeliveryType:
    SHIP = "ship"       # 配送
    PICKUP = "pickup"   # 店舗受取（BR-14 で送料0）


@dataclass(frozen=True)
class CartLine:
    """金額計算に要るぶんだけ。SKUの名前や画像はここに持ち込まない。"""

    sku_code: str
    unit_price: int   # 税込（BR-09）
    qty: int


def max_addable_qty(saleable_qty: int) -> int:
    """入れられる数量の上限（F-301）。99 と販売可能数の小さい方。"""
    return min(MAX_QTY_PER_LINE, max(saleable_qty, 0))


def line_amount(unit_price: int, qty: int) -> int:
    """BR-11 明細金額＝税込単価 × 数量。"""
    return unit_price * qty


def subtotal(lines: list[CartLine]) -> int:
    """BR-11 商品合計＝明細金額の合計。"""
    return sum(line_amount(l.unit_price, l.qty) for l in lines)


def apply_discount(item_total: int, discount: int) -> int:
    """BR-12 割引は商品合計が上限。負にしない。"""
    return max(item_total - min(max(discount, 0), item_total), 0)


def discount_for_targets(
    lines: list[CartLine], *, target_skus: set[str] | None, amount: int
) -> int:
    """BR-12 の後半。対象商品を限定したクーポンは、対象商品の明細金額の合計に適用する。

    ★上限は「注文全体の商品合計」ではなく「対象商品の明細金額の合計」。
      ここを注文全体にすると、対象外の商品まで値引きしたのと同じ結果になる。
    """
    base = (
        subtotal(lines)
        if target_skus is None
        else sum(line_amount(l.unit_price, l.qty) for l in lines if l.sku_code in target_skus)
    )
    return min(max(amount, 0), base)


def shipping_fee(
    after_discount: int, *, delivery_type: str, fee: int, free_line: int
) -> int:
    """BR-13・BR-14。

    ★送料無料の判定は「割引適用後の商品合計」で行う。
      割引前で判定すると、クーポンで5,000円を割ったのに送料が0のままになる。
    """
    if delivery_type == DeliveryType.PICKUP:
        return 0
    return 0 if after_discount >= free_line else fee


def free_shipping_remain(after_discount: int, *, delivery_type: str, free_line: int) -> int:
    """あと何円で送料無料になるか。店舗受取のときは 0（そもそも無料）。"""
    if delivery_type == DeliveryType.PICKUP:
        return 0
    return max(free_line - after_discount, 0)


def tax_amount(total: int, tax_rate: Decimal) -> int:
    """BR-15 消費税額＝支払総額 × 税率 ÷ (1 + 税率)。円未満切り捨て・注文単位で1回だけ。"""
    if total <= 0:
        return 0
    t = Decimal(total) * tax_rate / (Decimal(1) + tax_rate)
    return int(t.quantize(Decimal("1"), rounding=ROUND_DOWN))


@dataclass(frozen=True)
class Summary:
    item_total: int
    discount: int
    shipping_fee: int
    total_amount: int
    tax_amount: int
    free_shipping_remain: int
    delivery_type: str


def summarize(
    lines: list[CartLine],
    *,
    delivery_type: str = DeliveryType.SHIP,
    discount: int = 0,
    fee: int,
    free_line: int,
    tax_rate: Decimal,
) -> Summary:
    """BR-10 の順番どおりに計算する。順番を変えると結果が変わる。"""
    if not lines:
        # ★明細が0件なら送料の判定に進まない（UT-113）。まだ注文になっていない。
        #   ここを通していたので、空のカート画面が「送料550円・支払総額550円」を出していた。
        #   ★「割引で0円になった」（送料はかかる）とは別物。混ぜない。
        return Summary(0, 0, 0, 0, 0, free_line if delivery_type == DeliveryType.SHIP else 0,
                       delivery_type)
    item_total = subtotal(lines)                                   # ① 明細金額 → 商品合計
    after_discount = apply_discount(item_total, discount)          # ② 割引
    ship = shipping_fee(                                           # ③ 送料判定・④ 加算
        after_discount, delivery_type=delivery_type, fee=fee, free_line=free_line
    )
    total = after_discount + ship
    return Summary(
        item_total=item_total,
        discount=item_total - after_discount,
        shipping_fee=ship,
        total_amount=total,
        tax_amount=tax_amount(total, tax_rate),                    # ⑤ 消費税額
        free_shipping_remain=free_shipping_remain(
            after_discount, delivery_type=delivery_type, free_line=free_line
        ),
        delivery_type=delivery_type,
    )
