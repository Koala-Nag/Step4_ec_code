# -*- coding: utf-8 -*-
"""出荷の読み書き（設計 6.3・6.3.1）。

★DBに触るのはこの層だけ（設計 2.2）。どう分けるか・どの状態かは domain/shipping.py。

★6.3.1 はこの串でいちばん順序が効くところ。
  手順1〜4を1つのトランザクションでコミットし、手順5（外部）はその外。
  ★手順4を先に書く。後回しにすると、手順5の直前で落ちたとき何も残らない。
    出荷は「出荷済」なのに売上確定が送られず、しかも誰も気づけない。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from domain import shipping

# payment_tx.tx_kind / status（batch/jobs.py と同じ値）
TX_CAPTURE = 3
TX_SUCCESS, TX_FAILED, TX_PROCESSING, TX_TODO = 1, 2, 3, 4

CHANGED_BY_OPERATOR = 2
CHANGED_BY_SYSTEM = 3

# stock.section
SECTION_BACKYARD = 1


# ------------------------------------------------------------
# AP-B12  出荷指示の作成
# ------------------------------------------------------------
def allocated_lines(db: Session, order_no: str) -> list[dict]:
    """引当済の明細。★alloc_location_code が入っている行だけ。"""
    rows = db.execute(
        text("SELECT line_no, sku_code, alloc_qty AS qty, alloc_location_code, unit_price "
             "  FROM order_line "
             " WHERE order_no = :o AND alloc_status = 1 AND alloc_location_code IS NOT NULL "
             " ORDER BY line_no"),
        {"o": order_no},
    ).all()
    return [dict(r._mapping) for r in rows]


def location_calendar(db: Session, location_code: str) -> dict | None:
    """BR-23 の判定に要るもの。★休業日の一覧もここで読む。"""
    row = db.execute(
        text("SELECT location_code, name, pref_code, zip, address, tel, "
             "       business_days, cutoff_time FROM location WHERE location_code = :l"),
        {"l": location_code},
    ).first()
    if not row:
        return None
    days = db.execute(
        text("SELECT holiday FROM location_holiday WHERE location_code = :l"), {"l": location_code}
    ).all()
    return {**dict(row._mapping), "holidays": frozenset(d.holiday for d in days)}


def has_shipments(db: Session, order_no: str) -> bool:
    n = db.execute(text("SELECT COUNT(*) c FROM shipment WHERE order_no = :o"),
                   {"o": order_no}).first()
    return int(n.c) > 0


def create_shipments(db: Session, *, order_no: str, plans: list[dict],
                     operator_id: str | None, reason: str = "AP-B12 出荷指示の作成") -> list[int]:
    """手順2〜5。★1つのトランザクションで作る。

    plans は api 側で domain/shipping.py に組ませたもの。ここは書くだけ。
    """
    ids: list[int] = []
    for p in plans:
        res = db.execute(
            text("INSERT INTO shipment (order_no, from_location_code, dest_kind, dest_name, "
                 "  dest_zip, dest_pref_code, dest_address, dest_tel, status, planned_ship_date) "
                 "VALUES (:o, :from_loc, :kind, :name, :zip, :pref, :addr, :tel, :st, :planned)"),
            {"o": order_no, "from_loc": p["from_location_code"], "kind": p["dest_kind"],
             "name": p["dest_name"], "zip": p["dest_zip"], "pref": p["dest_pref_code"],
             "addr": p["dest_address"], "tel": p["dest_tel"],
             "st": shipping.SHIP_INSTRUCTED, "planned": p["planned_ship_date"]},
        )
        sid = int(res.lastrowid)
        ids.append(sid)
        for l in p["lines"]:
            db.execute(
                text("INSERT INTO shipment_line (shipment_id, order_no, line_no, qty) "
                     "VALUES (:s, :o, :ln, :q)"),
                {"s": sid, "o": order_no, "ln": l["line_no"], "q": l["qty"]},
            )

    # 手順5。注文を「出荷指示済」に。★引当済からしか進めない（二重指示を防ぐ）
    n = db.execute(
        text("UPDATE orders SET status = :to WHERE order_no = :o AND status = :fr"),
        {"o": order_no, "fr": shipping.ORDER_ALLOCATED, "to": shipping.ORDER_INSTRUCTED},
    ).rowcount
    if n == 0:
        db.rollback()
        raise AlreadyInstructed()          # ★条件付きUPDATEが0件＝先に取られた（6.2.2。やり直さない）
    db.execute(
        text("INSERT INTO order_status_log (order_no, status_from, status_to, changed_by, reason) "
             "VALUES (:o, :fr, :to, :by, :why)"),
        {"o": order_no, "fr": shipping.ORDER_ALLOCATED, "to": shipping.ORDER_INSTRUCTED,
         # ★手で押したら「運営者」、B-13 が作ったら「システム」（5.3 の履歴で見分けられるように）
         "by": CHANGED_BY_OPERATOR if operator_id else CHANGED_BY_SYSTEM, "why": reason},
    )
    if operator_id:
        # ★運営ログは「人がやったこと」の記録（E-36）。定期処理のぶんは入れない（applog に出す）
        db.execute(
            text("INSERT INTO operation_log (operator_id, target, action) VALUES (:p, :t, :a)"),
            {"p": operator_id, "t": f"order/{order_no}",
             "a": f"{reason} {len(ids)}件 shipment={ids}"},
        )
    db.commit()
    return ids


# ------------------------------------------------------------
# AP-B19  出荷一覧
# ------------------------------------------------------------
def list_shipments(db: Session, *, location_code: str | None, status: int | None = None,
                   limit: int = 50, order_no: str | None = None) -> list[dict]:
    """★拠点を絞るのは呼び出し側の判断（domain/authz.py）。ここは受けた値で絞るだけ。"""
    sql = ("SELECT s.id, s.order_no, s.from_location_code, s.dest_kind, s.dest_name, "
           "       s.dest_zip, s.dest_pref_code, s.dest_address, s.status, "
           "       s.planned_ship_date, s.carrier, s.tracking_no, s.shipped_at, s.staff_name, "
           "       o.orderer_name "
           "  FROM shipment s JOIN orders o ON o.order_no = s.order_no WHERE 1=1")
    params: dict = {"lim": max(1, min(limit, 100))}
    if location_code is not None:
        sql += " AND s.from_location_code = :loc"
        params["loc"] = location_code
    if status is not None:
        sql += " AND s.status = :st"
        params["st"] = status
    if order_no:
        sql += " AND s.order_no = :o"
        params["o"] = order_no
    # ★まだ発送していない（指示済）を先に。発送予定日の早い順（R-32）。
    #   ★以前は発送予定日の順だけで50件で切っていたので、出荷がたまると、
    #     いま作った出荷指示が一覧に出なかった（R-32 の1周で踏んだ）
    sql += " ORDER BY (s.status <> 1), s.planned_ship_date, s.id LIMIT :lim"
    return [dict(r._mapping) for r in db.execute(text(sql), params).all()]


def lines_for(db: Session, shipment_ids: list[int]) -> dict[int, list[dict]]:
    """一覧の出荷ぶんの明細を1回で引く（★行ごとに引き直さない。N-06・9.2.2）。

    ★欠品の報告（AP-B21）で、明細ごとに実在庫数を入れるために出す。
    """
    if not shipment_ids:
        return {}
    from sqlalchemy import bindparam

    rows = db.execute(
        text("SELECT sl.shipment_id, sl.line_no, sl.qty, ol.sku_code, p.name AS product_name "
             "  FROM shipment_line sl "
             "  JOIN order_line ol ON ol.order_no = sl.order_no AND ol.line_no = sl.line_no "
             "  JOIN sku k ON k.sku_code = ol.sku_code "
             "  JOIN product p ON p.product_code = k.product_code "
             " WHERE sl.shipment_id IN :ids ORDER BY sl.shipment_id, sl.line_no")
        .bindparams(bindparam("ids", expanding=True)),
        {"ids": list(shipment_ids)},
    ).all()
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(int(r.shipment_id), []).append(
            {"line_no": int(r.line_no), "qty": int(r.qty), "sku_code": r.sku_code,
             "product_name": r.product_name})
    return out


def get_shipment(db: Session, shipment_id: int) -> dict | None:
    row = db.execute(
        text("SELECT id, order_no, from_location_code, dest_kind, status, planned_ship_date "
             "  FROM shipment WHERE id = :i"),
        {"i": shipment_id},
    ).first()
    return dict(row._mapping) if row else None


def shipment_lines(db: Session, shipment_id: int) -> list[dict]:
    rows = db.execute(
        text("SELECT sl.line_no, sl.qty, ol.sku_code, ol.unit_price, ol.alloc_location_code, "
             "       ol.allocated_discount "
             "  FROM shipment_line sl "
             "  JOIN order_line ol ON ol.order_no = sl.order_no AND ol.line_no = sl.line_no "
             " WHERE sl.shipment_id = :i ORDER BY sl.line_no"),
        {"i": shipment_id},
    ).all()
    return [dict(r._mapping) for r in rows]


# ------------------------------------------------------------
# AP-B20  発送の記録（★6.3.1。順序が効く）
# ------------------------------------------------------------
def record_shipment(db: Session, *, shipment_id: int, carrier: str | None,
                    tracking_no: str | None, staff_name: str, operator_id: str,
                    this_items_after_discount: int, order_no: str,
                    mail_to: str, mail_subject: str, mail_body: str) -> dict:
    """手順1〜4を1つのトランザクションで。★手順5はここでは呼ばない。

    戻り値に「積んだ売上確定の行」を返す。呼び出し側がトランザクションの外で送る。
    """
    lines = shipment_lines(db, shipment_id)

    # 手順1。★在庫数と引当済数を同時に減らす（BR-04）。
    #   ★引き算の結果が負になる更新は通さない（3.2.2 ①）。
    #     UNSIGNED 同士の引き算は SQL 側でやらず、WHERE で条件にする
    for l in lines:
        n = db.execute(
            # ★最終販売日も書く（F-807 の材料。R-30 まで誰も書いていなかった）
            text("UPDATE stock SET qty = qty - :q, reserved_qty = reserved_qty - :q, "
                 "       last_sold_at = CURDATE() "
                 " WHERE sku_code = :sku AND location_code = :loc AND section = :sec "
                 "   AND qty >= :q AND reserved_qty >= :q"),
            {"q": l["qty"], "sku": l["sku_code"], "loc": l["alloc_location_code"],
             "sec": SECTION_BACKYARD},
        ).rowcount
        if n == 0:
            db.rollback()
            raise ValueError("ERR-1205")

    # 手順2。出荷を「出荷済」に。★指示済からしか進めない
    n = db.execute(
        text("UPDATE shipment SET status = :to, carrier = :c, tracking_no = :t, "
             "       staff_name = :s, shipped_at = NOW(3) "
             " WHERE id = :i AND status = :fr"),
        {"i": shipment_id, "fr": shipping.SHIP_INSTRUCTED, "to": shipping.SHIP_SHIPPED,
         "c": carrier, "t": tracking_no, "s": staff_name},
    ).rowcount
    if n == 0:
        db.rollback()
        raise ValueError("ERR-1205")

    # 手順3。★注文の状態は、出荷の状態から導出し直す（5.3）。持ち回さない
    #   ★注文の行をここでロックする（FOR UPDATE）。手順4の「最初の売上確定か」を、
    #     同じ注文の別の出荷の発送と取り合わないため。
    #     ★6.2.3 の順序（在庫 → 注文）は手順1で在庫を先に触っているので崩れない
    head = db.execute(text("SELECT status, total_amount, shipping_fee FROM orders "
                           " WHERE order_no = :o FOR UPDATE"), {"o": order_no}).first()
    statuses = [int(r.status) for r in db.execute(
        text("SELECT status FROM shipment WHERE order_no = :o"), {"o": order_no}).all()]
    before = head.status
    after = shipping.order_status_from_shipments(statuses)
    if after != before:
        db.execute(text("UPDATE orders SET status = :s WHERE order_no = :o"),
                   {"o": order_no, "s": after})
        db.execute(
            text("INSERT INTO order_status_log (order_no, status_from, status_to, changed_by, "
                 "                              reason) "
                 "VALUES (:o, :fr, :to, :by, 'AP-B20 発送を記録（5.3 の導出）')"),
            {"o": order_no, "fr": before, "to": after, "by": CHANGED_BY_OPERATOR},
        )

    # 手順4。★決済取引に「売上確定・要実行」を積む。
    #   ★ここが肝。先に記録しておけば、手順5で落ちても B-10 が拾って送り直す（6.6）
    import uuid as _uuid

    auth = db.execute(
        text("SELECT provider_tx_id FROM payment_tx "
             " WHERE order_no = :o AND tx_kind = 2 ORDER BY id DESC LIMIT 1"),
        {"o": order_no},
    ).first()
    # ★金額はロックの中で決める（6.3.1 ①②）
    captured = db.execute(
        text("SELECT COUNT(*) n, COALESCE(SUM(amount), 0) a FROM payment_tx "
             " WHERE order_no = :o AND tx_kind = :k AND status <> :failed"),
        {"o": order_no, "k": TX_CAPTURE, "failed": TX_FAILED},
    ).first()
    capture_amount = shipping.capture_amount(
        total_amount=int(head.total_amount), this_items_after_discount=this_items_after_discount,
        shipping_fee=int(head.shipping_fee), already_captured=int(captured.a),
        is_first=(int(captured.n) == 0),
    )
    key = str(_uuid.uuid4())
    res = db.execute(
        text("INSERT INTO payment_tx (order_no, shipment_id, tx_kind, provider_tx_id, amount, "
             "                        status, idempotency_key) "
             "VALUES (:o, :sid, :k, :p, :amt, :st, :key)"),
        {"o": order_no, "sid": shipment_id, "k": TX_CAPTURE,
         "p": auth.provider_tx_id if auth else None, "amt": capture_amount,
         "st": TX_TODO, "key": key},
    )
    tx_id = int(res.lastrowid)

    db.execute(
        text("INSERT INTO operation_log (operator_id, target, action) VALUES (:p, :t, :a)"),
        {"p": operator_id, "t": f"shipment/{shipment_id}",
         "a": f"AP-B20 発送を記録 担当={staff_name} 追跡={tracking_no or '-'}"},
    )

    # ★手順6の「積む」も、このトランザクションの中で書く。
    #   ★設計 6.3.1 は手順6を「トランザクションの外」に置いているが、
    #     7.3 が決めているとおり、ここでやるのは sent_mail に1行足すだけ——
    #     ★外部の呼び出しではなく、自分のDBへの書き込みである。
    #   外に置くと、コミットの直後に落ちたときに行が残らず、
    #   ★売上確定は B-10 が拾い直すのに、発送通知だけが永久に消える。
    #     客は荷物が出たことを知らされないまま、こちらも気づけない（R-22 で実際に踏んだ）。
    db.execute(
        text("INSERT INTO sent_mail (msg_kind, to_email, subject, body, status, attempt_count, "
             "                       next_retry_at, result, sent_at) "
             "VALUES ('MSG-06', :t, :s, :b, 0, 0, NOW(3), NULL, NULL)"),
        {"t": mail_to, "s": mail_subject, "b": mail_body},
    )

    # ★ここでコミット（6.3.1）。手順5より手前
    db.commit()

    return {"tx_id": tx_id, "idempotency_key": key,
            "provider_tx_id": auth.provider_tx_id if auth else None,
            "amount": capture_amount, "order_status": after}


def finish_capture(db: Session, tx_id: int, *, ok: bool, response_code: str | None) -> None:
    """手順5の結果。★失敗したら「要実行」に戻す。B-10 が拾う（6.6）。"""
    db.execute(
        text("UPDATE payment_tx SET status = :s, response_code = :c WHERE id = :i"),
        {"i": tx_id, "s": TX_SUCCESS if ok else TX_TODO, "c": response_code},
    )
    db.commit()


# ============================================================
# F-903a  出荷指示を作る（AP-B12 と B-13 の共通。R-34）
# ============================================================
class AlreadyInstructed(ValueError):
    """もう誰か（手／別のワーカ／B-13）が出荷指示を作っていた。★異常ではない（R-34）。

    ★B-13 は、これと「作れなかった（設定の誤りなど）」を分けて数える。
      同じ ERR-1205 にまとめると、設定の誤りが「先に取られた」に紛れて気づけない。
    """

    def __init__(self) -> None:
        super().__init__("ERR-1205")


def orders_ready_for_instruction(db: Session, limit: int = 50) -> list[str]:
    """出荷指示を作れる注文（状態＝引当済）。★古い順（待たせた注文から出す）。"""
    return [r.order_no for r in db.execute(
        text("SELECT order_no FROM orders WHERE status = :st ORDER BY ordered_at, order_no LIMIT :n"),
        {"st": shipping.ORDER_ALLOCATED, "n": max(1, min(limit, 200))}).all()]


def _as_time(v):
    """MySQL の TIME は timedelta で返る。★time に直す。"""
    from datetime import time as _time

    if isinstance(v, _time):
        return v
    total = int(v.total_seconds())
    return _time(total // 3600, (total % 3600) // 60, total % 60)


def instruct(db: Session, order_no: str, *, operator_id: str | None,
             reason: str = "AP-B12 出荷指示の作成") -> list[dict]:
    """引当拠点ごとに出荷（E-24）と出荷明細（E-25）を作り、注文を「出荷指示済」にする。

    ★手で押す口（AP-B12）と定期処理（B-13）の両方がここを呼ぶ。
      ★入口が2つあっても、条件を書くのは1か所（10.2.6）。片方だけ緩めない。
    ★発送予定日はここで確定して保存する（BR-23）。あとで拠点の営業日設定を変えても再計算しない（ST-413）。
    ★二重に作らない。「引当済 → 出荷指示済」の条件付きUPDATEが0件なら、
      もう片方（手／定期処理／別ワーカ）が先に取ったということ。やり直さない（6.2.2）。
    失敗は ValueError("ERR-…")。呼び出し側が 8.2 のコードに変える。
    """
    from datetime import datetime

    from domain import shipping_date as sd

    order = db.execute(
        text("SELECT order_no, status, receive_method, pickup_location_code, "
             "       ship_name, ship_zip, ship_pref_code, ship_address, ship_tel "
             "  FROM orders WHERE order_no = :o"), {"o": order_no}).first()
    if not order:
        raise ValueError("ERR-1215")
    if int(order.status) != shipping.ORDER_ALLOCATED:
        raise AlreadyInstructed()                  # ★引当済からしか進めない
    if has_shipments(db, order_no):
        raise AlreadyInstructed()
    lines = allocated_lines(db, order_no)
    if not lines:
        raise ValueError("ERR-1205")

    customer = shipping.Destination(
        kind=shipping.DEST_CUSTOMER, name=order.ship_name, zip=order.ship_zip,
        pref_code=order.ship_pref_code, address=order.ship_address, tel=order.ship_tel)
    pickup = None
    if int(order.receive_method) == shipping.RECEIVE_PICKUP:
        loc = location_calendar(db, order.pickup_location_code or "")
        if not loc:
            raise ValueError("ERR-1205")
        # ★届け先は作った時点の値を写して持つ（E-24）。あとで拠点を編集しても過去は変わらない
        pickup = shipping.Destination(
            kind=shipping.DEST_STORE, name=loc["name"], zip=loc["zip"], pref_code=loc["pref_code"],
            address=loc["address"], tel=loc["tel"], location_code=loc["location_code"])

    plans = shipping.plan_shipments(
        [shipping.AllocatedLine(int(l["line_no"]), l["sku_code"], int(l["qty"]),
                                l["alloc_location_code"]) for l in lines],
        receive_method=int(order.receive_method), customer=customer, pickup_store=pickup)

    now = datetime.now()
    rows: list[dict] = []
    for p in plans:
        loc = location_calendar(db, p.from_location_code)
        if not loc:
            raise ValueError("ERR-1205")
        cal = sd.LocationCalendar.from_bitmask(
            int(loc["business_days"]), _as_time(loc["cutoff_time"]), loc["holidays"])
        planned = sd.planned_ship_date(now, cal)
        if planned is None:
            # ★営業日が1つも無い設定。例外にせず、業務の失敗として返す（UT-407 と同じ扱い）
            raise ValueError("ERR-1205")
        rows.append({"from_location_code": p.from_location_code, "dest_kind": p.dest.kind,
                     "dest_name": p.dest.name, "dest_zip": p.dest.zip,
                     "dest_pref_code": p.dest.pref_code, "dest_address": p.dest.address,
                     "dest_tel": p.dest.tel, "planned_ship_date": planned,
                     "lines": [{"line_no": l.line_no, "qty": l.qty} for l in p.lines]})

    ids = create_shipments(db, order_no=order_no, plans=rows, operator_id=operator_id, reason=reason)
    return [{"id": i, "from_location_code": r["from_location_code"], "dest_kind": r["dest_kind"],
             "planned_ship_date": str(r["planned_ship_date"]), "lines": len(r["lines"])}
            for i, r in zip(ids, rows)]
