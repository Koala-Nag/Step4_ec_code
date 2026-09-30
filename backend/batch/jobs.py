# -*- coding: utf-8 -*-
"""定期処理 B-06〜B-11（設計 6.6）。

★すべてに共通する決めごと（6.6）
    ・実行ロック（E-38）を取る。取れなければ何もせず終わる
    ・アプリケーション内のロックは使わない（9.4 の禁止事項。複数インスタンスで効かない）
    ・途中で落ちても次の回でやり直せる形にする。1件ずつコミットする

★「要実行 → 実行中」は条件付きUPDATEで進める。読んでから書かない（6.6.2）。
  更新件数が0なら、他が先に触ったということなので飛ばす。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from core import applog
from batch import lock as block
from external import mailer
from payment import gateway
from repository import shipment as ship_repo

# 7.2.5。「実行中」のままこれを過ぎた行は拾い直す
STUCK_MINUTES = 10
# 9.8。与信の打ち切り
AUTH_CUTOFF_SECONDS = 35
# 6.6。3回失敗で通知
MAX_ATTEMPTS = 3

TX_AUTHORIZE, TX_CAPTURE, TX_REFUND, TX_VOID, TX_INQUIRY = 2, 3, 4, 5, 6
TX_SUCCESS, TX_FAILED, TX_PROCESSING, TX_TODO, TX_RUNNING, TX_NOT_NEEDED = 1, 2, 3, 4, 5, 6

STATUS_AUTHENTICATING, STATUS_AWAITING_PAY, STATUS_ALLOCATED = 2, 3, 5
STATUS_SHIPPED, STATUS_DONE = 9, 10

SHIP_SHIPPED, SHIP_ARRIVED, SHIP_HANDED = 2, 3, 5


@dataclass
class Result:
    name: str
    ran: bool = False           # ロックが取れて動いたか
    processed: int = 0
    notes: list[str] = field(default_factory=list)


def _cfg(db: Session, column: str, default: int) -> int:
    """期限値は販売設定から読む（FT-01。R-33）。引数で渡されたら（試験）そちらを使う。"""
    from repository import settings as settings_repo

    return settings_repo.value(db, column, default)


def _me() -> str:
    return f"inst-{uuid.uuid4().hex[:8]}"


# ------------------------------------------------------------
# B-07  「認証中」30分経過を支払い待ちに
# ------------------------------------------------------------
def b07_expire_authenticating(db: Session, *, minutes: int | None = None) -> Result:
    r = Result("B-07")
    with block.held(db, "B-07", holder=_me()) as got:
        if not got:
            return r
        r.ran = True
        rows = db.execute(
            text("SELECT order_no FROM orders "
                 " WHERE status = :s AND updated_at < NOW(3) - INTERVAL :m MINUTE"),
            {"s": STATUS_AUTHENTICATING, "m": minutes if minutes is not None else _cfg(db, "auth_timeout_min", 30)},
        ).all()
        for row in rows:
            # ★1件ずつコミットする。途中で落ちても次の回で続きから
            db.execute(
                text("UPDATE orders SET status = :to WHERE order_no = :o AND status = :fr"),
                {"o": row.order_no, "fr": STATUS_AUTHENTICATING, "to": STATUS_AWAITING_PAY},
            )
            db.execute(
                text("INSERT INTO order_status_log (order_no, status_from, status_to, changed_by, reason) "
                     "VALUES (:o, :fr, :to, 3, 'B-07 認証中のまま期限超過')"),
                {"o": row.order_no, "fr": STATUS_AUTHENTICATING, "to": STATUS_AWAITING_PAY},
            )
            db.commit()
            # ★6.2.6 支払い待ち＝注文は成立。★B-07 はリクエストを持たないので、注文に控えたカートから消す
            from repository import cart as cart_repo
            cart_repo.remove_ordered(db, row.order_no)
            r.processed += 1
    return r


# ------------------------------------------------------------
# B-08  決済取引の成否確定（1分ごと）
# ------------------------------------------------------------
def b08_confirm_payments(db: Session) -> Result:
    """★2種類を拾う（6.6 の表）。

        ・「処理中」のまま打ち切り時間を過ぎた与信
        ・「照会（tx_kind=6）・要実行」の印（7.2.4 で受け口が付けたもの）

    ★成立していたと確定したら、同じ注文の「取消・要実行」を「取消不要」に変える。
      ★★同じトランザクションで行う（6.6.2）。ここを分けると、
        そのすきまに B-09 が走って、通った与信を消す。
    """
    r = Result("B-08")
    with block.held(db, "B-08", holder=_me()) as got:
        if not got:
            return r
        r.ran = True

        targets = db.execute(
            text(
                "SELECT id, order_no, idempotency_key, tx_kind, amount "
                "  FROM payment_tx "
                " WHERE (tx_kind = :auth AND status = :processing "
                "        AND executed_at < NOW(3) - INTERVAL :sec SECOND) "
                "    OR (tx_kind = :inq  AND status = :todo) "
                " ORDER BY id"
            ),
            {"auth": TX_AUTHORIZE, "processing": TX_PROCESSING, "sec": AUTH_CUTOFF_SECONDS,
             "inq": TX_INQUIRY, "todo": TX_TODO},
        ).all()

        for t in targets:
            key = t.idempotency_key
            if not key and t.tx_kind == TX_INQUIRY:
                # 照会の印には冪等キーが無い。同じ注文の与信のキーを使う
                row = db.execute(
                    text("SELECT idempotency_key FROM payment_tx "
                         " WHERE order_no = :o AND tx_kind = :k ORDER BY id DESC LIMIT 1"),
                    {"o": t.order_no, "k": TX_AUTHORIZE},
                ).first()
                key = row.idempotency_key if row else None
            if not key:
                r.notes.append(f"{t.order_no}: 冪等キーが無く照会できない")
                continue

            # ★外部の呼び出しはトランザクションの外（6.1.2a）
            db.commit()
            try:
                res = gateway.inquiry(idempotency_key=str(key))
            except gateway.GatewayError as e:
                r.notes.append(f"{t.order_no}: 照会できず（{e.kind}）。次の回でやり直す")
                continue

            established = res.status in ("approved", "captured")

            # ★ここから1つのトランザクション（6.6.2）
            if t.tx_kind == TX_INQUIRY:
                db.execute(
                    text("UPDATE payment_tx SET status = :s, response_code = :c WHERE id = :i"),
                    {"i": t.id, "s": TX_SUCCESS, "c": res.response_code},
                )
            db.execute(
                text("UPDATE payment_tx SET status = :s, provider_tx_id = :p, response_code = :c "
                     " WHERE order_no = :o AND tx_kind = :k AND status = :processing"),
                {"o": t.order_no, "k": TX_AUTHORIZE,
                 "s": TX_SUCCESS if established else TX_FAILED,
                 "p": res.provider_tx_id, "c": res.response_code, "processing": TX_PROCESSING},
            )

            if established:
                # ★★通った与信を、あとから来た取消に消させない（6.6.2）
                voided = db.execute(
                    text("UPDATE payment_tx SET status = :notneeded "
                         " WHERE order_no = :o AND tx_kind = :void AND status IN (:todo, :running)"),
                    {"o": t.order_no, "void": TX_VOID, "todo": TX_TODO,
                     "running": TX_RUNNING, "notneeded": TX_NOT_NEEDED},
                )
                if voided.rowcount:
                    r.notes.append(
                        f"{t.order_no}: 与信が成立していたので、取消 {voided.rowcount} 件を「取消不要」にした"
                    )
            db.commit()
            r.processed += 1
    return r


# ------------------------------------------------------------
# B-09 / B-10  再送
# ------------------------------------------------------------
def _retry_transactions(db: Session, *, batch_id: str, tx_kinds: tuple[int, ...],
                        give_up: bool) -> Result:
    """「要実行」と「実行中のまま10分過ぎ」を拾って送り直す。

    ★条件付きUPDATEで「実行中」に変えてから送る。更新件数0なら飛ばす（6.6.2）。
      これが無いと、B-08 が「取消不要」に変えた行を、B-09 が掴んだまま送ってしまう。
    """
    r = Result(batch_id)
    with block.held(db, batch_id, holder=_me()) as got:
        if not got:
            return r
        r.ran = True

        kinds = ",".join(str(k) for k in tx_kinds)
        targets = db.execute(
            text(
                f"SELECT id, order_no, tx_kind, amount, provider_tx_id, idempotency_key, attempt_count, shipment_id "
                f"  FROM payment_tx "
                f" WHERE tx_kind IN ({kinds}) "
                f"   AND (status = :todo "
                f"        OR (status = :running AND started_at < NOW(3) - INTERVAL :m MINUTE)) "
                f" ORDER BY id"
            ),
            {"todo": TX_TODO, "running": TX_RUNNING, "m": STUCK_MINUTES},
        ).all()

        for t in targets:
            # ★掴む。0件なら他が触った（B-08 が「取消不要」にしたなど）ので飛ばす
            claimed = db.execute(
                text("UPDATE payment_tx "
                     "   SET status = :running, started_at = NOW(3), attempt_count = attempt_count + 1 "
                     " WHERE id = :i AND status IN (:todo, :running)"),
                {"i": t.id, "running": TX_RUNNING, "todo": TX_TODO},
            )
            db.commit()
            if claimed.rowcount == 0:
                r.notes.append(f"tx {t.id}: 他が触ったので飛ばした")
                continue

            attempt = int(t.attempt_count) + 1
            try:
                if t.tx_kind == TX_VOID:
                    res = gateway.void(provider_tx_id=str(t.provider_tx_id or ""),
                                       amount=int(t.amount),
                                       idempotency_key=str(t.idempotency_key or uuid.uuid4()))
                elif t.tx_kind == TX_CAPTURE:
                    res = gateway.capture(provider_tx_id=str(t.provider_tx_id or ""),
                                          amount=int(t.amount),
                                          idempotency_key=str(t.idempotency_key or uuid.uuid4()),
                                          reference=f"shipment:{t.shipment_id}" if t.shipment_id else None)
                else:
                    res = gateway.refund(provider_tx_id=str(t.provider_tx_id or ""),
                                         amount=int(t.amount),
                                         idempotency_key=str(t.idempotency_key or uuid.uuid4()))
                ok = res.approved
                code = res.response_code
            except gateway.GatewayError as e:
                ok, code = False, e.kind

            if ok:
                db.execute(text("UPDATE payment_tx SET status = :s, response_code = :c WHERE id = :i"),
                           {"i": t.id, "s": TX_SUCCESS, "c": code})
                r.processed += 1
            elif attempt >= MAX_ATTEMPTS:
                # ★取消は諦めてよい。売上確定は諦めない（6.6 の「B-09 と B-10 を分ける理由」）
                final = TX_FAILED if give_up else TX_TODO
                db.execute(text("UPDATE payment_tx SET status = :s, response_code = :c WHERE id = :i"),
                           {"i": t.id, "s": final, "c": code})
                subject = f"[{batch_id}] {t.order_no} の決済処理が {attempt} 回失敗しました"
                body = (f"注文番号 {t.order_no} / 種別 {t.tx_kind} / 応答 {code}" + chr(10)
                        + ("打ち切りました。手で対応してください。" if give_up
                           else "打ち切らず、次の回も試します。"))
                if give_up:
                    # ★B-09 は3回で打ち切るので、そのとき1通。まとめる必要が無い
                    mailer.notify_admin(db, subject=subject, body=body)
                else:
                    # ★B-10 は打ち切らない（6.6。請求漏れになる）。
                    #   打ち切らない側に「毎回通知」を組み合わせると、
                    #   1分間隔なら1日1440通になる（R-19 で実測した形）。
                    #   ★新しい決めごとを作らず、E-40 のまとめに載せる（8.4・R-21 の回答2）
                    mailer.notify_admin_throttled(
                        db, notify_kind=f"batch:{batch_id}", subject=subject, body=body)
                r.notes.append(f"tx {t.id}: {attempt}回失敗。"
                               + ("打ち切って通知" if give_up else "通知して試し続ける"))
            else:
                db.execute(text("UPDATE payment_tx SET status = :s, response_code = :c WHERE id = :i"),
                           {"i": t.id, "s": TX_TODO, "c": code})
                r.notes.append(f"tx {t.id}: {attempt}回目失敗。次の回でやり直す")
            db.commit()
    return r


def b09_retry_void(db: Session) -> Result:
    """与信取消・返金の再送。★3回失敗で通知して打ち切る。"""
    return _retry_transactions(db, batch_id="B-09", tx_kinds=(TX_VOID, TX_REFUND), give_up=True)


def b10_retry_capture(db: Session) -> Result:
    """売上確定の再送。★打ち切らない（代金が取れなくなるため）。"""
    return _retry_transactions(db, batch_id="B-10", tx_kinds=(TX_CAPTURE,), give_up=False)


# ------------------------------------------------------------
# B-06  到着済 → 注文を完了へ
# ------------------------------------------------------------
def b06_complete_orders(db: Session, *, arrive_days: int | None = None) -> Result:
    """出荷から3日で到着済に。★店舗受取の出荷は対象外（引渡済を到着相当とする）。"""
    r = Result("B-06")
    with block.held(db, "B-06", holder=_me()) as got:
        if not got:
            return r
        r.ran = True

        moved = db.execute(
            text("UPDATE shipment SET status = :arrived, arrived_at = NOW(3) "
                 " WHERE status = :shipped AND dest_kind = 1 "
                 "   AND shipped_at < NOW(3) - INTERVAL :d DAY"),
            {"arrived": SHIP_ARRIVED, "shipped": SHIP_SHIPPED,
             "d": arrive_days if arrive_days is not None else _cfg(db, "arrival_assume_days", 3)},
        )
        db.commit()
        r.notes.append(f"到着済にした出荷: {moved.rowcount} 件")

        # 全出荷が到着済または引渡済になった注文を完了に
        rows = db.execute(
            text("SELECT o.order_no FROM orders o "
                 " WHERE o.status <> :done "
                 "   AND EXISTS (SELECT 1 FROM shipment s WHERE s.order_no = o.order_no) "
                 "   AND NOT EXISTS (SELECT 1 FROM shipment s WHERE s.order_no = o.order_no "
                 "                     AND s.status NOT IN (:arrived, :handed))"),
            {"done": STATUS_DONE, "arrived": SHIP_ARRIVED, "handed": SHIP_HANDED},
        ).all()
        for row in rows:
            db.execute(text("UPDATE orders SET status = :s WHERE order_no = :o"),
                       {"o": row.order_no, "s": STATUS_DONE})
            db.execute(
                text("INSERT INTO order_status_log (order_no, status_from, status_to, changed_by, reason) "
                     "VALUES (:o, NULL, :s, 3, 'B-06 全出荷が到着済／引渡済')"),
                {"o": row.order_no, "s": STATUS_DONE},
            )
            db.commit()
            r.processed += 1
    return r


# ------------------------------------------------------------
# B-11  メールの送信・再送
# ------------------------------------------------------------
def b13_auto_instruct(db: Session, *, limit: int = 50) -> Result:
    """B-13｜引当済の注文に、自動で出荷指示を作る（F-903a・R-34）。5分間隔。

    ★受注担当が押すのを待たない。押し忘れると在庫を押さえたまま止まる（R-34 の①）。
    ★手で押す口（AP-B12）と同じ関数を呼ぶ（10.2.6）。
    ★二重に作らない。「引当済 → 出荷指示済」の条件付きUPDATEで先勝ち（6.2.2）。
      負けた側（手で押された／別ワーカが取った）は ERR-1205 になるので、数えて次へ進む。
    ★1件が失敗しても、ほかの注文は進める（1件の設定ミスで全部止めない）。
    """
    r = Result("B-13")
    with block.held(db, "B-13", holder=_me()) as got:
        if not got:
            return r                      # ★取れなければ何もしない（6.6.1）
        r.ran = True
        taken = 0
        for order_no in ship_repo.orders_ready_for_instruction(db, limit=limit):
            try:
                made = ship_repo.instruct(db, order_no, operator_id=None,
                                          reason="B-13 出荷指示の自動作成")
            except ship_repo.AlreadyInstructed:
                db.rollback()
                taken += 1              # ★先に誰かが作った。異常ではない
                continue
            except ValueError as e:
                db.rollback()
                # ★作れなかった（拠点の営業日設定が不正など）。★1件で止めず、次の注文へ
                applog.emit("batch.instruct_failed", order_no=order_no, reason_code=str(e))
                r.notes.append(f"{order_no}:{e}")
                continue
            r.processed += 1
            applog.emit("batch.instructed", order_no=order_no, count=len(made))
        if taken:
            r.notes.append(f"先に取られた {taken} 件")
    return r


def b11_send_mail(db: Session) -> Result:
    """★リクエストの中で再送を待たない（7.3）。ここがまとめて送る。"""
    r = Result("B-11")
    with block.held(db, "B-11", holder=_me()) as got:
        if not got:
            return r
        r.ran = True
        r.processed, notes = mailer.flush(db)
        r.notes.extend(notes)
    return r


def b12_heartbeat(db: Session) -> Result:
    """B-12｜生存通知（8.4）。★1日1回。異常が無くても1通出す。

    ★届かない日があれば、通知経路そのものが壊れていると分かる。
    ★ほかの定期処理と同じ形（ロックを取る・Result を返す）にそろえた（R-35）。
    """
    r = Result("B-12")
    with block.held(db, "B-12", holder=_me()) as got:
        if not got:
            return r
        r.ran = True
        r.processed = mailer.b12_heartbeat(db)
    return r


def b04_clean_carts(db: Session, *, keep_days: int | None = None) -> Result:
    """B-04｜保持期間を過ぎたカート明細を消す（F-301・6.2 の表）。1時間ごと。R-36。

    ★日数は販売設定（sales_config.cart_keep_days）から読む。定数にしない（FT-01）。
    ★会員のカートもゲストのカートも同じ（キーの持ち主で扱いを変えない）。
    ★明細が1つも残らなかったカートは、適用中のクーポン（cart_coupon）も外す——
      残すと、次に商品を入れたときに「前に適用したクーポン」が生きているように見える。
    """
    r = Result("B-04")
    with block.held(db, "B-04", holder=_me()) as got:
        if not got:
            return r
        r.ran = True
        days = keep_days if keep_days is not None else _cfg(db, "cart_keep_days", 30)
        keys = [x.cart_key for x in db.execute(
            text("SELECT DISTINCT cart_key FROM cart WHERE added_at < NOW(3) - INTERVAL :d DAY"),
            {"d": days}).all()]
        n = db.execute(text("DELETE FROM cart WHERE added_at < NOW(3) - INTERVAL :d DAY"),
                       {"d": days}).rowcount
        empty = 0
        for k in keys:
            left = db.execute(text("SELECT 1 FROM cart WHERE cart_key = :k LIMIT 1"), {"k": k}).first()
            if left is None:
                empty += db.execute(text("DELETE FROM cart_coupon WHERE cart_key = :k"), {"k": k}).rowcount
        db.commit()
        r.processed = int(n)
        if empty:
            r.notes.append(f"空になったカートのクーポンを外した {empty} 件")
        if n:
            applog.emit("batch.cart_cleaned", count=int(n))
    return r
