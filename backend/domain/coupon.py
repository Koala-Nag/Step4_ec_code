# -*- coding: utf-8 -*-
"""クーポンの判定（要件定義書 BR-12・BR-16・BR-16a）。

★このモジュールは repository も external も import しない（設計 2.2）。
  「使えるか」「いくら引くか」は、読んだ行を引数で渡せば決まる。

BR-16   クーポンは1注文に1枚のみ。併用しない。
        ★最低購入金額の判定は「割引前の商品合計」で行う
BR-16a  上限は2種類ある。
        ・全体の利用回数上限 → 利用済回数で判定。★在庫と同じく更新件数で先勝ち
        ・会員あたりの上限   → その会員の利用履歴の件数で判定
BR-12   割引は商品合計に適用。商品合計が上限

★「先勝ち」の判定そのものは、ここではできない（DBの更新件数が要る）。
  ここが決めるのは「その手前で弾けるもの」——期間・最低金額・会員あたりの上限。
  ★repository/coupon.py の条件付きUPDATE と役割を分けてある。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# coupon.discount_type
TYPE_RATE = 1     # 割合引き（discount_value は %）
TYPE_AMOUNT = 2   # 金額引き


@dataclass(frozen=True)
class Coupon:
    """coupon（E-28）から読んだ行。"""

    coupon_code: str
    discount_type: int
    discount_value: int
    start_at: datetime
    end_at: datetime
    min_amount: int
    total_limit: int | None
    used_count: int
    per_member_limit: int | None


def reason_unusable(c: Coupon, *, item_total: int, now: datetime,
                    member_used: int) -> str | None:
    """使えない理由の符号。使えれば None。

    ★ここで弾けるのは「読んだ時点で決まっているもの」だけ。
      全体上限は ★ここでは判定しない——読んでから書くまでの隙間に他が使う。
      それは条件付きUPDATEの更新件数で決める（BR-16a・6.2.3）。
    """
    if now < c.start_at or now > c.end_at:
        return "ERR-1211"                    # 期間外（8.2）
    if item_total < c.min_amount:
        # ★BR-16。最低購入金額の判定は「割引前」の商品合計で行う
        return "ERR-1212"                    # 最低購入金額（8.2）
    if c.per_member_limit is not None and member_used >= c.per_member_limit:
        return "ERR-1214"                    # 会員あたりの上限
    if c.total_limit is not None and c.used_count >= c.total_limit:
        # ★ここで弾けるのは「もう明らかに無い」場合だけ。
        #   ちょうど最後の1枚を2人が取り合う場合は、ここを通り抜ける。
        #   ★そこは条件付きUPDATEが決める（IT-413）
        return "ERR-1213"
    return None


def discount_for(c: Coupon, item_total: int) -> int:
    """割引額（BR-12）。★商品合計が上限。負にしない。

    ★割合引きは円未満を切り捨てる。BR-15 の丸めとは別のもので、
      こちらは「割引額をいくらにするか」の丸め。
    """
    if item_total <= 0:
        return 0
    if c.discount_type == TYPE_RATE:
        raw = item_total * max(c.discount_value, 0) // 100
    else:
        raw = max(c.discount_value, 0)
    return min(raw, item_total)


# ============================================================
# BR-12  対象を限定したクーポン（R-32）
# ============================================================
TARGET_ALL, TARGET_CATEGORY, TARGET_PRODUCT = 1, 2, 3


@dataclass(frozen=True)
class TargetLine:
    """カートの1行。★対象かどうかを決めるのに要るぶんだけ。"""

    amount: int                    # 明細金額（単価 × 数量）
    product_code: str
    category_code: str
    parent_category_code: str | None


def eligible_total(targets: list[tuple[int, str | None]], lines: list[TargetLine]) -> int:
    """BR-12「対象商品を限定したクーポンは、対象商品の明細金額の合計に適用する」。

    targets  coupon_target の (target_kind, target_id)。★行が無い・全商品が1つでもあれば全商品
    ★カテゴリは親でも子でも当たる（「トップス」を対象にすると、Tシャツもシャツも入る）。
    """
    if not targets or any(k == TARGET_ALL for k, _ in targets):
        return sum(l.amount for l in lines)
    cats = {t for k, t in targets if k == TARGET_CATEGORY and t}
    prods = {t for k, t in targets if k == TARGET_PRODUCT and t}
    return sum(l.amount for l in lines
               if l.product_code in prods or l.category_code in cats
               or (l.parent_category_code is not None and l.parent_category_code in cats))


# ============================================================
# F-1001  クーポンを作る・直す（R-32）
# ============================================================
COUPON_CODE_RE = re.compile(r"^[A-Z0-9]{1,20}$")     # ★20文字以内の半角英数大文字（要件 6.3）
COUPON_NAME_MAX = 50
AMOUNT_MAX = 9_999_999


def coupon_input_error(*, name: str | None = None, discount_type: int | None = None,
                       discount_value: int | None = None, start_at: datetime | None = None,
                       end_at: datetime | None = None, min_amount: int | None = None,
                       total_limit: int | None = None, per_member_limit: int | None = None,
                       used_count: int = 0) -> str | None:
    """通れば None。"項目:理由" を返す。"""
    if name is not None:
        if not name.strip():
            return "name:empty"
        if len(name.strip()) > COUPON_NAME_MAX:
            return "name:too_long"
    if discount_type is not None and discount_type not in (TYPE_RATE, TYPE_AMOUNT):
        return "discount_type:choice"
    if discount_value is not None:
        # ★割合は 1〜100（%）。金額は 1円以上。0 は割引にならないので作らせない
        hi = 100 if discount_type == TYPE_RATE else AMOUNT_MAX
        if not (1 <= discount_value <= hi):
            return "discount_value:range"
    if start_at is not None and end_at is not None and end_at < start_at:
        return "end_at:range"
    if min_amount is not None and not (0 <= min_amount <= AMOUNT_MAX):
        return "min_amount:range"
    for field, v in (("total_limit", total_limit), ("per_member_limit", per_member_limit)):
        if v is not None and v < 1:
            return f"{field}:range"
    if total_limit is not None and total_limit < used_count:
        return "total_limit:below_used"         # ★もう使われた回数より小さくはできない
    return None
