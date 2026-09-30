# -*- coding: utf-8 -*-
"""お気に入り（AP-107・F-108）・レビュー（AP-104・AP-105・F-206）・会員情報の変更（AP-504 PATCH・F-605）。R-32。

★会員だけの機能（要件 4.3「お気に入り・クーポン・住所帳は会員のみ」）。
  ゲストのセッションでは ERR-1101。★入口を隠すだけにしない（R-29 の提案64：会員だけの機能はゲストで空回りしないか）。

★レビューは「購入済みの会員だけ」（F-206・AP-105「購入済みでなければ 403」）。1商品1会員1件（T-31 の主キー）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictInt, StrictStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from core import applog
from core.config import IMAGE_BASE_URL
from core.db import get_db
from core.deps import current_member, require_internal_auth, session_id
from core.errors import AppError
from domain import catalog as cg

favorites = APIRouter(prefix="/favorites", tags=["mypage"], dependencies=[Depends(require_internal_auth)])
reviews = APIRouter(prefix="/products", tags=["mypage"], dependencies=[Depends(require_internal_auth)])
profile = APIRouter(prefix="/me", tags=["auth"], dependencies=[Depends(require_internal_auth)])

# 注文の状態（5.4）。★「購入済み」＝商品を発送した注文（一部出荷済・出荷済・完了）
ORDER_PURCHASED = (8, 9, 10)
RATING_MIN, RATING_MAX, REVIEW_BODY_MAX = 1, 5, 1000
MEMBER_NAME_MAX = 50


def _img(rel: str | None) -> str | None:
    return f"{IMAGE_BASE_URL.rstrip('/')}/{rel.lstrip('/')}" if rel else None


# ============================================================
# AP-107  お気に入り（F-108）
# ============================================================
class FavoriteBody(BaseModel):
    product_code: StrictStr


@favorites.get("")
def list_favorites(db: Session = Depends(get_db), member=Depends(current_member)) -> dict:
    rows = db.execute(text(
        "SELECT f.product_code, f.created_at, p.name, p.price, p.is_published, "
        "       (SELECT i.url FROM product_image i WHERE i.product_code = p.product_code "
        "         ORDER BY i.color_code, i.sort_no LIMIT 1) AS image_url "
        "  FROM favorite f JOIN product p ON p.product_code = f.product_code "
        " WHERE f.member_id = :m ORDER BY f.created_at DESC"), {"m": member["member_id"]}).all()
    return {"data": {"favorites": [
        {"product_code": r.product_code, "name": r.name, "price": int(r.price),
         # ★公開を終えた商品は、行は残して「公開を終えました」と出す（勝手に消すと、客は何が消えたか分からない）
         "is_published": bool(r.is_published), "image_url": _img(r.image_url),
         "added_at": str(r.created_at)} for r in rows]}}


@favorites.post("")
def add_favorite(body: FavoriteBody, db: Session = Depends(get_db), member=Depends(current_member)) -> dict:
    code = body.product_code.strip()
    p = db.execute(text("SELECT is_published FROM product WHERE product_code = :p"), {"p": code}).first()
    if not p or not p.is_published:
        raise AppError("ERR-1215")                  # ★非公開の商品は「無い」と同じ（F-705）
    n = db.execute(text("INSERT IGNORE INTO favorite (member_id, product_code) VALUES (:m, :p)"),
                   {"m": member["member_id"], "p": code}).rowcount
    db.commit()
    applog.emit("member.favorite_added")
    return {"data": {"product_code": code, "favorite": True, "added": bool(n)}}


@favorites.delete("/{product_code}")
def remove_favorite(product_code: str, db: Session = Depends(get_db), member=Depends(current_member)) -> dict:
    n = db.execute(text("DELETE FROM favorite WHERE member_id = :m AND product_code = :p"),
                   {"m": member["member_id"], "p": product_code}).rowcount
    db.commit()
    return {"data": {"product_code": product_code, "favorite": False, "removed": bool(n)}}


# ============================================================
# AP-104・AP-105  レビュー（F-206）
# ============================================================
class ReviewBody(BaseModel):
    rating: StrictInt
    body: StrictStr


def _member_of_session(db: Session, sid: str | None) -> str | None:
    from repository import auth as auth_repo

    row = auth_repo.load_session(db, sid)
    if row and row["user_kind"] == auth_repo.USER_MEMBER and row.get("member_id"):
        return row["member_id"]
    return None


def _purchased(db: Session, member_id: str, product_code: str) -> bool:
    """★購入済み＝その商品が乗った注文を発送した（一部出荷済・出荷済・完了）。支払い待ち・キャンセルは入れない。"""
    return db.execute(text(
        "SELECT 1 FROM orders o JOIN order_line ol ON ol.order_no = o.order_no "
        "  JOIN sku s ON s.sku_code = ol.sku_code "
        " WHERE o.member_id = :m AND s.product_code = :p AND o.status IN (8, 9, 10) LIMIT 1"),
        {"m": member_id, "p": product_code}).first() is not None


def _product_or_404(db: Session, code: str) -> None:
    p = db.execute(text("SELECT is_published FROM product WHERE product_code = :p"), {"p": code}).first()
    if not p or not p.is_published:
        raise AppError("ERR-1215")


@reviews.get("/{product_code}/reviews")
def list_reviews(product_code: str, db: Session = Depends(get_db), sid: str | None = Depends(session_id)) -> dict:
    _product_or_404(db, product_code)
    rows = db.execute(text(
        "SELECT r.member_id, r.rating, r.body, r.is_anonymous, r.posted_at "
        "  FROM review r WHERE r.product_code = :p ORDER BY r.posted_at DESC LIMIT 100"),
        {"p": product_code}).all()
    agg = db.execute(text("SELECT COUNT(*) n, AVG(rating) a FROM review WHERE product_code = :p"),
                     {"p": product_code}).first()
    me = _member_of_session(db, sid)
    if me is None:
        my = "guest"                                 # ★ログインしていない（投稿欄の代わりにログインの案内）
    elif any(r.member_id == me for r in rows):
        my = "posted"
    elif _purchased(db, me, product_code):
        my = "can_post"
    else:
        my = "not_purchased"
    return {"data": {
        "count": int(agg.n), "average": round(float(agg.a), 1) if agg.a is not None else None,
        "my_status": my,
        # ★投稿者の名前は出さない（表示名を決めていない。報告に書く）。自分の投稿だけ「あなたのレビュー」
        "reviews": [{"rating": int(r.rating), "body": r.body, "posted_at": str(r.posted_at)[:10],
                     "mine": me is not None and r.member_id == me} for r in rows],
    }}


@reviews.post("/{product_code}/reviews")
def post_review(product_code: str, body: ReviewBody, db: Session = Depends(get_db),
                member=Depends(current_member)) -> dict:
    _product_or_404(db, product_code)
    text_ = body.body.strip()
    if not (RATING_MIN <= body.rating <= RATING_MAX):
        raise AppError("ERR-1003", {"field": "rating"})       # ★1〜5の整数（6.3）
    if not text_:
        raise AppError("ERR-1001", {"field": "body"})
    if len(text_) > REVIEW_BODY_MAX:
        raise AppError("ERR-1003", {"field": "body"})
    if not _purchased(db, member["member_id"], product_code):
        raise AppError("ERR-1102", {"reason": "not_purchased"})   # ★購入済みでなければ 403（AP-105）
    n = db.execute(text("INSERT IGNORE INTO review (product_code, member_id, rating, body) VALUES (:p, :m, :r, :b)"),
                   {"p": product_code, "m": member["member_id"], "r": body.rating, "b": text_}).rowcount
    db.commit()
    if not n:
        raise AppError("ERR-1216", {"field": "review"})          # ★1商品1会員1件（T-31）
    applog.emit("member.review_posted")
    return {"data": {"product_code": product_code, "rating": body.rating}}


# ============================================================
# AP-504 PATCH  会員情報の変更（F-605）
# ============================================================
class ProfileBody(BaseModel):
    name: StrictStr | None = None
    tel: StrictStr | None = None


@profile.patch("")
def patch_me(body: ProfileBody, db: Session = Depends(get_db), member=Depends(current_member)) -> dict:
    """F-605「氏名・連絡先を変更する」。★メールアドレスは変えない（変えるなら確認メールの往復が要る。報告に書く）。"""
    fields: dict = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise AppError("ERR-1001", {"field": "name"})
        if len(name) > MEMBER_NAME_MAX or "\n" in name:
            raise AppError("ERR-1003", {"field": "name"})
        fields["name"] = name
    if body.tel is not None:
        tel = cg.digits_only(body.tel)             # ★ハイフンは入力時に除去する（6.3）
        if not tel:
            raise AppError("ERR-1001", {"field": "tel"})
        if not cg.TEL_RE.match(tel):
            raise AppError("ERR-1002", {"field": "tel"})
        fields["tel"] = tel
    if not fields:
        raise AppError("ERR-1001", {"field": "body"})
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(text(f"UPDATE member SET {sets} WHERE member_id = :m AND status <> 3"),
               {**fields, "m": member["member_id"]})
    db.commit()
    applog.emit("member.profile_updated")
    row = db.execute(text("SELECT member_id, email, name, tel FROM member WHERE member_id = :m"),
                     {"m": member["member_id"]}).first()
    return {"data": dict(row._mapping)}
