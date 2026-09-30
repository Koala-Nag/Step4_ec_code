# -*- coding: utf-8 -*-
"""欠品・再引当・部分キャンセル・キャンセル（設計 6.4・6.5.2・BR-04a・BR-17c〜f・BR-21a）。

★DBに触るのはこの層だけ（設計 2.2）。いくら・どう戻すかの判断は domain/refund.py。

★F-904（注文のキャンセル）と F-911（欠品分の部分キャンセル）は、後始末が同じ形になる。

    ① 引当を解放する
    ② 決済を戻す（売上確定の前なら取消、後なら返金。BR-17c・17d）
    ③ 注文の状態を 5.3 の導出で決め直す
    ④ 客に知らせる

  ★入口が2つあるので、この4つを書くのはここ1か所だけにする（設計 10.2.6）。
    R-24 のカート（入れる／数量を直す）で、条件が片方にだけ掛かっていたのと同じ形を作らない。

★「送る」は外、「積む」は中（R-22 の提案42）。
  決済の取消・返金は「要実行」で積んでコミットし、送るのは外（B-09 が拾い直す）。
  メールも同じトランザクションで積む。
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from domain import refund as refund_domain
from domain import shipping

# payment_tx（batch/jobs.py と同じ値）
TX_AUTHORIZE, TX_CAPTURE, TX_REFUND, TX_VOID = 2, 3, 4, 5
TX_SUCCESS, TX_FAILED, TX_PROCESSING, TX_TODO = 1, 2, 3, 4

# order_line.alloc_status
ALLOC_NONE, ALLOC_DONE, ALLOC_RELEASED = 0, 1, 2

SECTION_BACKYARD = 1
CHANGED_BY_CUSTOMER, CHANGED_BY_OPERATOR = 1, 2


# ============================================================
# ① 引当の解放（共通）
# ============================================================
def release_lines(db: Session, order_no: str, line_nos: list[int] | None = None) -> list[dict]:
    """引当済の明細の引当を解放する。★トランザクションはコミットしない（呼び出し側がまとめる）。

    ★「引当済（1）」の明細だけを解放する。
      欠品を報告した時点で解放済み（2）になった明細は、ここでは触らない——
      F-911 の部分キャンセルで二重に解放すると、他の注文の引当済数まで減ってしまう。
    ★引き算の結果が負になる更新は通さない（3.2.2 ①）。
    """
    sql = ("SELECT line_no, sku_code, alloc_qty, alloc_location_code FROM order_line "
           " WHERE order_no = :o AND alloc_status = :done AND alloc_location_code IS NOT NULL")
    params: dict = {"o": order_no, "done": ALLOC_DONE}
    if line_nos is not None:
        if not line_nos:
            return []
        sql += " AND line_no IN :lines"
        params["lines"] = tuple(line_nos)
    lines = [dict(r._mapping) for r in db.execute(
        text(sql).bindparams(*([_expanding("lines")] if line_nos else [])), params).all()]

    # ★6.2.3 の順序。在庫は (location_code, sku_code) の昇順で触る
    for l in sorted(lines, key=lambda x: (x["alloc_location_code"], x["sku_code"])):
        n = db.execute(
            text("UPDATE stock SET reserved_qty = reserved_qty - :q "
                 " WHERE sku_code = :s AND location_code = :loc AND section = :sec "
                 "   AND reserved_qty >= :q"),
            {"q": int(l["alloc_qty"]), "s": l["sku_code"], "loc": l["alloc_location_code"],
             "sec": SECTION_BACKYARD},
        ).rowcount
        if n == 0:
            raise ValueError("ERR-1205")
        db.execute(
            text("UPDATE order_line SET alloc_status = :rel WHERE order_no = :o AND line_no = :ln"),
            {"rel": ALLOC_RELEASED, "o": order_no, "ln": l["line_no"]},
        )
    return lines


def _expanding(name: str):
    from sqlalchemy import bindparam

    return bindparam(name, expanding=True)


# ============================================================
# ② 決済を戻す（共通）
# ============================================================
def authorization_of(db: Session, order_no: str) -> dict | None:
    """成功した与信。★無ければ（与信前・与信NG）戻すものが無い。"""
    row = db.execute(
        text("SELECT id, provider_tx_id, amount FROM payment_tx "
             " WHERE order_no = :o AND tx_kind = :k AND status = :ok ORDER BY id DESC LIMIT 1"),
        {"o": order_no, "k": TX_AUTHORIZE, "ok": TX_SUCCESS},
    ).first()
    return dict(row._mapping) if row else None


def captured_for_shipment(db: Session, shipment_id: int) -> bool:
    """その出荷ぶんの売上確定が成功しているか（BR-17d の分かれ目）。"""
    row = db.execute(
        text("SELECT 1 FROM payment_tx "
             " WHERE shipment_id = :s AND tx_kind = :k AND status = :ok LIMIT 1"),
        {"s": shipment_id, "k": TX_CAPTURE, "ok": TX_SUCCESS},
    ).first()
    return row is not None


def refunded_total(db: Session, order_no: str) -> int:
    """これまでに戻した（または戻すと積んだ）額の合計。★支払総額の頭打ちに使う（BR-21）。"""
    row = db.execute(
        text("SELECT COALESCE(SUM(amount), 0) a FROM payment_tx "
             " WHERE order_no = :o AND tx_kind IN (:v, :r) AND status IN (:ok, :todo, :proc)"),
        {"o": order_no, "v": TX_VOID, "r": TX_REFUND,
         "ok": TX_SUCCESS, "todo": TX_TODO, "proc": TX_PROCESSING},
    ).first()
    return int(row.a)


def queue_money_back(db: Session, *, order_no: str, amount: int, kind: str,
                     shipment_id: int | None = None, return_no: str | None = None) -> int | None:
    """取消・返金を「要実行」で積む。★ここでは送らない（外で送る。B-09 が拾い直す）。

    ★BR-17e。1つの出荷に対する欠品の返金・取消は1件まで。2件目は積まない。
    """
    if amount <= 0:
        return None
    if shipment_id is not None:
        dup = db.execute(
            text("SELECT 1 FROM payment_tx WHERE shipment_id = :s AND tx_kind IN (:v, :r) "
                 "   AND status IN (:ok, :todo, :proc) LIMIT 1"),
            {"s": shipment_id, "v": TX_VOID, "r": TX_REFUND,
             "ok": TX_SUCCESS, "todo": TX_TODO, "proc": TX_PROCESSING},
        ).first()
        if dup:
            raise ValueError("ERR-1205")

    auth = authorization_of(db, order_no)
    res = db.execute(
        text("INSERT INTO payment_tx (order_no, shipment_id, return_req_id, tx_kind, provider_tx_id, "
             "                        amount, status, idempotency_key) "
             "VALUES (:o, :s, :r, :k, :p, :a, :st, :key)"),
        {"o": order_no, "s": shipment_id, "r": return_no,     # ★返品の返金は返品申請に紐づける（BR-17e (c)）
         "k": TX_REFUND if kind == refund_domain.KIND_REFUND else TX_VOID,
         "p": auth["provider_tx_id"] if auth else None, "a": amount,
         "st": TX_TODO, "key": str(uuid.uuid4())},     # ★冪等キーは INSERT の1回で決める
    )
    return int(res.lastrowid)


# ============================================================
# ③ 注文の状態を決め直す（共通）
# ============================================================
def rederive_order_status(db: Session, order_no: str, *, reason: str, changed_by: int,
                          operator_id: str | None = None) -> int:
    statuses = [int(r.status) for r in db.execute(
        text("SELECT status FROM shipment WHERE order_no = :o"), {"o": order_no}).all()]
    before = int(db.execute(text("SELECT status FROM orders WHERE order_no = :o"),
                            {"o": order_no}).first().status)
    after = shipping.order_status_from_shipments(statuses) if statuses else before
    if after != before:
        db.execute(text("UPDATE orders SET status = :s WHERE order_no = :o"),
                   {"o": order_no, "s": after})
        db.execute(
            text("INSERT INTO order_status_log (order_no, status_from, status_to, changed_by, "
                 "                              operator_id, reason) "
                 "VALUES (:o, :fr, :to, :by, :op, :why)"),
            {"o": order_no, "fr": before, "to": after, "by": changed_by, "op": operator_id,
             "why": reason},
        )
    return after


# ============================================================
# ④ 客に知らせる（共通）
# ============================================================
def enqueue_mail(db: Session, *, msg_kind: str, to_email: str, subject: str, body: str) -> None:
    """★同じトランザクションで積む（コミットは呼び出し側）。mailer.enqueue はコミットするので使わない。"""
    db.execute(
        text("INSERT INTO sent_mail (msg_kind, to_email, subject, body, status, attempt_count, "
             "                       next_retry_at, result, sent_at) "
             "VALUES (:k, :t, :s, :b, 0, 0, NOW(3), NULL, NULL)"),
        {"k": msg_kind, "t": to_email, "s": subject, "b": body},
    )


def order_head(db: Session, order_no: str) -> dict | None:
    row = db.execute(
        text("SELECT order_no, status, member_id, orderer_name, orderer_email, "
             "       item_total, discount_amount, shipping_fee, total_amount, coupon_code "
             "  FROM orders WHERE order_no = :o"),
        {"o": order_no},
    ).first()
    return dict(row._mapping) if row else None


def op_log(db: Session, operator_id: str | None, target: str, action: str) -> None:
    if operator_id:
        db.execute(
            text("INSERT INTO operation_log (operator_id, target, action) VALUES (:p, :t, :a)"),
            {"p": operator_id, "t": target, "a": action[:100]},
        )


def shortage_notice(*, all_short: bool) -> tuple[str, list[str]]:
    """MSG-05 の件名と本文（要件 4.4。2026-09-13 変更）。

    全欠品   「ご注文の商品をお調べしています」
    一部欠品 「一部の商品の手配に時間がかかっています。他の商品は予定どおりお届けします」
    """
    if all_short:
        return ("ご注文の商品をお調べしています",
                ["ご注文の商品をお調べしています。",
                 "確認の結果は、あらためてご連絡いたします。"])
    return ("一部の商品の手配に時間がかかっています",
            ["一部の商品の手配に時間がかかっています。",
             "他の商品は予定どおりお届けします。",
             "手配に時間がかかっている商品の結果は、あらためてご連絡いたします。"])


# ============================================================
# AP-B21  欠品の報告（F-805・BR-04a・設計 6.4）
# ============================================================
def report_shortage(db: Session, *, shipment_id: int, actual: dict[int, int],
                    reporter: str, reason: str, operator_id: str) -> dict:
    """欠品を報告する。★BR-04a の順序が決まっている。

        (a) まず当該出荷分の引当済数を解放する
        (b) そのうえで在庫数を、報告された実在庫数に上書きする

    ★(a) と (b) を逆にすると壊れる。先に在庫数を上書きすると、
      解放すべき引当済数の根拠が消える（6.4）。

    ★この順で正しく踏んでも、他の注文の引当が残っていれば
      「引当済数 > 在庫数」が残る（BR-04a）。★異常ではない。販売可能数は 0 として扱う。

    actual  {明細の行番号: 実在庫数}。★1つの出荷に SKU が複数あり得るので、明細ごとに受ける。
    """
    sh = db.execute(
        text("SELECT id, order_no, from_location_code, status FROM shipment WHERE id = :i"),
        {"i": shipment_id},
    ).first()
    if not sh:
        raise ValueError("ERR-1215")
    if int(sh.status) != shipping.SHIP_INSTRUCTED:
        raise ValueError("ERR-1205")             # ★指示済の出荷だけ

    lines = db.execute(
        text("SELECT sl.line_no, ol.sku_code, ol.alloc_qty, ol.alloc_location_code "
             "  FROM shipment_line sl "
             "  JOIN order_line ol ON ol.order_no = sl.order_no AND ol.line_no = sl.line_no "
             " WHERE sl.shipment_id = :i ORDER BY sl.line_no"),
        {"i": shipment_id},
    ).all()
    line_nos = [int(l.line_no) for l in lines]
    if set(actual) - set(line_nos):
        raise ValueError("ERR-1004")             # この出荷に無い明細を指している

    # (a) まず引当を解放する（★BR-04a の1段目）
    release_lines(db, sh.order_no, line_nos)

    # (b) そのうえで在庫数を実在庫数に上書きする（★BR-04a の2段目）
    #     ★報告の無かった明細は上書きしない（在庫数は分からないまま触らない）
    for l in sorted(lines, key=lambda x: x.sku_code):
        if int(l.line_no) not in actual:
            continue
        q = max(int(actual[int(l.line_no)]), 0)
        before = db.execute(
            text("SELECT qty FROM stock WHERE sku_code = :s AND location_code = :loc "
                 "   AND section = :sec FOR UPDATE"),
            {"s": l.sku_code, "loc": sh.from_location_code, "sec": SECTION_BACKYARD},
        ).first()
        if before is None:
            raise ValueError("ERR-1215")
        db.execute(
            text("UPDATE stock SET qty = :q "
                 " WHERE sku_code = :s AND location_code = :loc AND section = :sec"),
            {"q": q, "s": l.sku_code, "loc": sh.from_location_code, "sec": SECTION_BACKYARD},
        )
        # ★誰が・なぜ を残す（T-13a。理由区分 2=欠品報告）。共有アカウントなので担当者名は手入力
        db.execute(
            text("INSERT INTO stock_change_log (sku_code, location_code, section, reason, "
                 "  qty_before, qty_after, note, operator_id, staff_name) "
                 "VALUES (:s, :loc, :sec, 2, :b, :a, :n, :op, :st)"),
            {"s": l.sku_code, "loc": sh.from_location_code, "sec": SECTION_BACKYARD,
             "b": int(before.qty), "a": q, "n": f"shipment/{shipment_id} {reason}"[:200],
             "op": operator_id, "st": reporter[:50]},
        )

    db.execute(
        text("UPDATE shipment SET status = :to, short_actual_qty = :aq, short_reporter = :r, "
             "       short_at = NOW(3) WHERE id = :i AND status = :fr"),
        {"to": shipping.SHIP_SHORT, "fr": shipping.SHIP_INSTRUCTED, "i": shipment_id,
         "aq": sum(max(int(v), 0) for v in actual.values()) if actual else None,
         "r": reporter[:50]},
    )

    after = rederive_order_status(db, sh.order_no, reason="AP-B21 欠品の報告",
                                  changed_by=CHANGED_BY_OPERATOR, operator_id=operator_id)

    head = order_head(db, sh.order_no)
    # ★客へ「確認中」を伝える（F-408・MSG-05）。★結果は改めて伝えると書く（8.5）
    #   ★全欠品と一部欠品で文面を分ける（要件 4.4。R-27）。
    #     同じ文面だと、一部欠品の客が「全部止まった」と誤解する。
    subject, lines_ = shortage_notice(all_short=(after == shipping.ORDER_SHORT_HOLD))
    enqueue_mail(
        db, msg_kind="MSG-05", to_email=str(head["orderer_email"]), subject=subject,
        body=chr(10).join([f"{head['orderer_name']} 様", ""] + lines_
                          + ["", f"注文番号：{sh.order_no}"]),
    )
    op_log(db, operator_id, f"shipment/{shipment_id}",
           f"AP-B21 欠品 報告者={reporter} 実在庫={actual} 理由={reason}")
    db.commit()
    return {"order_no": sh.order_no, "shipment_id": shipment_id, "order_status": after,
            "released_lines": line_nos}


# ============================================================
# AP-B16  欠品分の部分キャンセルと返金（F-911・BR-21a・BR-17d）
# ============================================================
def partial_cancel(db: Session, *, order_no: str, operator_id: str) -> dict:
    """欠品になっている出荷を取り消し、そのぶんを戻す。

    ★1出荷ずつ、BR-17d で「取消」か「返金」かを決める。
      売上確定済みなら返金、未確定なら取消。★混ぜると二重に返すか、返らないか。
    """
    head = order_head(db, order_no)
    if not head:
        raise ValueError("ERR-1215")

    shorts = db.execute(
        text("SELECT id FROM shipment WHERE order_no = :o AND status = :st ORDER BY id"),
        {"o": order_no, "st": shipping.SHIP_SHORT},
    ).all()
    if not shorts:
        raise ValueError("ERR-1205")             # 取り消す欠品が無い

    all_lines = db.execute(
        text("SELECT line_no, unit_price, qty, allocated_discount FROM order_line "
             " WHERE order_no = :o ORDER BY line_no"),
        {"o": order_no},
    ).all()
    by_no = {int(l.line_no): l for l in all_lines}

    # ★「全明細が欠品か」は、生きている出荷（欠品でもキャンセルでもない）に
    #   載っている明細が1つも無いかで決める。
    #   ★「欠品かキャンセルの出荷に載っているか」で数えると間違える——
    #     再引当した明細は、キャンセルした古い出荷と、新しい出荷の両方に載っている。
    live_lines = {int(r.line_no) for r in db.execute(
        text("SELECT sl.line_no FROM shipment_line sl JOIN shipment s ON s.id = sl.shipment_id "
             " WHERE s.order_no = :o AND s.status NOT IN (:short, :cancel)"),
        {"o": order_no, "short": shipping.SHIP_SHORT, "cancel": shipping.SHIP_CANCELLED},
    ).all()}
    all_lines_short = not (live_lines & set(by_no))

    # ★全明細が部分キャンセルになって注文がキャンセル済になるなら、クーポンの利用回数を戻す
    #   （要件 F-911。2026-09-13 追加）。★F-904 と結果が同じなら後始末も同じにする（10.2.6）。
    #   ★6.2.3 の順序（クーポン → 在庫 → 明細 → 注文）に合わせて、在庫に触る前に戻す。
    #   ★MSG-07 は送らない。下の MSG-05 の続報が金額まで伝えている（同じことを2通送らない）
    coupon_released = 0
    if all_lines_short and head.get("coupon_code"):
        from repository import coupon as coupon_repo

        coupon_released = coupon_repo.release(db, order_no)

    results = []
    already = refunded_total(db, order_no)
    for idx, r in enumerate(shorts):
        sid = int(r.id)
        sl = [int(x.line_no) for x in db.execute(
            text("SELECT line_no FROM shipment_line WHERE shipment_id = :s"), {"s": sid}).all()]
        short_alloc = [refund_domain.AllocatedLine(
            n, int(by_no[n].unit_price) * int(by_no[n].qty), int(by_no[n].allocated_discount))
            for n in sl]

        # ★送料を返すのは「全明細が欠品」のときの、最後の1件にだけ載せる（二重に返さない）
        last = idx == len(shorts) - 1
        amount = refund_domain.shortage_refund(
            short_alloc, all_lines_short=all_lines_short and last,
            shipping_fee=int(head["shipping_fee"]), total_amount=int(head["total_amount"]),
            already_refunded=already,
        )
        kind = refund_domain.money_back_kind(captured=captured_for_shipment(db, sid))
        tx_id = queue_money_back(db, order_no=order_no, amount=amount, kind=kind, shipment_id=sid)
        already += amount

        # ★欠品の報告で引当は解放済み。ここで二重に解放しない（release_lines は 1 だけを見る）
        release_lines(db, order_no, sl)

        db.execute(text("UPDATE shipment SET status = :c WHERE id = :s AND status = :short"),
                   {"c": shipping.SHIP_CANCELLED, "s": sid, "short": shipping.SHIP_SHORT})
        results.append({"shipment_id": sid, "lines": sl, "amount": amount, "kind": kind,
                        "tx_id": tx_id})

    after = rederive_order_status(db, order_no, reason="AP-B16 欠品分の部分キャンセル",
                                  changed_by=CHANGED_BY_OPERATOR, operator_id=operator_id)

    total_back = sum(x["amount"] for x in results)
    # ★MSG-05 の続報（F-911）。★結果を伝える
    enqueue_mail(
        db, msg_kind="MSG-05", to_email=str(head["orderer_email"]),
        subject="ご注文の商品の確認結果",
        body=chr(10).join([
            f"{head['orderer_name']} 様", "",
            "先日ご連絡した商品は、ご用意できませんでした。",
            "該当の商品は取り消しとし、代金をお返しいたします。", "",
            f"注文番号：{order_no}",
            f"お返しする金額：{total_back:,} 円",
            "（" + ("お支払い前の取り消しのため、請求は発生しません"
                    if all(x["kind"] == refund_domain.KIND_VOID for x in results)
                    else "ご利用のカードへ返金いたします") + "）",
        ]),
    )
    op_log(db, operator_id, f"order/{order_no}",
           f"AP-B16 部分キャンセル {[(x['shipment_id'], x['kind'], x['amount']) for x in results]}")
    db.commit()
    return {"order_no": order_no, "order_status": after, "cancelled": results,
            "refund_total": total_back, "all_lines_short": all_lines_short,
            "coupon_released": coupon_released}


# ============================================================
# AP-B14 / AP-303  注文のキャンセル（F-904・F-909・BR-17f）
# ============================================================
def cancel_order(db: Session, *, order_no: str, by: int, operator_id: str | None,
                 reason: str) -> dict:
    """注文全体を取り消す。★出荷指示の前だけ（BR-17f）。

    ★判定は注文の状態で行う。経過時間では判定しない（5.3.1）。
    ★出荷指示の前なので、売上確定はまだ無い → 戻すのは必ず「取消」（BR-17c）。
    """
    head = order_head(db, order_no)
    if not head:
        raise ValueError("ERR-1215")
    if not shipping.can_cancel(int(head["status"])):
        raise ValueError("ERR-1205")

    # ★6.2.3 の順序（① クーポン → ② 在庫 → ③ 注文明細 → ④ 注文）で書く。
    #   引当（AP-301a）と同じ順にしないと、キャンセルと引当がぶつかったときにデッドロックする
    if head.get("coupon_code"):
        from repository import coupon as coupon_repo

        coupon_repo.release(db, order_no)       # BR-16a の後半。利用済回数を戻す

    # ① 引当を解放する（引当前の注文なら何もしない）
    released = release_lines(db, order_no, None)

    # ② 決済を戻す。★成功した与信があるときだけ。与信前・与信NGなら戻すものは無い
    auth = authorization_of(db, order_no)
    tx_id = None
    if auth:
        tx_id = queue_money_back(db, order_no=order_no, amount=int(auth["amount"]),
                                 kind=refund_domain.KIND_VOID)

    before = int(head["status"])
    # ★読んだ状態のままのときだけ書く（条件付きUPDATE）。
    #   読んでから書くまでのあいだに出荷指示が入ったら、キャンセルしない（BR-17f）
    n = db.execute(text("UPDATE orders SET status = :c WHERE order_no = :o AND status = :b"),
                   {"c": shipping.ORDER_CANCELLED, "o": order_no, "b": before}).rowcount
    if n == 0:
        db.rollback()
        raise ValueError("ERR-1205")
    db.execute(
        text("INSERT INTO order_status_log (order_no, status_from, status_to, changed_by, "
             "                              operator_id, reason) "
             "VALUES (:o, :fr, :to, :by, :op, :why)"),
        {"o": order_no, "fr": before, "to": shipping.ORDER_CANCELLED, "by": by,
         "op": operator_id, "why": reason},
    )

    # ④ MSG-07（ご注文を取り消しました。★取り消した理由の区分を入れる。8.5）
    enqueue_mail(
        db, msg_kind="MSG-07", to_email=str(head["orderer_email"]),
        subject="ご注文を取り消しました",
        body=chr(10).join([
            f"{head['orderer_name']} 様", "",
            "ご注文を取り消しました。", "",
            f"注文番号：{order_no}",
            f"取り消しの区分：{'お客様によるキャンセル' if by == CHANGED_BY_CUSTOMER else '当店によるキャンセル'}",
            "※ お支払い前の取り消しのため、代金は発生しません。" if auth
            else "※ 決済は行われていません。",
        ]),
    )
    op_log(db, operator_id, f"order/{order_no}", f"注文のキャンセル {reason}")
    db.commit()
    return {"order_no": order_no, "status": shipping.ORDER_CANCELLED,
            "released_lines": [int(l["line_no"]) for l in released],
            "void_tx_id": tx_id, "voided": bool(auth)}


# ============================================================
# AP-B15  再引当（F-912・設計 6.4 手順5）
# ============================================================
def short_shipments(db: Session, order_no: str) -> list[dict]:
    """欠品のままの出荷と、その明細。★再引当と部分キャンセルの両方の画面が読む。"""
    shs = db.execute(
        text("SELECT id, from_location_code, dest_kind, dest_name, dest_zip, dest_pref_code, "
             "       dest_address, dest_tel, short_actual_qty, short_reporter, short_at "
             "  FROM shipment WHERE order_no = :o AND status = :st ORDER BY id"),
        {"o": order_no, "st": shipping.SHIP_SHORT},
    ).all()
    out = []
    for sh in shs:
        lines = db.execute(
            text("SELECT sl.line_no, ol.sku_code, sl.qty, ol.unit_price, ol.allocated_discount "
                 "  FROM shipment_line sl JOIN order_line ol "
                 "    ON ol.order_no = sl.order_no AND ol.line_no = sl.line_no "
                 " WHERE sl.shipment_id = :s ORDER BY sl.line_no"),
            {"s": sh.id},
        ).all()
        out.append({**dict(sh._mapping), "lines": [dict(l._mapping) for l in lines]})
    return out


def live_locations(db: Session, order_no: str) -> set[str]:
    """生きている出荷（欠品でもキャンセルでもない）の出荷元。★BR-07 の拠点数に数える。"""
    return {r.from_location_code for r in db.execute(
        text("SELECT DISTINCT from_location_code FROM shipment "
             " WHERE order_no = :o AND status NOT IN (:short, :cancel)"),
        {"o": order_no, "short": shipping.SHIP_SHORT, "cancel": shipping.SHIP_CANCELLED},
    ).all()}


def apply_reallocation(db: Session, *, order_no: str, short_ids: list[int],
                       updates: list[dict], assignments: list[dict], plans: list[dict],
                       operator_id: str) -> dict | None:
    """★1つのトランザクション。条件付きUPDATEが0件なら全部取り消して None（6.2.2。やり直さない）。

        ② 在庫（引当済数を足す。location, sku の昇順）
        ③ 注文明細（引当先を付け替える）
        欠品の出荷をキャンセルにし、新しい出荷を作る
        ④ 注文の状態を導出し直す（→ 出荷指示済）
    """
    try:
        for u in updates:                       # ★build_updates で (location, sku) の昇順
            n = db.execute(
                text("UPDATE stock SET reserved_qty = reserved_qty + :q "
                     " WHERE sku_code = :s AND location_code = :loc AND section = :sec "
                     "   AND qty >= reserved_qty + :q"),     # ★引き算をしない（3.2.2 ①）
                {"q": u["add_qty"], "s": u["sku_code"], "loc": u["location_code"],
                 "sec": SECTION_BACKYARD},
            ).rowcount
            if n == 0:
                db.rollback()
                return None
        for a in assignments:
            n = db.execute(
                text("UPDATE order_line SET alloc_location_code = :loc, alloc_status = :done, "
                     "       alloc_qty = :q "
                     " WHERE order_no = :o AND line_no = :ln AND alloc_status = :rel"),
                {"loc": a["location_code"], "done": ALLOC_DONE, "q": a["qty"],
                 "o": order_no, "ln": a["line_no"], "rel": ALLOC_RELEASED},
            ).rowcount
            if n == 0:                          # ★解放済みでない明細を付け替えない（二重引当）
                db.rollback()
                raise ValueError("ERR-1205")

        for sid in short_ids:
            n = db.execute(
                text("UPDATE shipment SET status = :c WHERE id = :s AND status = :short"),
                {"c": shipping.SHIP_CANCELLED, "s": sid, "short": shipping.SHIP_SHORT},
            ).rowcount
            if n == 0:                          # ★先に部分キャンセルされていた
                db.rollback()
                raise ValueError("ERR-1205")

        new_ids = []
        for p in plans:
            res = db.execute(
                text("INSERT INTO shipment (order_no, from_location_code, dest_kind, dest_name, "
                     "  dest_zip, dest_pref_code, dest_address, dest_tel, status, planned_ship_date) "
                     "VALUES (:o, :f, :k, :n, :z, :p, :a, :t, :st, :d)"),
                {"o": order_no, "f": p["from_location_code"], "k": p["dest_kind"],
                 "n": p["dest_name"], "z": p["dest_zip"], "p": p["dest_pref_code"],
                 "a": p["dest_address"], "t": p["dest_tel"], "st": shipping.SHIP_INSTRUCTED,
                 "d": p["planned_ship_date"]},
            )
            sid = int(res.lastrowid)
            new_ids.append(sid)
            for l in p["lines"]:
                db.execute(
                    text("INSERT INTO shipment_line (shipment_id, order_no, line_no, qty) "
                         "VALUES (:s, :o, :ln, :q)"),
                    {"s": sid, "o": order_no, "ln": l["line_no"], "q": l["qty"]},
                )

        after = rederive_order_status(db, order_no, reason="AP-B15 再引当",
                                      changed_by=CHANGED_BY_OPERATOR, operator_id=operator_id)
        head = order_head(db, order_no)
        # ★MSG-05 の続報（「確認の結果は、あらためてご連絡します」と伝えてあるため）
        enqueue_mail(
            db, msg_kind="MSG-05", to_email=str(head["orderer_email"]),
            subject="ご注文の商品の確認結果",
            body=chr(10).join([
                f"{head['orderer_name']} 様", "",
                "先日ご連絡した商品は、別の拠点からお届けできることになりました。", "",
                f"注文番号：{order_no}",
                "発送予定日：" + "、".join(sorted({str(p["planned_ship_date"]) for p in plans})),
            ]),
        )
        op_log(db, operator_id, f"order/{order_no}",
               f"AP-B15 再引当 欠品={short_ids} 新出荷={new_ids}")
        db.commit()
        return {"order_no": order_no, "order_status": after, "cancelled_shipments": short_ids,
                "new_shipments": new_ids}
    except Exception:
        db.rollback()
        raise
