# -*- coding: utf-8 -*-
"""AP-201 カート / AP-202 投入 / AP-203 数量変更・削除 / AP-205 金額の内訳。

★金額はサーバが決める（N-35）。
  本文に unit_price を足されても読まない。単価は商品マスタから引く（SEC-402）。

★カートキーは専用の識別子（T-19。ゲストは「発行した識別子」）。
  ★セッションIDは流用しない（09-06 決定）。セッションは60分、カートは30日（F-301）。
  会員が入ったら会員IDに切り替える（BR-24a）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StrictInt
from sqlalchemy.orm import Session

from api.schemas import CartResponse, CartSummaryResponse, ErrorResponse
from core.config import IMAGE_BASE_URL
from core.db import get_db
from core.deps import cart_key as cart_key_header, require_internal_auth, session_id
from core.errors import AppError
from domain.pricing import (
    MAX_LINES,
    CartLine,
    DeliveryType,
    max_addable_qty,
    summarize,
)
from datetime import datetime

from pydantic import StrictStr

from domain import coupon as coupon_domain
from repository import cart as repo
from repository import coupon as coupon_repo

router = APIRouter(prefix="/cart", tags=["cart"])

DELIVERY_TYPES = (DeliveryType.SHIP, DeliveryType.PICKUP)


class AddItem(BaseModel):
    """★StrictInt。"1" も 1.5 も 1e2 も受けない（SEC-405）。

    ★unit_price は定義しない。本文に足されても、ここに入る場所が無い（SEC-402）。
    """

    sku_code: str
    qty: StrictInt


class ChangeQty(BaseModel):
    qty: StrictInt


def _cart_key(key: str | None) -> str:
    """★カートキーはセッションIDではない（09-06 決定）。

    無いときは ERR-1101 を返す。文言はフロント層が画面ごとに決める（設計 8.2）。
    カート画面では「カートを読み込めませんでした。開き直してください」と出す。
    """
    if not key:
        raise AppError("ERR-1101")
    return key


def _image_url(relative: str | None) -> str | None:
    if not relative:
        return None
    return f"{IMAGE_BASE_URL.rstrip('/')}/{relative.lstrip('/')}"


def _build(db: Session, cart_key: str, delivery_type: str) -> dict:
    """カートの中身と金額を組み立てる。AP-201 と AP-205 で共有する。"""
    rows = repo.list_lines(db, cart_key)
    cfg = repo.sales_config(db)

    lines = []
    for r in rows:
        saleable = repo.saleable_qty(db, r["sku_code"])
        lines.append(
            {
                "sku_code": r["sku_code"],
                "product_code": r["product_code"],
                "product_name": r["product_name"],
                "color_code": r["color_code"],
                "color_name": r["color_name"],
                "size_code": r["size_code"],
                "size_name": r["size_name"],
                # ★単価はマスタの値。本文から来た値ではない
                "unit_price": int(r["unit_price"]),
                "qty": int(r["qty"]),
                "line_amount": int(r["unit_price"]) * int(r["qty"]),
                "image_url": _image_url(r["image_url"]),
                # 在庫が減っていたら、画面で気づけるようにしておく
                "saleable_qty": saleable,
                "max_qty": max_addable_qty(saleable),
            }
        )

    item_total = sum(l["line_amount"] for l in lines)
    coupon = _coupon_view(db, cart_key, item_total, [(l["sku_code"], l["line_amount"]) for l in lines])
    s = summarize(
        [CartLine(l["sku_code"], l["unit_price"], l["qty"]) for l in lines],
        delivery_type=delivery_type,
        # ★割引はサーバが決める（N-35・BR-16）。★送料無料の判定と残額は割引後で数える（BR-13）
        discount=coupon["discount"] if coupon and coupon["usable"] else 0,
        fee=cfg["shipping_fee"],
        free_line=cfg["free_shipping_line"],
        tax_rate=cfg["tax_rate"],
    )
    return {
        "items": lines,
        "summary": {
            "item_total": s.item_total,
            "discount": s.discount,
            "shipping_fee": s.shipping_fee,
            "total_amount": s.total_amount,
            "tax_amount": s.tax_amount,
            "free_shipping_remain": s.free_shipping_remain,
            "delivery_type": s.delivery_type,
            "coupon": coupon,
        },
    }


def _coupon_check(db: Session, coupon_code: str, member_id: str | None,
                  item_total: int, lines: list[tuple[str, int]] | None = None
                  ) -> tuple[object | None, str | None, int | None, int]:
    """(クーポン, 使えない理由のコード, 不足額, 割引額)。★判定は domain/coupon（注文のときと同じ関数）。"""
    c = coupon_repo.find(db, coupon_code)
    if c is None:
        return None, "ERR-1203", None, 0
    bad = coupon_domain.reason_unusable(
        c, item_total=item_total, now=datetime.now(),
        member_used=coupon_repo.member_used_count(db, coupon_code, member_id))
    shortfall = int(c.min_amount) - item_total if bad == "ERR-1212" else None
    # ★BR-12。対象を限定したクーポンは、対象商品の明細金額の合計に適用する（R-32）
    eligible = coupon_repo.eligible_total(db, coupon_code, lines or []) if lines is not None else item_total
    if bad is None and eligible <= 0:
        bad = "ERR-1203"             # ★カートに対象の商品が無い（8.2 に専用のコードが無い。報告に書く）
    discount = coupon_domain.discount_for(c, eligible) if bad is None else 0
    return c, bad, shortfall, discount


def _coupon_view(db: Session, cart_key: str, item_total: int,
                 lines: list[tuple[str, int]]) -> dict | None:
    """カートに適用中のクーポンを、いまのカートの中身で判定し直す（F-310）。

    ★適用したあとで商品を減らすと、最低購入金額を割ることがある。
      そのときは外さずに「使えない理由」と不足額を出す（客が気づいて足せるように）。
    ★会員のカートキーは会員ID（BR-24a）。クーポンは会員だけが適用できる（要件 4.3）。
    """
    applied = repo.get_cart_coupon(db, cart_key)
    if not applied:
        return None
    member_id = cart_key if repo.member_exists(db, cart_key) else None
    c, bad, shortfall, discount = _coupon_check(db, applied["coupon_code"], member_id, item_total, lines)
    if c is None:
        return None
    return {"coupon_code": applied["coupon_code"], "name": applied["name"],
            "usable": bad is None,
            "discount": discount,
            "error_code": bad, "shortfall": shortfall}


def _delivery(v: str) -> str:
    if v not in DELIVERY_TYPES:
        raise AppError("ERR-1004", {"field": "delivery_type"})
    return v


@router.get(
    "",
    dependencies=[Depends(require_internal_auth)],
    response_model=CartResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_cart(
    db: Session = Depends(get_db),
    sid: str | None = Depends(cart_key_header),
    delivery_type: str = Query(default=DeliveryType.SHIP),
) -> dict:
    """AP-201 カートの中身と金額。"""
    return {"data": _build(db, _cart_key(sid), _delivery(delivery_type))}


@router.get(
    "/summary",
    dependencies=[Depends(require_internal_auth)],
    response_model=CartSummaryResponse,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_summary(
    db: Session = Depends(get_db),
    sid: str | None = Depends(cart_key_header),
    delivery_type: str = Query(default=DeliveryType.SHIP),
) -> dict:
    """AP-205 金額の内訳と、送料無料までの残額。

    ★delivery_type で送料が変わる（BR-14）。画面が受取方法を切り替えたら、ここを引き直す。
    """
    built = _build(db, _cart_key(sid), _delivery(delivery_type))
    return {"data": built["summary"]}


def _check_qty_limit(db: Session, sku_code: str, wanted: int) -> None:
    """数量の上限を確かめる（F-301）。★入口が2つあるので、判定はここ1か所だけ。

    ★「入れる」と「数量を直す」で別々に書いていたため、
      合算の直し忘れが片方にだけ残った（R-24 の AT-406）。
      ★同じことをする入口が2つあるなら、条件は両方に掛かっているか確かめる（10.2.6）。

    `wanted` は「この操作のあとにカートへ入る数量」。
    ★足す数ではなく、足したあとの数を渡す。
    """
    limit = max_addable_qty(repo.saleable_qty(db, sku_code))
    if limit <= 0 or wanted > limit:
        raise AppError("ERR-1202", {"field": "qty", "max_qty": limit})


@router.post(
    "/items",
    dependencies=[Depends(require_internal_auth)],
    response_model=CartResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def add_item(
    body: AddItem,
    db: Session = Depends(get_db),
    sid: str | None = Depends(cart_key_header),
) -> dict:
    """AP-202 カート投入（F-301）。

    ★数量の上限は「99」と「販売可能数」の小さい方。超えたら ERR-1202。
    ★同じSKUがすでに入っていれば合算する（6.2.4）。「入れる」は足す操作。
      数量を決め打ちで置き換えたいときは PATCH（AP-203）。
    """
    key = _cart_key(sid)

    if body.qty < 1:
        # ★負も0も入り口で止める。在庫にも金額にも触らせない（SEC-403）
        raise AppError("ERR-1003", {"field": "qty"})

    if not repo.sku_exists(db, body.sku_code):
        raise AppError("ERR-1215")

    # ★同じSKUなら数量を合算する（設計 6.2.4・BR-24a・F-301）。
    #   ★上書きにしていたので、5個入れたあと1個足すと黙って1個に減っていた（R-24）。
    exist = repo.get_line(db, key, body.sku_code)
    wanted = (int(exist["qty"]) if exist else 0) + body.qty

    _check_qty_limit(db, body.sku_code, wanted)

    # 明細の件数の上限（F-301）。すでに入っているSKUなら件数は増えない
    if exist is None and repo.line_count(db, key) >= MAX_LINES:
        raise AppError("ERR-1202", {"field": "lines", "max_lines": MAX_LINES})

    repo.upsert_line(db, key, body.sku_code, wanted, repo.USER_KIND_GUEST)
    return {"data": _build(db, key, DeliveryType.SHIP)}


@router.patch(
    "/items/{sku_code}",
    dependencies=[Depends(require_internal_auth)],
    response_model=CartResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def change_qty(
    sku_code: str,
    body: ChangeQty,
    db: Session = Depends(get_db),
    sid: str | None = Depends(cart_key_header),
) -> dict:
    """AP-203 数量変更。★負の数は ERR-1003（SEC-403）。"""
    key = _cart_key(sid)

    if body.qty < 1:
        raise AppError("ERR-1003", {"field": "qty"})

    if repo.get_line(db, key, sku_code) is None:
        raise AppError("ERR-1215")

    # ★こちらは「その数量にする」。合算しない
    _check_qty_limit(db, sku_code, body.qty)

    repo.set_qty(db, key, sku_code, body.qty)
    return {"data": _build(db, key, DeliveryType.SHIP)}


@router.delete(
    "/items/{sku_code}",
    dependencies=[Depends(require_internal_auth)],
    response_model=CartResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def remove_item(
    sku_code: str,
    db: Session = Depends(get_db),
    sid: str | None = Depends(cart_key_header),
) -> dict:
    """AP-203 削除。"""
    key = _cart_key(sid)
    if repo.delete_line(db, key, sku_code) == 0:
        raise AppError("ERR-1215")
    return {"data": _build(db, key, DeliveryType.SHIP)}


# ============================================================
# AP-204  クーポンの適用・解除（F-309・F-310。R-29）
# ============================================================
class ApplyCoupon(BaseModel):
    coupon_code: StrictStr


def _member_cart(db: Session, sid: str | None, ckey: str | None) -> tuple[str, str]:
    """★クーポンは会員だけ（要件 4.3）。カートキーは会員ID（BR-24a）。"""
    from repository import auth as auth_repo

    row = auth_repo.load_session(db, sid)
    if row is None or row["user_kind"] != auth_repo.USER_MEMBER or not row.get("member_id"):
        raise AppError("ERR-1101")
    key = _cart_key(ckey)
    if key != row["member_id"]:
        # ★ログイン直後にカートキーが切り替わっていない。会員のカートでなければ適用しない
        raise AppError("ERR-1101")
    return row["member_id"], key


@router.post("/coupon", dependencies=[Depends(require_internal_auth)], response_model=CartResponse)
def apply_coupon(body: ApplyCoupon, db: Session = Depends(get_db),
                 sid: str | None = Depends(session_id),
                 ckey: str | None = Depends(cart_key_header)) -> dict:
    """★使えないクーポンは適用しない。理由は 8.2 のコード（1203・1211〜1214）で返す。

    ★全体上限は「読んだ時点でもう無い」ときだけここで弾く。最後の1枚の取り合いは、
      注文の引当と同じトランザクションの条件付きUPDATEが決める（BR-16a・IT-413）。
    """
    member_id, key = _member_cart(db, sid, ckey)
    code = body.coupon_code.strip().upper()
    if not code:
        raise AppError("ERR-1001", {"field": "coupon_code"})
    rows = repo.list_lines(db, key)
    item_total = sum(int(r["unit_price"]) * int(r["qty"]) for r in rows)
    c, bad, shortfall, _ = _coupon_check(db, code, member_id, item_total,
                                         [(r["sku_code"], int(r["unit_price"]) * int(r["qty"])) for r in rows])
    if bad:
        detail: dict = {"field": "coupon_code"}
        if shortfall is not None:
            detail["shortfall"] = shortfall       # ★「あと◯円のお買い上げで使えます」（要件 9.5）
        raise AppError(bad, detail)
    repo.set_cart_coupon(db, key, code)
    return {"data": _build(db, key, DeliveryType.SHIP)}


@router.delete("/coupon", dependencies=[Depends(require_internal_auth)], response_model=CartResponse)
def remove_coupon(db: Session = Depends(get_db), sid: str | None = Depends(session_id),
                  ckey: str | None = Depends(cart_key_header)) -> dict:
    _, key = _member_cart(db, sid, ckey)
    repo.delete_cart_coupon(db, key)
    return {"data": _build(db, key, DeliveryType.SHIP)}
