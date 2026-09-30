# -*- coding: utf-8 -*-
"""クーポンの判定（BR-12・BR-16・BR-16a）。★DBを立てない。"""
from __future__ import annotations

from datetime import datetime

import pytest

from domain import coupon as cp
from domain.coupon import Coupon

NOW = datetime(2026, 9, 11, 12, 0, 0)


def make(**kw) -> Coupon:
    base = dict(
        coupon_code="C500", discount_type=cp.TYPE_AMOUNT, discount_value=500,
        start_at=datetime(2026, 9, 1), end_at=datetime(2026, 9, 30),
        min_amount=0, total_limit=None, used_count=0, per_member_limit=None,
    )
    base.update(kw)
    return Coupon(**base)


# --- 割引額（BR-12）------------------------------------------
def test_金額引き():
    assert cp.discount_for(make(), 3000) == 500


def test_割合引きは円未満を切り捨てる():
    c = make(discount_type=cp.TYPE_RATE, discount_value=10)
    assert cp.discount_for(c, 3999) == 399        # 399.9 → 399


def test_割引額は商品合計が上限():
    """★BR-12。支払総額を負にしない。"""
    assert cp.discount_for(make(discount_value=9999), 1000) == 1000
    c = make(discount_type=cp.TYPE_RATE, discount_value=200)
    assert cp.discount_for(c, 1000) == 1000


def test_商品合計が0なら割引も0():
    assert cp.discount_for(make(), 0) == 0


# --- 期間（BR-16）--------------------------------------------
@pytest.mark.parametrize("now,expected", [
    (datetime(2026, 9, 1), None),                 # 開始ちょうど
    (datetime(2026, 8, 31, 23, 59, 59), "ERR-1211"),
    (datetime(2026, 9, 30), None),                # 終了ちょうど
    (datetime(2026, 9, 30, 0, 0, 1), "ERR-1211"),
])
def test_期間の境目(now, expected):
    assert cp.reason_unusable(make(), item_total=1000, now=now, member_used=0) == expected


# --- 最低購入金額（BR-16）------------------------------------
def test_最低購入金額は割引前の商品合計で判定する():
    """★BR-16 が明記している。★割引後で判定すると、

    「3,000円以上で500円引き」のクーポンを 3,000円の注文に使ったとき、
    割引後が 2,500円になって条件を割り、使えたり使えなかったりが揺れる。
    """
    c = make(min_amount=3000)
    assert cp.reason_unusable(c, item_total=3000, now=NOW, member_used=0) is None
    assert cp.reason_unusable(c, item_total=2999, now=NOW, member_used=0) == "ERR-1212"


# --- 上限（BR-16a）-------------------------------------------
def test_会員あたりの上限は利用履歴の件数で判定する():
    c = make(per_member_limit=1)
    assert cp.reason_unusable(c, item_total=1000, now=NOW, member_used=0) is None
    assert cp.reason_unusable(c, item_total=1000, now=NOW, member_used=1) == "ERR-1214"


def test_全体上限は明らかに無いときだけここで弾く():
    """★ここで弾けるのは「読んだ時点でもう無い」場合だけ。

    ★ちょうど最後の1枚を2人が取り合う場合は、ここを通り抜ける。
      そこは条件付きUPDATEの更新件数が決める（BR-16a・IT-413）。
      ★この関数だけで守ろうとすると、必ず二重に使われる。
    """
    assert cp.reason_unusable(make(total_limit=1, used_count=1),
                              item_total=1000, now=NOW, member_used=0) == "ERR-1213"
    # 最後の1枚。★ここは通る（通ったうえで、更新件数で1人だけが勝つ）
    assert cp.reason_unusable(make(total_limit=1, used_count=0),
                              item_total=1000, now=NOW, member_used=0) is None


def test_上限が無いクーポンは何回でも通る():
    assert cp.reason_unusable(make(total_limit=None, used_count=999),
                              item_total=1000, now=NOW, member_used=0) is None
