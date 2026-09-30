# -*- coding: utf-8 -*-
"""クーポン管理（AP-B32・F-1001）。R-32。

★作るのは運用管理者だけ（2.4 F-1001）。
★対象（全商品／カテゴリ／商品）は coupon_target に行で持つ。★行が無い＝全商品として扱う（既存のクーポン）。
  対象を限定したクーポンは、対象商品の明細金額の合計に割引を適用する（BR-12。domain/coupon.eligible_total）。
★コードはあとから変えない（注文と利用履歴が参照している）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictInt, StrictStr
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from core import applog
from core.db import get_db
from core.deps import current_operator, require_internal_auth
from core.errors import AppError
from domain import authz
from domain import coupon as cd
from domain.authz import Role

router = APIRouter(prefix="/admin/coupons", tags=["admin-promo"], dependencies=[Depends(require_internal_auth)])

TYPES = {"rate": cd.TYPE_RATE, "amount": cd.TYPE_AMOUNT}
TARGETS = {"all": cd.TARGET_ALL, "category": cd.TARGET_CATEGORY, "product": cd.TARGET_PRODUCT}


def _guard(operator: dict, *, write: bool) -> Role:
    role = Role(int(operator["role"]))
    ok = authz.can_write(role, "F-1001") if write else authz.can_read(role, "F-1001")
    if not ok:
        raise AppError("ERR-1102", {"feature": "F-1001"})
    return role


def _field(reason: str) -> AppError:
    field, _, why = reason.partition(":")
    return AppError({"empty": "ERR-1001", "choice": "ERR-1004"}.get(why, "ERR-1003"), {"field": field, "reason": why})


def _dt(v: str | None, field: str) -> datetime | None:
    if v is None:
        return None
    try:
        return datetime.fromisoformat(v.strip())
    except ValueError:
        raise AppError("ERR-1002", {"field": field})


class CouponBody(BaseModel):
    coupon_code: StrictStr | None = None      # 作るときだけ
    name: StrictStr | None = None
    discount_type: StrictStr | None = None    # rate | amount
    discount_value: StrictInt | None = None
    start_at: StrictStr | None = None         # YYYY-MM-DDTHH:MM
    end_at: StrictStr | None = None
    min_amount: StrictInt | None = None
    total_limit: StrictInt | None = None      # 0 または未指定で「上限なし」にするときは clear_total_limit
    per_member_limit: StrictInt | None = None
    clear_total_limit: bool = False
    clear_per_member_limit: bool = False
    target_kind: StrictStr | None = None      # all | category | product
    target_ids: list[StrictStr] | None = None


def _targets(db: Session, kind: str | None, ids: list[str] | None) -> list[tuple[int, str | None]] | None:
    if kind is None:
        return None
    if kind not in TARGETS:
        raise AppError("ERR-1004", {"field": "target_kind"})
    if kind == "all":
        return [(cd.TARGET_ALL, None)]
    ids = sorted({i.strip().upper() for i in (ids or []) if i.strip()})
    if not ids:
        raise AppError("ERR-1001", {"field": "target_ids"})
    table, col = ("category", "category_code") if kind == "category" else ("product", "product_code")
    found = {r[0] for r in db.execute(text(f"SELECT {col} FROM {table} WHERE {col} IN :ids")
                                      .bindparams(bindparam("ids", expanding=True)), {"ids": ids}).all()}
    if set(ids) - found:
        raise AppError("ERR-1004", {"field": "target_ids", "unknown": sorted(set(ids) - found)})
    return [(TARGETS[kind], i) for i in ids]


def _row(db: Session, code: str) -> dict | None:
    r = db.execute(text("SELECT * FROM coupon WHERE coupon_code = :c"), {"c": code}).first()
    return dict(r._mapping) if r else None


def _view(db: Session, c: dict) -> dict:
    ts = [dict(t._mapping) for t in db.execute(
        text("SELECT target_kind, target_id FROM coupon_target WHERE coupon_code = :c ORDER BY id"),
        {"c": c["coupon_code"]}).all()]
    kind = "all" if not ts or any(t["target_kind"] == cd.TARGET_ALL for t in ts) else \
        ("category" if ts[0]["target_kind"] == cd.TARGET_CATEGORY else "product")
    return {"coupon_code": c["coupon_code"], "name": c["name"],
            "discount_type": "rate" if int(c["discount_type"]) == cd.TYPE_RATE else "amount",
            "discount_value": int(c["discount_value"]),
            "start_at": c["start_at"].strftime("%Y-%m-%dT%H:%M"), "end_at": c["end_at"].strftime("%Y-%m-%dT%H:%M"),
            "min_amount": int(c["min_amount"]), "total_limit": c["total_limit"], "used_count": int(c["used_count"]),
            "per_member_limit": c["per_member_limit"], "target_kind": kind,
            "target_ids": [t["target_id"] for t in ts if t["target_id"]]}


@router.get("")
def list_coupons(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    _guard(operator, write=False)
    rows = [dict(r._mapping) for r in db.execute(text("SELECT * FROM coupon ORDER BY start_at DESC, coupon_code")).all()]
    cats = [dict(r._mapping) for r in db.execute(text(
        "SELECT category_code AS code, name, parent_code FROM category ORDER BY sort_no, category_code")).all()]
    return {"data": {"coupons": [_view(db, c) for c in rows], "categories": cats}}


@router.post("")
def create_coupon(body: CouponBody, db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    _guard(operator, write=True)
    code = (body.coupon_code or "").strip().upper()
    if not code:
        raise AppError("ERR-1001", {"field": "coupon_code"})
    if not cd.COUPON_CODE_RE.match(code):
        raise AppError("ERR-1002", {"field": "coupon_code"})          # ★20文字以内の半角英数大文字（6.3）
    for f in ("name", "discount_type", "discount_value", "start_at", "end_at"):
        if getattr(body, f) is None:
            raise AppError("ERR-1001", {"field": f})
    if body.discount_type not in TYPES:
        raise AppError("ERR-1004", {"field": "discount_type"})
    start, end = _dt(body.start_at, "start_at"), _dt(body.end_at, "end_at")
    vals = dict(name=body.name, discount_type=TYPES[body.discount_type], discount_value=body.discount_value,
                start_at=start, end_at=end, min_amount=body.min_amount or 0,
                total_limit=body.total_limit, per_member_limit=body.per_member_limit)
    bad = cd.coupon_input_error(**vals)
    if bad:
        raise _field(bad)
    targets = _targets(db, body.target_kind or "all", body.target_ids)
    n = db.execute(text(
        "INSERT IGNORE INTO coupon (coupon_code, name, discount_type, discount_value, start_at, end_at, "
        "  min_amount, total_limit, used_count, per_member_limit) "
        "VALUES (:c, :name, :discount_type, :discount_value, :start_at, :end_at, :min_amount, :total_limit, 0, "
        "        :per_member_limit)"), {**vals, "c": code, "name": body.name.strip()}).rowcount
    if not n:
        db.rollback()
        raise AppError("ERR-1216", {"field": "coupon_code"})
    for k, t in targets:
        db.execute(text("INSERT INTO coupon_target (coupon_code, target_kind, target_id) VALUES (:c, :k, :t)"),
                   {"c": code, "k": k, "t": t})
    db.execute(text("INSERT INTO operation_log (operator_id, target, action) VALUES (:p, :t, :a)"),
               {"p": operator["operator_id"], "t": f"coupon/{code}", "a": "AP-B32 作成"})
    db.commit()
    applog.emit("admin.coupon_created")
    return {"data": _view(db, _row(db, code))}


@router.patch("/{coupon_code}")
def patch_coupon(coupon_code: str, body: CouponBody, db: Session = Depends(get_db),
                 operator=Depends(current_operator)) -> dict:
    """★注文ずみの金額は変わらない（割引額は注文に保存してある。BR-17）。★上限は使われた回数より小さくできない。"""
    _guard(operator, write=True)
    cur = _row(db, coupon_code)
    if not cur:
        raise AppError("ERR-1215")
    if body.coupon_code is not None and body.coupon_code.strip().upper() != coupon_code:
        raise AppError("ERR-1004", {"field": "coupon_code", "reason": "not_allowed"})
    if body.discount_type is not None and body.discount_type not in TYPES:
        raise AppError("ERR-1004", {"field": "discount_type"})
    new = {
        "name": body.name.strip() if body.name is not None else cur["name"],
        "discount_type": TYPES[body.discount_type] if body.discount_type else int(cur["discount_type"]),
        "discount_value": body.discount_value if body.discount_value is not None else int(cur["discount_value"]),
        "start_at": _dt(body.start_at, "start_at") or cur["start_at"],
        "end_at": _dt(body.end_at, "end_at") or cur["end_at"],
        "min_amount": body.min_amount if body.min_amount is not None else int(cur["min_amount"]),
        "total_limit": None if body.clear_total_limit else (body.total_limit if body.total_limit is not None else cur["total_limit"]),
        "per_member_limit": None if body.clear_per_member_limit else (
            body.per_member_limit if body.per_member_limit is not None else cur["per_member_limit"]),
    }
    bad = cd.coupon_input_error(**new, used_count=int(cur["used_count"]))
    if bad:
        raise _field(bad)
    targets = _targets(db, body.target_kind, body.target_ids)
    db.execute(text("UPDATE coupon SET name = :name, discount_type = :discount_type, discount_value = :discount_value, "
                    "  start_at = :start_at, end_at = :end_at, min_amount = :min_amount, total_limit = :total_limit, "
                    "  per_member_limit = :per_member_limit WHERE coupon_code = :c"), {**new, "c": coupon_code})
    if targets is not None:
        db.execute(text("DELETE FROM coupon_target WHERE coupon_code = :c"), {"c": coupon_code})
        for k, t in targets:
            db.execute(text("INSERT INTO coupon_target (coupon_code, target_kind, target_id) VALUES (:c, :k, :t)"),
                       {"c": coupon_code, "k": k, "t": t})
    db.execute(text("INSERT INTO operation_log (operator_id, target, action) VALUES (:p, :t, :a)"),
               {"p": operator["operator_id"], "t": f"coupon/{coupon_code}", "a": "AP-B32 編集"})
    db.commit()
    return {"data": _view(db, _row(db, coupon_code))}
