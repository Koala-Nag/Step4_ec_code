# -*- coding: utf-8 -*-
"""APIの応答の形（設計 4.1.4）。

★ここを OpenAPI に出すことが目的。
  フロントは openapi.json から型を生成するので、
  この形を変えるとフロントのビルドが落ちる（付録A-0b・9.4a）。
  「気づかないまま項目名が変わる」を、コンパイルで止めるための仕掛け。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProductListItem(BaseModel):
    product_code: str
    name: str
    price: int
    category_code: str
    # ★2値。一覧では販売可能数を合計しない（設計 9.2.1b・R-08）
    in_stock: bool
    image_url: str | None = None
    # 一覧のカードに出すサイズ展開（09-05 決定）。sku から引く。追加のAPI呼び出しは無い
    size_range: list[str] = []
    # ★新着バッジ（R-28）。登録から14日以内。判定はサーバ（domain/stock.is_new）
    is_new: bool = False


class PageInfo(BaseModel):
    limit: int
    sort: str
    # ★キーセット方式。offset は持たない（設計 4.1.7）。次が無ければ null
    next_after: str | None = None
    # ★件数は cap 件で打ち切って数える（9.2.1d・R-16）。
    #   total_capped が true のとき、total は「total 件以上」の意味になる
    total: int = 0
    total_capped: bool = False


class ProductListResponse(BaseModel):
    data: list[ProductListItem]
    page: PageInfo


class ColorInfo(BaseModel):
    color_code: str
    name: str
    image_url: str | None = None


class SizeInfo(BaseModel):
    size_code: str
    name: str
    sort: int


class Variant(BaseModel):
    sku_code: str
    color_code: str
    size_code: str
    # ★3値。商品詳細だけ（BR-25）
    stock_label: str = Field(description="in_stock / low / out")
    # ★0点のサイズは選べない（F-203）
    selectable: bool


class ProductDetail(BaseModel):
    product_code: str
    name: str
    price: int
    category_code: str
    material: str | None = None
    description: str | None = None
    colors: list[ColorInfo]
    sizes: list[SizeInfo]
    variants: list[Variant]


class ProductDetailResponse(BaseModel):
    data: ProductDetail


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict | None = None


class ErrorResponse(BaseModel):
    """失敗の形（設計 4.1.4・8.2）。★例外をそのまま出さない。"""

    error: ErrorBody


# ------------------------------------------------------------
# カート（AP-201・202・203・205）
# ------------------------------------------------------------
class CartItem(BaseModel):
    sku_code: str
    product_code: str
    product_name: str
    color_code: str
    color_name: str
    size_code: str
    size_name: str
    # ★単価はマスタの値。本文から受け取らない（N-35・SEC-402）
    unit_price: int
    qty: int
    line_amount: int
    image_url: str | None = None
    saleable_qty: int
    # 99 と販売可能数の小さい方（F-301）
    max_qty: int


class CartCoupon(BaseModel):
    """カートに適用したクーポン（F-310。R-29）。★判定はサーバ。"""
    coupon_code: str
    name: str
    # ★いまのカートで使えるか。使えなければ割引は 0 で、理由のコード（8.2）と不足額を返す
    usable: bool
    discount: int = 0
    error_code: str | None = None
    shortfall: int | None = None


class CartSummary(BaseModel):
    item_total: int
    discount: int
    shipping_fee: int
    total_amount: int
    tax_amount: int
    # あと何円で送料無料か（BR-13）。★割引後の商品合計で数える
    free_shipping_remain: int
    delivery_type: str
    coupon: CartCoupon | None = None


class CartData(BaseModel):
    items: list[CartItem]
    summary: CartSummary


class CartResponse(BaseModel):
    data: CartData


class CartSummaryResponse(BaseModel):
    data: CartSummary


# ------------------------------------------------------------
# 注文（AP-301・301a・302）
# ------------------------------------------------------------
class OrderCreated(BaseModel):
    order_no: str
    total_amount: int
    status: int
    # ★決済取引にはしない。応答に載せて返すだけ（7.2.1）
    client_token: str
    # ブラウザが行く先。★当社を通らない（N-21・CON-08）
    three_ds_url: str
    # 同じ冪等キーで2回目だったか（IT-302）
    replayed: bool = False


class OrderCreatedResponse(BaseModel):
    data: OrderCreated


class UnavailableItem(BaseModel):
    """引き当てられなかった明細（FR-1202）。★どの商品かが分かる形で返す。"""

    line_no: int
    sku_code: str
    qty: int
    product_name: str
    color_name: str | None = None
    size_name: str | None = None


class OrderResult(BaseModel):
    order_no: str
    status: int
    # allocated / declined / payment_pending / allocation_failed
    result: str
    reason: str | None = None
    # ★いくつに分けて届くか（FR-306）。完了画面と確認メールの両方に出す
    shipments: int | None = None
    # ★引き当てられなかった商品（FR-1202）
    unavailable_items: list[UnavailableItem] | None = None
    # ★代金をいただいていないことを、はっきり返す（FR-1202）
    charged: bool | None = None


class OrderResultResponse(BaseModel):
    data: OrderResult
