# -*- coding: utf-8 -*-
"""商品マスタ・払い出し・運営者の決まりごと（R-27）。★DBを立てない。"""
from __future__ import annotations

import pytest

from domain import catalog as cg


def test_F702_色3サイズ4で12件():
    made, skipped = cg.plan_skus("P0100", ["BK", "WH", "NV"], ["S", "M", "L", "XL"], set())
    assert len(made) == 12 and skipped == []
    assert made[0].sku_code == "P0100-BK-S"


def test_F702_すでにある組み合わせは作らない():
    """★重ねると 6.2.4 の前提（1注文に同じSKUの明細が2行並ばない）が崩れる。"""
    made, skipped = cg.plan_skus("P0100", ["BK", "WH"], ["S", "M"], {("BK", "S")})
    assert [m.sku_code for m in made] == ["P0100-BK-M", "P0100-WH-S", "P0100-WH-M"]
    assert skipped == [("BK", "S")]


def test_F702_同じ指定を2回しても1件():
    made, _ = cg.plan_skus("P0100", ["BK", "BK"], ["S", "S"], set())
    assert len(made) == 1


def test_F702_SKUコードが20桁を超えるなら作らない():
    made, skipped = cg.plan_skus("P0100-LONGCODE", ["BLACK"], ["XXXL"], set())
    assert made == [] and skipped == [("BLACK", "XXXL")]


def test_N36_中身で判定する_拡張子は見ない():
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 10
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 10
    assert cg.image_kind(jpg) == "jpg" and cg.image_kind(png) == "png"
    assert cg.image_kind(b"GIF89a....") is None
    assert cg.image_kind(b"<svg onload=alert(1)>") is None      # ★名前が .jpg でも中身で落とす


@pytest.mark.parametrize("size,count,expected", [
    (cg.IMAGE_MAX_BYTES, 0, None),
    (cg.IMAGE_MAX_BYTES + 1, 0, "too_large"),
    (10, cg.IMAGES_PER_PRODUCT - 1, None),
    (10, cg.IMAGES_PER_PRODUCT, "too_many"),
])
def test_N36_5MBと50枚の境界(size, count, expected):
    data = b"\xff\xd8\xff" + b"0" * (size - 3)
    assert cg.image_error(data, count) == expected


@pytest.mark.parametrize("qty,backyard,reserved,expected", [
    (2, 5, 3, None),                   # 販売可能数 2 ちょうど
    (3, 5, 3, "qty:over_saleable"),    # ★引当済は払い出せない
    (1, 3, 5, "qty:over_saleable"),    # 引当済数 > 在庫数（BR-04a のあと）でも負にしない
    (0, 5, 0, "qty:range"),
])
def test_F808_払い出しの上限は販売可能数(qty, backyard, reserved, expected):
    assert cg.floor_move_error(qty=qty, backyard_qty=backyard, reserved_qty=reserved) == expected


@pytest.mark.parametrize("role,loc,kind,expected", [
    (4, "T003", 2, None),                           # 店舗スタッフ × 店舗
    (4, None, None, "location_code:required"),
    (4, "W001", 1, "location_code:kind_mismatch"),  # 店舗の役割に倉庫を付けない
    (3, "W001", 1, None),
    (2, None, None, None),                          # 受注担当は拠点を持たない
    (2, "T003", 2, "location_code:not_allowed"),
    (9, None, None, "role:choice"),
])
def test_F1302_役割と拠点の組み合わせ(role, loc, kind, expected):
    assert cg.operator_location_error(role, loc, kind) == expected


def test_商品の入力():
    assert cg.product_input_error(name="Tシャツ", price=2500) is None
    assert cg.product_input_error(name=" ", price=2500) == "name:empty"
    assert cg.product_input_error(name="x", price=0) == "price:range"
