# -*- coding: utf-8 -*-
"""UT-500番台｜返金の按分（単体テスト仕様書 5章）。"""
from __future__ import annotations

from domain import refund
from domain.refund import AllocatedLine, Line

TOTAL_AMOUNT = 2900   # 3,000円 − 割引100円（送料は無料ラインを超えているので0）


def allocated(order_discount=100, amounts=(1000, 1000, 1000)):
    lines = [Line(i + 1, a) for i, a in enumerate(amounts)]
    return refund.allocate_discount(lines, order_discount)


# --- UT-501 ★境界値 ------------------------------------------------
def test_ut501_端数は行番号が最大の明細に寄せる():
    got = allocated()
    assert [(l.line_no, l.allocated_discount) for l in got] == [(1, 33), (2, 33), (3, 34)]
    assert sum(l.allocated_discount for l in got) == 100      # 割引額とちょうど一致
    amount = refund.refund_amount(got, total_amount=TOTAL_AMOUNT)
    assert amount == 2900


# --- UT-502 ★境界値 ------------------------------------------------
def test_ut502_2回に分けて申請しても合計が1円もずれない():
    """★これが「注文確定時に保存する」理由（設計 6.5.2）。

    申請のたびに割り直すと、1回目の3明細ぶんと2回目の1明細ぶんで端数の行き先が変わり、
    合計が注文の割引額と合わなくなる。★誰も気づかない1円。
    """
    saved = allocated()                                       # 注文確定時に1回だけ割った値
    first = refund.refund_amount(saved[:2], total_amount=TOTAL_AMOUNT)
    second = refund.refund_amount(
        saved[2:], total_amount=TOTAL_AMOUNT, already_refunded=first
    )
    assert first + second == 2900


# --- UT-503 正常値 -------------------------------------------------
def test_ut503_明細金額の比で按分する():
    got = allocated(order_discount=600, amounts=(1000, 2000, 3000))
    assert [l.allocated_discount for l in got] == [100, 200, 300]
    assert sum(l.allocated_discount for l in got) == 600


# --- UT-504 ★異常値 ------------------------------------------------
def test_ut504_返金の累計は支払総額で頭打ちになる():
    saved = allocated()
    already = 2500
    got = refund.refund_amount(saved, total_amount=TOTAL_AMOUNT, already_refunded=already)
    assert got == 400                                         # 2,900 − 2,500
    assert already + got == TOTAL_AMOUNT
    # すでに満額返していたら0
    assert refund.refund_amount(saved, total_amount=TOTAL_AMOUNT, already_refunded=2900) == 0


# --- UT-505 異常値 -------------------------------------------------
def test_ut505_割引が0円なら按分の計算に入らない():
    got = allocated(order_discount=0)
    assert [l.allocated_discount for l in got] == [0, 0, 0]
    assert refund.refund_amount(got, total_amount=3000) == 3000


def test_割引が商品合計を超えても按分が明細金額を超えない():
    got = allocated(order_discount=99999)
    assert sum(l.allocated_discount for l in got) == 3000
    assert all(refund.line_refund(l) >= 0 for l in got)


# ============================================================
# 欠品・キャンセル（BR-17c・BR-17d・BR-21a。R-26）
# ============================================================
def test_売上確定の前は取消_後は返金():
    """★BR-17c・17d。ここを混ぜると二重に返すか、返らないか。"""
    assert refund.money_back_kind(captured=False) == refund.KIND_VOID
    assert refund.money_back_kind(captured=True) == refund.KIND_REFUND


def test_全明細が欠品したら支払総額ちょうどを返す():
    """★BR-21a の「その明細の金額」を、按分を引いた額として読む根拠。

    3明細×1,000円・割引100円・送料550円 → 支払総額 3,450円。
    全部欠品なら 3,450円ちょうど返す（払った以上でも以下でもない）。
    """
    saved = refund.allocate_discount([Line(1, 1000), Line(2, 1000), Line(3, 1000)], 100)
    got = refund.shortage_refund(saved, all_lines_short=True, shipping_fee=550,
                                 total_amount=3450)
    assert got == 3450


def test_割引前の金額で返すと払った以上になる():
    """★反対の読み方をしたときに何が起きるかを残しておく。"""
    saved = refund.allocate_discount([Line(1, 1000), Line(2, 1000), Line(3, 1000)], 100)
    wrong = sum(l.amount for l in saved) + 550        # 割引前の明細金額 ＋ 送料
    assert wrong == 3550                               # 支払総額 3,450 より 100 多い
    right = refund.shortage_refund(saved, all_lines_short=True, shipping_fee=550,
                                   total_amount=3450)
    assert right < wrong


def test_一部だけ欠品なら送料は返さない():
    """BR-21a 後半。★送料無料ラインを割り込んでも、後から請求もしない。"""
    saved = refund.allocate_discount([Line(1, 1000), Line(2, 1000), Line(3, 1000)], 100)
    got = refund.shortage_refund([saved[0]], all_lines_short=False, shipping_fee=550,
                                 total_amount=3450)
    assert got == 967          # 明細1 の 1,000 − 按分 33。送料は足さない


def test_欠品の返金も支払総額で頭打ちになる():
    saved = refund.allocate_discount([Line(1, 1000), Line(2, 1000)], 0)
    got = refund.shortage_refund(saved, all_lines_short=True, shipping_fee=550,
                                 total_amount=2550, already_refunded=2000)
    assert got == 550
