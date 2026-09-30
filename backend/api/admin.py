# -*- coding: utf-8 -*-
"""運営者の認証と権限（AP-B01・B06・B07。設計 4.3・要件 2.4・N-28・N-28a）。

★この串で作るのは「入口と関所」まで。出荷指示・発送記録の中身は R-22。
  ここが無いと ⑦⑧ に進めない、という順番の話（R-21 の前提）。

★2つ、絶対に外さないところ。

  ① APIが自分で判定する（4.1.2・SEC-703）
     画面がボタンを隠すかどうかとは無関係。curl で直接叩かれる前提で書く。

  ② 自拠点のみの役割には、拠点を指定する引数をそもそも持たせない（N-28a・SEC-701）
     ★「渡された拠点が自分のものか確かめる」ではなく「受け取らない」。
       確かめる形だと、確かめ忘れた1本のAPIから全部漏れる。
"""
from __future__ import annotations

from datetime import datetime, time as _time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, StrictInt, StrictStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from core import applog, security
from core.db import get_db
from core.deps import current_operator, require_internal_auth, session_id
from core.errors import AppError
from domain import authz, password as pw, shipping, shipping_date as sd
from domain.authz import Perm, Role
from external import mailer
from payment import gateway
from api import money_back
from domain.allocation import AllocationFailed, Candidate, MAX_LOCATIONS, allocate, build_updates
from domain.allocation import OrderLine as AllocLine
from repository import auth as repo, shipment as ship_repo
from repository import cancellation as cancel_repo, order as order_repo
from testing import fault

router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_internal_auth)])


def _as_time(v) -> _time:
    """MySQL の TIME は timedelta で返る。★time に直す（ここで1か所だけ吸収する）。"""
    if isinstance(v, _time):
        return v
    total = int(v.total_seconds())
    return _time(total // 3600, (total % 3600) // 60, total % 60)


def _src_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _guard(operator: dict, feature: str, *, write: bool) -> Role:
    """2.4 の権限表で判定する。★判定は domain/authz.py（DBを立てずに全通り試せる）。"""
    role = Role(int(operator["role"]))
    allowed = authz.can_write(role, feature) if write else authz.can_read(role, feature)
    if not allowed:
        raise AppError("ERR-1102", {"feature": feature})
    return role


# ============================================================
# AP-B01  運営者ログイン
# ============================================================
class AdminLoginBody(BaseModel):
    email: EmailStr
    password: StrictStr


@router.post("/auth/login")
def admin_login(body: AdminLoginBody, request: Request, db: Session = Depends(get_db)) -> dict:
    """★会員と同じ制限をかける（F-1301・N-22〜26）。

    ★客のログインAPI（AP-502）では運営者に入れない。
      あちらは member テーブルしか見ないので、運営者のアドレスは「未登録」になる（SEC-706）。
    """
    ip = _src_ip(request)
    email = pw.normalize_email(str(body.email))

    if repo.ip_rate_exceeded(db, ip):
        security.verify_dummy(body.password)
        raise AppError("ERR-1104")

    op = repo.find_operator_by_email(db, email)
    if op is None:
        security.verify_dummy(body.password)          # ★時間をそろえる（N-26）
        repo.record_ip_failure(db, ip)
        repo.record_auth_event(db, event_kind=repo.EV_LOGIN_NG, src_ip=ip)
        raise AppError("ERR-1104")

    locked = repo.is_locked(op, datetime.now())
    ok = security.verify_password(body.password, op["password_hash"])
    if locked or not ok or not op["is_active"]:
        if not locked:
            repo.record_failure(db, repo.USER_OPERATOR, op["operator_id"])
        repo.record_ip_failure(db, ip)
        repo.record_auth_event(db, event_kind=repo.EV_LOCK if locked else repo.EV_LOGIN_NG,
                               operator_id=op["operator_id"], src_ip=ip)
        raise AppError("ERR-1104")

    repo.record_success(db, repo.USER_OPERATOR, op["operator_id"])
    new_sid = security.new_session_id()               # ★再発行（N-24・SEC-308）
    repo.create_session(db, session_id=new_sid, user_kind=repo.USER_OPERATOR,
                        operator_id=op["operator_id"])
    db.commit()
    repo.record_auth_event(db, event_kind=repo.EV_LOGIN_OK,
                           operator_id=op["operator_id"], src_ip=ip)
    applog.emit("operator.login")
    # ★役割と所属拠点は返す。画面の出し分けに使ってよい。
    #   ただし★判定はサーバで行う。画面が隠すことを権限の代わりにしない（4.1.2）
    return {"data": {"session_id": new_sid, "operator_id": op["operator_id"],
                     "name": op["name"], "role": int(op["role"]),
                     "location_code": op["location_code"]}}


@router.post("/auth/logout")
def admin_logout(db: Session = Depends(get_db), sid: str | None = Depends(session_id)) -> dict:
    n = repo.delete_session(db, sid) if sid else 0
    applog.emit("operator.logout", count=n)
    return {"data": {"logged_out": True}}


@router.get("/me")
def admin_me(operator=Depends(current_operator)) -> dict:
    return {"data": {"operator_id": operator["operator_id"], "name": operator["name"],
                     "role": int(operator["role"]), "location_code": operator["location_code"]}}


# ============================================================
# AP-B06  在庫一覧（F-801）
# ============================================================
@router.get("/stocks")
def list_stocks(db: Session = Depends(get_db), operator=Depends(current_operator),
                sku_code: str | None = None) -> dict:
    """★拠点を指定する引数を持たせていない（N-28a・SEC-701）。

    ★倉庫・店舗は自分の拠点しか見えない。「見せない」のではなく「絞る引数が無い」。
      引数があると、うっかり通す枝が1本でもできた時点で漏れる。
    """
    role = _guard(operator, "F-801", write=False)
    loc = authz.effective_location(role, "F-801", operator["location_code"], None)

    # ★販売可能数も返す（FR-801。在庫数・引当済数・販売可能数の3つ）。
    #   ★SQLで引き算しない——UNSIGNED 同士だと ERROR 1690（3.2.2 ①）。
    #     GREATEST で床を 0 にしてから引く形にする
    sql = ("SELECT location_code, sku_code, section, qty, reserved_qty, "
           "       GREATEST(CAST(qty AS SIGNED) - CAST(reserved_qty AS SIGNED), 0) AS saleable_qty "
           "  FROM stock WHERE 1=1")
    params: dict = {}
    if loc is not None:
        sql += " AND location_code = :loc"
        params["loc"] = loc
    if sku_code:
        sql += " AND sku_code = :sku"
        params["sku"] = sku_code
    sql += " ORDER BY location_code, sku_code LIMIT 100"
    rows = db.execute(text(sql), params).all()
    return {"data": {"scope": loc or "all", "stocks": [dict(r._mapping) for r in rows]}}


# ============================================================
# AP-B07  在庫の修正（F-802）
# ============================================================
class StockPatchBody(BaseModel):
    qty: StrictInt
    reason: StrictStr
    # ★location_code をここに置かない（N-28a）。下の関数の引数にもしない


@router.patch("/stocks/{location_code}/{sku_code}/{section}")
def patch_stock(location_code: str, sku_code: str, section: int, body: StockPatchBody,
                db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    """★URLに拠点が出るが、自拠点のみの役割は自分の拠点しか通らない（SEC-701）。

    ★一覧（B-06）と違い、修正はどの行かをURLで指す必要があるので拠点が出る。
      そこで effective_location が「指定 ≠ 自拠点」なら ERR-1106 を投げる。
      ★見えないものは書けない、を1か所で決めている。
    """
    role = _guard(operator, "F-802", write=True)
    try:
        authz.effective_location(role, "F-802", operator["location_code"], location_code)
    except ValueError:
        raise AppError("ERR-1106", {"location_code": location_code})

    if body.qty < 0:
        raise AppError("ERR-1003", {"field": "qty"})

    # ★引当済数を下回る値にはしない（8.2 ERR-1208・9.9）。R-27 で気づいて足した。
    #   条件付きUPDATEにして、読んでから書くまでに引当が入っても下回らないようにする
    n = db.execute(
        text("UPDATE stock SET qty = :q "
             " WHERE location_code = :loc AND sku_code = :sku AND section = :sec "
             "   AND reserved_qty <= :q"),
        {"q": body.qty, "loc": location_code, "sku": sku_code, "sec": section},
    ).rowcount
    if n == 0:
        exists = db.execute(
            text("SELECT reserved_qty FROM stock "
                 " WHERE location_code = :loc AND sku_code = :sku AND section = :sec"),
            {"loc": location_code, "sku": sku_code, "sec": section},
        ).first()
        db.rollback()
        if exists is None:
            raise AppError("ERR-1215")
        raise AppError("ERR-1208", {"field": "qty", "reserved_qty": int(exists.reserved_qty)})
    # ★誰が・何を・なぜ を残す（T-13a・N-14）
    db.execute(
        text("INSERT INTO operation_log (operator_id, target, action) VALUES (:o, :t, :a)"),
        {"o": operator["operator_id"],
         "t": f"stock/{location_code}/{sku_code}/{section}",
         "a": f"qty={body.qty} reason={body.reason[:60]}"},
    )
    db.commit()
    applog.emit("admin.stock_patched")
    return {"data": {"updated": True}}


# ============================================================
# AP-B10  注文一覧（F-901）。★参照だけの役割と、—— の役割を分けて確かめるため
# ============================================================
@router.get("/orders")
def list_orders(db: Session = Depends(get_db), operator=Depends(current_operator),
                status: int | None = None, order_no: str | None = None,
                orderer_email: str | None = None, limit: int = 50) -> dict:
    """AP-B10 注文一覧（F-901）。★状態・注文番号・メールアドレスで絞れる（R-25 ⑦）。"""
    _guard(operator, "F-901", write=False)

    sql = ("SELECT order_no, status, total_amount, created_at, orderer_name, orderer_email "
           "  FROM orders WHERE 1=1")
    params: dict = {"lim": max(1, min(limit, 100))}
    if status is not None:
        sql += " AND status = :st"
        params["st"] = status
    if order_no:
        sql += " AND order_no = :no"
        params["no"] = order_no
    if orderer_email:
        # ★メールアドレスは完全一致にする。部分一致にすると、
        #   運営の画面から会員のアドレスを総当たりで引けてしまう（N-15 と同じ考え方）
        sql += " AND orderer_email = :em"
        params["em"] = orderer_email
    sql += " ORDER BY created_at DESC LIMIT :lim"
    rows = db.execute(text(sql), params).all()
    return {"data": {"orders": [dict(r._mapping) for r in rows]}}


class MemoBody(BaseModel):
    body: StrictStr


@router.post("/orders/{order_no}/memos")
def add_memo(order_no: str, body: MemoBody, db: Session = Depends(get_db),
             operator=Depends(current_operator)) -> dict:
    """AP-B18 対応メモ（F-908）。★運用管理者・受注担当・サポートは「可」。倉庫・店舗は「—」。

    ★R-29 で直した。これまで F-901（注文一覧。運用管理者とサポートは「参照」）で判定していたので、
      2.4 で「可」のはずの運用管理者とサポートが 403 になっていた。
    ★追記だけ。直さない・消さない（対応の履歴なので、あとから書き換えられると意味がない）。
    """
    _guard(operator, "F-908", write=True)
    text_ = body.body.strip()
    if not text_:
        raise AppError("ERR-1001", {"field": "body"})
    if len(text_) > 500:
        raise AppError("ERR-1003", {"field": "body", "max": 500})
    if not db.execute(text("SELECT 1 FROM orders WHERE order_no = :o"), {"o": order_no}).first():
        raise AppError("ERR-1215")
    db.execute(text("INSERT INTO order_memo (order_no, operator_id, body) VALUES (:o, :p, :b)"),
               {"o": order_no, "p": operator["operator_id"], "b": text_})
    db.commit()
    applog.emit("admin.memo_added", order_no=order_no)
    return {"data": {"added": True}}


# ============================================================
# AP-B12  出荷指示の作成（F-903a。設計 6.3）
# ============================================================
@router.post("/orders/{order_no}/shipping-instructions")
def create_shipping_instructions(order_no: str, db: Session = Depends(get_db),
                                 operator=Depends(current_operator)) -> dict:
    """引当拠点ごとに出荷（E-24）と出荷明細（E-25）を作る（F-903a）。

    ★中身は定期処理（B-13）とまったく同じ関数（repository/shipment.instruct）。
      ★R-34 で B-13 を足したとき、ここを「手で押す例外用の入口」にした。
        入口が2つあっても、条件と発送予定日の決め方を書くのは1か所だけ（10.2.6）。
    ★先に B-13 が作っていたら ERR-1205（条件付きUPDATEが0件。やり直さない）。
    """
    _guard(operator, "F-903a", write=True)
    try:
        shipments = ship_repo.instruct(db, order_no, operator_id=operator["operator_id"])
    except ValueError as e:
        raise _value_error(db, e)
    applog.emit("admin.shipping_instructed", order_no=order_no, count=len(shipments))
    return {"data": {"order_no": order_no, "shipment_ids": [s["id"] for s in shipments],
                     "shipments": shipments}}


# ============================================================
# AP-B19  出荷一覧（F-805）
# ============================================================
@router.get("/shipments")
def list_shipments(db: Session = Depends(get_db), operator=Depends(current_operator),
                   status: int | None = None, order_no: str | None = None) -> dict:
    """★拠点を指定する引数を持たせていない（N-28a・SEC-701）。

    倉庫・店舗は自分の拠点ぶんだけ。「見せない」のではなく「絞る引数が無い」。
    """
    role = _guard(operator, "F-805", write=False)
    loc = authz.effective_location(role, "F-805", operator["location_code"], None)
    rows = ship_repo.list_shipments(db, location_code=loc, status=status, order_no=(order_no or "").strip() or None)
    lines = ship_repo.lines_for(db, [int(r["id"]) for r in rows])
    return {"data": {"scope": loc or "all",
                     "shipments": [{**r, "planned_ship_date": str(r["planned_ship_date"]),
                                    "lines": lines.get(int(r["id"]), []),
                                    "shipped_at": str(r["shipped_at"]) if r["shipped_at"] else None}
                                   for r in rows]}}


# ============================================================
# AP-B20  発送の記録（F-805。★設計 6.3.1）
# ============================================================
class ShipBody(BaseModel):
    carrier: StrictStr | None = None
    tracking_no: StrictStr | None = None
    # ★拠点のアカウントは共有なので、誰がやったかを画面で手入力させる（2.4・8.6）
    staff_name: StrictStr


@router.post("/shipments/{shipment_id}/ship")
def ship(shipment_id: int, body: ShipBody, db: Session = Depends(get_db),
         operator=Depends(current_operator)) -> dict:
    """6.3.1。★順序が効く。

        【1つのトランザクション】手順1 在庫を減らす → 2 出荷を出荷済に
                                 → 3 注文の状態を導出し直す → 4 売上確定を「要実行」で積む
        【コミット】
        【外】手順5 売上確定を送る → 6 発送通知を積む

    ★手順4を先に書く。後回しにすると手順5の直前で落ちたとき何も残らない。
      出荷は「出荷済」なのに売上確定が送られず、しかも誰も気づけない。
    """
    role = _guard(operator, "F-805", write=True)

    sh = ship_repo.get_shipment(db, shipment_id)
    if not sh:
        raise AppError("ERR-1215")
    # ★自拠点のものだけ（N-28a・SEC-702）
    try:
        authz.effective_location(role, "F-805", operator["location_code"],
                                 sh["from_location_code"])
    except ValueError:
        raise AppError("ERR-1106", {"from_location_code": sh["from_location_code"]})

    if int(sh["status"]) != shipping.SHIP_INSTRUCTED:
        raise AppError("ERR-1205", {"status": int(sh["status"])})

    # ★客の住所宛は追跡番号が必須、取り置きは空でよい（E-24）
    if shipping.tracking_required(int(sh["dest_kind"])) and not body.tracking_no:
        raise AppError("ERR-1001", {"field": "tracking_no"})

    order = db.execute(
        text("SELECT order_no, total_amount, orderer_name, orderer_email "
             "  FROM orders WHERE order_no = :o"),
        {"o": sh["order_no"]},
    ).first()

    # 分割出荷のときの金額（6.3.1）。
    #   ★明細は「明細金額 − 割引の按分」（6.3.1 ①。R-26）。
    #   ★送料は「最初に確定する出荷」に載せる（6.3.1 ②。R-27）。
    #     「最初か」は record_shipment の中で、注文の行をロックしてから数える——
    #     2つの出荷を同時に発送したとき、両方が「最初」と読んで送料を2回取らないため。
    this_items = sum(int(x["unit_price"]) * int(x["qty"]) - int(x["allocated_discount"])
                     for x in ship_repo.shipment_lines(db, shipment_id))

    # ★手順6の本文はここで組み立て、トランザクションの中で積む（下の record_shipment）。
    #   ★「積む」は自分のDBへの書き込みなので、外に出す理由が無い。
    #     外に置くと、コミット直後に落ちたときに発送通知だけが永久に消える（R-22）。
    mail_body = chr(10).join([
        f"{order.orderer_name} 様", "", "ご注文の商品を発送しました。", "",
        f"注文番号：{sh['order_no']}",
        f"配送会社：{body.carrier or '-'}",
        f"追跡番号：{body.tracking_no or '（店舗でのお受け取りです）'}",
    ])

    try:
        res = ship_repo.record_shipment(
            db, shipment_id=shipment_id, carrier=body.carrier, tracking_no=body.tracking_no,
            staff_name=body.staff_name, operator_id=operator["operator_id"],
            this_items_after_discount=this_items, order_no=sh["order_no"],
            mail_to=str(order.orderer_email), mail_subject="商品を発送しました",
            mail_body=mail_body,
        )
    except ValueError as e:
        raise AppError(str(e))

    # ★★ここから先はトランザクションの外（6.3.1・9.4）
    # AP-T08。★「コミットの直後に1回だけ落ちる」を起こせるようにする（IT-407）
    fault.fire(db, "after_ship_commit")

    ok, code = False, None
    try:
        fault.fire(db, "capture_send")       # IT-408。手順5だけを失敗させる
        g = gateway.capture(provider_tx_id=str(res["provider_tx_id"] or ""),
                            amount=int(res["amount"]),
                            idempotency_key=res["idempotency_key"],
                            reference=f"shipment:{shipment_id}")
        ok, code = g.approved, g.response_code
    except (gateway.GatewayError, fault.InjectedFault) as e:
        ok, code = False, getattr(e, "kind", "INJECTED")
    ship_repo.finish_capture(db, res["tx_id"], ok=ok, response_code=code)

    # ★手順6（MSG-06）はコミットの中で積み終わっている。送るのは B-11（7.3。串の⑨）
    applog.emit("admin.shipped", order_no=sh["order_no"])
    return {"data": {"shipment_id": shipment_id, "order_status": res["order_status"],
                     "capture": {"amount": res["amount"], "sent": ok, "response_code": code}}}


# ============================================================
# AP-B11  注文詳細（F-902）。★明細・金額・状態・出荷が1画面（R-25 ⑦）
# ============================================================
@router.get("/orders/{order_no}")
def admin_order_detail(order_no: str, db: Session = Depends(get_db),
                       operator=Depends(current_operator)) -> dict:
    """運営が1件の注文を1画面で見る。

    ★客側の注文詳細（AP-305）と分けてある。見せるものが違う——
      運営には注文者・届け先・出荷元拠点・状態の履歴が要る。
    """
    _guard(operator, "F-901", write=False)

    o = db.execute(
        text("SELECT order_no, status, ordered_at, member_id, orderer_name, orderer_email, "
             "       receive_method, ship_name, ship_zip, ship_pref_code, ship_address, ship_tel, "
             "       item_total, discount_amount, shipping_fee, tax_amount, total_amount, "
             "       coupon_code "
             "  FROM orders WHERE order_no = :o"),
        {"o": order_no},
    ).first()
    if not o:
        raise AppError("ERR-1215")

    lines = db.execute(
        text("SELECT ol.line_no, ol.sku_code, ol.qty, ol.unit_price, ol.allocated_discount, "
             "       ol.alloc_status, ol.alloc_location_code, p.name AS product_name "
             "  FROM order_line ol "
             "  JOIN sku s ON s.sku_code = ol.sku_code "
             "  JOIN product p ON p.product_code = s.product_code "
             " WHERE ol.order_no = :o ORDER BY ol.line_no"),
        {"o": order_no},
    ).all()
    ships = db.execute(
        text("SELECT id, from_location_code, dest_kind, dest_name, status, planned_ship_date, "
             "       carrier, tracking_no, staff_name, shipped_at, "
             "       short_actual_qty, short_reporter, short_at "
             "  FROM shipment WHERE order_no = :o ORDER BY id"),
        {"o": order_no},
    ).all()
    logs = db.execute(
        text("SELECT status_from, status_to, changed_by, reason, created_at "
             "  FROM order_status_log WHERE order_no = :o ORDER BY id"),
        {"o": order_no},
    ).all()
    txs = db.execute(
        text("SELECT tx_kind, status, amount, response_code, shipment_id FROM payment_tx "
             " WHERE order_no = :o ORDER BY id"),
        {"o": order_no},
    ).all()
    memos = db.execute(
        text("SELECT m.id, m.body, m.created_at, m.operator_id, o.name AS operator_name "
             "  FROM order_memo m LEFT JOIN operator o ON o.operator_id = m.operator_id "
             " WHERE m.order_no = :o ORDER BY m.id DESC"),
        {"o": order_no},
    ).all()
    ship_lines: dict[int, list[int]] = {}
    for r in db.execute(text("SELECT shipment_id, line_no FROM shipment_line "
                             " WHERE order_no = :o ORDER BY shipment_id, line_no"),
                        {"o": order_no}).all():
        ship_lines.setdefault(int(r.shipment_id), []).append(int(r.line_no))
    has_short = any(int(r.status) == shipping.SHIP_SHORT for r in ships)

    return {"data": {
        "order_no": o.order_no, "status": int(o.status), "ordered_at": str(o.ordered_at),
        "member_id": o.member_id, "orderer_name": o.orderer_name,
        "orderer_email": o.orderer_email, "receive_method": int(o.receive_method),
        "ship_to": {"name": o.ship_name, "zip": o.ship_zip, "pref_code": o.ship_pref_code,
                    "address": o.ship_address, "tel": o.ship_tel},
        "item_total": int(o.item_total), "discount_amount": int(o.discount_amount),
        "shipping_fee": int(o.shipping_fee), "tax_amount": int(o.tax_amount),
        "total_amount": int(o.total_amount), "coupon_code": o.coupon_code,
        "lines": [{"line_no": int(r.line_no), "sku_code": r.sku_code,
                   "product_name": r.product_name, "qty": int(r.qty),
                   "unit_price": int(r.unit_price),
                   "allocated_discount": int(r.allocated_discount),
                   "alloc_status": int(r.alloc_status),
                   "alloc_location_code": r.alloc_location_code} for r in lines],
        "shipments": [{"id": int(r.id), "from_location_code": r.from_location_code,
                       "dest_kind": int(r.dest_kind), "dest_name": r.dest_name,
                       "status": int(r.status),
                       "planned_ship_date": str(r.planned_ship_date),
                       "carrier": r.carrier, "tracking_no": r.tracking_no,
                       "staff_name": r.staff_name,
                       "shipped_at": str(r.shipped_at) if r.shipped_at else None,
                       "short_actual_qty": r.short_actual_qty,
                       "short_reporter": r.short_reporter,
                       "short_at": str(r.short_at) if r.short_at else None,
                       "line_nos": ship_lines.get(int(r.id), [])}
                      for r in ships],
        # ★ボタンを出す条件はサーバが決める。API が受ける条件と同じ関数から取る（IT-101・102）
        # ★対応メモ（F-908）。新しい順。書けるかはサーバが返す（2.4）
        "memos": [{"id": int(m.id), "body": m.body, "at": str(m.created_at),
                   "operator_id": m.operator_id, "operator_name": m.operator_name} for m in memos],
        "can_add_memo": authz.can_write(Role(int(operator["role"])), "F-908"),
        "actions": {"cancel": shipping.can_cancel(int(o.status)),
                    "reallocate": has_short, "partial_cancel": has_short},
        "status_log": [{"from": r.status_from, "to": r.status_to, "by": r.changed_by,
                        "reason": r.reason, "at": str(r.created_at)} for r in logs],
        "payments": [{"tx_kind": int(r.tx_kind), "status": int(r.status),
                      "amount": int(r.amount), "response_code": r.response_code,
                      "shipment_id": r.shipment_id}
                     for r in txs],
    }}


# ============================================================
# ★R-26  欠品 → 再引当 → 部分キャンセルと返金／注文のキャンセル
#   DBの書き込みは repository/cancellation.py の1か所。ここは入口と関所だけ（10.2.6）
# ============================================================


def _value_error(db: Session, e: ValueError) -> AppError:
    db.rollback()
    return AppError(str(e) if str(e).startswith("ERR-") else "ERR-1205")


class ShortageLine(BaseModel):
    line_no: StrictInt
    actual_qty: StrictInt


class ShortageBody(BaseModel):
    lines: list[ShortageLine]
    staff_name: StrictStr        # ★共有アカウントなので担当者名は手入力（2.4・8.6）
    reason: StrictStr


# AP-B21  欠品の報告（F-805・BR-04a・設計 6.4）
@router.post("/shipments/{shipment_id}/shortage")
def report_shortage(shipment_id: int, body: ShortageBody, db: Session = Depends(get_db),
                    operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-805", write=True)
    sh = ship_repo.get_shipment(db, shipment_id)
    if not sh:
        raise AppError("ERR-1215")
    try:                                       # ★自拠点の出荷だけ（N-28a・SEC-702）
        authz.effective_location(role, "F-805", operator["location_code"],
                                 sh["from_location_code"])
    except ValueError:
        raise AppError("ERR-1106", {"from_location_code": sh["from_location_code"]})
    if not body.staff_name.strip():
        raise AppError("ERR-1001", {"field": "staff_name"})
    if not body.reason.strip():
        raise AppError("ERR-1001", {"field": "reason"})
    if any(l.actual_qty < 0 for l in body.lines):
        raise AppError("ERR-1003", {"field": "actual_qty"})
    try:
        res = cancel_repo.report_shortage(
            db, shipment_id=shipment_id,
            actual={l.line_no: l.actual_qty for l in body.lines},
            reporter=body.staff_name.strip(), reason=body.reason.strip(),
            operator_id=operator["operator_id"])
    except ValueError as e:
        raise _value_error(db, e)
    applog.emit("admin.shortage_reported", order_no=res["order_no"])
    return {"data": res}


# AP-B15  再引当（F-912）
@router.post("/orders/{order_no}/reallocate")
def reallocate(order_no: str, db: Session = Depends(get_db),
               operator=Depends(current_operator)) -> dict:
    """欠品の出荷の明細を、他拠点へ引き当て直す。

    ★候補を選ぶのはメモリ、書くのは1つのトランザクション（6.2 と同じ形）。
    ★引き当てられなければ何も書かない。★自動でキャンセルしない（6.4 手順5・9.3）。
      受注担当が画面で「部分キャンセルと返金」（AP-B16）を選ぶ。
    """
    _guard(operator, "F-912", write=True)
    head = cancel_repo.order_head(db, order_no)
    if not head:
        raise AppError("ERR-1215")
    shorts = cancel_repo.short_shipments(db, order_no)
    if not shorts:
        raise AppError("ERR-1205", {"reason": "欠品の出荷が無い"})

    order = db.execute(text("SELECT ship_pref_code FROM orders WHERE order_no = :o"),
                       {"o": order_no}).first()
    lines = [l for sh in shorts for l in sh["lines"]]
    short_locs = {sh["from_location_code"] for sh in shorts}
    cands = [c for c in order_repo.allocation_candidates(
                 db, order_no, sorted({l["sku_code"] for l in lines}), order.ship_pref_code)
             # ★欠品を報告した拠点には戻さない
             if c["location_code"] not in short_locs]
    try:
        assigns = allocate(
            [AllocLine(int(l["line_no"]), l["sku_code"], int(l["qty"])) for l in lines],
            [Candidate(c["sku_code"], c["location_code"], int(c["kind"]), int(c["step"]),
                       int(c["qty"]), int(c["reserved_qty"])) for c in cands])
    except AllocationFailed:
        return {"data": {"reallocated": False, "order_no": order_no,
                         "reason": "他の拠点にも在庫がありません", "next": "partial-cancel"}}

    # ★BR-07。生きている出荷の拠点と合わせて2か所まで
    locs = cancel_repo.live_locations(db, order_no) | {a.location_code for a in assigns}
    if len(locs) > MAX_LOCATIONS:
        return {"data": {"reallocated": False, "order_no": order_no,
                         "reason": "出荷元が3か所以上になります（BR-07）",
                         "next": "partial-cancel"}}

    dest = shorts[0]
    now = datetime.now()
    plans = []
    for loc_code in sorted({a.location_code for a in assigns}):
        loc = ship_repo.location_calendar(db, loc_code)
        cal = sd.LocationCalendar.from_bitmask(
            int(loc["business_days"]), _as_time(loc["cutoff_time"]), loc["holidays"])
        planned = sd.planned_ship_date(now, cal)       # ★作成時に確定（BR-23）
        if planned is None:
            raise AppError("ERR-1205", {"reason": f"{loc_code} の営業日設定が不正"})
        plans.append({
            "from_location_code": loc_code, "dest_kind": int(dest["dest_kind"]),
            "dest_name": dest["dest_name"], "dest_zip": dest["dest_zip"],
            "dest_pref_code": dest["dest_pref_code"], "dest_address": dest["dest_address"],
            "dest_tel": dest["dest_tel"], "planned_ship_date": planned,
            "lines": [{"line_no": a.line_no, "qty": a.qty}
                      for a in assigns if a.location_code == loc_code]})
    try:
        res = cancel_repo.apply_reallocation(
            db, order_no=order_no, short_ids=[int(sh["id"]) for sh in shorts],
            updates=[{"location_code": u.location_code, "sku_code": u.sku_code,
                      "add_qty": u.add_qty} for u in build_updates(assigns)],
            assignments=[{"line_no": a.line_no, "location_code": a.location_code, "qty": a.qty}
                         for a in assigns],
            plans=plans, operator_id=operator["operator_id"])
    except ValueError as e:
        raise _value_error(db, e)
    if res is None:
        # ★条件付きUPDATEが0件＝選んだあとで横から取られた。やり直さない（6.2.2）
        return {"data": {"reallocated": False, "order_no": order_no,
                         "reason": "在庫が他の注文に引き当てられました。もう一度お試しください",
                         "next": "retry"}}
    applog.emit("admin.reallocated", order_no=order_no, count=len(res["new_shipments"]))
    return {"data": {"reallocated": True, **res,
                     "shipments": [{"from_location_code": p["from_location_code"],
                                    "planned_ship_date": str(p["planned_ship_date"]),
                                    "lines": [l["line_no"] for l in p["lines"]]}
                                   for p in plans]}}


# AP-B16  欠品分の部分キャンセルと返金（F-911・BR-21a・BR-17d）
@router.post("/orders/{order_no}/partial-cancel")
def partial_cancel(order_no: str, db: Session = Depends(get_db),
                   operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-911", write=True)
    try:
        res = cancel_repo.partial_cancel(db, order_no=order_no,
                                         operator_id=operator["operator_id"])
    except ValueError as e:
        raise _value_error(db, e)
    # ★★ここから外。積んだ取消・返金を1回だけ送ってみる。だめなら B-09
    res["sent"] = money_back.send_now(db, [x["tx_id"] for x in res["cancelled"]])
    applog.emit("admin.partial_cancelled", order_no=order_no, count=len(res["cancelled"]))
    return {"data": res}


# AP-B14  注文のキャンセル（F-904・BR-17f）
@router.post("/orders/{order_no}/cancel")
def admin_cancel(order_no: str, db: Session = Depends(get_db),
                 operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-904", write=True)
    try:
        res = cancel_repo.cancel_order(db, order_no=order_no,
                                       by=cancel_repo.CHANGED_BY_OPERATOR,
                                       operator_id=operator["operator_id"],
                                       reason="AP-B14 運営によるキャンセル")
    except ValueError as e:
        raise _value_error(db, e)
    res["sent"] = money_back.send_now(db, [res["void_tx_id"]])
    applog.emit("admin.order_cancelled", order_no=order_no)
    return {"data": res}
