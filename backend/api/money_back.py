# -*- coding: utf-8 -*-
"""積んだ取消・返金を、コミットのあとで1回だけ送ってみる（6.3.1・7.2.5）。

★「送る」は外、「積む」は中。ここは「外」のほう。
  送れなくても何もしない——「要実行」に戻しておけば B-09 が拾い直す。
★掴むのは条件付きUPDATE（要実行 → 実行中）。B-09 と同時に掴んでも、片方しか送らない（6.6.2）。

★AP-B14（運営のキャンセル）・AP-303（客のキャンセル）・AP-B16（部分キャンセル）の3つが使う。
  入口ごとに送り方を書かない（10.2.6）。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from core import applog
from payment import gateway

TX_REFUND, TX_VOID = 4, 5
TX_SUCCESS, TX_TODO, TX_RUNNING = 1, 4, 5


def send_now(db: Session, tx_ids: list[int | None]) -> list[dict]:
    out: list[dict] = []
    for tx_id in [t for t in tx_ids if t]:
        claimed = db.execute(
            text("UPDATE payment_tx SET status = :run, started_at = NOW(3), "
                 "       attempt_count = attempt_count + 1 "
                 " WHERE id = :i AND status = :todo"),
            {"i": tx_id, "run": TX_RUNNING, "todo": TX_TODO},
        ).rowcount
        db.commit()
        if claimed == 0:
            out.append({"tx_id": tx_id, "sent": False, "note": "他が掴んだ"})
            continue
        t = db.execute(
            text("SELECT tx_kind, provider_tx_id, amount, idempotency_key FROM payment_tx "
                 " WHERE id = :i"), {"i": tx_id}).first()
        send = gateway.refund if int(t.tx_kind) == TX_REFUND else gateway.void
        ok, code = False, None
        try:
            r = send(provider_tx_id=str(t.provider_tx_id or ""), amount=int(t.amount),
                     idempotency_key=str(t.idempotency_key))
            ok, code = r.approved, r.response_code
        except gateway.GatewayError as e:
            ok, code = False, e.kind
        # ★失敗したら「要実行」に戻す。B-09 が拾う（3回で打ち切って通知）
        db.execute(text("UPDATE payment_tx SET status = :s, response_code = :c WHERE id = :i"),
                   {"i": tx_id, "s": TX_SUCCESS if ok else TX_TODO, "c": code})
        db.commit()
        applog.emit("payment.money_back", payment_tx_id=tx_id, reason_code=code)
        out.append({"tx_id": tx_id, "kind": "refund" if int(t.tx_kind) == TX_REFUND else "void",
                    "amount": int(t.amount), "sent": ok, "response_code": code})
    return out
