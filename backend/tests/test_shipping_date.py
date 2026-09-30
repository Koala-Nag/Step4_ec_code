# -*- coding: utf-8 -*-
"""UT-400番台｜発送予定日（単体テスト仕様書 4章）。

★「いまの日時」を引数で渡す。中で date.today() を呼ぶと、
  日付が変わった瞬間に落ちる試験ができあがって、誰も直せなくなる。
"""
from __future__ import annotations

from datetime import date, datetime, time

from domain import shipping_date as sd
from domain.shipping_date import LocationCalendar

ALL_DAYS = frozenset(range(7))
# 2026-09-14 は月曜。以降 火=15 水=16 木=17 金=18 土=19 日=20
MON = date(2026, 9, 14)


def cal(*, weekdays=ALL_DAYS, cutoff=time(15, 0), holidays=frozenset()):
    return LocationCalendar(business_weekdays=weekdays, cutoff=cutoff, holidays=holidays)


# --- UT-401 ★境界値 ------------------------------------------------
def test_ut401_締め時刻ちょうどは当日発送():
    got = sd.planned_ship_date(datetime(2026, 9, 14, 15, 0, 0), cal())
    assert got == MON


# --- UT-402 ★境界値 ------------------------------------------------
def test_ut402_締め時刻を1秒過ぎたら翌営業日():
    """★間違えると、1日ずれた予定日を客に伝える。画面は正しく見える。"""
    got = sd.planned_ship_date(datetime(2026, 9, 14, 15, 0, 1), cal())
    assert got == date(2026, 9, 15)


# --- UT-403 正常値 -------------------------------------------------
def test_ut403_締め時刻は拠点ごとに見る():
    """15:00 固定にしない。12:00 の拠点では 14:00 は翌営業日。"""
    noon = cal(cutoff=time(12, 0))
    assert sd.planned_ship_date(datetime(2026, 9, 14, 11, 59), noon) == MON
    assert sd.planned_ship_date(datetime(2026, 9, 14, 14, 0), noon) == date(2026, 9, 15)


# --- UT-404 ★境界値 ------------------------------------------------
def test_ut404_翌日が休業日なら次に営業する日():
    c = cal(holidays=frozenset({date(2026, 9, 15)}))
    got = sd.planned_ship_date(datetime(2026, 9, 14, 16, 0), c)
    assert got == date(2026, 9, 16)


# --- UT-405 ★境界値 ------------------------------------------------
def test_ut405_休業日が2日続いたら2日飛ばす():
    c = cal(holidays=frozenset({date(2026, 9, 15), date(2026, 9, 16)}))
    got = sd.planned_ship_date(datetime(2026, 9, 14, 16, 0), c)
    assert got == date(2026, 9, 17)


# --- UT-406 正常値 -------------------------------------------------
def test_ut406_日曜休業の拠点に土曜16時():
    """2026-09-19 は土曜。締めを過ぎているので翌日＝日曜だが、日曜は営業しない → 月曜。"""
    no_sunday = cal(weekdays=frozenset({1, 2, 3, 4, 5, 6}))   # 0=日 を外す
    got = sd.planned_ship_date(datetime(2026, 9, 19, 16, 0), no_sunday)
    assert got == date(2026, 9, 21)


# --- UT-407 異常値 -------------------------------------------------
def test_ut407_営業する曜日が1つも無ければ判定できないと返す():
    """★例外にせず、無限に探さない。設定が間違っているのであって、注文の異常ではない。"""
    got = sd.planned_ship_date(datetime(2026, 9, 14, 10, 0), cal(weekdays=frozenset()))
    assert got is None


def test_DDLのビット列をそのまま開ける():
    """location.business_days（日=bit0 〜 土=bit6）。127 は全曜日営業。"""
    assert sd.LocationCalendar.from_bitmask(127, time(15, 0)).business_weekdays == ALL_DAYS
    # 126 = 日曜(bit0)だけ落とす
    assert sd.LocationCalendar.from_bitmask(126, time(15, 0)).business_weekdays == frozenset(
        {1, 2, 3, 4, 5, 6}
    )
