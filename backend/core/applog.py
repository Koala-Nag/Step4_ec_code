# -*- coding: utf-8 -*-
"""アプリケーションログの出口（設計 8.6）。

★N-15 を、人の注意力に頼らない形にする。

    ・ログ出力の入口を1つの関数にし、★許可した項目名の辞書だけを受け取る。
      辞書に無い項目は捨てる
    ・例外は種別と発生位置だけを出し、★例外の文言をそのまま出さない
      （文言に、渡された値がそのまま混ざる）
    ・禁止項目が出力されないことを確かめる試験を CI で走らせる

★「出してはいけないものの一覧」ではなく「出してよいものの一覧」で作る。
  禁止の一覧は、新しい項目が増えるたびに追記が要る。追記を忘れたものが漏れる。
  許可の一覧なら、忘れたものは黙って捨てられる。

★この関数を通さない logging / print は、scripts/check_no_direct_log.py が落とす。
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("ec")

# 8.6「すべてのログに入れる共通項目」＋ 各所で要る識別子。★ここに無い名前は捨てる
ALLOWED_FIELDS = frozenset({
    "request_id",        # 客が「エラーが出た」と言ってきたとき、その1件を引く
    "order_no",          # ★リクエストIDだけでは1回の呼び出しの中しか繋がらない
    "payment_tx_id",     # 決済取引（E-23）の行
    "provider_tx_id",    # 決済代行側の取引ID。相手の管理画面と突き合わせる
    "elapsed_ms",        # 遅さの切り分け
    "instance",          # 複数インスタンスのどれで起きたか
    "run_id",            # 定期処理の1回の実行
    "batch_id",          # B-06〜B-12
    "error_code",        # 8.2 の ERR-xxxx
    "exc_type",          # 例外の種別だけ。★文言は入れない
    "exc_at",            # 発生位置（ファイル:行）
    "status_code",
    "method",
    "path",
    "count",
    "reason_code",       # ★分類された理由。自由文の reason は入れない
})

# ★試験（tests/test_applog.py）が、この名前で漏れを探す
FORBIDDEN_EXAMPLES = ("password", "card_number", "client_token", "session_id", "to_email")


def configure(level: int = logging.INFO) -> None:
    """起動時に1回だけ。★ここ以外で basicConfig を呼ばない。"""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def _instance() -> str:
    return os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("COMPUTERNAME") or "local"


def allowed(fields: dict[str, Any]) -> dict[str, Any]:
    """★許可した項目だけを残す。ここが N-15 の実体。"""
    return {k: v for k, v in fields.items() if k in ALLOWED_FIELDS}


def emit(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """アプリケーションログはすべてここを通す。

    ★`event` は固定の文字列にする。値を混ぜない（f-string で組み立てない）。
    """
    payload = allowed(fields)
    payload["instance"] = _instance()
    log.log(level, "%s %s", event, payload)


def emit_exception(event: str, exc: BaseException, **fields: Any) -> None:
    """例外は★種別と発生位置だけ。文言もスタックの中身も出さない（8.6）。"""
    tb = exc.__traceback__
    at = "-"
    while tb is not None:                       # いちばん奥のフレームを使う
        at = f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}"
        tb = tb.tb_next
    emit(event, level=logging.ERROR, exc_type=type(exc).__name__, exc_at=at, **fields)
