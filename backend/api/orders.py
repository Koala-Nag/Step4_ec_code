# -*- coding: utf-8 -*-
"""AP-301 注文作成 / AP-301a 与信・引当 / AP-302 再決済（設計 4.2・6.1.2・7.2.2a）。

★3段に分ける。1つのトランザクションにできない（6.1.2）。
    ① 注文作成            短いトランザクション1つ。ここで必ずコミット
    ② 与信                ★外部通信。トランザクションの外（要件 9.4）
    ③ 引当                短いトランザクション1つ。行ロックを握るのはここだけ

★金額も冪等キーも「注文の決済取引の行」から取る。本文からは取らない（7.2.2a ③・N-35）。
★ブラウザが持ち帰った認証結果は「入力」であって判定ではない（7.2.2）。
  正は、その値を添えて決済代行に与信を投げた結果。
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, EmailStr, StrictStr
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from api.schemas import (
    ErrorResponse,
    OrderCreatedResponse,
    OrderResultResponse,
)
from core.config import FRONTEND_BASE_URL
from core.db import get_db
from core.deps import current_member, cart_key as cart_key_header
from core.deps import require_internal_auth, session_id
from core.errors import AppError
from domain.allocation import (
    AllocationFailed,
    Candidate,
    OrderLine as DomainLine,
    allocate,
    build_updates,
)
from domain import coupon as coupon_domain, refund as refund_domain, shipping
from domain.pricing import CartLine, DeliveryType, summarize
from external import mailer
from payment import gateway
from repository import cart as cart_repo
from repository import coupon as coupon_repo
from repository import order as repo
from repository import cancellation as cancel_repo
from api import money_back

router = APIRouter(prefix="/orders", tags=["orders"])

RECEIVE_SHIP = 1
RECEIVE_PICKUP = 2


class ShipTo(BaseModel):
    name: StrictStr
    zip: StrictStr
    pref_code: StrictStr
    address: StrictStr
    tel: StrictStr


class CreateOrder(BaseModel):
    """★total も unit_price も定義しない。

    足されても入る場所が無い（N-35・SEC-401）。金額はサーバがカートから計算し直す。
    """

    orderer_name: StrictStr
    orderer_email: StrictStr
    delivery_type: StrictStr = DeliveryType.SHIP
    ship_to: ShipTo
    # ★割引額はここで受け取らない。コードだけ。額はサーバが決める（N-35・BR-16）
    coupon_code: StrictStr | None = None


class AuthorizeBody(BaseModel):
    """★auth_result は「入力」。判定には使わない（7.2.2）。

    ★amount も idempotency_key も定義しない。決済取引の行から取る（7.2.2a ③）。
    """

    auth_result: StrictStr | None = None
    auth_ref: StrictStr | None = None


# ============================================================
# 状態が変わったことを客に知らせる（FR-1204・設計 7.3・8.5）
#   ★積むだけ。送るのは B-11（7.3）。ここで送らない
#   ★MSG-02（注文確定）と MSG-06（発送）は既にある。足りていなかったのは下の3つ
# ============================================================
def _unavailable_items(db: Session, order_no: str) -> list[dict]:
    """引き当てられなかった明細を、客の言葉で返せる形にする（FR-1202）。

    ★「条件付きUPDATEが0件」は内部の言い方。そのまま客に出さない（5.4）。
      どの商品かが分からないと、客は次に何をすればいいか決められない。
    """
    rows = db.execute(
        text("SELECT ol.line_no, ol.sku_code, ol.qty, p.name AS product_name, "
             "       c.name AS color_name, z.name AS size_name "
             "  FROM order_line ol "
             "  JOIN sku s   ON s.sku_code = ol.sku_code "
             "  JOIN product p ON p.product_code = s.product_code "
             "  LEFT JOIN color c ON c.color_code = s.color_code "
             "  LEFT JOIN size  z ON z.size_code  = s.size_code "
             " WHERE ol.order_no = :o AND ol.alloc_status <> 1 "
             " ORDER BY ol.line_no"),
        {"o": order_no},
    ).all()
    return [{"line_no": int(r.line_no), "sku_code": r.sku_code, "qty": int(r.qty),
             "product_name": r.product_name, "color_name": r.color_name,
             "size_name": r.size_name} for r in rows]


def _item_label(i: dict) -> str:
    parts = [i["product_name"]]
    if i.get("color_name") or i.get("size_name"):
        parts.append(f"（{i.get('color_name') or ''} {i.get('size_name') or ''}".strip() + "）")
    return "".join(parts)


def _mail_awaiting_pay(db: Session, order: dict, order_no: str, reason: str) -> None:
    """MSG-03 支払い待ち。★再決済のURLを載せる（7.3）。"""
    mailer.enqueue(
        db, msg_kind="MSG-03", to_email=str(order["orderer_email"]),
        subject="お支払いの確認が必要です",
        body=chr(10).join([
            f"{order['orderer_name']} 様", "",
            "ご注文のお支払いを確認できませんでした。",
            "お手数ですが、下記から改めてお手続きください。", "",
            f"注文番号：{order_no}",
            f"支払総額：{int(order['total_amount']):,} 円", "",
            _order_url(order, order_no), "",
            "※ この時点では代金はいただいておりません。",
        ]),
    )


def _mail_cancelled(db: Session, order: dict, order_no: str, *, kind: str,
                    items: list[dict] | None = None) -> None:
    """MSG-04（引当できずに取り消し）。

    ★要件 4.4 の割り当て。MSG-04＝引当に失敗して取り消し／MSG-07＝客または受注担当が取り消し。
      R-25 では逆に積んでいた（R-26 で直した）。MSG-07 は repository/cancellation.py が積む。
    """
    if kind == "MSG-04":
        subject = "ご注文を承れませんでした"
        head = ["申し訳ありません。ご注文の商品をご用意できませんでした。",
                "ご注文は取り消しとなり、★代金はいただいておりません。"]
    else:
        subject = "ご注文をキャンセルしました"
        head = ["ご注文をキャンセルしました。"]

    lines = [f"{order['orderer_name']} 様", ""] + head + ["", f"注文番号：{order_no}"]
    if items:
        # ★どの商品かを書く（FR-1202）
        lines += ["", "ご用意できなかった商品："]
        lines += [f"　・{_item_label(i)} × {i['qty']}" for i in items]
    mailer.enqueue(db, msg_kind=kind, to_email=str(order["orderer_email"]),
                   subject=subject, body=chr(10).join(lines))


def _member_of(db: Session, sid: str | None) -> str | None:
    """そのセッションが会員なら会員ID、そうでなければ None。

    ★ここでは 401 にしない。ゲストでも注文できる（FR-311）。
      「ログインしているかどうか」を見るだけで、必須にはしない。
    """
    from repository import auth as auth_repo

    row = auth_repo.load_session(db, sid)
    if row and row["user_kind"] == auth_repo.USER_MEMBER:
        return row["member_id"]
    return None


def _order_for_viewer(db: Session, sid: str | None, order_no: str) -> tuple[dict, str]:
    """★その注文を、このセッションが見てよいか（N-27）。見てよいなら (注文, "member"|"guest")。

    会員   その注文の member_id が自分
    ゲスト 照会（AP-306）を通った注文番号が、セッションの guest_order_no と一致し、しかもゲストの注文
    ★詳細・キャンセル・再決済の3つとも、ここを通す（参照だけでなく状態を変える操作も毎回確認する。N-27）。
    ★見てよい相手でなければ 404（在ることを教えない。8.2 ERR-1215）。セッションが無ければ 401。
    """
    from repository import auth as auth_repo

    row = auth_repo.load_session(db, sid)
    if row is None or (not row.get("member_id") and not row.get("guest_order_no")):
        raise AppError("ERR-1101")
    head = db.execute(text("SELECT order_no, member_id FROM orders WHERE order_no = :o"),
                      {"o": order_no}).first()
    if head is None:
        raise AppError("ERR-1215")
    if row.get("member_id") and row["user_kind"] == auth_repo.USER_MEMBER \
            and head.member_id == row["member_id"]:
        return dict(head._mapping), "member"
    if row.get("guest_order_no") == order_no and head.member_id is None:
        return dict(head._mapping), "guest"
    raise AppError("ERR-1215")


def _order_url(order: dict, order_no: str) -> str:
    """メールに載せる注文のURL。★ゲストは照会画面（要件 4.3。MSG-02・MSG-03）。

    ★メールアドレスはURLに入れない（個人情報をクエリ文字列に置かない）。注文番号だけを入れておく。
    """
    if order.get("member_id"):
        return f"{FRONTEND_BASE_URL}/orders/{order_no}/detail"
    return f"{FRONTEND_BASE_URL}/orders/lookup?order_no={order_no}"


def _require_session(sid: str | None) -> str:
    if not sid:
        raise AppError("ERR-1101")
    return sid


def _amounts_from_cart(db: Session, cart_key: str, delivery_type: str,
                       coupon_code: str | None = None,
                       member_id: str | None = None) -> tuple[dict, list[dict]]:
    """★カートから計算し直す。画面から来た金額は使わない（N-35）。"""
    rows = cart_repo.list_lines(db, cart_key)
    if not rows:
        raise AppError("ERR-1207", {"reason": "カートが空"})
    # ★非公開になった商品は注文させない（F-705・R-27）。
    #   一覧・検索・詳細から消しても、カートに残っていれば買えてしまう——
    #   「片方だけ直すと、URLを直接叩けば見える」と同じ形の穴
    hidden = [r["sku_code"] for r in rows if not r.get("is_published", True)]
    if hidden:
        raise AppError("ERR-1207", {"reason": "unpublished", "sku_codes": hidden})

    cfg = cart_repo.sales_config(db)
    lines = [CartLine(r["sku_code"], int(r["unit_price"]), int(r["qty"])) for r in rows]

    # クーポン（BR-12・BR-16）。★ここで決めるのは割引額だけ。
    #   ★全体上限の先勝ちはここで判定しない——引当と同じトランザクションで、
    #     条件付きUPDATEの更新件数で決める（BR-16a・6.2.3・IT-413）
    discount = 0
    if coupon_code:
        c = coupon_repo.find(db, coupon_code)
        if c is None:
            raise AppError("ERR-1203", {"field": "coupon_code"})     # 存在しない（8.2）
        item_total_before = sum(l.unit_price * l.qty for l in lines)
        bad = coupon_domain.reason_unusable(
            c, item_total=item_total_before, now=datetime.now(),
            member_used=coupon_repo.member_used_count(db, coupon_code, member_id),
        )
        if bad:
            detail: dict = {"field": "coupon_code"}
            if bad == "ERR-1212":
                # ★「あと◯円のお買い上げで使えます」（要件 9.5）。不足額はサーバが出す
                detail["shortfall"] = int(c.min_amount) - item_total_before
            raise AppError(bad, detail)
        # ★BR-12。対象を限定したクーポンは、対象商品の明細金額の合計に適用する（カートと同じ関数。R-32）
        eligible = coupon_repo.eligible_total(db, coupon_code, [(l.sku_code, l.unit_price * l.qty) for l in lines])
        if eligible <= 0:
            raise AppError("ERR-1203", {"field": "coupon_code", "reason": "no_target"})
        discount = coupon_domain.discount_for(c, eligible)

    s = summarize(
        lines,
        delivery_type=delivery_type,
        discount=discount,
        fee=cfg["shipping_fee"],
        free_line=cfg["free_shipping_line"],
        tax_rate=cfg["tax_rate"],
    )

    # BR-21・6.5.2。★割引の按分は注文確定のときに1回だけ計算して保存する。
    #   ★返品のたびに割り直すと、3回に分けて申請したとき合計が1円ずれる（UT-502）
    allocated = refund_domain.allocate_discount(
        [refund_domain.Line(i, int(r["unit_price"]) * int(r["qty"]))
         for i, r in enumerate(rows, start=1)],
        s.discount,
    )
    by_line = {a.line_no: a.allocated_discount for a in allocated}
    out_lines = []
    for i, r in enumerate(rows, start=1):
        out_lines.append(
            {
                "line_no": i,
                "sku_code": r["sku_code"],
                "qty": int(r["qty"]),
                "unit_price": int(r["unit_price"]),
                "allocated_discount": by_line.get(i, 0),
            }
        )
    amounts = {
        "item_total": s.item_total,
        "discount": s.discount,
        "shipping_fee": s.shipping_fee,
        "tax_amount": s.tax_amount,
        "total_amount": s.total_amount,
        "tax_rate": Decimal(str(cfg["tax_rate"])),
    }
    return amounts, out_lines


@router.post(
    "",
    dependencies=[Depends(require_internal_auth)],
    response_model=OrderCreatedResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse},
               403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_order(
    body: CreateOrder,
    db: Session = Depends(get_db),
    sid: str | None = Depends(session_id),
    ckey: str | None = Depends(cart_key_header),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """AP-301。注文の作成と認証の開始。

    ★同じ Idempotency-Key で2回来たら、新しい与信を作らず1回目の注文番号を返す（IT-302）。
    """
    session = _require_session(sid)
    cart_key = _require_session(ckey)

    if not idempotency_key:
        # IT-303。冪等キーが無い呼び出しは受けない（N-40）
        raise AppError("ERR-1003", {"field": "Idempotency-Key"})

    # ★セッションと組にする。客のキーだけだと他人の注文番号が渡る（4.1.6a）
    gateway_key = repo.gateway_key_for(session, idempotency_key)

    # ★2回目はここで止まる。payment_tx も注文も増えない
    existing = repo.find_by_gateway_key(db, gateway_key)
    if existing:
        order = repo.get_order(db, existing["order_no"])
        return {
            "data": {
                "order_no": existing["order_no"],
                "total_amount": int(existing["amount"]),
                "status": int(order["status"]) if order else 0,
                "client_token": "",
                "three_ds_url": gateway.three_ds_url(
                    existing["order_no"],
                    f"{FRONTEND_BASE_URL}/orders/{existing['order_no']}/authorizing",
                ),
                "replayed": True,
            }
        }

    delivery = body.delivery_type if body.delivery_type in (
        DeliveryType.SHIP, DeliveryType.PICKUP) else DeliveryType.SHIP

    # ★ログイン中なら、その会員の注文としてひもづける（R-25 ①）。
    #   ★ゲストでも買える（FR-311）ので、セッションが会員でなければ None のまま。
    #   ★ここを入れ忘れていたので、購入履歴が永久に空だった（R-24 で見つけた）。
    #     会員あたりのクーポン上限（BR-16a）もこの値で数える。
    member_id = _member_of(db, sid)

    # ★クーポンは、カートに適用したもの（AP-204）を使う。本文の coupon_code は API から直接呼ぶときだけ。
    #   ★会員だけ（要件 4.3）。ゲストに使わせると、会員あたりの上限（BR-16a）を数える相手がいない
    applied = cart_repo.get_cart_coupon(db, cart_key)
    coupon_code = body.coupon_code or (applied["coupon_code"] if applied else None)
    if coupon_code and not member_id:
        raise AppError("ERR-1101", {"field": "coupon_code"})

    amounts, lines = _amounts_from_cart(db, cart_key, delivery, coupon_code, member_id)

    order_no = repo.new_order_no()
    repo.create_order(
        db,
        order_no=order_no,
        session_id=session,          # ★7.2.2a ①。作ったセッションを控える
        orderer_name=body.orderer_name,
        orderer_email=body.orderer_email,
        ship=body.ship_to.model_dump(),
        receive_method=RECEIVE_PICKUP if delivery == DeliveryType.PICKUP else RECEIVE_SHIP,
        amounts=amounts,
        lines=lines,
        gateway_key=gateway_key,
        coupon_code=coupon_code,
        member_id=member_id,
        cart_key=cart_key,
    )

    # トークン発行は決済取引にしない（7.2.1）。応答に載せて返すだけ
    try:
        token = gateway.issue_token(order_no, amounts["total_amount"])
    except gateway.GatewayError:
        token = ""

    return {
        "data": {
            "order_no": order_no,
            "total_amount": amounts["total_amount"],
            "status": repo.STATUS_AUTHENTICATING,
            "client_token": token,
            "three_ds_url": gateway.three_ds_url(
                order_no, f"{FRONTEND_BASE_URL}/orders/{order_no}/authorizing"
            ),
            "replayed": False,
        }
    }


@router.post(
    "/{order_no}/authorize",
    dependencies=[Depends(require_internal_auth)],
    response_model=OrderResultResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
               404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def authorize_order(
    order_no: str,
    body: AuthorizeBody,
    db: Session = Depends(get_db),
    sid: str | None = Depends(session_id),
) -> dict:
    """AP-301a。認証結果の中継と、与信 → 引当。"""
    session = _require_session(sid)

    order = repo.get_order(db, order_no)
    # ★7.2.2a ②。控えたセッションと同じ呼び出しだけを受ける。
    #   違えば 404 / ERR-1215。存在するかどうかも答えない（8.2）
    if order is None or order["origin_session_id"] != session:
        raise AppError("ERR-1215")

    if order["status"] not in (repo.STATUS_AUTHENTICATING,):
        raise AppError("ERR-1205", {"status": order["status"]})

    tx = repo.authorize_tx_of(db, order_no)
    if tx is None:
        raise AppError("ERR-1215")

    # ------------------------------------------------------------
    # ② 与信。★外部通信はトランザクションの外（要件 9.4・IT-501）
    #    金額も冪等キーも、この注文の決済取引の行から取る（7.2.2a ③）
    #
    # ★ここまでの SELECT で開いたトランザクションを、呼ぶ前に閉じる。
    #   行ロックを持っていなくても開いていることに変わりはなく、
    #   35秒待つあいだスナップショットが固定される（IT-501 で実際に見つけた）。
    # ------------------------------------------------------------
    repo.end_read_transaction(db)

    try:
        result = gateway.authorize(
            order_no=order_no,
            amount=int(tx["amount"]),              # ★本文の値ではない
            auth_ref=body.auth_ref,                # 入力。判定はしない（7.2.2）
            idempotency_key=str(tx["idempotency_key"]),
        )
    except gateway.GatewayError as e:
        # 応答不明・タイムアウトは「支払い待ち」（9.8）。★在庫は押さえない
        repo.set_status(db, order_no, order["status"], repo.STATUS_AWAITING_PAY,
                        f"AP-301a 与信の応答不明（{e.kind}）")
        cart_repo.remove_ordered(db, order_no)              # ★6.2.6 支払い待ち＝成立
        _mail_awaiting_pay(db, order, order_no, e.kind)     # ★MSG-03（R-25 ④）
        return {"data": {"order_no": order_no, "status": repo.STATUS_AWAITING_PAY,
                         "result": "payment_pending", "reason": e.kind}}

    if not result.approved:
        repo.finish_authorize(db, int(tx["id"]), ok=False,
                              provider_tx_id=result.provider_tx_id,
                              response_code=result.response_code)
        repo.set_status(db, order_no, order["status"], repo.STATUS_AWAITING_PAY,
                        "AP-301a 与信が通らなかった")
        cart_repo.remove_ordered(db, order_no)              # ★6.2.6 支払い待ち＝成立
        _mail_awaiting_pay(db, order, order_no, result.response_code)   # ★MSG-03（R-25 ④）
        return {"data": {"order_no": order_no, "status": repo.STATUS_AWAITING_PAY,
                         "result": "declined", "reason": result.response_code}}

    repo.finish_authorize(db, int(tx["id"]), ok=True,
                          provider_tx_id=result.provider_tx_id,
                          response_code=result.response_code)
    repo.set_status(db, order_no, order["status"], repo.STATUS_ALLOCATING, "AP-301a 与信OK")

    # ------------------------------------------------------------
    # ③ 引当（6.2.1）。手順1〜5 はメモリ、手順6だけがDBを触る
    # ------------------------------------------------------------
    lines = repo.order_lines(db, order_no)
    cands = repo.allocation_candidates(
        db, order_no, [l["sku_code"] for l in lines], order["ship_pref_code"]
    )
    try:
        assigns = allocate(
            [DomainLine(l["line_no"], l["sku_code"], l["qty"]) for l in lines],
            [Candidate(c["sku_code"], c["location_code"], int(c["kind"]), int(c["step"]),
                       int(c["qty"]), int(c["reserved_qty"])) for c in cands],
        )
    except AllocationFailed as e:
        repo.queue_void(db, order_no, result.provider_tx_id, int(tx["amount"]))
        repo.set_status(db, order_no, repo.STATUS_ALLOCATING, repo.STATUS_CANCELLED,
                        f"引当失敗: {e.reason}")
        # ★どの商品かを返す（FR-1202・R-25 ⑤）。内部の言い方は出さない（5.4）
        items = _unavailable_items(db, order_no)
        _mail_cancelled(db, order, order_no, kind="MSG-04", items=items)
        return {"data": {"order_no": order_no, "status": repo.STATUS_CANCELLED,
                         "result": "allocation_failed",
                         "reason": "ご注文の商品をご用意できませんでした",
                         "unavailable_items": items,
                         "charged": False}}

    updates = [
        {"location_code": u.location_code, "sku_code": u.sku_code, "add_qty": u.add_qty}
        for u in build_updates(assigns)
    ]
    try:
        ok = repo.apply_allocation(
            db, order_no, updates,
            [{"line_no": a.line_no, "location_code": a.location_code, "qty": a.qty}
             for a in assigns],
            # ★クーポンは引当と同じトランザクションで消費する（6.2.3 の①・BR-16a）。
            #   ★注文を作った時点では消費しない——与信が通らなければ使われないため
            coupon_code=order.get("coupon_code"),
            member_id=order.get("member_id"),
            discount=int(order["discount_amount"]),
        )
    except repo.CouponExhausted:
        # ★先勝ちの負けた側（IT-413）。在庫は1行も触っていない（先に落ちている）
        repo.queue_void(db, order_no, result.provider_tx_id, int(tx["amount"]))
        repo.set_status(db, order_no, repo.STATUS_ALLOCATING, repo.STATUS_CANCELLED,
                        "クーポンの全体上限（BR-16a）")
        _mail_cancelled(db, order, order_no, kind="MSG-04")     # ★MSG-04（引当と同じトランザクションで負けた）
        raise AppError("ERR-1213", {"field": "coupon_code"})
    if not ok:
        # ★更新件数0。やり直さない（6.2.2）。与信取消を「要実行」で書いてキャンセル
        repo.queue_void(db, order_no, result.provider_tx_id, int(tx["amount"]))
        repo.set_status(db, order_no, repo.STATUS_ALLOCATING, repo.STATUS_CANCELLED,
                        "引当失敗: 手順6が0件（横から在庫を取られた）")
        items = _unavailable_items(db, order_no)
        _mail_cancelled(db, order, order_no, kind="MSG-04", items=items)
        return {"data": {"order_no": order_no, "status": repo.STATUS_CANCELLED,
                         "result": "allocation_failed",
                         "reason": "ご注文の商品をご用意できませんでした",
                         "unavailable_items": items,
                         "charged": False}}

    # ★6.2.6。注文が成立したので、その注文になった明細だけカートから消す（戻さない）
    cart_repo.remove_ordered(db, order_no)

    # ★MSG-02 を積むだけ。ここでは送らない（7.3）。B-11 が拾う
    lines_for_mail = repo.order_lines(db, order_no)
    parts = [
        f"{order['orderer_name']} 様",
        "",
        "ご注文ありがとうございます。",
        "",
        f"注文番号：{order_no}",
        f"商品合計：{int(order['item_total']):,} 円",
        f"送料：{int(order['shipping_fee']):,} 円",
        f"支払総額：{int(order['total_amount']):,} 円"
        f"（うち消費税 {int(order['tax_amount']):,} 円）",
        f"明細：{len(lines_for_mail)} 件",
    ]
    if len({a.location_code for a in assigns}) >= 2:
        # BR-08。 2拠点から出すときは、そう伝える
        parts += ["", "※ 商品は2つに分けてお届けします。"]
    # ★ゲスト宛には照会画面の URL を載せる（要件 4.4 MSG-02。R-29）
    parts += ["", "ご注文の状況はこちらから確かめられます：", _order_url(order, order_no)]
    mailer.enqueue(db, msg_kind="MSG-02", to_email=str(order["orderer_email"]),
                   subject="ご注文ありがとうございました",
                   body=chr(10).join(parts))

    return {"data": {"order_no": order_no, "status": repo.STATUS_ALLOCATED,
                     "result": "allocated", "reason": None,
                     # ★いくつに分けて届くか（FR-306）。完了画面にも出す（AT-131）
                     "shipments": len({a.location_code for a in assigns})}}


@router.post(
    "/{order_no}/repay",
    dependencies=[Depends(require_internal_auth)],
    response_model=OrderCreatedResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
               404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def repay(
    order_no: str,
    db: Session = Depends(get_db),
    sid: str | None = Depends(session_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """AP-302 再決済。★そのときのセッションIDで origin_session_id を書き換える（7.2.2a）。"""
    session = _require_session(sid)
    if not idempotency_key:
        raise AppError("ERR-1003", {"field": "Idempotency-Key"})
    # ★本人（会員）か、照会を通ったゲストだけ（N-27。R-29 で足した）。
    #   これまでは注文番号を知っていれば、誰のセッションからでも再決済を始められた
    _order_for_viewer(db, sid, order_no)

    order = repo.get_order(db, order_no)
    if order is None:
        raise AppError("ERR-1215")
    if order["status"] != repo.STATUS_AWAITING_PAY:
        raise AppError("ERR-1205", {"status": order["status"]})

    gateway_key = repo.gateway_key_for(session, idempotency_key)
    repo.start_repay(db, order_no, session, gateway_key, int(order["total_amount"]))

    try:
        token = gateway.issue_token(order_no, int(order["total_amount"]))
    except gateway.GatewayError:
        token = ""

    return {
        "data": {
            "order_no": order_no,
            "total_amount": int(order["total_amount"]),
            "status": repo.STATUS_AUTHENTICATING,
            "client_token": token,
            "three_ds_url": gateway.three_ds_url(
                order_no, f"{FRONTEND_BASE_URL}/orders/{order_no}/authorizing"
            ),
            "replayed": False,
        }
    }


# ============================================================
# AP-304  購入履歴（F-603。串の⑩）
# ============================================================
@router.get("", dependencies=[Depends(require_internal_auth)])
def list_my_orders(db: Session = Depends(get_db), member=Depends(current_member)) -> dict:
    """会員の注文を新しい順に。★自分のぶんだけ（N-27）。

    ★`member_id` で絞る。注文番号を引数に取らないので、他人のぶんを指しようがない
      （R-21 の N-28a と同じ考え方）。
    """
    rows = db.execute(
        text("SELECT order_no, status, ordered_at, total_amount, receive_method "
             "  FROM orders WHERE member_id = :m ORDER BY ordered_at DESC LIMIT 50"),
        {"m": member["member_id"]},
    ).all()
    return {"data": {"orders": [
        {"order_no": r.order_no, "status": int(r.status),
         "ordered_at": str(r.ordered_at), "total_amount": int(r.total_amount),
         "receive_method": int(r.receive_method),
         # ★キャンセルできるかはサーバが決める（BR-17f）。
         #   ★画面がボタンを出す条件と、AP-303 が受ける条件を同じ1か所から取る（IT-101・102）
         "cancellable": shipping.can_cancel(int(r.status)),
         # ★支払い待ちなら再決済できる（F-314）。条件は AP-302 と同じ（状態＝支払い待ち）
         "repayable": int(r.status) == repo.STATUS_AWAITING_PAY}
        for r in rows]}}


@router.get("/{order_no}/detail", dependencies=[Depends(require_internal_auth)])
def my_order_detail(order_no: str, db: Session = Depends(get_db),
                    sid: str | None = Depends(session_id)) -> dict:
    """注文詳細（AP-305）。★会員は自分の注文、ゲストは照会を通った1件（N-27。R-29）。"""
    _, viewer = _order_for_viewer(db, sid, order_no)
    o = db.execute(
        text("SELECT order_no, status, ordered_at, item_total, discount_amount, shipping_fee, "
             "       tax_amount, total_amount, receive_method, member_id, "
             "       ship_name, ship_zip, ship_pref_code, ship_address, ship_tel "
             "  FROM orders WHERE order_no = :o"),
        {"o": order_no},
    ).first()
    if not o:
        raise AppError("ERR-1215")

    lines = db.execute(
        text("SELECT ol.line_no, ol.sku_code, ol.qty, ol.unit_price, p.name AS product_name "
             "  FROM order_line ol "
             "  JOIN sku s ON s.sku_code = ol.sku_code "
             "  JOIN product p ON p.product_code = s.product_code "
             " WHERE ol.order_no = :o ORDER BY ol.line_no"),
        {"o": order_no},
    ).all()
    ships = db.execute(
        text("SELECT id, status, planned_ship_date, carrier, tracking_no, shipped_at, dest_kind "
             "  FROM shipment WHERE order_no = :o ORDER BY id"),
        {"o": order_no},
    ).all()
    return {"data": {
        "order_no": o.order_no, "status": int(o.status), "ordered_at": str(o.ordered_at),
        "item_total": int(o.item_total), "discount_amount": int(o.discount_amount),
        "shipping_fee": int(o.shipping_fee), "tax_amount": int(o.tax_amount),
        "total_amount": int(o.total_amount), "receive_method": int(o.receive_method),
        "cancellable": shipping.can_cancel(int(o.status)),
        "repayable": int(o.status) == repo.STATUS_AWAITING_PAY,
        "viewer": viewer,          # ★画面がパンくず（購入履歴／照会）を出し分けるため
        # ★返品（F-501・F-502・F-507。R-31）。★期限と「申請できる数」はサーバが決める。画面は計算しない
        "returnable": _returnable(db, order_no),
        "returns": _returns_of(db, order_no),
        # ★注文したときの届け先（FR-401）。★あとで住所帳を直しても、この注文は変わらない
        "ship_to": {"name": o.ship_name, "zip": o.ship_zip, "pref_code": o.ship_pref_code,
                    "address": o.ship_address, "tel": o.ship_tel},
        "lines": [{"line_no": r.line_no, "sku_code": r.sku_code, "qty": int(r.qty),
                   "unit_price": int(r.unit_price), "product_name": r.product_name}
                  for r in lines],
        "shipments": [{"id": int(r.id), "status": int(r.status),
                       "planned_ship_date": str(r.planned_ship_date),
                       "carrier": r.carrier, "tracking_no": r.tracking_no,
                       "shipped_at": str(r.shipped_at) if r.shipped_at else None,
                       "dest_kind": int(r.dest_kind)}
                      for r in ships],
    }}


def _returnable(db: Session, order_no: str) -> dict:
    from repository import returns as returns_repo

    return returns_repo.returnable_view(db, order_no)


def _returns_of(db: Session, order_no: str) -> list[dict]:
    from domain import returns as rd
    from repository import returns as returns_repo

    return [{"return_no": x["return_no"], "status": int(x["status"]),
             "status_label": rd.STATUS_LABEL[int(x["status"])], "applied_at": str(x["applied_at"]),
             "qty": int(x["qty"]), "refund_total": int(x["refund_total"]) if int(x["status"]) == rd.REFUNDED else None}
            for x in returns_repo.list_for_orders(db, [order_no])]


# ============================================================
# AP-303  客によるキャンセル（F-909・BR-17f）
# ============================================================
@router.post("/{order_no}/cancel", dependencies=[Depends(require_internal_auth)])
def cancel_my_order(order_no: str, db: Session = Depends(get_db),
                    sid: str | None = Depends(session_id)) -> dict:
    """★入力は空（設計 4.2 ③）。「キャンセルできる状態か」を画面から送らせない。

    ★判定は注文の状態で行う。経過時間では判定しない（BR-17f・5.3.1）。
      ボタンを出す条件（AP-304 の cancellable）と、ここで受ける条件は
      どちらも domain/shipping.can_cancel() の1か所から取る（IT-101・102）。
    ★後始末（引当の解放・与信の取消・MSG-07）は運営のキャンセル（AP-B14）と同じ関数（10.2.6）。
    """
    # ★会員は自分の注文、ゲストは照会を通った1件（N-27）。他人の注文は 404（8.2）
    _order_for_viewer(db, sid, order_no)
    try:
        res = cancel_repo.cancel_order(db, order_no=order_no,
                                       by=cancel_repo.CHANGED_BY_CUSTOMER, operator_id=None,
                                       reason="AP-303 客によるキャンセル")
    except ValueError as e:
        db.rollback()
        raise AppError(str(e) if str(e).startswith("ERR-") else "ERR-1205")
    money_back.send_now(db, [res["void_tx_id"]])    # ★外で1回だけ。だめなら B-09
    return {"data": {"status": "cancelled", "order_no": order_no}}


# ============================================================
# AP-306  ゲスト注文の照会（F-313・N-27。R-29）
# ============================================================
class LookupBody(BaseModel):
    order_no: StrictStr
    email: EmailStr


@router.post("/lookup", dependencies=[Depends(require_internal_auth)])
def lookup_guest_order(body: LookupBody, request: Request, db: Session = Depends(get_db),
                       sid: str | None = Depends(session_id)) -> dict:
    """注文番号とメールアドレスの2つが一致したときだけ、その注文1件の照会権をセッションに持たせる。

    ★出力は注文番号だけ。中身は AP-305（注文詳細）を呼び直す（設計 4.2 ⑤）。
    ★一致しないときは「注文番号が無い」と「メールが違う」を区別しない。どちらも ERR-1107（8.2）。
    ★連続失敗にレート制限（BR-26 と同じ形。失敗だけを数える）。制限中も同じ ERR-1107。
    """
    import hmac

    from domain import password as pw
    from repository import auth as auth_repo

    session = _require_session(sid)
    ip = request.client.host if request.client else None
    if auth_repo.lookup_rate_exceeded(db, ip):
        raise AppError("ERR-1107")
    order_no = body.order_no.strip().upper()
    found = auth_repo.find_guest_order(db, order_no)
    wanted = pw.normalize_email(str(body.email))
    ok = bool(found) and hmac.compare_digest(pw.normalize_email(str(found["orderer_email"])), wanted)
    if not ok:
        auth_repo.record_lookup_failure(db, ip)
        raise AppError("ERR-1107")
    auth_repo.grant_guest_order(db, session, order_no)
    return {"data": {"order_no": order_no}}
