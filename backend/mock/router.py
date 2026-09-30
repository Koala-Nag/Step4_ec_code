# -*- coding: utf-8 -*-
"""ダミー決済API（設計 7.2.3）。検証環境だけで動かす。

★クラスのスタブにしない。本当にHTTPで呼ぶ。
  クラスだと、タイムアウトも署名も冪等キーも「偽装」でしか試せない。
  ここを本物のHTTPにしておくと、35秒の打ち切り（7.2.5）も、
  「相手が2回目を実行しない」も、実物で確かめられる。

★「常に成功を返すダミー」にしない。
  異常系を起こせないダミーでは 9.1・9.2・9.8・9.9 のどれも試験できない。
  挙動は AP-T03（FT-03）で指定する。

★署名する。ダミーも本物と同じ鍵で検証する（7.2.4）。
  署名しないダミーは「検証が素通りの、誰でも叩ける公開の口」になる。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.config import APP_ENV, PAYMENT_WEBHOOK_SECRET
from domain import payment_ledger as ledger
from mock import store
from payment.signing import verify

router = APIRouter(prefix="/mock-gateway", tags=["mock-gateway"])

# FT-03 が起こせる挙動
SCENARIOS = (
    "success",          # 通常
    "auth_fail",        # 3Dセキュアの認証失敗
    "auth_abandon",     # 3Dセキュアの離脱
    "authorize_ng",     # 与信NG
    "timeout",          # 応答を返さない（打ち切りの相手）
    "connection_drop",  # 通信断
    "slow",             # 遅いが返る（打ち切りの境目）
)


def _guard_env() -> JSONResponse | None:
    """★本番では動かさない。検証環境だけの口（7.2.3）。"""
    if APP_ENV == "production":
        return JSONResponse(status_code=404, content={"error": {"code": "ERR-1215", "message": ""}})
    return None


async def _verified_body(request: Request) -> tuple[bytes, str | None]:
    """生の本文と、署名の検証結果（駄目なら理由）を返す。"""
    body = await request.body()
    reason = verify(
        PAYMENT_WEBHOOK_SECRET,
        request.headers.get("X-Timestamp"),
        request.headers.get("X-Signature"),
        body,
    )
    return body, reason


def _unauthorized(reason: str) -> JSONResponse:
    # ★理由は返さない。攻める側に手がかりを渡さない
    return JSONResponse(status_code=401, content={"error_code": "SIGNATURE_INVALID"})


async def _apply_scenario(scenario: str) -> JSONResponse | None:
    """待ち・切断を本当に起こす。★ここが「クラスのスタブでは試せない」ところ。"""
    if scenario == "timeout":
        await asyncio.sleep(120)          # こちらの打ち切り（35秒）より確実に長く
        return None
    if scenario == "slow":
        await asyncio.sleep(20)
        return None
    if scenario == "connection_drop":
        # 応答を返さずに切る。502 で「上流が落ちた」を模す
        return JSONResponse(status_code=502, content={"error_code": "UPSTREAM_DOWN"})
    return None


# ------------------------------------------------------------
# 挙動の指定（AP-T03 の受け皿。FT-03）
# ------------------------------------------------------------
@router.post("/_control/scenario")
async def set_scenario(request: Request) -> JSONResponse:
    if (r := _guard_env()) is not None:
        return r
    payload = await request.json()
    name = str(payload.get("scenario", "success"))
    if name not in SCENARIOS:
        return JSONResponse(status_code=400, content={"error_code": "UNKNOWN_SCENARIO",
                                                     "allowed": list(SCENARIOS)})
    store.reset(name)
    return JSONResponse({"scenario": name})


@router.post("/_control/ledger")
async def seed_ledger(request: Request) -> JSONResponse:
    """★試験だけの口。与信を通さずに作った決済取引の行に、ダミー側の与信を置く。

    B-09・B-10 の再送の試験は、DBに直接「要実行」の行を入れる。
    ★ダミーが知らない取引を断るようになったので（7.2.3）、その相手の与信をここで置く。
    """
    if (r := _guard_env()) is not None:
        return r
    body = await request.json()

    def _put(d: dict) -> None:
        d.setdefault("ledger", {})[str(body["provider_tx_id"])] = ledger.to_dict(
            ledger.Authorization(int(body["authorized"]), int(body.get("captured", 0))))

    store.update(_put)
    return JSONResponse({"ok": True})


@router.get("/_control/state")
async def get_state() -> JSONResponse:
    if (r := _guard_env()) is not None:
        return r
    return JSONResponse(store.read())


# ------------------------------------------------------------
# トークン発行（7.2.1。決済取引にはしない）
# ------------------------------------------------------------
@router.post("/tokens")
async def issue_token(request: Request) -> JSONResponse:
    if (r := _guard_env()) is not None:
        return r
    _, reason = await _verified_body(request)
    if reason:
        return _unauthorized(reason)
    return JSONResponse({"client_token": f"tok_{uuid.uuid4().hex[:24]}"})


# ------------------------------------------------------------
# 3Dセキュアの画面（当社を通らない。ブラウザが直接ここへ来る）
# ------------------------------------------------------------
@router.get("/3ds", response_class=HTMLResponse)
async def three_ds(order_no: str, return_url: str) -> HTMLResponse:
    """★本物では決済代行の画面。ここでは押すだけの簡単な画面にする。

    認証の結果（成功／失敗／離脱）は、いま設定されている scenario で決まる。
    ★この結果は「入力」であって判定ではない（7.2.2）。
      バックエンドは必ず与信を呼んで確かめる。
    """
    if (r := _guard_env()) is not None:
        return HTMLResponse("<h1>404</h1>", status_code=404)
    st = store.read()
    scenario = st.get("scenario", "success")
    result = {
        "auth_fail": "failed",
        "auth_abandon": "abandoned",
    }.get(scenario, "succeeded")
    ref = f"3ds_{uuid.uuid4().hex[:20]}"

    store.update(lambda d: d["transactions"].__setitem__(
        ref, {"order_no": order_no, "auth_result": result, "used": False}
    ))

    sep = "&" if "?" in return_url else "?"
    back = f"{return_url}{sep}auth_result={result}&auth_ref={ref}"
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8">
<title>ダミー決済（3Dセキュア）</title>
<body style="font-family:system-ui;max-width:520px;margin:60px auto;line-height:1.9">
<h2>ダミー決済代行</h2>
<p>これは検証用の画面です。実際の決済は行われません。</p>
<p>注文番号：<code>{order_no}</code><br>
   今回の挙動：<b>{scenario}</b> → 認証結果 <b>{result}</b></p>
<p><a href="{back}" style="display:inline-block;background:#1f3864;color:#fff;
   padding:12px 22px;border-radius:6px;text-decoration:none">お店に戻る</a></p>
</body>""")


# ------------------------------------------------------------
# 与信（冪等キーが要る。7.2.1）
# ------------------------------------------------------------
@router.post("/authorize")
async def authorize(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    if (r := _guard_env()) is not None:
        return r
    body, reason = await _verified_body(request)
    if reason:
        return _unauthorized(reason)
    if not idempotency_key:
        return JSONResponse(status_code=400, content={"error_code": "IDEMPOTENCY_KEY_REQUIRED"})

    payload: dict[str, Any] = __import__("json").loads(body or b"{}")
    st = store.read()
    scenario = st.get("scenario", "success")

    # ★冪等。2回目は実行せず、1回目の応答をそのまま返す（IT-510・SEC-409）
    def _check(d: dict) -> Any:
        d["call_count"]["authorize"] = d["call_count"].get("authorize", 0) + 1
        return d["idempotent"].get(idempotency_key)

    cached = store.update(_check)
    if cached is not None:
        return JSONResponse({**cached, "idempotent_replay": True})

    if (early := await _apply_scenario(scenario)) is not None:
        return early

    auth_ref = payload.get("auth_ref")
    auth_ok = False
    if auth_ref:
        tx = st.get("transactions", {}).get(auth_ref)
        # ★認証結果は「その注文のもの」でなければ通さない（7.2.2a ③）
        if tx and tx.get("auth_result") == "succeeded" and tx.get("order_no") == payload.get("order_no"):
            auth_ok = not tx.get("used", False)

    if scenario == "authorize_ng" or not auth_ok:
        result = {
            "status": "declined",
            "provider_tx_id": f"tx_{uuid.uuid4().hex[:20]}",
            "response_code": "AUTH_NG" if scenario == "authorize_ng" else "AUTH_NOT_VERIFIED",
            "amount": payload.get("amount"),
        }
    else:
        result = {
            "status": "approved",
            "provider_tx_id": f"tx_{uuid.uuid4().hex[:20]}",
            "response_code": "OK",
            "amount": payload.get("amount"),
        }

    def _save(d: dict) -> None:
        d["idempotent"][idempotency_key] = result
        if auth_ref and auth_ref in d["transactions"]:
            d["transactions"][auth_ref]["used"] = True   # 使い回しを1回で止める
        if result["status"] == "approved":
            # ★通った与信の額を覚える。売上確定・取消・返金はこれと突き合わせる（7.2.3。R-27）
            d.setdefault("ledger", {})[result["provider_tx_id"]] = ledger.to_dict(
                ledger.Authorization(int(payload.get("amount") or 0)))

    store.update(_save)
    return JSONResponse(result)


# ------------------------------------------------------------
# 売上確定・取消・返金・照会
# ------------------------------------------------------------
async def _simple_op(request: Request, op: str, ok_status: str) -> JSONResponse:
    if (r := _guard_env()) is not None:
        return r
    body, reason = await _verified_body(request)
    if reason:
        return _unauthorized(reason)
    payload: dict[str, Any] = __import__("json").loads(body or b"{}")
    key = request.headers.get("Idempotency-Key")

    st = store.read()
    if (early := await _apply_scenario(st.get("scenario", "success"))) is not None:
        return early

    def _run(d: dict) -> Any:
        d["call_count"][op] = d["call_count"].get(op, 0) + 1
        if key and key in d["idempotent"]:
            return d["idempotent"][key]          # ★冪等。2回目は実行しない（突き合わせもしない）
        tx_id = payload.get("provider_tx_id") or ""
        amount = int(payload.get("amount") or 0)
        ref = payload.get("reference")
        # ★本物が断る条件だけは断る（設計 7.2.3。判定は domain/payment_ledger.py）
        auth = ledger.from_dict(d.setdefault("ledger", {}).get(tx_id))
        why = ledger.refuse_reason(op, auth, amount, ref)
        if why:
            d["call_count"][f"{op}_refused"] = d["call_count"].get(f"{op}_refused", 0) + 1
            res = {"status": "declined", "provider_tx_id": tx_id or None,
                   "response_code": why, "amount": amount}
        else:
            d["ledger"][tx_id] = ledger.to_dict(ledger.apply(op, auth, amount, ref))
            res = {"status": ok_status, "provider_tx_id": tx_id,
                   "response_code": "OK", "amount": amount}
        if key:
            d["idempotent"][key] = res
        return res

    return JSONResponse(store.update(_run))


@router.post("/capture")
async def capture(request: Request) -> JSONResponse:
    return await _simple_op(request, "capture", "captured")


@router.post("/void")
async def void(request: Request) -> JSONResponse:
    return await _simple_op(request, "void", "voided")


@router.post("/refund")
async def refund(request: Request) -> JSONResponse:
    return await _simple_op(request, "refund", "refunded")


@router.post("/inquiry")
async def inquiry(request: Request) -> JSONResponse:
    if (r := _guard_env()) is not None:
        return r
    body, reason = await _verified_body(request)
    if reason:
        return _unauthorized(reason)
    payload = __import__("json").loads(body or b"{}")
    key = payload.get("idempotency_key")
    st = store.read()
    found = st.get("idempotent", {}).get(key)
    if found is None:
        return JSONResponse({"status": "unknown", "response_code": "NOT_FOUND"})
    return JSONResponse({**found, "inquiry": True})


# ------------------------------------------------------------
# 通知を投げる（試験から叩く。7.2.4 の相手）
# ------------------------------------------------------------
@router.post("/_control/notify")
async def send_notification(request: Request) -> JSONResponse:
    """当社の受け口へ、署名つきの通知を投げる。

    ★時刻をずらして投げられるようにしてある（SEC-614「5分より古い通知」の相手）。
    """
    if (r := _guard_env()) is not None:
        return r
    import json as _json

    import httpx

    from payment.signing import sign

    payload = await request.json()
    target = payload.get("target_url", "http://127.0.0.1:8000/webhooks/payment")
    age = int(payload.get("age_seconds", 0))
    notification = payload.get("notification", {})
    notification.setdefault("notification_id", f"ntf_{uuid.uuid4().hex[:16]}")

    raw = _json.dumps(notification, ensure_ascii=False).encode("utf-8")
    ts = str(int(time.time()) - age)
    async with httpx.AsyncClient(timeout=10) as c:
        res = await c.post(
            target,
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Timestamp": ts,
                "X-Signature": sign(PAYMENT_WEBHOOK_SECRET, ts, raw),
            },
        )
    return JSONResponse({"sent": notification, "status_code": res.status_code,
                         "body": res.text[:300]})
