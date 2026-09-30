# -*- coding: utf-8 -*-
"""返品（AP-401・AP-402・AP-B24〜B30。設計 4.2・4.3・6.5）。R-31。

★客の側（/returns）
  会員は自分の注文、ゲストは照会（AP-306）を通った1件だけ（N-27）。
  ★判定は api/orders._order_for_viewer の1か所（詳細・キャンセル・再決済と同じ。返品申請も状態を変える操作）。

★運営の側（/admin/returns）
  権限は要件 2.4 の行そのまま（F-507・F-503a〜e・F-504。★近い機能の行で代用しない。10.2.11c）。
  倉庫の「自拠点」は返送先の倉庫（BR-19）。★拠点を指定する引数は持たせない（N-28a）。

★入っていないもの（設計 4.5 ⑦）
  返金額・期限の判定結果・送料の負担の判定は、画面から送らせない。
  ★申請は SKU ではなく注文明細の行番号で指定する。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictInt, StrictStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from api import money_back
from api.orders import _order_for_viewer, _order_url
from core import applog
from core.db import get_db
from core.deps import current_operator, require_internal_auth, session_id
from core.errors import AppError
from domain import authz
from domain import returns as rd
from domain.authz import Role
from repository import returns as repo

router = APIRouter(prefix="/returns", tags=["returns"], dependencies=[Depends(require_internal_auth)])
admin_router = APIRouter(prefix="/admin/returns", tags=["admin-returns"],
                         dependencies=[Depends(require_internal_auth)])


def _err(db: Session, e: ValueError) -> AppError:
    db.rollback()
    return AppError(str(e) if str(e).startswith("ERR-") else "ERR-1205")


def _url_of(db: Session, order_no: str) -> str:
    o = db.execute(text("SELECT member_id FROM orders WHERE order_no = :o"), {"o": order_no}).first()
    return _order_url({"member_id": o.member_id if o else None}, order_no)


def _customer_view(r: dict) -> dict:
    """★客に見せるもの。検品した人の名前・運営者IDは出さない。"""
    st = int(r["status"])
    return {
        "return_no": r["return_no"], "order_no": r["order_no"], "status": st,
        "status_label": rd.STATUS_LABEL[st], "applied_at": str(r["applied_at"]),
        "reject_reason": r["reject_reason"] if st == rd.REJECTED else None,
        "return_deadline": str(r["return_deadline"]) if r.get("return_deadline") else None,
        "return_fee_bearer": rd.FEE_BEARER_LABEL[int(r["return_fee_bearer"])] if st != rd.APPLIED else None,
        "refund_total": int(r["refund_total"]) if st == rd.REFUNDED else None,
        "shipping_refund": int(r["shipping_refund"]) if st == rd.REFUNDED else None,
        "lines": [{"line_no": int(l["line_no"]), "sku_code": l["sku_code"], "product_name": l["product_name"],
                   "color_name": l["color_name"], "size_name": l["size_name"], "qty": int(l["qty"]),
                   "reason": rd.REASON_LABEL[int(l["reason_kind"])], "reason_text": l["reason_text"],
                   # ★検品の結果は、検品済になってから見せる（途中の1明細だけの結果で客を迷わせない）
                   "inspect_result": ({rd.PASS: "合格", rd.FAIL: "不合格"}.get(l["inspect_result"])
                                      if st in (rd.INSPECTED, rd.REFUNDED) else None),
                   "inspect_note": l["inspect_note"] if st in (rd.INSPECTED, rd.REFUNDED) else None,
                   "refund_amount": int(l["refund_amount"]) if st == rd.REFUNDED else None}
                  for l in r["lines"]],
    }


# ============================================================
# AP-401  返品申請（F-502）
# ============================================================
class ReturnLineIn(BaseModel):
    line_no: StrictInt
    qty: StrictInt


class ReturnBody(BaseModel):
    order_no: StrictStr
    lines: list[ReturnLineIn]      # ★SKUではなく注文明細の行番号で指定する（設計 4.5 ⑦）
    reason_code: StrictStr         # size | image | defect | wrong_item | other
    reason_text: StrictStr | None = None


@router.post("")
def apply_return(body: ReturnBody, db: Session = Depends(get_db),
                 sid: str | None = Depends(session_id)) -> dict:
    """★出力に返金額を入れない。検品が終わるまで確定しないため（設計 4.5 ⑦）。"""
    _order_for_viewer(db, sid, body.order_no)       # ★会員は自分の注文、ゲストは照会を通った1件（N-27）
    bad = rd.reason_error(body.reason_code, body.reason_text)
    if bad:
        raise AppError(bad[0], {"field": bad[1]})
    nos = [l.line_no for l in body.lines]
    if len(nos) != len(set(nos)):
        raise AppError("ERR-1004", {"field": "lines"})          # 同じ明細を2回書いた
    try:
        no = repo.apply(db, order_no=body.order_no, asked={l.line_no: l.qty for l in body.lines},
                        reason_kind=rd.REASONS[body.reason_code], reason_text=body.reason_text)
    except ValueError as e:
        raise _err(db, e)
    applog.emit("return.applied", order_no=body.order_no)
    return {"data": {"return_no": no, "status": "applied"}}


# ============================================================
# AP-402  返品申請の状態（F-507。客）
# ============================================================
@router.get("")
def my_returns(db: Session = Depends(get_db), sid: str | None = Depends(session_id)) -> dict:
    """会員は自分の注文ぶん全部、ゲストは照会を通った1件ぶん。"""
    from repository import auth as auth_repo

    row = auth_repo.load_session(db, sid)
    if row is None or (not row.get("member_id") and not row.get("guest_order_no")):
        raise AppError("ERR-1101")
    if row.get("member_id") and row["user_kind"] == auth_repo.USER_MEMBER:
        orders = [r.order_no for r in db.execute(
            text("SELECT order_no FROM orders WHERE member_id = :m"), {"m": row["member_id"]}).all()]
    else:
        orders = [row["guest_order_no"]]
    return {"data": {"returns": [{**x, "status_label": rd.STATUS_LABEL[int(x["status"])],
                                  "applied_at": str(x["applied_at"]),
                                  "refunded_at": str(x["refunded_at"]) if x["refunded_at"] else None,
                                  "qty": int(x["qty"])}
                                 for x in repo.list_for_orders(db, orders)]}}


@router.get("/{return_no}")
def my_return(return_no: str, db: Session = Depends(get_db), sid: str | None = Depends(session_id)) -> dict:
    r = repo.get(db, return_no)
    if not r:
        raise AppError("ERR-1215")
    _order_for_viewer(db, sid, r["order_no"])       # ★他人の申請は 404（在ることを教えない）
    return {"data": _customer_view(r)}


# ============================================================
# 運営：権限と「自拠点」
# ============================================================
def _guard(operator: dict, feature: str, *, write: bool) -> Role:
    role = Role(int(operator["role"]))
    ok = authz.can_write(role, feature) if write else authz.can_read(role, feature)
    if not ok:
        raise AppError("ERR-1102", {"feature": feature})
    return role


def _own_site(db: Session, operator: dict, role: Role, feature: str) -> None:
    """★自拠点の役割（倉庫）は、返送先の倉庫のアカウントだけ（BR-19・N-28a）。"""
    if authz.is_site_scoped(role, feature):
        wh = repo.return_warehouse(db)["location_code"]
        if operator["location_code"] != wh:
            raise AppError("ERR-1106", {"location_code": wh})


def _visible_to_warehouse(r: dict) -> bool:
    """F-507「倉庫スタッフには返送待ちと受領のものだけ見せる」＋ 在庫に戻していない合格品（F-504）。"""
    st = int(r["status"])
    if st in (rd.AWAITING, rd.RECEIVED):
        return True
    return st in (rd.INSPECTED, rd.REFUNDED) and any(
        l["inspect_result"] == rd.PASS and l["restocked_at"] is None for l in r["lines"])


def _can(role: Role, feature: str) -> bool:
    return authz.can_write(role, feature)


# ============================================================
# AP-B24  返品申請の一覧（F-507）
# ============================================================
@admin_router.get("")
def list_returns(db: Session = Depends(get_db), operator=Depends(current_operator),
                 status: int | None = None, return_no: str | None = None, order_no: str | None = None,
                 date_from: str | None = None, date_to: str | None = None) -> dict:
    role = _guard(operator, "F-507", write=False)
    wh_view = authz.is_site_scoped(role, "F-507")
    if wh_view:
        _own_site(db, operator, role, "F-507")
    if status is not None and status not in rd.STATUS_LABEL:
        raise AppError("ERR-1004", {"field": "status"})
    rows, counts = repo.list_admin(db, statuses=[status] if status else None,
                                   return_no=(return_no or "").strip() or None,
                                   order_no=(order_no or "").strip() or None,
                                   date_from=date_from or None, date_to=date_to or None,
                                   warehouse_view=wh_view)
    return {"data": {
        "scope": "warehouse" if wh_view else "all",
        # ★状態ごとの件数を先頭に出す（F-507）。★0件の状態も並べる（無い状態を画面が推測しない）
        "counts": [{"status": s, "label": rd.STATUS_LABEL[s], "count": counts.get(s, 0)}
                   for s in rd.STATUS_LABEL
                   if not wh_view or s in (rd.AWAITING, rd.RECEIVED, rd.INSPECTED, rd.REFUNDED)],
        "returns": [{**x, "status_label": rd.STATUS_LABEL[int(x["status"])], "applied_at": str(x["applied_at"]),
                     "qty": int(x["qty"]), "restock_pending": int(x["restock_pending"])} for x in rows],
    }}


@admin_router.get("/{return_no}")
def get_return(return_no: str, db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-507", write=False)
    r = repo.get(db, return_no)
    if not r:
        raise AppError("ERR-1215")
    if authz.is_site_scoped(role, "F-507"):
        _own_site(db, operator, role, "F-507")
        if not _visible_to_warehouse(r):
            raise AppError("ERR-1215")
    st = int(r["status"])
    lines = r["lines"]
    wh = repo.return_warehouse(db)
    return {"data": {
        "return_no": r["return_no"], "order_no": r["order_no"], "status": st,
        "status_label": rd.STATUS_LABEL[st], "applied_at": str(r["applied_at"]),
        "orderer_name": r["orderer_name"],
        "orderer_email": r["orderer_email"] if role in (Role.ADMIN, Role.SUPPORT, Role.ORDER) else None,
        "reject_reason": r["reject_reason"], "decided_at": str(r["decided_at"]) if r["decided_at"] else None,
        "return_deadline": str(r["return_deadline"]) if r["return_deadline"] else None,
        "return_fee_bearer": int(r["return_fee_bearer"]),
        "return_fee_bearer_label": rd.FEE_BEARER_LABEL[int(r["return_fee_bearer"])],
        "received_at": str(r["received_at"]) if r["received_at"] else None, "receiver": r["receiver"],
        "refund_total": int(r["refund_total"]), "shipping_refund": int(r["shipping_refund"]),
        "refunded_at": str(r["refunded_at"]) if r["refunded_at"] else None,
        "warehouse": {"location_code": wh["location_code"], "name": wh["name"]},
        "lines": [{"line_no": int(l["line_no"]), "sku_code": l["sku_code"], "product_name": l["product_name"],
                   "color_name": l["color_name"], "size_name": l["size_name"], "qty": int(l["qty"]),
                   "line_qty": int(l["line_qty"]), "unit_price": int(l["unit_price"]),
                   "reason": rd.REASON_LABEL[int(l["reason_kind"])], "reason_text": l["reason_text"],
                   "inspect_result": l["inspect_result"], "inspect_note": l["inspect_note"],
                   "inspected_at": str(l["inspected_at"]) if l["inspected_at"] else None,
                   "inspector": l["inspector"], "disposal": l["disposal"],
                   "disposal_label": rd.DISPOSAL_LABEL.get(l["disposal"]) if l["disposal"] else None,
                   "refund_amount": int(l["refund_amount"]),
                   "restocked_at": str(l["restocked_at"]) if l["restocked_at"] else None,
                   "restocker": l["restocker"]} for l in lines],
        # ★返金額の確認（F-503d「返金額を確認し」）。検品済のときだけ。★書かない計算
        "refund_preview": repo.refund_preview(db, return_no) if st == rd.INSPECTED and _can(role, "F-503d") else None,
        # ★ボタンを出す条件。★表示の親切であって、判定は各 POST が自分でする（4.1.2）
        "can": {
            "approve": st == rd.APPLIED and _can(role, "F-503a"),
            "reject": st == rd.APPLIED and _can(role, "F-503a"),
            "receive": st == rd.AWAITING and _can(role, "F-503b"),
            "inspect": st == rd.RECEIVED and _can(role, "F-503c"),
            "restock": st in (rd.INSPECTED, rd.REFUNDED) and _can(role, "F-504")
                       and any(l["inspect_result"] == rd.PASS and l["restocked_at"] is None for l in lines),
            "disposal": st in (rd.INSPECTED, rd.REFUNDED) and _can(role, "F-503e")
                        and any(l["inspect_result"] == rd.FAIL and l["disposal"] is None for l in lines),
            "refund": st == rd.INSPECTED and _can(role, "F-503d"),
        },
    }}


# ============================================================
# AP-B25  承認・却下（F-503a）
# ============================================================
class ApproveBody(BaseModel):
    fee_bearer: StrictStr            # customer | company（★判定はシステムがせず、サポートが選ぶ。6.5.3）


class RejectBody(BaseModel):
    reason: StrictStr                # ★自由入力。却下の条件はコード化しない（BR-18a）


@admin_router.post("/{return_no}/approve")
def approve(return_no: str, body: ApproveBody, db: Session = Depends(get_db),
            operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-503a", write=True)
    if body.fee_bearer not in rd.FEE_BEARER:
        raise AppError("ERR-1004", {"field": "fee_bearer"})
    r = repo.get(db, return_no)
    if not r:
        raise AppError("ERR-1215")
    try:
        res = repo.approve(db, return_no=return_no, fee_bearer=rd.FEE_BEARER[body.fee_bearer],
                           operator_id=operator["operator_id"], order_url=_url_of(db, r["order_no"]))
    except ValueError as e:
        raise _err(db, e)
    return {"data": res}


@admin_router.post("/{return_no}/reject")
def reject(return_no: str, body: RejectBody, db: Session = Depends(get_db),
           operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-503a", write=True)
    reason = body.reason.strip()
    if not reason:
        raise AppError("ERR-1001", {"field": "reason"})
    if len(reason) > 200:
        raise AppError("ERR-1003", {"field": "reason"})
    r = repo.get(db, return_no)
    if not r:
        raise AppError("ERR-1215")
    try:
        res = repo.reject(db, return_no=return_no, reason=reason, operator_id=operator["operator_id"],
                          order_url=_url_of(db, r["order_no"]))
    except ValueError as e:
        raise _err(db, e)
    return {"data": res}


# ============================================================
# AP-B26  受領（F-503b）／AP-B30  在庫戻入（F-504）
# ============================================================
class StaffBody(BaseModel):
    staff_name: StrictStr            # ★拠点のアカウントは共有なので、誰がやったかを手入力（2.4）


def _staff(body: StaffBody) -> str:
    s = body.staff_name.strip()
    if not s:
        raise AppError("ERR-1001", {"field": "staff_name"})
    if len(s) > 50:
        raise AppError("ERR-1003", {"field": "staff_name"})
    return s


@admin_router.post("/{return_no}/receive")
def receive(return_no: str, body: StaffBody, db: Session = Depends(get_db),
            operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-503b", write=True)
    _own_site(db, operator, role, "F-503b")
    staff = _staff(body)
    try:
        return {"data": repo.receive(db, return_no=return_no, staff_name=staff,
                                     operator_id=operator["operator_id"])}
    except ValueError as e:
        raise _err(db, e)


@admin_router.post("/{return_no}/restock")
def restock(return_no: str, body: StaffBody, db: Session = Depends(get_db),
            operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-504", write=True)
    _own_site(db, operator, role, "F-504")
    staff = _staff(body)
    try:
        return {"data": repo.restock(db, return_no=return_no, staff_name=staff,
                                     operator_id=operator["operator_id"])}
    except ValueError as e:
        raise _err(db, e)


# ============================================================
# AP-B27  検品（F-503c）
# ============================================================
class InspectLine(BaseModel):
    line_no: StrictInt
    result: StrictStr                # pass | fail
    note: StrictStr | None = None


class InspectBody(BaseModel):
    staff_name: StrictStr
    lines: list[InspectLine]


@admin_router.post("/{return_no}/inspect")
def inspect(return_no: str, body: InspectBody, db: Session = Depends(get_db),
            operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-503c", write=True)
    _own_site(db, operator, role, "F-503c")
    staff = _staff(StaffBody(staff_name=body.staff_name))
    if not body.lines:
        raise AppError("ERR-1001", {"field": "lines"})
    out = []
    for l in body.lines:
        if l.result not in ("pass", "fail"):
            raise AppError("ERR-1004", {"field": "result"})
        note = (l.note or "").strip()
        if len(note) > 200:
            raise AppError("ERR-1003", {"field": "note"})
        if l.result == "fail" and not note:
            # ★不合格は理由が要る（F-503c「合格・不合格と理由」。MSG-08 で客に伝える。9.10）
            raise AppError("ERR-1001", {"field": "note"})
        out.append({"line_no": l.line_no, "result": rd.PASS if l.result == "pass" else rd.FAIL,
                    "note": note or None})
    if len({x["line_no"] for x in out}) != len(out):
        raise AppError("ERR-1004", {"field": "lines"})
    try:
        return {"data": repo.inspect(db, return_no=return_no, results=out, staff_name=staff,
                                     operator_id=operator["operator_id"])}
    except ValueError as e:
        raise _err(db, e)


# ============================================================
# AP-B28  不合格品の処分指示（F-503e）
# ============================================================
class DisposalLine(BaseModel):
    line_no: StrictInt
    disposal: StrictStr              # return | discard


class DisposalBody(BaseModel):
    lines: list[DisposalLine]


@admin_router.post("/{return_no}/disposal")
def disposal(return_no: str, body: DisposalBody, db: Session = Depends(get_db),
             operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-503e", write=True)
    if not body.lines:
        raise AppError("ERR-1001", {"field": "lines"})
    if any(l.disposal not in rd.DISPOSAL for l in body.lines):
        raise AppError("ERR-1004", {"field": "disposal"})
    choices = {l.line_no: rd.DISPOSAL[l.disposal] for l in body.lines}
    if len(choices) != len(body.lines):
        raise AppError("ERR-1004", {"field": "lines"})
    try:
        return {"data": repo.disposal(db, return_no=return_no, choices=choices,
                                      operator_id=operator["operator_id"])}
    except ValueError as e:
        raise _err(db, e)


# ============================================================
# AP-B29  返金の実行（F-503d）
# ============================================================
@admin_router.post("/{return_no}/refund")
def refund(return_no: str, db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    """★入力は空。返金額を画面から送らせない（サーバが保存済みの按分から計算する。4.5）。"""
    _guard(operator, "F-503d", write=True)
    r = repo.get(db, return_no)
    if not r:
        raise AppError("ERR-1215")
    try:
        res = repo.refund(db, return_no=return_no, operator_id=operator["operator_id"],
                          order_url=_url_of(db, r["order_no"]))
    except ValueError as e:
        raise _err(db, e)
    sent = money_back.send_now(db, [res["tx_id"]])     # ★外で1回だけ。だめなら B-09 が拾う
    applog.emit("return.refunded", order_no=r["order_no"])
    return {"data": {**res, "sent": sent}}
