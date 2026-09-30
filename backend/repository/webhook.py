# -*- coding: utf-8 -*-
"""通知の記録と「照会要」の印（設計 7.2.4）。"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

TX_INQUIRY = 6   # 照会（7.2.1）
TX_TODO = 4      # 要実行


def remember(db: Session, notification_id: str, payload: dict) -> bool:
    """初めて受けた通知なら True、すでに受けていれば False。

    ★「見てから書く」にしない。INSERT IGNORE の更新件数で判定する。
      同じ通知が同時に2本届いたとき、見てから書くと2本とも通る。
    """
    res = db.execute(
        text(
            "INSERT IGNORE INTO payment_notification "
            "  (notification_id, provider_tx_id, idempotency_key, body) "
            "VALUES (:n, :p, :k, :b)"
        ),
        {
            "n": notification_id,
            "p": payload.get("provider_tx_id"),
            "k": payload.get("idempotency_key"),
            "b": json.dumps(payload, ensure_ascii=False),
        },
    )
    db.commit()
    return res.rowcount == 1


def mark_for_inquiry(db: Session, idempotency_key: str | None,
                     provider_tx_id: str | None) -> bool:
    """その決済取引に「照会要」の印を付ける。

    ★印は「照会（tx_kind=6）の行を『要実行』で1本積む」形にした。
      payment_tx.status に「照会要」の値が無いため（1成功 2失敗 3処理中
      4要実行 5実行中 6取消不要）。新しい状態値を勝手に増やすより、
      すでにある種別と状態の組み合わせで表すほうが安全だと判断した。
      → HANDOFF に「設計側で決めてほしい」として書いた。

    ★ここでは照会しない。B-08 がこの行を拾う（7.2.4）。
    """
    row = db.execute(
        text(
            "SELECT order_no, amount, provider_tx_id FROM payment_tx "
            " WHERE (:k IS NOT NULL AND idempotency_key = :k) "
            "    OR (:p IS NOT NULL AND provider_tx_id = :p) "
            " ORDER BY id DESC LIMIT 1"
        ),
        {"k": idempotency_key, "p": provider_tx_id},
    ).first()
    if row is None:
        # 知らない取引の通知。★捨てるが 200 は返す（相手に再送させない）
        return False

    exists = db.execute(
        text(
            "SELECT 1 FROM payment_tx "
            " WHERE order_no = :o AND tx_kind = :k AND status = :s LIMIT 1"
        ),
        {"o": row.order_no, "k": TX_INQUIRY, "s": TX_TODO},
    ).first()
    if exists:
        db.commit()
        return True   # すでに印がある。増やさない

    db.execute(
        text(
            "INSERT INTO payment_tx (order_no, tx_kind, provider_tx_id, amount, status) "
            "VALUES (:o, :k, :p, :a, :s)"
        ),
        {"o": row.order_no, "k": TX_INQUIRY,
         "p": provider_tx_id or row.provider_tx_id, "a": row.amount, "s": TX_TODO},
    )
    db.commit()
    return True
