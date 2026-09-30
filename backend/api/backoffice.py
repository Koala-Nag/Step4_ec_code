# -*- coding: utf-8 -*-
"""販売設定（AP-B33・F-308・FT-01）と、運営者による会員の照会（AP-B31・F-609）。R-33。

★どちらも「要求（FR）を持たない機能」で、受け入れテストから落ちていた（R-33 の依頼）。

販売設定
  ★版を重ねる（T-30）。直に UPDATE しない。適用開始日を過去にできない。
  ★再デプロイなしで効く（NFR-11）。値はプロセスに持たず、使う処理が毎回 DB から読む。
  ★確定した注文は変わらない（BR-17。注文に金額を保存してある）。

会員の照会
  ★参照だけ。会員情報を直す口は作らない（要件 2.4 の下の注記）。
  ★パスワードは返さない（ハッシュも）。メールアドレスは完全一致で探す（F-901 と同じ理由。部分一致は総当たりで引ける）。
"""
from __future__ import annotations


from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from core import applog
from core.db import get_db
from core.deps import current_operator, require_internal_auth
from core.errors import AppError
from domain import authz
from domain import settings as sd
from domain.authz import Role
from repository import settings as repo

router = APIRouter(prefix="/admin", tags=["admin-backoffice"], dependencies=[Depends(require_internal_auth)])


def _guard(operator: dict, feature: str, *, write: bool) -> Role:
    role = Role(int(operator["role"]))
    ok = authz.can_write(role, feature) if write else authz.can_read(role, feature)
    if not ok:
        raise AppError("ERR-1102", {"feature": feature})
    return role


def _plain(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k == "tax_rate":
            out[k] = f"{v:.3f}"
        elif k in ("effective_from",):
            out[k] = str(v)
        elif k in ("notice_from", "notice_to"):
            out[k] = v.strftime("%Y-%m-%dT%H:%M") if v else None
        else:
            out[k] = v
    return out


# ============================================================
# AP-B33  販売設定（F-308・FT-01）
# ============================================================
@router.get("/sales-config")
def get_sales_config(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-308", write=False)
    cur = repo.current(db)
    today = db.execute(text("SELECT CURDATE() d")).first().d
    vs = repo.versions(db)
    return {"data": {
        "today": str(today),
        "current": _plain(cur),
        # ★まだ効いていない版（適用開始日が未来）。いま効いている版と並べて見せる
        "scheduled": [_plain(v) for v in vs if v["effective_from"] > today],
        "history": [_plain(v) for v in vs if v["effective_from"] <= today],
        "fields": [{"name": f.name, "label": f.label, "kind": f.kind, "min": f.min, "max": f.max, "unit": f.unit, "used": f.used}
                   for f in sd.FIELDS],
        "can_edit": authz.can_write(role, "F-308"),
    }}


class SalesConfigBody(BaseModel):
    model_config = {"extra": "allow"}         # ★列ごとの検査は domain/settings.parse が1か所でやる


@router.put("/sales-config")
def put_sales_config(body: SalesConfigBody, db: Session = Depends(get_db),
                     operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-308", write=True)
    today = db.execute(text("SELECT CURDATE() d")).first().d
    values, bad = sd.parse(body.model_dump(), today)
    if bad:
        field, _, why = bad.partition(":")
        code = {"empty": "ERR-1001", "format": "ERR-1002"}.get(why, "ERR-1003")
        raise AppError(code, {"field": field, "reason": why})
    before = repo.current(db)
    added = repo.save_version(db, values, by=operator["operator_id"])
    applog.emit("admin.sales_config_saved")
    return {"data": {"effective_from": str(values["effective_from"]), "added": added,
                     "effective_now": values["effective_from"] <= today,
                     "changed": sd.changed(before, values)}}


# ============================================================
# AP-B31  会員の照会（F-609）
# ============================================================
STATUS_LABEL = {1: "有効", 2: "ロック", 3: "退会済"}


@router.get("/members")
def search_members(db: Session = Depends(get_db), operator=Depends(current_operator),
                   email: str | None = None, name: str | None = None, member_id: str | None = None) -> dict:
    _guard(operator, "F-609", write=False)
    email, name, member_id = (email or "").strip(), (name or "").strip(), (member_id or "").strip().upper()
    if not (email or name or member_id):
        # ★条件なしで全件は出さない（照会であって名簿の閲覧ではない）
        return {"data": {"members": [], "searched": False}}
    where, p = [], {}
    if email:
        where.append("m.email = :e"); p["e"] = email          # ★完全一致
    if member_id:
        where.append("m.member_id = :id"); p["id"] = member_id
    if name:
        where.append("m.name LIKE :n"); p["n"] = "%" + name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = db.execute(text(
        "SELECT m.member_id, m.email, m.name, m.status, m.created_at, "
        "       (SELECT COUNT(*) FROM orders o WHERE o.member_id = m.member_id) AS order_count "
        f"  FROM member m WHERE {' AND '.join(where)} ORDER BY m.member_id LIMIT 50"), p).all()
    return {"data": {"searched": True, "members": [
        {"member_id": r.member_id, "email": r.email, "name": r.name, "status": int(r.status),
         "status_label": STATUS_LABEL.get(int(r.status), "—"), "created_at": str(r.created_at)[:10],
         "order_count": int(r.order_count)} for r in rows]}}


@router.get("/members/{member_id}")
def member_detail(member_id: str, db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-609", write=False)
    # ★password_hash は SELECT に書かない（うっかり返さないように、読まない）
    m = db.execute(text(
        "SELECT member_id, email, name, tel, shop_member_id, status, locked_until, created_at, updated_at "
        "  FROM member WHERE member_id = :id"), {"id": member_id}).first()
    if not m:
        raise AppError("ERR-1215")
    orders = db.execute(text(
        "SELECT order_no, ordered_at, status, total_amount, receive_method FROM orders "
        " WHERE member_id = :id ORDER BY ordered_at DESC LIMIT 100"), {"id": member_id}).all()
    addrs = db.execute(text(
        "SELECT name, zip, pref_code, address, tel FROM address WHERE member_id = :id ORDER BY id"),
        {"id": member_id}).all()
    return {"data": {
        "member_id": m.member_id, "email": m.email, "name": m.name, "tel": m.tel, "shop_member_id": m.shop_member_id,
        "status": int(m.status), "status_label": STATUS_LABEL.get(int(m.status), "—"),
        "locked_until": str(m.locked_until) if m.locked_until else None,
        "created_at": str(m.created_at)[:16], "updated_at": str(m.updated_at)[:16],
        "addresses": [dict(a._mapping) for a in addrs],
        "orders": [{"order_no": o.order_no, "ordered_at": str(o.ordered_at)[:16], "status": int(o.status),
                    "total_amount": int(o.total_amount), "receive_method": int(o.receive_method)} for o in orders],
        "can_open_order": authz.can_read(Role(int(operator["role"])), "F-901"),
    }}


# ============================================================
# AP-T02  定期処理の手動実行（FT-02。R-35）
# ============================================================
@router.get("/batches")
def list_batches(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    """定期処理の一覧と、いまのロックの状態（6.6.1）。★運用管理者だけ。"""
    from batch import lock as block
    from batch import scheduler

    _guard(operator, "F-308", write=False)
    out = []
    for j in scheduler.JOBS:
        st = block.state(db, j.batch_id) or {}
        out.append({"batch_id": j.batch_id, "note": j.note, "every_seconds": j.every_seconds,
                    "status": int(st.get("status") or 0), "holder": st.get("holder"),
                    "acquired_at": str(st["acquired_at"]) if st.get("acquired_at") else None})
    return {"data": {"scheduler": scheduler.enabled(), "batches": out}}


@router.post("/batches/{batch_id}/run")
def run_batch(batch_id: str, operator=Depends(current_operator)) -> dict:
    """★スケジューラと同じ関数を呼ぶ（10.2.6）。手で押しても、条件を書くのは1か所。

    ★FT-01・FT-02 は本番でも使える（要件 4.11）。権限は運用管理者だけ。
    """
    from batch import scheduler

    _guard(operator, "F-308", write=True)
    if batch_id not in scheduler.BY_ID:
        raise AppError("ERR-1215")
    res = scheduler.run_once(batch_id)
    applog.emit("batch.manual_run", batch_id=batch_id, count=res.processed)
    # ★ran=False は「他が動いていた」。異常ではない（6.6.1）
    return {"data": {"batch_id": batch_id, "ran": res.ran, "processed": res.processed,
                     "notes": res.notes}}
