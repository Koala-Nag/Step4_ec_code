# -*- coding: utf-8 -*-
"""R-33｜販売設定（F-308・T-30）の入力と、権限（F-308・F-609）。DBを立てない。"""
from datetime import date
from decimal import Decimal

import pytest

from domain import settings as sd
from domain.authz import Perm, Role, permission

TODAY = date(2026, 9, 15)


def base(**kw):
    v = {f.name: (("0.100" if f.kind == "rate" else 550 if f.kind == "yen" else 7)) for f in sd.FIELDS}
    v.update({"effective_from": "2026-09-15", "free_shipping_line": 5000})
    v.update(kw)
    return v


def test_parse_ok_and_types():
    out, bad = sd.parse(base(tax_rate="0.080", notice_text="  メンテナンス  "), TODAY)
    assert bad is None
    assert out["tax_rate"] == Decimal("0.080") and out["shipping_fee"] == 550 and out["notice_text"] == "メンテナンス"
    assert out["effective_from"] == TODAY                      # ★今日は可


@pytest.mark.parametrize("kw, err", [
    (dict(effective_from="2026-09-14"), "effective_from:past"),   # ★過去にできない
    (dict(effective_from="9/20"), "effective_from:format"),
    (dict(tax_rate="1.001"), "tax_rate:range"),
    (dict(tax_rate="-0.1"), "tax_rate:range"),
    (dict(tax_rate="0.1234"), "tax_rate:range"),                 # DECIMAL(4,3)
    (dict(tax_rate="abc"), "tax_rate:format"),
    (dict(shipping_fee=-1), "shipping_fee:range"),
    (dict(free_shipping_line=""), "free_shipping_line:empty"),
    (dict(return_limit_days=0), "return_limit_days:range"),      # ★日数は1以上
    (dict(stagnant_days="x"), "stagnant_days:format"),
    (dict(notice_text="あ" * 201), "notice_text:too_long"),
    (dict(notice_from="2026-09-20T10:00", notice_to="2026-09-19T10:00"), "notice_to:range"),
])
def test_parse_errors(kw, err):
    assert sd.parse(base(**kw), TODAY)[1] == err


def test_zero_is_allowed_for_money():
    assert sd.parse(base(shipping_fee=0, free_shipping_line=0, tax_rate="0"), TODAY)[1] is None


def test_every_config_column_is_editable():
    """★sales_config の列を全部（R-33 の依頼）。お知らせの3列は別扱い、適用開始日は版のキー。"""
    cols = {"tax_rate", "shipping_fee", "free_shipping_line", "session_idle_min", "reset_url_valid_min",
            "auth_timeout_min", "unpaid_cancel_hour", "return_limit_days", "return_ship_back_days",
            "arrival_assume_days", "stagnant_days", "login_lock_min", "login_fail_limit", "cart_keep_days",
            "error_digest_min", "pickup_limit_days", "shortage_judge_hour", "confirm_url_valid_min"}
    assert {f.name for f in sd.FIELDS} == cols


def test_permissions_follow_2_4():
    assert [permission(r, "F-308") for r in Role] == [Perm.FULL, Perm.NONE, Perm.NONE, Perm.NONE, Perm.NONE]
    # ★F-609 は 2.4 の表のとおり（運用管理者・受注担当・サポートが参照）
    assert [permission(r, "F-609") for r in Role] == [Perm.READ, Perm.READ, Perm.NONE, Perm.NONE, Perm.READ]
