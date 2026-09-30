# -*- coding: utf-8 -*-
"""UT-300番台｜在庫の見せ方（単体テスト仕様書 3章）。"""
from __future__ import annotations

import pytest

from domain import stock
from domain.stock import StockLabel


# --- UT-301〜304 ★境界値 -------------------------------------------
@pytest.mark.parametrize("saleable,expected", [
    (0, StockLabel.OUT),      # UT-301 品切れ
    (1, StockLabel.LOW),      # UT-302 残りわずか
    (3, StockLabel.LOW),      # UT-303 残りわずか（境目の内側）
    (4, StockLabel.IN_STOCK), # UT-304 在庫あり（境目の外側）
])
def test_ut301_304_BR25の3値の境界(saleable, expected):
    assert stock.label_from_qty(saleable) == expected


# --- UT-305 正常値 -------------------------------------------------
def test_ut305_一覧は2値にしか落とさない():
    """★一覧に「残りわずか」を出さない（9.2.1b・F-104）。

    3値にすると販売可能数の合計が要る。同時20人で 16.4 秒かかることを実測した（R-08）。
    """
    labels = {stock.list_label(q) for q in (0, 1, 3, 4, 999)}
    assert labels == {StockLabel.OUT, StockLabel.IN_STOCK}
    assert StockLabel.LOW not in labels
    # 詳細のほうは3値のまま（両方が同じ関数にならないこと）
    assert stock.label_from_qty(1) == StockLabel.LOW


# --- UT-306 異常値 -------------------------------------------------
def test_ut306_負の数は0として扱う():
    assert stock.label_from_qty(-5) == StockLabel.OUT
    assert stock.list_label(-5) == StockLabel.OUT
    assert stock.is_selectable(-5) is False
    assert stock.saleable(3, 8) == 0     # 引き算の結果を負にしない（3.2.2 ①）


# --- 新着バッジ（画面の型 1.3 ⑥・R-28）-------------------------------
def test_新着は登録から14日以内():
    from datetime import datetime, timedelta

    from domain.stock import NEW_DAYS, is_new

    now = datetime(2026, 9, 13, 12, 0, 0)
    assert is_new(now - timedelta(days=NEW_DAYS - 1, hours=23), now) is True
    assert is_new(now - timedelta(days=NEW_DAYS), now) is False      # ★ちょうど14日で外れる
    assert is_new(None, now) is False


# --- 滞留在庫（F-807・要件 6.4「58日／60日／62日 × 在庫2点／3点」。R-30）----------
import pytest as _pytest


@_pytest.mark.parametrize("days,qty,expected", [
    (62, 3, True),
    (60, 3, True),      # ★60日ちょうど・3点ちょうどは含む
    (58, 3, False),
    (62, 2, False),
    (60, 2, False),
])
def test_滞留は最終販売日から60日以上かつ在庫3点以上(days, qty, expected):
    from datetime import date, timedelta

    from domain.stock import is_stagnant

    today = date(2026, 9, 13)
    assert is_stagnant(today - timedelta(days=days), qty, today) is expected


def test_一度も売れていない行は滞留と判定しない():
    from datetime import date

    from domain.stock import is_stagnant

    assert is_stagnant(None, 99, date(2026, 9, 13)) is False
