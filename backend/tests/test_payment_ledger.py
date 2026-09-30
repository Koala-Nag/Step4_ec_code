# -*- coding: utf-8 -*-
"""ダミーの決済代行が断る条件（設計 7.2.3。R-27）。★DBもHTTPも立てない。"""
from __future__ import annotations

from domain import payment_ledger as pl
from domain.payment_ledger import Authorization


def test_与信の残りを超える取消は断る():
    """★R-26 の不具合1（割引前の売上確定）を、ダミーが落とす形。

    与信 6,999。先の出荷を割引前の 4,999 で確定 → 残り 2,000。
    欠品の取消 2,332 は残りを超える → 断る。
    """
    a = pl.apply(pl.CAPTURE, Authorization(6999), 4999, "shipment:1")
    assert a.remaining == 2000
    assert pl.refuse_reason(pl.VOID, a, 2332) == pl.EXCEEDS_REMAINING
    # 正しい額（按分後 4,667）なら残り 2,332 でちょうど通る
    ok = pl.apply(pl.CAPTURE, Authorization(6999), 4667, "shipment:1")
    assert pl.refuse_reason(pl.VOID, ok, 2332) is None


def test_確定したぶんは取消では戻せない():
    """★R-26 の不具合2（欠品の代金を別の出荷が取った）を、ダミーが落とす形。"""
    a = pl.apply(pl.CAPTURE, Authorization(6999), 6999, "shipment:1")
    assert pl.refuse_reason(pl.VOID, a, 2332) == pl.EXCEEDS_REMAINING
    assert pl.refuse_reason(pl.REFUND, a, 2332) is None          # 戻すなら返金


def test_分割出荷の2回の売上確定は通る_同じ出荷の2回目は断る():
    a = pl.apply(pl.CAPTURE, Authorization(5530), 2540, "shipment:1")
    assert pl.refuse_reason(pl.CAPTURE, a, 2990, "shipment:2") is None
    assert pl.refuse_reason(pl.CAPTURE, a, 100, "shipment:1") == pl.DUPLICATE_CAPTURE


def test_与信を超える売上確定は断る():
    a = pl.apply(pl.CAPTURE, Authorization(5530), 3540, "shipment:1")
    assert pl.refuse_reason(pl.CAPTURE, a, 2540, "shipment:2") == pl.EXCEEDS_REMAINING


def test_返金は確定した額まで():
    a = pl.apply(pl.CAPTURE, Authorization(3000), 1000, "shipment:1")
    assert pl.refuse_reason(pl.REFUND, a, 1001) == pl.EXCEEDS_CAPTURED
    assert pl.refuse_reason(pl.REFUND, a, 1000) is None


def test_知らない取引は断る():
    assert pl.refuse_reason(pl.VOID, None, 100) == pl.UNKNOWN_TRANSACTION


def test_記憶の形を行き来できる():
    a = pl.apply(pl.CAPTURE, Authorization(5000), 1000, "shipment:9")
    assert pl.from_dict(pl.to_dict(a)) == a
