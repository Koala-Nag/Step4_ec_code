# -*- coding: utf-8 -*-
"""非同期通知の受け口（設計 7.2.4）。

★通知は「きっかけ」であって「正」ではない。

    ① 署名を検証する。合わなければ 401 で捨てる
    ② 通知IDを保存する。すでにあれば 200 を返して何もしない（重複対策）
    ③ その決済取引に「照会要」の印を付けて 200 を返す
    ★ 受け口は照会しない。ここで終わり
    → 照会は B-08 だけが行う（1分ごと）。照会の結果で状態を決める

★受け口が自分で照会しない理由。
  B-08 は実行ロック（E-38）を取るが、受け口は取らない。
  受け口が照会すると、同じ取引に照会が2本走り、6.6.2 の書き換えが二重に走る。

★認証はしない。セッションも要らない。署名だけで判断する。
  決済代行はこちらのセッションを持っていない。
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from core import applog
from core.config import PAYMENT_WEBHOOK_SECRET
from core.db import get_db
from payment.signing import verify
from repository import webhook as repo

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
# ★ログはすべて applog.emit を通す（8.6・N-15）


@router.post("/payment")
async def payment_webhook(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    body = await request.body()

    # ① 署名。★生のバイト列に対して検証する（組み直すと一致しなくなる）
    reason = verify(
        PAYMENT_WEBHOOK_SECRET,
        request.headers.get("X-Timestamp"),
        request.headers.get("X-Signature"),
        body,
    )
    if reason:
        # ★理由は返さない。ログにだけ残す（SEC-614・615）
        # ★理由の文言はそのまま出さない。分類した符号だけ（8.6）
        applog.emit("webhook.rejected", level=logging.WARNING, error_code="ERR-1103",
                    reason_code="signature")
        return JSONResponse(status_code=401, content={"error": {"code": "ERR-1103", "message": ""}})

    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        applog.emit("webhook.rejected", level=logging.WARNING, error_code="ERR-1002",
                    reason_code="malformed_body")
        return JSONResponse(status_code=400, content={"error": {"code": "ERR-1002", "message": ""}})

    notification_id = str(payload.get("notification_id") or "")
    if not notification_id:
        return JSONResponse(status_code=400, content={"error": {"code": "ERR-1001", "message": ""}})

    # ② 重複。すでにあれば何もしないで 200
    if not repo.remember(db, notification_id, payload):
        return JSONResponse({"data": {"accepted": True, "duplicate": True}})

    # ③ 「照会要」の印を付けるだけ。★ここで照会しない
    marked = repo.mark_for_inquiry(db, payload.get("idempotency_key"), payload.get("provider_tx_id"))
    return JSONResponse({"data": {"accepted": True, "duplicate": False, "marked": marked}})
