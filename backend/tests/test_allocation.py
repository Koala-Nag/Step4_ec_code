# -*- coding: utf-8 -*-
"""UT-200番台｜引当の計画（単体テスト仕様書 2章）。

★手順2〜5 だけ。手順1（在庫を読む）と手順6（条件付きUPDATE）は結合テスト（0.3）。
  読んだ在庫の一覧を引数で渡す。
"""
from __future__ import annotations

import pytest

from domain import allocation
from domain.allocation import AllocationFailed, Candidate, OrderLine

WAREHOUSE, STORE = 1, 2


def cand(loc, step, qty, *, sku="S1", kind=STORE, reserved=0):
    return Candidate(sku_code=sku, location_code=loc, kind=kind, step=step,
                     qty=qty, reserved_qty=reserved)


# --- UT-201 ★正常値 ------------------------------------------------
def test_ut201_BR05の3キーで並ぶ():
    """届け先が東京(13)のとき T003 → T004 → W001 → T001（R-01 の検証4と同じ期待値）。

    ★在庫が最多で倉庫の W001 が、在庫3の T003 より後ろに来る。
      並び順を決めるのは「近さ → 拠点区分 → 拠点コード」であって、在庫数ではない。
    """
    given = [
        cand("T001", 4, 99, kind=STORE),               # それ以外
        cand("W001", 3, 99, kind=WAREHOUSE),           # 同一ブロック・倉庫
        cand("T004", 2, 99, kind=STORE),               # 同一都道府県
        cand("T003", 2, 3, kind=STORE),                # 同一都道府県・在庫3
    ]
    got = [c.location_code for c in allocation.sort_candidates(given)]
    assert got == ["T003", "T004", "W001", "T001"]


# --- UT-202 正常値 -------------------------------------------------
def test_ut202_受取店は段1なので先頭に来る():
    """★「配送の注文では段1が空になる」のは、候補を読むSQL側の話（手順1）。

    ここで確かめられるのは「段1があれば必ず先頭に来る」まで。残りは結合（IT-401）。
    """
    given = [
        cand("W001", 3, 10, kind=WAREHOUSE),
        cand("T009", 1, 1, kind=STORE),                # 受取店
        cand("T002", 2, 10, kind=STORE),
    ]
    got = [c.location_code for c in allocation.sort_candidates(given)]
    assert got[0] == "T009"
    # 配送の注文＝段1の候補が渡ってこない
    without_pickup = [c for c in given if c.step != 1]
    assert allocation.sort_candidates(without_pickup)[0].location_code == "T002"


# --- UT-203 ★正常値 ------------------------------------------------
def test_ut203_同一SKUの明細2本が同じ在庫を食い合わない():
    """手順3で、割り付けるたびに手元の残数を減らしているか。

    ★減らさないと、在庫3点の拠点に「2点」と「2点」を両方割り当てて、出荷できない。
    """
    lines = [OrderLine(1, "S1", 2), OrderLine(2, "S1", 2)]
    candidates = [cand("T003", 2, 3), cand("W001", 3, 10, kind=WAREHOUSE)]
    got = allocation.allocate(lines, candidates)
    assert got[0].location_code == "T003"
    assert got[1].location_code == "W001", "T003 の在庫3点に2点＋2点を割り当ててしまっている"


# --- UT-204 ★異常値 ------------------------------------------------
def test_ut204_1明細を複数拠点に分割しない():
    """同一SKUが3店舗に1点ずつ。3点ほしい明細1本 → 引当失敗（BR-06）。

    ★合計3点あるので「在庫はある」。分割を許すと引当できたように見えて、出荷できない。
    """
    lines = [OrderLine(1, "S1", 3)]
    candidates = [cand("T001", 2, 1), cand("T002", 2, 1), cand("T003", 2, 1)]
    with pytest.raises(AllocationFailed) as e:
        allocation.allocate(lines, candidates)
    assert "BR-06" in e.value.reason


# --- UT-205 ★境界値 ------------------------------------------------
def test_ut205_2拠点で収まればそのまま成立する():
    lines = [OrderLine(1, "A", 1), OrderLine(2, "B", 1)]
    candidates = [cand("T001", 2, 5, sku="A"), cand("T002", 2, 5, sku="B")]
    got = allocation.allocate(lines, candidates)
    assert {a.location_code for a in got} == {"T001", "T002"}


# --- UT-206 ★境界値 ------------------------------------------------
def test_ut206_3拠点になったら倉庫だけで組み直す():
    lines = [OrderLine(1, "A", 1), OrderLine(2, "B", 1), OrderLine(3, "C", 1)]
    candidates = [
        cand("T001", 2, 5, sku="A"), cand("T002", 2, 5, sku="B"), cand("T003", 2, 5, sku="C"),
        cand("W001", 3, 5, sku="A", kind=WAREHOUSE),
        cand("W001", 3, 5, sku="B", kind=WAREHOUSE),
        cand("W001", 3, 5, sku="C", kind=WAREHOUSE),
    ]
    got = allocation.allocate(lines, candidates)
    assert {a.location_code for a in got} == {"W001"}


# --- UT-207 異常値 -------------------------------------------------
def test_ut207_3拠点になり倉庫にも足りなければ引当失敗():
    lines = [OrderLine(1, "A", 1), OrderLine(2, "B", 1), OrderLine(3, "C", 1)]
    candidates = [
        cand("T001", 2, 5, sku="A"), cand("T002", 2, 5, sku="B"), cand("T003", 2, 5, sku="C"),
        cand("W001", 3, 5, sku="A", kind=WAREHOUSE),
        cand("W001", 3, 5, sku="B", kind=WAREHOUSE),
        # C が倉庫に無い
    ]
    with pytest.raises(AllocationFailed) as e:
        allocation.allocate(lines, candidates)
    assert "BR-07" in e.value.reason


# --- UT-208 異常値 -------------------------------------------------
def test_ut208_候補が0件なら引当失敗():
    """★予期しない例外（IndexError など）で落ちない。業務上の結果として返す。

    ★仕様書は「例外にしない」と書いているが、実装は AllocationFailed を投げている。
      呼び出し側は ERR-1207 に変換していて、500 にはならない（api/orders.py）。
      名前だけの食い違いなので、報告に書いて設計側の判断を仰ぐ。
    """
    with pytest.raises(AllocationFailed):
        allocation.allocate([OrderLine(1, "S1", 1)], [])


# --- UT-209 境界値 -------------------------------------------------
def test_ut209_販売可能数がちょうど必要数なら成立する():
    got = allocation.allocate([OrderLine(1, "S1", 3)], [cand("T001", 2, 5, reserved=2)])
    assert got[0].qty == 3


# --- UT-210 ★異常値 ------------------------------------------------
def test_ut210_引当済数が在庫数を超えても負の数を出さない():
    """通常運用で起きる（欠品報告のあとなど）。

    ★SQL側で INT UNSIGNED 同士を引くと ERROR 1690 で落ちる（R-01 で実機確認）。
      だから引き算はここでやる。ここで負を許すと、その負の数が SQL に戻っていく。
    """
    c = cand("T001", 2, 3, reserved=8)
    assert c.saleable == 0
    with pytest.raises(AllocationFailed):
        allocation.allocate([OrderLine(1, "S1", 1)], [c])


def test_手順6の指示は拠点とSKUの昇順にまとまる():
    """★「選ぶ順序（BR-05）」と「書く順序（9.4 デッドロック回避）」は別物。"""
    assigns = [
        allocation.Assignment(1, "B", "T002", 1),
        allocation.Assignment(2, "A", "T001", 2),
        allocation.Assignment(3, "A", "T001", 3),
    ]
    got = allocation.build_updates(assigns)
    assert [(u.location_code, u.sku_code, u.add_qty) for u in got] == [
        ("T001", "A", 5),   # 同じ 拠点×SKU は1本にまとまる
        ("T002", "B", 1),
    ]
