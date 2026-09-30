# -*- coding: utf-8 -*-
"""注文・決済取引・引当のDBアクセス（AP-301・301a・302）。

★外部の呼び出しはここに書かない。トランザクションの外で呼ぶ（要件 9.4）。
  この層は「短いトランザクションで書く」ことだけを受け持つ。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, and_, func, select, text, update
from sqlalchemy.orm import Session

from repository import coupon as coupon_repo
from testing.pause import pause_point
from repository.models import (
    EcExclusion,
    Location,
    Order,
    OrderLine,
    OrderStatusLog,
    PaymentTx,
    Prefecture,
    Product,
    Sku,
    Stock,
)

_SECTION_BACKYARD = 1

# 要件定義書 5.4 の注文状態。
# ★設計仕様書は状態の名前だけを決めていて、数値を割り当てていない。
#   ここで割り当てた（HANDOFF に「設計側で決めてほしい」として書いた）。
STATUS_RECEIVED = 1        # 受付
STATUS_AUTHENTICATING = 2  # 認証中
STATUS_AWAITING_PAY = 3    # 支払い待ち
STATUS_ALLOCATING = 4      # 引当処理
STATUS_ALLOCATED = 5       # 引当済
STATUS_CANCELLED = 11      # キャンセル済

# T-23 決済取引の種別（7.2.1）
TX_AUTH = 1        # 認証
TX_AUTHORIZE = 2   # 与信
TX_CAPTURE = 3     # 売上確定
TX_REFUND = 4      # 返金
TX_VOID = 5        # 取消
TX_INQUIRY = 6     # 照会
TX_NO_AUTH = 7     # 与信不要

# T-23 の状態
TX_SUCCESS = 1
TX_FAILED = 2
TX_PROCESSING = 3
TX_TODO = 4        # 要実行
TX_RUNNING = 5     # 実行中

CHANGED_BY_SYSTEM = 3


def new_order_no() -> str:
    """注文番号。★推測できない値にする（連番にしない）。

    ★orders.order_no は VARCHAR(20)（T-20）。19文字に収める。
      ORD-YYMMDD-XXXXXXXX = 3+1+6+1+8 = 19
    """
    return f"ORD-{datetime.now():%y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def gateway_key_for(session_id: str, client_key: str) -> str:
    """決済代行に渡す冪等キー。

    ★client の Idempotency-Key から決まる値にする（同じ操作なら同じキー）。
      7.2.1 は「行を作るときに決める。あとから書き戻さない」と決めている。
      UUID5 なら INSERT の1回で値が決まるので、書き戻す隙間そのものが無くなる。

    ★★呼び出し元のセッションと組にする（09-06 の指摘。設計 4.1.6a）。
      客のキーだけで作ると、payment_tx.idempotency_key が全客で一意になる。
      別の客がたまたま／わざと同じ "abc" を送ると「2回目」とみなされ、
      N-40 のとおり記録済みの注文番号が返ってしまう——
      つまり、他人の実在する注文番号を1つ渡すことになる。
      AP-306 のゲスト照会は「注文番号＋メールアドレス」なので、片方を渡したのと同じ。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"authorize:{session_id}:{client_key}"))


def find_by_gateway_key(db: Session, gateway_key: str) -> dict | None:
    """同じ冪等キーの決済取引がすでにあるか（IT-302・SEC-409）。"""
    stmt = (
        select(PaymentTx.order_no, PaymentTx.id, PaymentTx.amount, PaymentTx.status)
        .where(PaymentTx.idempotency_key == gateway_key)
        .limit(1)
    )
    row = db.execute(stmt).first()
    return dict(row._mapping) if row else None


def create_order(
    db: Session,
    *,
    order_no: str,
    session_id: str,
    orderer_name: str,
    orderer_email: str,
    ship: dict,
    receive_method: int,
    amounts: dict,
    lines: list[dict],
    gateway_key: str,
    coupon_code: str | None = None,
    member_id: str | None = None,
    cart_key: str | None = None,
) -> int:
    """AP-301。★注文・明細・決済取引を1つのトランザクションで書き、ここで必ずコミットする（6.1.2）。

    ★origin_session_id を控える（7.2.2a ①）。AP-301a はこれと一致する呼び出しだけを受ける。
    """
    db.execute(
        Order.__table__.insert().values(
            order_no=order_no,
            member_id=member_id,   # ★ログイン中ならひもづける（R-25 ①）
            origin_session_id=session_id,
            orderer_name=orderer_name,
            orderer_email=orderer_email,
            status=STATUS_AUTHENTICATING,
            receive_method=receive_method,
            ship_name=ship["name"],
            ship_zip=ship["zip"],
            ship_pref_code=ship["pref_code"],
            ship_address=ship["address"],
            ship_tel=ship["tel"],
            item_total=amounts["item_total"],
            discount_amount=amounts["discount"],
            shipping_fee=amounts["shipping_fee"],
            tax_amount=amounts["tax_amount"],
            total_amount=amounts["total_amount"],
            coupon_code=coupon_code,
            cart_key=cart_key,      # 6.2.6。成立したらこのカートから消す
        )
    )
    for l in lines:
        db.execute(
            OrderLine.__table__.insert().values(
                order_no=order_no,
                line_no=l["line_no"],
                sku_code=l["sku_code"],
                qty=l["qty"],
                unit_price=l["unit_price"],
                tax_rate=amounts["tax_rate"],
                allocated_discount=l["allocated_discount"],
                alloc_status=0,
                alloc_qty=0,
            )
        )
    res = db.execute(
        PaymentTx.__table__.insert().values(
            order_no=order_no,
            tx_kind=TX_AUTHORIZE,
            idempotency_key=gateway_key,   # ★INSERT の1回で決める。書き戻さない
            amount=amounts["total_amount"],
            status=TX_PROCESSING,
        )
    )
    db.execute(
        OrderStatusLog.__table__.insert().values(
            order_no=order_no, status_from=None, status_to=STATUS_AUTHENTICATING,
            changed_by=CHANGED_BY_SYSTEM, reason="AP-301 注文作成",
        )
    )
    db.commit()   # ★ここで必ずコミット（6.1.2）
    return int(res.inserted_primary_key[0])


def get_order(db: Session, order_no: str) -> dict | None:
    stmt = select(
        Order.order_no, Order.status, Order.origin_session_id, Order.total_amount,
        Order.receive_method, Order.ship_pref_code, Order.orderer_name, Order.orderer_email,
        Order.item_total, Order.discount_amount, Order.shipping_fee, Order.tax_amount,
        Order.coupon_code, Order.member_id,
    ).where(Order.order_no == order_no)
    row = db.execute(stmt).first()
    return dict(row._mapping) if row else None


def authorize_tx_of(db: Session, order_no: str) -> dict | None:
    """その注文の与信の行。★金額も冪等キーもここから取る（7.2.2a ③・N-35）。"""
    stmt = (
        select(PaymentTx.id, PaymentTx.amount, PaymentTx.idempotency_key,
               PaymentTx.status, PaymentTx.provider_tx_id)
        .where(PaymentTx.order_no == order_no, PaymentTx.tx_kind == TX_AUTHORIZE)
        .order_by(PaymentTx.id.desc())
        .limit(1)
    )
    row = db.execute(stmt).first()
    return dict(row._mapping) if row else None


def finish_authorize(db: Session, tx_id: int, *, ok: bool,
                     provider_tx_id: str | None, response_code: str | None) -> None:
    db.execute(
        update(PaymentTx).where(PaymentTx.id == tx_id).values(
            status=TX_SUCCESS if ok else TX_FAILED,
            provider_tx_id=provider_tx_id,
            response_code=response_code,
        )
    )
    db.commit()


def set_status(db: Session, order_no: str, status_from: int, status_to: int, reason: str) -> None:
    db.execute(update(Order).where(Order.order_no == order_no).values(status=status_to))
    db.execute(
        OrderStatusLog.__table__.insert().values(
            order_no=order_no, status_from=status_from, status_to=status_to,
            changed_by=CHANGED_BY_SYSTEM, reason=reason,
        )
    )
    db.commit()


def order_lines(db: Session, order_no: str) -> list[dict]:
    stmt = (
        select(OrderLine.line_no, OrderLine.sku_code, OrderLine.qty)
        .where(OrderLine.order_no == order_no)
        .order_by(OrderLine.line_no)
    )
    return [dict(r._mapping) for r in db.execute(stmt).all()]


def allocation_candidates(db: Session, order_no: str, sku_codes: list[str],
                          ship_pref: str) -> list[dict]:
    """手順1。★数量の条件は付けない（3.2.2 ⑥（a））。

    優先段（BR-05）｜1=受取店 2=同一都道府県 3=同一ブロック 4=それ以外
    ★店舗受取は未実装なので、段1はここでは現れない（3.2.2 ⑥）。
    """
    if not sku_codes:
        return []
    region = select(Prefecture.region).where(Prefecture.pref_code == ship_pref).scalar_subquery()
    exclusion = (
        select(EcExclusion.product_code)
        .where(
            EcExclusion.product_code == Sku.product_code,
            EcExclusion.location_code == Location.location_code,
        )
        .exists()
    )
    step = func.if_(
        Location.pref_code == ship_pref, 2,
        func.if_(Prefecture.region == region, 3, 4),
    )
    stmt = (
        select(
            Stock.sku_code, Stock.location_code, Location.kind,
            step.label("step"), Stock.qty, Stock.reserved_qty,
        )
        .select_from(Stock)
        .join(Sku, Sku.sku_code == Stock.sku_code)
        .join(Location, Location.location_code == Stock.location_code)
        .join(Prefecture, Prefecture.pref_code == Location.pref_code)
        .where(
            Stock.sku_code.in_(sku_codes),
            Stock.section == _SECTION_BACKYARD,
            Location.ec_saleable.is_(True),
            Location.suspended.is_(False),
            ~exclusion,
        )
    )
    return [dict(r._mapping) for r in db.execute(stmt).all()]


class CouponExhausted(Exception):
    """クーポンの全体上限に当たった（BR-16a・ERR-1213）。★先勝ちの負けた側。"""

    def __init__(self, coupon_code: str) -> None:
        super().__init__(coupon_code)
        self.coupon_code = coupon_code


def apply_allocation(db: Session, order_no: str, updates: list[dict],
                     assignments: list[dict], *, coupon_code: str | None = None,
                     member_id: str | None = None, discount: int = 0) -> bool:
    """手順6。★短いトランザクション1つ。行ロックを握るのはここだけ（6.1.2）。

    ★条件付きUPDATE。更新件数が0なら、その場ですべて取り消して失敗（6.2.2）。
      ★やり直さない。待ち行列を作らない（要件 9.4）。
    """
    try:
        # ★6.2.3 の順序。① クーポン → ② 在庫 → ③ 注文明細 → ④ 注文。
        #   ★2行以上を更新する処理は、すべて同じ順序で書く。
        #     違う順序で書く処理が1本でもあると、そこでデッドロックする（IT-406）。
        if coupon_code:
            # ★FT-07。全体上限の条件付きUPDATEの直前で止められるようにする（IT-413）
            pause_point(db, "before_coupon_update")
            if not coupon_repo.consume(db, coupon_code):
                # ★更新件数が0＝他が先に最後の1枚を取った（BR-16a の先勝ち）
                db.rollback()
                raise CouponExhausted(coupon_code)
            coupon_repo.record_use(db, coupon_code=coupon_code, member_id=member_id,
                                   order_no=order_no, discount=discount)

        # ★FT-07。手順6の条件付きUPDATEの直前で止められるようにする（設計 10.2.1）。
        #   domain/ ではなくここに置くのは、行ロックの取り合いを再現するため。
        pause_point(db, "before_stock_update")

        for u in updates:
            res = db.execute(
                update(Stock)
                .where(
                    Stock.sku_code == u["sku_code"],
                    Stock.location_code == u["location_code"],
                    Stock.section == _SECTION_BACKYARD,
                    # ★引き算をしない（3.2.2 ①）。UNSIGNED 同士を引くと ERROR 1690
                    Stock.qty >= Stock.reserved_qty + u["add_qty"],
                )
                .values(reserved_qty=Stock.reserved_qty + u["add_qty"])
            )
            if res.rowcount == 0:
                db.rollback()
                return False
        for a in assignments:
            db.execute(
                update(OrderLine)
                .where(OrderLine.order_no == order_no, OrderLine.line_no == a["line_no"])
                .values(alloc_location_code=a["location_code"], alloc_status=1, alloc_qty=a["qty"])
            )
        db.execute(update(Order).where(Order.order_no == order_no).values(status=STATUS_ALLOCATED))
        db.execute(
            OrderStatusLog.__table__.insert().values(
                order_no=order_no, status_from=STATUS_ALLOCATING, status_to=STATUS_ALLOCATED,
                changed_by=CHANGED_BY_SYSTEM, reason="AP-301a 引当成功",
            )
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def queue_void(db: Session, order_no: str, provider_tx_id: str | None, amount: int) -> None:
    """引当失敗のとき、与信取消を「要実行」で書く（6.1.2）。

    ★ここでは呼ばない。B-09 が拾う。外部の呼び出しをこの経路に混ぜない。
    """
    db.execute(
        PaymentTx.__table__.insert().values(
            order_no=order_no,
            tx_kind=TX_VOID,
            provider_tx_id=provider_tx_id,
            idempotency_key=str(uuid.uuid4()),   # ★INSERT の1回で決める（7.2.1）
            amount=amount,
            status=TX_TODO,
        )
    )
    db.commit()


def end_read_transaction(db: Session) -> None:
    """外部を呼ぶ前に、読みのトランザクションを閉じる（要件 9.4・IT-501）。

    ★行ロックを持っていなくても、SELECT を投げた時点でトランザクションは開いている。
      REPEATABLE READ では、そのまま外部の応答を35秒待つあいだ、
      一貫読み取りのスナップショットが固定され、UNDO ログが伸び続ける。
      「外部通信はトランザクションの外」は、書き込みだけの話ではない。
    """
    db.commit()


def open_transaction_count(db: Session) -> int:
    """IT-501 の確認用。いま開いているトランザクションの数。"""
    return int(db.execute(text("SELECT COUNT(*) FROM information_schema.innodb_trx")).scalar() or 0)


def start_repay(db: Session, order_no: str, session_id: str,
                gateway_key: str, amount: int) -> None:
    """AP-302。支払い待ち → 認証中 に戻し、新しい冪等キーで与信の行を作る。

    ★origin_session_id をそのときのセッションで書き換える（7.2.2a）。
      本人／照会の認証を通ったあとなので、書き換えてよい。
    """
    db.execute(
        update(Order).where(Order.order_no == order_no).values(
            status=STATUS_AUTHENTICATING, origin_session_id=session_id,
        )
    )
    db.execute(
        PaymentTx.__table__.insert().values(
            order_no=order_no,
            tx_kind=TX_AUTHORIZE,
            idempotency_key=gateway_key,
            amount=amount,
            status=TX_PROCESSING,
        )
    )
    db.execute(
        OrderStatusLog.__table__.insert().values(
            order_no=order_no, status_from=STATUS_AWAITING_PAY, status_to=STATUS_AUTHENTICATING,
            changed_by=CHANGED_BY_SYSTEM, reason="AP-302 再決済",
        )
    )
    db.commit()
