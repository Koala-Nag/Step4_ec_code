# -*- coding: utf-8 -*-
"""出荷指示の組み立てと、注文状態の導出（設計 6.3・要件 5.3）。★DBを立てない。"""
from __future__ import annotations

import pytest

from domain import shipping as sp
from domain.shipping import AllocatedLine as L, Destination


CUST = Destination(kind=sp.DEST_CUSTOMER, name="山田太郎", zip="1600022", pref_code="13",
                   address="東京都新宿区1-2-3", tel="09000000001")
STORE = Destination(kind=sp.DEST_STORE, name="新宿店", zip="1600022", pref_code="13",
                    address="東京都新宿区4-5-6", tel="0300000000", location_code="T003")


# --- 手順1〜3｜出荷の分け方 ------------------------------------
def test_引当拠点ごとに1つの出荷になる():
    plans = sp.plan_shipments(
        [L(1, "A", 1, "W001"), L(2, "B", 1, "T003"), L(3, "C", 2, "W001")],
        receive_method=sp.RECEIVE_SHIP, customer=CUST, pickup_store=None,
    )
    assert [p.from_location_code for p in plans] == ["T003", "W001"]   # 拠点コードの昇順
    assert [l.line_no for l in plans[1].lines] == [1, 3]


def test_1拠点なら出荷は1つ():
    plans = sp.plan_shipments([L(1, "A", 1, "W001"), L(2, "B", 1, "W001")],
                              receive_method=sp.RECEIVE_SHIP, customer=CUST, pickup_store=None)
    assert len(plans) == 1


def test_配送の届け先は客の住所():
    plans = sp.plan_shipments([L(1, "A", 1, "W001")], receive_method=sp.RECEIVE_SHIP,
                              customer=CUST, pickup_store=None)
    assert plans[0].dest.kind == sp.DEST_CUSTOMER
    assert plans[0].dest.name == "山田太郎"


# --- BR-08b ---------------------------------------------------
def test_BR08b_店舗受取はどの拠点から出しても届け先が受取店():
    plans = sp.plan_shipments([L(1, "A", 1, "W001"), L(2, "B", 1, "T004")],
                              receive_method=sp.RECEIVE_PICKUP, customer=CUST, pickup_store=STORE)
    assert all(p.dest.kind == sp.DEST_STORE for p in plans)
    assert all(p.dest.name == "新宿店" for p in plans)


def test_受取店から引き当てた分も出荷を作る():
    """★出荷元＝受取店でも出荷は作る（6.3 手順3）。

    作らないと 5.3 の「出荷指示済 → 出荷済」を通れず、MSG-11 も送れない。
    """
    plans = sp.plan_shipments([L(1, "A", 1, "T003")], receive_method=sp.RECEIVE_PICKUP,
                              customer=CUST, pickup_store=STORE)
    assert len(plans) == 1
    assert plans[0].is_pickup_at_origin is True      # 取り置きで進める出荷
    # 他拠点から受取店へ送るぶんは、ふつうの出荷
    other = sp.plan_shipments([L(1, "A", 1, "W001")], receive_method=sp.RECEIVE_PICKUP,
                              customer=CUST, pickup_store=STORE)
    assert other[0].is_pickup_at_origin is False


def test_店舗受取なのに受取店が無ければ組み立てられない():
    with pytest.raises(ValueError):
        sp.plan_shipments([L(1, "A", 1, "W001")], receive_method=sp.RECEIVE_PICKUP,
                          customer=CUST, pickup_store=None)


# --- 5.3 の導出表 ---------------------------------------------
@pytest.mark.parametrize("statuses,expected", [
    ([sp.SHIP_ARRIVED, sp.SHIP_ARRIVED], sp.ORDER_DONE),
    ([sp.SHIP_HANDED], sp.ORDER_DONE),
    ([sp.SHIP_ARRIVED, sp.SHIP_HANDED], sp.ORDER_DONE),
    ([sp.SHIP_SHIPPED, sp.SHIP_SHIPPED], sp.ORDER_SHIPPED),
    ([sp.SHIP_SHIPPED, sp.SHIP_ARRIVED], sp.ORDER_SHIPPED),
    ([sp.SHIP_SHIPPED, sp.SHIP_INSTRUCTED], sp.ORDER_PARTIAL_SHIPPED),
    ([sp.SHIP_INSTRUCTED, sp.SHIP_INSTRUCTED], sp.ORDER_INSTRUCTED),
    ([sp.SHIP_SHORT, sp.SHIP_SHORT], sp.ORDER_SHORT_HOLD),
    ([sp.SHIP_CANCELLED, sp.SHIP_CANCELLED], sp.ORDER_CANCELLED),
])
def test_注文の状態は出荷の状態から決まる(statuses, expected):
    assert sp.order_status_from_shipments(statuses) == expected


def test_欠品が決着したら除外して残りで決める():
    """★5.3 の5行目。欠品分を「キャンセル済出荷として」除外し、残りで決める。

    ★除外されるのは F-911 でキャンセルになった出荷（7）。
    """
    assert sp.order_status_from_shipments([sp.SHIP_SHIPPED, sp.SHIP_CANCELLED]) == sp.ORDER_SHIPPED
    assert sp.order_status_from_shipments([sp.SHIP_ARRIVED, sp.SHIP_CANCELLED]) == sp.ORDER_DONE


def test_未解決の欠品は除外しない():
    """★報告されただけの欠品（6）は、まだ決着していない（R-26 で直した）。

    ★以前は [出荷済, 欠品] を「出荷済」にしていた。
      残り1点が宙に浮いたまま、客には「発送済み」と見える形だった。
    """
    assert sp.order_status_from_shipments([sp.SHIP_SHIPPED, sp.SHIP_SHORT]) == sp.ORDER_PARTIAL_SHIPPED
    assert sp.order_status_from_shipments([sp.SHIP_INSTRUCTED, sp.SHIP_SHORT]) == sp.ORDER_INSTRUCTED


def test_全出荷が欠品のときだけ欠品保留():
    """設計 6.4 手順3。★一部だけなら欠品保留にしない。"""
    assert sp.order_status_from_shipments([sp.SHIP_SHORT]) == sp.ORDER_SHORT_HOLD
    assert sp.order_status_from_shipments([sp.SHIP_SHORT, sp.SHIP_SHORT]) == sp.ORDER_SHORT_HOLD
    # 1つ欠品・1つキャンセル（決着）→ 残りは全部欠品なので欠品保留
    assert sp.order_status_from_shipments([sp.SHIP_SHORT, sp.SHIP_CANCELLED]) == sp.ORDER_SHORT_HOLD


def test_出荷が1つも無ければ出荷指示済のまま():
    assert sp.order_status_from_shipments([]) == sp.ORDER_INSTRUCTED


# --- 追跡番号（E-24）------------------------------------------
def test_客の住所宛は追跡番号が要るが取り置きは要らない():
    assert sp.tracking_required(sp.DEST_CUSTOMER) is True
    assert sp.tracking_required(sp.DEST_STORE) is False


# --- BR-17f キャンセルの可否 ----------------------------------
@pytest.mark.parametrize("status,expected", [
    (sp.ORDER_ALLOCATED, True),          # 引当済まではできる
    (sp.ORDER_INSTRUCTED, False),        # ★出荷指示済からできない
    (sp.ORDER_PARTIAL_SHIPPED, False),
    (sp.ORDER_SHIPPED, False),
    (sp.ORDER_DONE, False),
    (sp.ORDER_CANCELLED, False),
])
def test_BR17f_キャンセルできる状態(status, expected):
    assert sp.can_cancel(status) is expected


# --- 分割出荷の売上確定（6.3.1。R-27 で送料を「最初」に）--------------------
def test_分割出荷の売上確定は合計が支払総額と一致する():
    """★送料は「最初に確定する出荷」に載せる（6.3.1 ②）。"""
    total = 5530            # 商品 4,980 + 送料 550
    first = sp.capture_amount(total_amount=total, this_items_after_discount=1990,
                              shipping_fee=550, already_captured=0, is_first=True)
    second = sp.capture_amount(total_amount=total, this_items_after_discount=2990,
                               shipping_fee=550, already_captured=first, is_first=False)
    assert first == 2540                 # 明細 1,990 ＋ 送料 550
    assert second == 2990                # 明細だけ
    assert first + second == total


def test_発送の順番がIDの順と違っても送料は最初の1回に載る():
    """★現場の発送順は出荷IDの順とは限らない。判定は「確定がまだ無いか」だけ。"""
    total = 5530
    a = sp.capture_amount(total_amount=total, this_items_after_discount=2990,
                          shipping_fee=550, already_captured=0, is_first=True)
    b = sp.capture_amount(total_amount=total, this_items_after_discount=1990,
                          shipping_fee=550, already_captured=a, is_first=False)
    assert a == 3540
    assert b == 1990
    assert a + b == total


def test_出荷が1つなら支払総額の全額():
    got = sp.capture_amount(total_amount=2540, this_items_after_discount=1990,
                            shipping_fee=550, already_captured=0, is_first=True)
    assert got == 2540


def test_合計は必ず与信額以下になる():
    """★超える場合は送らない（6.3.1）。ここでは頭打ちで担保する。"""
    got = sp.capture_amount(total_amount=1000, this_items_after_discount=9999,
                            shipping_fee=0, already_captured=1000, is_first=False)
    assert got == 0


def test_後の出荷が欠品で取り消されても送料は宙に浮かない():
    """★R-26 で実測した形（6.3.1 ② の例）。

    1,290（W001）＋ 2,500（T003）＋ 送料 550 ＝ 4,340。T003 が欠品。
      W001 を発送 → 最初の確定なので 1,290 ＋ 550 ＝ 1,840
      T003 を部分キャンセル（一部欠品なので送料は返さない）→ 取消 2,500
      1,840 ＋ 2,500 ＝ 4,340 ★ちょうど
    """
    from domain import refund as rf
    cap = sp.capture_amount(total_amount=4340, this_items_after_discount=1290,
                            shipping_fee=550, already_captured=0, is_first=True)
    back = rf.shortage_refund([rf.AllocatedLine(2, 2500, 0)], all_lines_short=False,
                              shipping_fee=550, total_amount=4340)
    assert (cap, back) == (1840, 2500)
    assert cap + back == 4340


def test_割引があっても明細は按分を引いた額で確定する():
    """★R-26 の不具合1（6.3.1 ①）。割引前で取ると、欠品の取消と合わせて支払総額を超える。"""
    from domain import refund as rf
    got = sp.capture_amount(total_amount=6999, this_items_after_discount=(2500 - 166) + (2499 - 166),
                            shipping_fee=0, already_captured=0, is_first=True)
    back = rf.shortage_refund([rf.AllocatedLine(3, 2500, 168)], all_lines_short=False,
                              shipping_fee=0, total_amount=6999)
    assert (got, back) == (4667, 2332)
    assert got + back == 6999
