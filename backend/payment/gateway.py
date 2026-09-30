# -*- coding: utf-8 -*-
"""決済代行を呼ぶ口（設計 7.2.3）。

★呼ぶ側は、本物が動いているかダミーが動いているかを知らない。
  切り替えは PAYMENT_BASE_URL を変えるだけ。★コードの分岐にしない。

★打ち切りは 7.2.5 の表のとおり。
  与信だけ長い（その場で客を待たせているため）。裏で動くものは短くして、やり直す。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from core.config import PAYMENT_BASE_URL, PAYMENT_WEBHOOK_SECRET
from payment.signing import now_timestamp, sign

# 7.2.5。接続の確立は共通5秒
CONNECT_TIMEOUT = 5.0
TIMEOUTS = {
    "authorize": 30.0,   # 与信。接続5＋読み取り30＝最大35秒
    "capture": 10.0,
    "void": 10.0,
    "refund": 10.0,
    "inquiry": 10.0,
    "token": 5.0,
}


class GatewayError(Exception):
    """決済代行を呼べなかった／応答が読めなかった。

    ★「与信が通らなかった」とは別物。
      通らなかったのは結果が返ってきている。こちらは結果が分からない（9.8）。
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(kind)
        self.kind = kind          # timeout / network / bad_response / http_error
        self.detail = detail


@dataclass(frozen=True)
class GatewayResult:
    status: str                   # approved / declined / captured / voided / refunded / unknown
    provider_tx_id: str | None
    response_code: str | None
    raw: dict[str, Any]

    @property
    def approved(self) -> bool:
        return self.status in ("approved", "captured", "voided", "refunded")


def _headers(body: bytes, idempotency_key: str | None) -> dict[str, str]:
    ts = now_timestamp()
    h = {
        "Content-Type": "application/json",
        "X-Timestamp": ts,
        # ★ダミーにも本物と同じ鍵で署名する（7.2.4）
        "X-Signature": sign(PAYMENT_WEBHOOK_SECRET, ts, body),
    }
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    return h


def _call(path: str, payload: dict[str, Any], *, op: str,
          idempotency_key: str | None = None) -> GatewayResult:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timeout = httpx.Timeout(TIMEOUTS[op], connect=CONNECT_TIMEOUT)
    url = f"{PAYMENT_BASE_URL.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=timeout) as c:
            res = c.post(url, content=body, headers=_headers(body, idempotency_key))
    except httpx.TimeoutException as e:
        raise GatewayError("timeout", str(e)) from None
    except httpx.HTTPError as e:
        raise GatewayError("network", str(e)) from None

    if res.status_code >= 500:
        raise GatewayError("http_error", f"status={res.status_code}")
    try:
        data = res.json()
    except ValueError:
        raise GatewayError("bad_response", res.text[:200]) from None

    if res.status_code >= 400:
        raise GatewayError("http_error", str(data)[:200])

    return GatewayResult(
        status=str(data.get("status", "unknown")),
        provider_tx_id=data.get("provider_tx_id"),
        response_code=data.get("response_code"),
        raw=data,
    )


# ------------------------------------------------------------
# 7.2.1 の7種類。★認証はブラウザ側なので、ここには無い
# ------------------------------------------------------------
def issue_token(order_no: str, amount: int) -> str:
    r = _call("/tokens", {"order_no": order_no, "amount": amount}, op="token")
    return str(r.raw.get("client_token", ""))


def authorize(*, order_no: str, amount: int, auth_ref: str | None,
              idempotency_key: str) -> GatewayResult:
    """与信。★冪等キーは必須（N-40）。"""
    return _call(
        "/authorize",
        {"order_no": order_no, "amount": amount, "auth_ref": auth_ref},
        op="authorize",
        idempotency_key=idempotency_key,
    )


def capture(*, provider_tx_id: str, amount: int, idempotency_key: str,
            reference: str | None = None) -> GatewayResult:
    """reference は「どの出荷の確定か」（BR-17e 1出荷に1件）。相手はこれで2回目を断る。"""
    payload: dict[str, Any] = {"provider_tx_id": provider_tx_id, "amount": amount}
    if reference:
        payload["reference"] = reference
    return _call("/capture", payload, op="capture", idempotency_key=idempotency_key)


def void(*, provider_tx_id: str, amount: int, idempotency_key: str) -> GatewayResult:
    return _call("/void", {"provider_tx_id": provider_tx_id, "amount": amount},
                 op="void", idempotency_key=idempotency_key)


def refund(*, provider_tx_id: str, amount: int, idempotency_key: str) -> GatewayResult:
    return _call("/refund", {"provider_tx_id": provider_tx_id, "amount": amount},
                 op="refund", idempotency_key=idempotency_key)


def inquiry(*, idempotency_key: str) -> GatewayResult:
    return _call("/inquiry", {"idempotency_key": idempotency_key}, op="inquiry")


def three_ds_url(order_no: str, return_url: str) -> str:
    """ブラウザが行く先。★当社を通らない（N-21・CON-08）。"""
    from urllib.parse import quote

    return (
        f"{PAYMENT_BASE_URL.rstrip('/')}/3ds"
        f"?order_no={quote(order_no)}&return_url={quote(return_url, safe='')}"
    )
