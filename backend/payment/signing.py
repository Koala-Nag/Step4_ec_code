# -*- coding: utf-8 -*-
"""決済代行とのやりとりの署名（設計 7.2.4）。

    方式   HMAC-SHA256
    鍵     アプリ設定（Key Vault 参照）。★ダミーも本物と同じ鍵で署名する
           署名しないダミーにすると、検証が素通りの「誰でも叩ける公開の口」になる
    古さ   5分以上古いものは捨てる（同じ通知を後から投げ直されないため）

★署名の対象は「時刻 + '.' + 本文そのもの」。
  JSONを組み直してから署名すると、キーの順や空白の違いで一致しなくなる。
  受け側は必ず生のバイト列に対して検証する。
"""
from __future__ import annotations

import hashlib
import hmac
import time

# 7.2.4。これより古い署名は受けない
MAX_SKEW_SECONDS = 300


def sign(secret: str, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str | None, signature: str | None, body: bytes) -> str | None:
    """検証。通れば None、駄目なら理由を返す。

    ★理由は呼び出し側のログにだけ出す。応答には出さない（8.2 ERR-1103 と同じ考え）。
    """
    if not timestamp or not signature:
        return "署名または時刻が無い"
    try:
        ts = int(timestamp)
    except ValueError:
        return "時刻が数値でない"
    if abs(int(time.time()) - ts) > MAX_SKEW_SECONDS:
        return f"{MAX_SKEW_SECONDS}秒より古い（投げ直しの疑い）"
    expected = sign(secret, timestamp, body)
    # ★compare_digest。1バイトずつ返す比較にすると、時間差で正解を探られる
    if not hmac.compare_digest(expected, signature):
        return "署名が合わない"
    return None


def now_timestamp() -> str:
    return str(int(time.time()))
