# -*- coding: utf-8 -*-
"""UT-100番台｜金額の計算（単体テスト仕様書 1章）。

★DBを立てない。domain/ だけを import する。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from domain import pricing
from domain.pricing import CartLine, DeliveryType

FEE = 550          # BR-13 全国一律
FREE_LINE = 5000   # BR-13 送料無料ライン
TAX = Decimal("0.1")


def summarize(lines, *, discount=0, delivery_type=DeliveryType.SHIP):
    return pricing.summarize(
        lines, discount=discount, delivery_type=delivery_type,
        fee=FEE, free_line=FREE_LINE, tax_rate=TAX,
    )


# --- UT-101 正常値 -------------------------------------------------
def test_ut101_一点だけ買うと送料がつく():
    s = summarize([CartLine("S1", 2990, 1)])
    assert s.item_total == 2990
    assert s.shipping_fee == 550
    assert s.total_amount == 3540
    assert s.tax_amount == 321


# --- UT-102 正常値 -------------------------------------------------
def test_ut102_五千円以上は送料無料():
    s = summarize([CartLine("S1", 2990, 2)])
    assert s.item_total == 5980
    assert s.shipping_fee == 0
    assert s.total_amount == 5980


# --- UT-103 ★境界値 ------------------------------------------------
def test_ut103_割引後がちょうど五千円なら送料は0():
    assert pricing.shipping_fee(5000, delivery_type=DeliveryType.SHIP,
                                fee=FEE, free_line=FREE_LINE) == 0


# --- UT-104 ★境界値 ------------------------------------------------
def test_ut104_割引後が四千九百九十九円なら送料がつく():
    assert pricing.shipping_fee(4999, delivery_type=DeliveryType.SHIP,
                                fee=FEE, free_line=FREE_LINE) == 550


# --- UT-105 境界値 -------------------------------------------------
def test_ut105_割引後が五千一円なら送料は0():
    assert pricing.shipping_fee(5001, delivery_type=DeliveryType.SHIP,
                                fee=FEE, free_line=FREE_LINE) == 0


# --- UT-106 ★正常値 ------------------------------------------------
def test_ut106_送料無料の判定は割引の後で行う():
    """★これがこの章でいちばん大事。

    商品合計 5,200円・割引 500円 → 割引後 4,700円 → 送料 550円。
    ★割引「前」で判定すると 0円になり、550円を取り損ねる。画面はふつうに動く。
    """
    s = summarize([CartLine("S1", 5200, 1)], discount=500)
    assert s.item_total == 5200
    assert s.discount == 500
    assert s.shipping_fee == 550, "割引前の 5,200円 で判定してしまっている"
    assert s.total_amount == 5250


# --- UT-107 正常値 -------------------------------------------------
def test_ut107_店舗受取は金額にかかわらず送料0():
    s = summarize([CartLine("S1", 1000, 1)], delivery_type=DeliveryType.PICKUP)
    assert s.shipping_fee == 0
    assert s.total_amount == 1000


# --- UT-108 正常値 -------------------------------------------------
def test_ut108_消費税は支払総額から逆算して切り捨てる():
    # 3540 × 0.1 ÷ 1.1 = 321.81... → 321
    assert pricing.tax_amount(3540, TAX) == 321


# --- UT-109 境界値 -------------------------------------------------
def test_ut109_丸めは注文単位で一回だけ():
    """明細ごとに丸めてから足すと、注文単位で丸めた額とずれる。"""
    lines = [CartLine("A", 333, 1), CartLine("B", 333, 1), CartLine("C", 333, 1)]
    s = summarize(lines)
    per_line = sum(pricing.tax_amount(l.unit_price, TAX) for l in lines)
    assert s.tax_amount == pricing.tax_amount(s.total_amount, TAX)
    assert s.tax_amount != per_line, "明細ごとに丸めた値と一致してしまっている"


# --- UT-110 ★異常値 ------------------------------------------------
def test_ut110_割引が商品合計を超えても支払総額は負にならない():
    s = summarize([CartLine("S1", 1000, 1)], discount=1500)
    assert s.discount == 1000       # BR-12 商品合計が上限
    assert s.total_amount >= 0
    assert s.total_amount == 550    # 割引後0円 → 送料はかかる


# --- UT-111 正常値 -------------------------------------------------
def test_ut111_対象商品限定のクーポンは対象の明細金額にだけかかる():
    lines = [CartLine("A", 3000, 1), CartLine("B", 2000, 1)]
    # 対象は A だけ。5,000円のクーポンでも A の 3,000円が上限
    assert pricing.discount_for_targets(lines, target_skus={"A"}, amount=5000) == 3000
    assert pricing.discount_for_targets(lines, target_skus={"A"}, amount=1000) == 1000
    # 対象を限定しないクーポンは注文全体が上限
    assert pricing.discount_for_targets(lines, target_skus=None, amount=9999) == 5000


# --- UT-112 正常値 -------------------------------------------------
def test_ut112_計算の順番():
    """明細金額 → 商品合計 → 割引 → 送料判定 → 送料加算 → 消費税（BR-10）。"""
    s = summarize([CartLine("S1", 2600, 2)], discount=300)   # 5,200 → 4,900
    assert s.item_total == 5200
    assert s.discount == 300
    assert s.shipping_fee == 550                              # 4,900 で判定
    assert s.total_amount == 5450                             # 4,900 + 550
    assert s.tax_amount == pricing.tax_amount(5450, TAX)      # 支払総額から逆算


# --- UT-113 異常値 -------------------------------------------------
def test_ut113_明細が0件なら商品合計0():
    s = summarize([])
    assert s.item_total == 0
    assert s.tax_amount == 0


@pytest.mark.parametrize("saleable,expected", [(0, 0), (1, 1), (98, 98), (99, 99), (150, 99)])
def test_数量の上限は99と販売可能数の小さい方(saleable, expected):
    assert pricing.max_addable_qty(saleable) == expected
