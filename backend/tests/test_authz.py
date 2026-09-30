# -*- coding: utf-8 -*-
"""権限の判定（要件定義書 2.4・N-28a）。★DBを立てない。

★権限は「表」なので、全通り確かめられる。
  役割5 × 機能8 = 40 通りを目で追うより、試験で回すほうが速くて確実。
"""
from __future__ import annotations

import pytest

from domain import authz
from domain.authz import Perm, Role


def test_2_4_の表と一致する_在庫の修正():
    """F-802 在庫の修正｜運用管理者=可 受注=— 倉庫=自拠点 店舗=自拠点 サポート=—"""
    assert authz.permission(Role.ADMIN, "F-802") == Perm.FULL
    assert authz.permission(Role.ORDER, "F-802") == Perm.NONE
    assert authz.permission(Role.WAREHOUSE, "F-802") == Perm.OWN_SITE
    assert authz.permission(Role.STORE, "F-802") == Perm.OWN_SITE
    assert authz.permission(Role.SUPPORT, "F-802") == Perm.NONE


def test_参照は書けない():
    """★ここを緩めると SEC-703 が通る。"""
    assert authz.can_read(Role.ORDER, "F-701") is True       # 商品は「参照」
    assert authz.can_write(Role.ORDER, "F-701") is False
    assert authz.can_read(Role.ADMIN, "F-701") is True
    assert authz.can_write(Role.ADMIN, "F-701") is True


def test_表に無い機能は既定で不許可():
    """★知らない機能を「通す」にしない。新しいAPIを足したとき、

    2.4 に書き忘れていたら 403 になる。黙って通るより、落ちたほうがよい。
    """
    assert authz.permission(Role.ADMIN, "F-999") == Perm.NONE
    assert authz.can_read(Role.ADMIN, "F-999") is False
    assert authz.can_write(Role.ADMIN, "F-999") is False


@pytest.mark.parametrize("role,expected", [
    (Role.WAREHOUSE, True), (Role.STORE, True),
    (Role.ADMIN, False), (Role.ORDER, False), (Role.SUPPORT, False),
])
def test_自拠点のみの役割はどれか(role, expected):
    assert authz.is_site_scoped(role, "F-801") is expected


# --- N-28a ---------------------------------------------------
def test_自拠点のみの役割は指定が無くても自拠点に絞られる():
    got = authz.effective_location(Role.STORE, "F-801", "T003", None)
    assert got == "T003"


def test_自拠点のみの役割が他拠点を指定したら弾く():
    """★SEC-701。URLを直接指定しても表示しない。"""
    with pytest.raises(ValueError) as e:
        authz.effective_location(Role.STORE, "F-801", "T003", "T004")
    assert "ERR-1106" in str(e.value)


def test_自拠点を指定したぶんには通る():
    assert authz.effective_location(Role.STORE, "F-801", "T003", "T003") == "T003"


def test_絞らない役割は指定に従う():
    assert authz.effective_location(Role.ADMIN, "F-801", None, "T004") == "T004"
    assert authz.effective_location(Role.ADMIN, "F-801", None, None) is None


def test_倉庫と店舗はお互いの拠点を見られない():
    with pytest.raises(ValueError):
        authz.effective_location(Role.WAREHOUSE, "F-801", "W001", "T003")
    with pytest.raises(ValueError):
        authz.effective_location(Role.STORE, "F-801", "T003", "W001")


@pytest.mark.parametrize("feature", ["F-904", "F-911", "F-912"])
def test_2_4_の表と一致する_キャンセル_部分キャンセル_再引当(feature):
    """F-904・F-911・F-912｜運用管理者=可 受注=可 倉庫=— 店舗=— サポート=—（R-26）

    ★お金が動く操作なので、倉庫・店舗・サポートには書かせない。
      欠品の報告（F-805）は倉庫・店舗が書き、判断（再引当か取り消しか）は受注担当が持つ（6.4 手順5）。
    """
    assert authz.can_write(Role.ADMIN, feature) is True
    assert authz.can_write(Role.ORDER, feature) is True
    for role in (Role.WAREHOUSE, Role.STORE, Role.SUPPORT):
        assert authz.permission(role, feature) == Perm.NONE


def test_2_4_の表と一致する_対応メモ():
    """F-908｜運用管理者=可 受注=可 倉庫=— 店舗=— サポート=可（R-29）

    ★R-29 まで対応メモは F-901（注文一覧。運用管理者とサポートは「参照」）で判定していたので、
      2.4 で「可」の運用管理者とサポートが書けなかった。機能ごとに行を持つ。
    """
    for role in (Role.ADMIN, Role.ORDER, Role.SUPPORT):
        assert authz.can_write(role, "F-908") is True
    for role in (Role.WAREHOUSE, Role.STORE):
        assert authz.permission(role, "F-908") == Perm.NONE


def test_2_4_の表と一致する_EC販売可否と滞留在庫():
    """F-806｜運用管理者だけ可。F-807｜運用管理者は可・受注担当は参照（R-30）"""
    assert authz.can_write(Role.ADMIN, "F-806") is True
    for role in (Role.ORDER, Role.WAREHOUSE, Role.STORE, Role.SUPPORT):
        assert authz.permission(role, "F-806") == Perm.NONE
    assert authz.can_write(Role.ADMIN, "F-807") is True
    assert authz.can_read(Role.ORDER, "F-807") is True and authz.can_write(Role.ORDER, "F-807") is False
    for role in (Role.WAREHOUSE, Role.STORE, Role.SUPPORT):
        assert authz.permission(role, "F-807") == Perm.NONE


def test_returns_rows_follow_2_4():
    """R-31。返品は 2.4 の行そのまま（F-507・F-503a〜e・F-504）。★近い機能の行で代用しない（10.2.11c）"""
    from domain.authz import Perm, Role, permission

    A, O, W, S, U = Role.ADMIN, Role.ORDER, Role.WAREHOUSE, Role.STORE, Role.SUPPORT
    expect = {
        "F-507": (Perm.READ, Perm.READ, Perm.OWN_SITE, Perm.NONE, Perm.FULL),
        "F-503a": (Perm.FULL, Perm.NONE, Perm.NONE, Perm.NONE, Perm.FULL),
        "F-503b": (Perm.READ, Perm.NONE, Perm.OWN_SITE, Perm.NONE, Perm.READ),
        "F-503c": (Perm.READ, Perm.NONE, Perm.OWN_SITE, Perm.NONE, Perm.READ),
        "F-503d": (Perm.FULL, Perm.NONE, Perm.NONE, Perm.NONE, Perm.FULL),
        "F-503e": (Perm.FULL, Perm.NONE, Perm.READ, Perm.NONE, Perm.FULL),
        "F-504": (Perm.READ, Perm.NONE, Perm.OWN_SITE, Perm.NONE, Perm.NONE),
    }
    for f, perms in expect.items():
        assert tuple(permission(r, f) for r in (A, O, W, S, U)) == perms, f
