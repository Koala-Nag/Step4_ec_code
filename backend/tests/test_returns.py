# -*- coding: utf-8 -*-
"""返品（domain/returns.py）。BR-18・5.3「返品の状態」・6.5.2。DBを立てない。"""
from datetime import date, datetime

import pytest

from domain import returns as rd


# ---------------- BR-18 期限（6.5.1）----------------
@pytest.mark.parametrize("now, ok", [
    (datetime(2026, 9, 17, 23, 59, 59), True),
    (datetime(2026, 9, 18, 0, 0, 0), True),      # ★ちょうどは可
    (datetime(2026, 9, 18, 0, 0, 1), False),     # ★1秒でも過ぎたら不可
])
def test_deadline_boundary(now, ok):
    # 出荷日 9/1 なら 9/18 00:00:00 まで可（BR-18 の例）
    assert rd.within_deadline(datetime(2026, 9, 1, 10, 30), now) is ok


def test_deadline_counts_from_midnight_of_ship_date():
    # ★出荷が 23:59 でも、起算はその日の 00:00
    assert rd.deadline(datetime(2026, 9, 1, 23, 59)) == datetime(2026, 9, 18)
    assert rd.deadline(date(2026, 9, 1), 10) == datetime(2026, 9, 11)


@pytest.mark.parametrize("days_ago, ok", [(16, True), (17, False), (18, False)])
def test_deadline_16_17_18_days(days_ago, ok):
    # 要件 7.x の境界（出荷から16日／17日／18日）。昼の12時に申請したとき
    from datetime import timedelta
    now = datetime(2026, 9, 20, 12, 0)
    assert rd.within_deadline(now - timedelta(days=days_ago), now) is ok


# ---------------- 状態の遷移（5.3）----------------
def test_transitions_in_order():
    s = rd.APPLIED
    for action in ("approve", "receive", "inspect", "refund"):
        s = rd.transition(action, s)
    assert s == rd.REFUNDED
    assert rd.transition("reject", rd.APPLIED) == rd.REJECTED


@pytest.mark.parametrize("action, current", [
    ("receive", rd.APPLIED),       # ★飛び越し（承認前に受領）
    ("inspect", rd.AWAITING),      # ★飛び越し（受領前に検品）
    ("refund", rd.RECEIVED),       # ★飛び越し（検品前に返金）
    ("approve", rd.REJECTED),      # 却下したものを承認
    ("reject", rd.AWAITING),       # 承認したあとで却下
    ("refund", rd.REFUNDED),       # 2回目の返金
    ("approve", rd.AWAITING),      # 2回目の承認
])
def test_undefined_transition_is_err_1205(action, current):
    with pytest.raises(ValueError, match="ERR-1205"):
        rd.transition(action, current)


# ---------------- 理由（6.3）----------------
def test_reason_rules():
    assert rd.reason_error("size", None) is None
    assert rd.reason_error("other", "  ") == ("ERR-1001", "reason_text")   # ★その他は自由記述が必須
    assert rd.reason_error("other", "袖が長い") is None
    assert rd.reason_error("nope", None) == ("ERR-1004", "reason_code")
    assert rd.reason_error("size", "あ" * 201) == ("ERR-1003", "reason_text")


# ---------------- 申請の判定 ----------------
NOW = datetime(2026, 9, 10, 12, 0)
LINES = {
    1: rd.ShippedLine(1, 2, 0, datetime(2026, 9, 1)),
    2: rd.ShippedLine(2, 1, 1, datetime(2026, 9, 1)),       # もう申請済み
    3: rd.ShippedLine(3, 0, 0, None),                        # まだ届いていない
    4: rd.ShippedLine(4, 1, 0, datetime(2026, 8, 1)),        # 期限切れ
}


@pytest.mark.parametrize("asked, err", [
    ({1: 2}, None),
    ({1: 3}, "ERR-1003"),          # 届いた数を超える
    ({2: 1}, "ERR-1003"),          # 申請済みのぶんは申請できない
    ({3: 1}, "ERR-1205"),          # 届いていない
    ({4: 1}, "ERR-1204"),          # 期限切れ
    ({1: 1, 4: 1}, "ERR-1204"),    # ★1明細でも期限切れなら申請ごと受けない
    ({9: 1}, "ERR-1004"),          # 無い明細
    ({1: 0}, "ERR-1003"),
    ({}, "ERR-1001"),
])
def test_check_application(asked, err):
    assert rd.check_application(LINES, asked, NOW) == err


# ---------------- 返金額（6.5.2）----------------
def test_refund_whole_line_equals_amount_minus_allocated():
    assert rd.refund_for_qty(unit_price=1000, line_qty=1, allocated_discount=34,
                             before_qty=0, qty=1) == 966


def test_refund_split_by_qty_sums_to_design_value():
    """★1明細を数で分けて返しても、合計は「明細金額 − 按分額」に一致する（割り直しの端数が溜まらない）。"""
    kw = dict(unit_price=1000, line_qty=3, allocated_discount=100)
    parts = [rd.refund_for_qty(**kw, before_qty=0, qty=1),
             rd.refund_for_qty(**kw, before_qty=1, qty=1),
             rd.refund_for_qty(**kw, before_qty=2, qty=1)]
    assert sum(parts) == 3000 - 100
    assert rd.refund_for_qty(**kw, before_qty=0, qty=3) == 2900


def test_design_example_three_applications():
    """設計 6.5.2 の例。3明細・各1000円・割引100円 → 按分 33/33/34（端数は行番号最大へ）。
    1回目に明細1・2、2回目に明細3を返しても合計 2900。"""
    from domain.refund import Line, allocate_discount
    al = {a.line_no: a.allocated_discount for a in allocate_discount([Line(1, 1000), Line(2, 1000), Line(3, 1000)], 100)}
    first = sum(rd.refund_for_qty(unit_price=1000, line_qty=1, allocated_discount=al[n], before_qty=0, qty=1)
                for n in (1, 2))
    second = rd.refund_for_qty(unit_price=1000, line_qty=1, allocated_discount=al[3], before_qty=0, qty=1)
    assert (first, second) == (1934, 966)
    assert first + second == 2900


def test_all_lines_returned():
    assert rd.all_lines_returned({1: 2, 2: 1}, {1: 2, 2: 1}) is True
    assert rd.all_lines_returned({1: 2}, {1: 2, 2: 1}) is False      # 1明細残っている
    assert rd.all_lines_returned({1: 1, 2: 1}, {1: 2, 2: 1}) is False  # 数が足りない
    assert rd.all_lines_returned({}, {}) is False
