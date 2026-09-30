# -*- coding: utf-8 -*-
"""カートのDBアクセス（AP-201・202・203・205）。

★cart（T-19）の主キーは「カートキー×SKU」。
  だから同じSKUを2回入れても行は増えない。数量が上書きされるだけ。
  これが結合テスト IT-404 の前提になっている。

★SQL は ORM。文字列連結しない（N-32）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, and_, delete, func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from repository.models import (
    Cart,
    Color,
    EcExclusion,
    Location,
    Product,
    ProductImage,
    SalesConfig,
    Size,
    Sku,
    Stock,
)

_SECTION_BACKYARD = 1

USER_KIND_GUEST = 1
USER_KIND_MEMBER = 2


def sales_config(db: Session) -> dict:
    """いま効いている販売設定（T-30）。送料・送料無料の線・税率はここが正。"""
    stmt = (
        select(
            SalesConfig.tax_rate,
            SalesConfig.shipping_fee,
            SalesConfig.free_shipping_line,
        )
        .where(SalesConfig.effective_from <= func.current_date())
        .order_by(SalesConfig.effective_from.desc())
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row is None:
        # 設定が無い環境では動かさない。既定値でごまかすと、
        # あとで「なぜこの送料になったのか」が追えなくなる
        raise RuntimeError("sales_config が空。seed/02_master.sql を流す")
    return {
        "tax_rate": Decimal(str(row.tax_rate)),
        "shipping_fee": int(row.shipping_fee),
        "free_shipping_line": int(row.free_shipping_line),
    }


def saleable_qty(db: Session, sku_code: str) -> int:
    """そのSKUの販売可能数（BR-05c（a）の候補拠点だけを足す）。

    ★GREATEST で負にしない（設計 3.2.2 ①。UNSIGNED 同士の引き算を避ける）。
    """
    exclusion = (
        select(EcExclusion.product_code)
        .where(
            EcExclusion.product_code == Sku.product_code,
            EcExclusion.location_code == Location.location_code,
        )
        .exists()
    )
    stmt = (
        select(
            func.coalesce(
                func.sum(
                    func.greatest(
                        func.cast(Stock.qty, Integer) - func.cast(Stock.reserved_qty, Integer),
                        0,
                    )
                ),
                0,
            )
        )
        .select_from(Sku)
        .join(Stock, and_(Stock.sku_code == Sku.sku_code, Stock.section == _SECTION_BACKYARD))
        .join(
            Location,
            and_(
                Location.location_code == Stock.location_code,
                Location.ec_saleable.is_(True),
                Location.suspended.is_(False),
            ),
        )
        .where(Sku.sku_code == sku_code, ~exclusion)
    )
    return int(db.execute(stmt).scalar() or 0)


def sku_exists(db: Session, sku_code: str) -> bool:
    stmt = (
        select(Sku.sku_code)
        .join(Product, Product.product_code == Sku.product_code)
        .where(Sku.sku_code == sku_code, Product.is_published.is_(True))
    )
    return db.execute(stmt).first() is not None


def line_count(db: Session, cart_key: str) -> int:
    return int(
        db.execute(select(func.count()).select_from(Cart).where(Cart.cart_key == cart_key)).scalar()
        or 0
    )


def get_line(db: Session, cart_key: str, sku_code: str) -> dict | None:
    stmt = select(Cart.qty).where(Cart.cart_key == cart_key, Cart.sku_code == sku_code)
    row = db.execute(stmt).first()
    return {"qty": int(row.qty)} if row else None


def upsert_line(db: Session, cart_key: str, sku_code: str, qty: int, user_kind: int) -> None:
    """入れる／数量を上書きする。

    ★主キーが (cart_key, sku_code) なので、同じSKUは必ず1行にまとまる。
      2本目の明細は作れない（IT-404 の前提）。
    """
    stmt = mysql_insert(Cart).values(
        cart_key=cart_key,
        sku_code=sku_code,
        user_kind=user_kind,
        qty=qty,
        added_at=datetime.now(),
    )
    stmt = stmt.on_duplicate_key_update(qty=stmt.inserted.qty, added_at=stmt.inserted.added_at)
    db.execute(stmt)
    db.commit()


def set_qty(db: Session, cart_key: str, sku_code: str, qty: int) -> int:
    res = db.execute(
        update(Cart)
        .where(Cart.cart_key == cart_key, Cart.sku_code == sku_code)
        .values(qty=qty)
    )
    db.commit()
    return res.rowcount


def delete_line(db: Session, cart_key: str, sku_code: str) -> int:
    res = db.execute(
        delete(Cart).where(Cart.cart_key == cart_key, Cart.sku_code == sku_code)
    )
    db.commit()
    return res.rowcount


def list_lines(db: Session, cart_key: str) -> list[dict]:
    """カートの中身。★単価はここで商品マスタから引く。本文から受け取らない（N-35）。"""
    stmt = (
        select(
            Cart.sku_code,
            Cart.qty,
            Cart.added_at,
            Sku.product_code,
            Sku.color_code,
            Sku.size_code,
            Product.name.label("product_name"),
            Product.price.label("unit_price"),
            Product.is_published.label("is_published"),   # ★非公開になった商品は注文させない（R-27）
            Color.name.label("color_name"),
            Size.name.label("size_name"),
            ProductImage.url.label("image_url"),
        )
        .select_from(Cart)
        .join(Sku, Sku.sku_code == Cart.sku_code)
        .join(Product, Product.product_code == Sku.product_code)
        .join(Color, Color.color_code == Sku.color_code)
        .join(Size, Size.size_code == Sku.size_code)
        .outerjoin(
            ProductImage,
            and_(
                ProductImage.product_code == Sku.product_code,
                ProductImage.color_code == Sku.color_code,
                ProductImage.sort_no == 1,
            ),
        )
        .where(Cart.cart_key == cart_key)
        .order_by(Cart.added_at, Cart.sku_code)
    )
    return [dict(r._mapping) for r in db.execute(stmt).all()]


# ------------------------------------------------------------
# 6.2.6  注文が成立したら、その注文になった明細だけをカートから消す（R-27）
# ------------------------------------------------------------
def remove_ordered(db: Session, order_no: str) -> int:
    """引当済・支払い待ちになったときに呼ぶ。★何度呼んでも1回ぶんしか減らさない。

    ★カート全体を消さない。その注文の明細の SKU を、注文した数だけ減らす。
      注文したあとにカートへ足した別の商品（同じ SKU の追加分も）を巻き込まない。
    ★戻さない。引当失敗・キャンセルでは呼ばない（6.2.6）。
    ★注文の cart_key を NULL にする条件付きUPDATEで「まだ消していない」を取り合う。
      再決済で支払い待ち → 引当済と2回成立しても、2回目は 0件で何もしない。
    """
    from sqlalchemy import text as _t

    row = db.execute(_t("SELECT cart_key FROM orders WHERE order_no = :o FOR UPDATE"),
                     {"o": order_no}).first()
    if not row or not row.cart_key:
        db.rollback()
        return 0
    key = row.cart_key
    db.execute(_t("UPDATE orders SET cart_key = NULL WHERE order_no = :o AND cart_key IS NOT NULL"),
               {"o": order_no})
    # ★その注文で使ったクーポンは、カートの適用からも外す（R-29）。
    #   残すと、次の買い物で同じクーポンが「適用済み」に見え、会員あたりの上限で弾かれる
    db.execute(_t("DELETE cc FROM cart_coupon cc JOIN orders o ON o.coupon_code = cc.coupon_code "
                  " WHERE cc.cart_key = :k AND o.order_no = :o"), {"k": key, "o": order_no})
    removed = 0
    for l in db.execute(_t("SELECT sku_code, qty FROM order_line WHERE order_no = :o "
                           " ORDER BY sku_code"), {"o": order_no}).all():
        # ★引き算をしない更新と、消す更新に分ける（3.2.2 ①。UNSIGNED で負にしない）
        removed += db.execute(
            _t("DELETE FROM cart WHERE cart_key = :k AND sku_code = :s AND qty <= :q"),
            {"k": key, "s": l.sku_code, "q": int(l.qty)}).rowcount
        db.execute(
            _t("UPDATE cart SET qty = qty - :q WHERE cart_key = :k AND sku_code = :s AND qty > :q"),
            {"k": key, "s": l.sku_code, "q": int(l.qty)})
    db.commit()
    return removed


# ------------------------------------------------------------
# AP-204  カートに適用したクーポン（F-309。R-29）
# ------------------------------------------------------------
def get_cart_coupon(db: Session, cart_key: str) -> dict | None:
    from sqlalchemy import text as _t

    row = db.execute(_t("SELECT cc.coupon_code, c.name FROM cart_coupon cc "
                        "  JOIN coupon c ON c.coupon_code = cc.coupon_code WHERE cc.cart_key = :k"),
                     {"k": cart_key}).first()
    return dict(row._mapping) if row else None


def set_cart_coupon(db: Session, cart_key: str, coupon_code: str) -> None:
    """★1注文に1枚（BR-16）。入れ直したら差し替える。"""
    from sqlalchemy import text as _t

    db.execute(_t("INSERT INTO cart_coupon (cart_key, coupon_code) VALUES (:k, :c) "
                  "ON DUPLICATE KEY UPDATE coupon_code = :c, applied_at = NOW(3)"),
               {"k": cart_key, "c": coupon_code})
    db.commit()


def delete_cart_coupon(db: Session, cart_key: str) -> int:
    from sqlalchemy import text as _t

    n = db.execute(_t("DELETE FROM cart_coupon WHERE cart_key = :k"), {"k": cart_key}).rowcount
    db.commit()
    return int(n)


def member_exists(db: Session, member_id: str) -> bool:
    from sqlalchemy import text as _t

    return db.execute(_t("SELECT 1 FROM member WHERE member_id = :m"), {"m": member_id}).first() is not None
