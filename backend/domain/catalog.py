# -*- coding: utf-8 -*-
"""商品マスタの決まりごと（F-701〜705・F-709・F-808・F-1302。R-27）。

★このモジュールは repository も external も import しない（設計 2.2）。
  ここにあるのは「通してよい値か」「何を作るか」の判断だけ。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ------------------------------------------------------------
# 入力の形（6.1 の入力仕様の範囲で、コード類は ascii_bin の列に入る形だけを通す）
# ------------------------------------------------------------
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,19}$")          # 商品・カテゴリ・種別コード（20桁）
SHORT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,9}$")     # 色・サイズ・共通サイズ（10桁）
OPERATOR_ID_RE = re.compile(r"^[A-Z0-9]{1,20}$")

PRICE_MIN, PRICE_MAX = 1, 9_999_999
NAME_MAX = 100
MATERIAL_MAX = 200
DESCRIPTION_MAX = 2000


def product_input_error(*, name: str | None, price: int | None, material: str | None = None,
                        description: str | None = None) -> str | None:
    """通れば None。★例外にしない（呼び出し側が ERR-100x に変換する）。"""
    if name is not None:
        if not name.strip():
            return "name:empty"
        if len(name) > NAME_MAX:
            return "name:too_long"
    if price is not None and not (PRICE_MIN <= price <= PRICE_MAX):
        return "price:range"
    if material is not None and len(material) > MATERIAL_MAX:
        return "material:too_long"
    if description is not None and len(description) > DESCRIPTION_MAX:
        return "description:too_long"
    return None


# ------------------------------------------------------------
# F-702  SKUの一括生成
# ------------------------------------------------------------
@dataclass(frozen=True)
class NewSku:
    sku_code: str
    color_code: str
    size_code: str


def sku_code_of(product_code: str, color_code: str, size_code: str) -> str:
    """seed と同じ命名（P0001-BK-M）。★20桁を超えるなら作らない（列が VARCHAR(20)）。"""
    return f"{product_code}-{color_code}-{size_code}"


def plan_skus(product_code: str, colors: list[str], sizes: list[str],
              existing: set[tuple[str, str]]) -> tuple[list[NewSku], list[tuple[str, str]]]:
    """色×サイズの組み合わせのうち、まだ無いものだけを作る。

    ★すでにある組み合わせは作らない（重ねると 6.2.4 の前提——
      1注文に同じ SKU の明細が2行並ばない——が崩れる。R-27 の依頼）。
      一意制約（uq_sku_combo）でも弾かれるが、弾かれる前に「作らない」と決める。
    ★選ばれた順ではなく、選択肢の並びのまま作る。重複した指定は1つにまとめる。
    戻り値  (作るもの, すでにあって作らなかった組み合わせ)
    """
    made: list[NewSku] = []
    skipped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for c in dict.fromkeys(colors):
        for s in dict.fromkeys(sizes):
            if (c, s) in seen:
                continue
            seen.add((c, s))
            if (c, s) in existing:
                skipped.append((c, s))
                continue
            code = sku_code_of(product_code, c, s)
            if len(code) > 20:
                skipped.append((c, s))
                continue
            made.append(NewSku(code, c, s))
    return made, skipped


# ------------------------------------------------------------
# F-703  画像（N-36）
# ------------------------------------------------------------
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGES_PER_PRODUCT = 50


def image_kind(data: bytes) -> str | None:
    """★拡張子ではなく中身で判定する（N-36）。JPEG・PNG 以外は None。"""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def image_error(data: bytes, current_count: int) -> str | None:
    if not data:
        return "empty"
    if len(data) > IMAGE_MAX_BYTES:
        return "too_large"
    if image_kind(data) is None:
        return "not_image"
    if current_count >= IMAGES_PER_PRODUCT:
        return "too_many"
    return None


# ------------------------------------------------------------
# F-808  店頭への払い出し
# ------------------------------------------------------------
def floor_move_error(*, qty: int, backyard_qty: int, reserved_qty: int) -> str | None:
    """★引当済の数量は払い出せない。上限は販売可能数（qty − reserved_qty）。

    ★引き算は Python の int で行う（UNSIGNED の引き算は SQL でしない。3.2.2 ①）。
      SQL 側は WHERE qty >= reserved_qty + :q の条件付きUPDATEで同じ条件を掛ける。
    """
    if qty <= 0:
        return "qty:range"
    if qty > max(backyard_qty - reserved_qty, 0):
        return "qty:over_saleable"
    return None


# ------------------------------------------------------------
# F-709  マスタ
# ------------------------------------------------------------
@dataclass(frozen=True)
class MasterKind:
    table: str
    key: str
    code_re: re.Pattern
    has_sort: bool
    has_parent: bool = False


MASTERS: dict[str, MasterKind] = {
    "colors": MasterKind("color", "color_code", SHORT_CODE_RE, True),
    "sizes": MasterKind("size", "size_code", SHORT_CODE_RE, True),
    "common-sizes": MasterKind("common_size", "common_size_code", SHORT_CODE_RE, True),
    "categories": MasterKind("category", "category_code", CODE_RE, True, has_parent=True),
    "item-types": MasterKind("item_type", "item_type_code", CODE_RE, False),
}

# ★「使われている」を数える先（使われていれば削除できず、無効化のみ。F-709）
MASTER_USAGE: dict[str, list[tuple[str, str]]] = {
    "colors": [("sku", "color_code"), ("product_image", "color_code")],
    "sizes": [("sku", "size_code"), ("size_map", "size_code"), ("dimension", "size_code")],
    "common-sizes": [("sku", "common_size_code"), ("size_map", "common_size_code")],
    "categories": [("product", "category_code"), ("category", "parent_code")],
    "item-types": [("product", "item_type_code"), ("measure_template", "item_type_code")],
}


# ------------------------------------------------------------
# F-1302  運営者
# ------------------------------------------------------------
SITE_ROLES = (3, 4)          # 倉庫・店舗（2.4。拠点で共有するアカウント）
ROLES = (1, 2, 3, 4, 5)


def operator_location_error(role: int, location_code: str | None,
                            location_kind: int | None) -> str | None:
    """★倉庫・店舗は所属拠点が必須。ほかの役割は拠点を持たない（operator.location_code）。

    ★倉庫の役割に店舗を、店舗の役割に倉庫を付けない（拠点区分 1=倉庫 2=店舗）。
      付けると「自拠点」の範囲が役割と食い違う。
    """
    if role not in ROLES:
        return "role:choice"
    if role in SITE_ROLES:
        if not location_code or location_kind is None:
            return "location_code:required"
        if (role == 3) != (location_kind == 1):
            return "location_code:kind_mismatch"
        return None
    return "location_code:not_allowed" if location_code else None


# ------------------------------------------------------------
# F-809  拠点の登録・編集（R-32）
# ------------------------------------------------------------
LOCATION_CODE_RE = re.compile(r"^[A-Z0-9]{1,10}$")
ZIP_RE = re.compile(r"^\d{7}$")
TEL_RE = re.compile(r"^\d{10,11}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
LOCATION_NAME_MAX, ADDRESS_MAX = 50, 100
KIND_WAREHOUSE, KIND_STORE = 1, 2


def digits_only(v: str | None) -> str:
    """★郵便番号・電話番号はハイフンを入力時に除去する（要件 6.3）。"""
    return re.sub(r"[-‐－ー\s]", "", v or "")


def business_days_mask(weekdays: list[int]) -> int:
    """営業曜日（0=日〜6=土）の集合を location.business_days（日=bit0 〜 土=bit6）にする。"""
    m = 0
    for d in weekdays:
        m |= 1 << int(d)
    return m


def location_input_error(*, name: str | None = None, pref_code: str | None = None,
                         zip_: str | None = None, address: str | None = None, tel: str | None = None,
                         weekdays: list[int] | None = None, cutoff_time: str | None = None,
                         prefs: set[str] | None = None) -> str | None:
    """通れば None。"項目:理由" を返す（api/catalog._field_error で 8.2 のコードに寄せる）。"""
    if name is not None:
        if not name.strip():
            return "name:empty"
        if len(name.strip()) > LOCATION_NAME_MAX:
            return "name:too_long"
    if pref_code is not None and prefs is not None and pref_code not in prefs:
        return "pref_code:choice"                  # ★47都道府県からの選択式（BR-05a に使う）
    if zip_ is not None and not ZIP_RE.match(zip_):
        return "zip:format"
    if address is not None:
        if not address.strip():
            return "address:empty"
        if len(address.strip()) > ADDRESS_MAX:
            return "address:too_long"
    if tel is not None and not TEL_RE.match(tel):
        return "tel:format"
    if weekdays is not None:
        if not weekdays:
            return "business_days:empty"           # ★営業日が無い拠点は、発送予定日が決まらない（BR-23）
        if any(not (0 <= int(d) <= 6) for d in weekdays):
            return "business_days:choice"
    if cutoff_time is not None and not TIME_RE.match(cutoff_time):
        return "cutoff_time:format"
    return None
