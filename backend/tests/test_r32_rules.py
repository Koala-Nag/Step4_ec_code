# -*- coding: utf-8 -*-
"""R-32｜クーポンの対象（BR-12）と入力、拠点の入力（F-809）、権限（F-1001）。DBを立てない。"""
from datetime import datetime

import pytest

from domain import catalog as cg
from domain import coupon as cd
from domain.authz import Perm, Role, permission

LINES = [
    cd.TargetLine(2500, "P0051", "TSHIRT", "TOPS"),
    cd.TargetLine(3000, "P0060", "PANTS", "BOTTOMS"),
    cd.TargetLine(1000, "P0070", "SHIRT", "TOPS"),
]


@pytest.mark.parametrize("targets, expect", [
    ([], 6500),                                        # 行が無い＝全商品（既存のクーポン）
    ([(cd.TARGET_ALL, None)], 6500),
    ([(cd.TARGET_CATEGORY, "TSHIRT")], 2500),          # 子カテゴリ
    ([(cd.TARGET_CATEGORY, "TOPS")], 3500),            # ★親カテゴリなら子も入る
    ([(cd.TARGET_PRODUCT, "P0060")], 3000),
    ([(cd.TARGET_PRODUCT, "P0060"), (cd.TARGET_PRODUCT, "P0070")], 4000),
    ([(cd.TARGET_CATEGORY, "OUTER")], 0),              # 対象が無い
])
def test_eligible_total_br12(targets, expect):
    assert cd.eligible_total(targets, LINES) == expect


def test_discount_is_capped_by_eligible_total():
    c = cd.Coupon("X", cd.TYPE_AMOUNT, 3000, datetime(2026, 1, 1), datetime(2027, 1, 1), 0, None, 0, None)
    assert cd.discount_for(c, cd.eligible_total([(cd.TARGET_PRODUCT, "P0070")], LINES)) == 1000
    r = cd.Coupon("R", cd.TYPE_RATE, 10, datetime(2026, 1, 1), datetime(2027, 1, 1), 0, None, 0, None)
    assert cd.discount_for(r, cd.eligible_total([(cd.TARGET_CATEGORY, "TOPS")], LINES)) == 350


@pytest.mark.parametrize("kw, err", [
    (dict(name="春の10%", discount_type=cd.TYPE_RATE, discount_value=10), None),
    (dict(name=" "), "name:empty"),
    (dict(name="あ" * 51), "name:too_long"),
    (dict(discount_type=9), "discount_type:choice"),
    (dict(discount_type=cd.TYPE_RATE, discount_value=101), "discount_value:range"),
    (dict(discount_type=cd.TYPE_RATE, discount_value=0), "discount_value:range"),
    (dict(discount_type=cd.TYPE_AMOUNT, discount_value=5000), None),
    (dict(start_at=datetime(2026, 9, 2), end_at=datetime(2026, 9, 1)), "end_at:range"),
    (dict(min_amount=-1), "min_amount:range"),
    (dict(total_limit=0), "total_limit:range"),
    (dict(total_limit=3, used_count=5), "total_limit:below_used"),
    (dict(per_member_limit=0), "per_member_limit:range"),
])
def test_coupon_input(kw, err):
    assert cd.coupon_input_error(**kw) == err


def test_coupon_code_format():
    assert cd.COUPON_CODE_RE.match("SPRING10")
    assert not cd.COUPON_CODE_RE.match("spring10")          # ★半角英数大文字（6.3）
    assert not cd.COUPON_CODE_RE.match("A" * 21)


@pytest.mark.parametrize("kw, err", [
    (dict(name="川崎店", zip_="2100001", tel="0442000011", weekdays=[1, 2, 3, 4, 5], cutoff_time="14:00"), None),
    (dict(name=""), "name:empty"),
    (dict(zip_="210-0001"), "zip:format"),
    (dict(tel="044"), "tel:format"),
    (dict(weekdays=[]), "business_days:empty"),
    (dict(weekdays=[7]), "business_days:choice"),
    (dict(cutoff_time="24:00"), "cutoff_time:format"),
    (dict(pref_code="99", prefs={"13", "14"}), "pref_code:choice"),
])
def test_location_input(kw, err):
    assert cg.location_input_error(**kw) == err


def test_location_helpers():
    assert cg.digits_only("044-200-0011") == "0442000011"
    assert cg.business_days_mask([0, 6]) == 0b1000001     # 日=bit0・土=bit6（DDL と同じ）
    assert cg.business_days_mask(list(range(7))) == 127


def test_f1001_admin_only():
    assert [permission(r, "F-1001") for r in Role] == [Perm.FULL, Perm.NONE, Perm.NONE, Perm.NONE, Perm.NONE]
