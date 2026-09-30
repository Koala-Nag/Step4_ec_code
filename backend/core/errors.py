# -*- coding: utf-8 -*-
"""エラーの形を1か所に決める（設計 4.1.4・8.2）。

    失敗   { "error": { "code": "ERR-xxxx", "message": "...", "detail": {...} } }

★バックエンドの例外をそのまま出さない（IT-207・SEC-611）。
  想定外の例外も、ここで ERR-1401 に包んでからJSONにする。
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# ★8.2 の表と同じ集合（R-28）。★どちらか片方にしか無いコードがあれば CI が落ちる
#   （scripts/check_error_codes.py・設計 10.2.11）。
#   ★エラーコードは「表に足してから実装する」。ここで採番しない。
#   まだ投げる場所が無いコード（Should 以降の機能のもの）も、表にあるので載せておく。
MESSAGES: dict[str, str] = {
    # 10xx 入力の誤り
    "ERR-1001": "入力してください",
    "ERR-1002": "形式が正しくありません",
    "ERR-1003": "入力できる範囲を超えています",
    "ERR-1004": "選択し直してください",
    # 11xx 認証・認可
    "ERR-1101": "ログインしてください",
    "ERR-1102": "この操作は行えません",
    "ERR-1103": "",                    # サーバ間認証の失敗。客には出さない
    # ★未登録・パスワード誤り・ロック中の3つを、ここに統合している（8.3.1・N-23）。
    #   ロック中だけ別の文言にすると、そのアドレスが登録済みだと分かる（ERR-1105 は廃止）
    "ERR-1104": "メールアドレスまたはパスワードが違います",
    "ERR-1106": "この拠点の情報は表示できません",
    "ERR-1107": "注文番号またはメールアドレスが一致しません",
    # 12xx 業務上できない
    "ERR-1201": "在庫を確保できませんでした。決済は行われていません",
    "ERR-1202": "これ以上追加できません",
    # クーポン（BR-16・BR-16a・要件 9.5）。★R-24 で独自に 1210〜1214 を採番していたのを 8.2 に合わせた（R-28）
    "ERR-1203": "このクーポンは使えません",                  # 存在しない
    "ERR-1211": "このクーポンは期限が切れています",          # 期間外
    "ERR-1212": "あと少しのお買い上げで使えます",            # 最低購入金額。★detail.shortfall に不足額
    "ERR-1213": "このクーポンは配布数の上限に達しました",    # 全体上限
    "ERR-1214": "このクーポンはすでにご利用済みです",        # 自分の上限
    "ERR-1204": "返品の受付期間を過ぎています",
    "ERR-1205": "この注文は現在の状態では操作できません",
    "ERR-1206": "お支払いを確認できませんでした",
    "ERR-1207": "商品の内容が変わりました。ご確認ください",
    "ERR-1208": "引当済の数量を下回る値は設定できません",
    "ERR-1209": "処理中です。しばらくしてからお試しください",
    "ERR-1210": "お手続き中のご注文があるため退会できません",
    "ERR-1215": "ページが見つかりません",
    "ERR-1216": "すでに登録されています",                    # 運営者向け
    "ERR-1217": "使われているため削除できません。無効にしてください",   # 運営者向け
    # 13xx 外部サービス
    "ERR-1301": "お支払いの結果を確認しています",
    "ERR-1302": "お支払いを確認できませんでした",
    "ERR-1303": "ログインできませんでした",
    # 14xx システム。★客に見せる文言を1種類にする（8.2）
    "ERR-1401": "エラーが発生しました。時間をおいてお試しください",
    "ERR-1402": "エラーが発生しました。時間をおいてお試しください",
}

STATUS: dict[str, int] = {
    "ERR-1001": 400, "ERR-1002": 400, "ERR-1003": 400, "ERR-1004": 400,
    "ERR-1101": 401, "ERR-1102": 403, "ERR-1103": 403, "ERR-1104": 401,
    "ERR-1106": 403, "ERR-1107": 429,
    "ERR-1201": 409, "ERR-1202": 409, "ERR-1203": 409, "ERR-1204": 409, "ERR-1205": 409,
    "ERR-1206": 409, "ERR-1207": 409, "ERR-1208": 409, "ERR-1209": 409, "ERR-1210": 409,
    "ERR-1211": 409, "ERR-1212": 409, "ERR-1213": 409, "ERR-1214": 409, "ERR-1215": 404,
    "ERR-1216": 409, "ERR-1217": 409,
    "ERR-1301": 503, "ERR-1302": 503, "ERR-1303": 503,
    "ERR-1401": 500, "ERR-1402": 500,
}


class AppError(Exception):
    """業務上の失敗。コードだけを投げ、文言は 8.2 の表から引く。"""

    def __init__(self, code: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def error_body(code: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": MESSAGES.get(code, "")}
    if detail:
        body["detail"] = detail
    return {"error": body}


def error_response(code: str, detail: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(status_code=STATUS.get(code, 500), content=error_body(code, detail))


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.code, exc.detail)


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """想定外の例外。★中身を客に出さない（SEC-611）。ログにだけ残す。"""
    from core import applog

    # ★例外の種別と発生位置だけ。文言を出すと、渡された値がそのまま混ざる（8.6）
    applog.emit_exception("unhandled", exc, method=request.method, path=request.url.path,
                          error_code="ERR-1401")
    return error_response("ERR-1401")


async def validation_handler(request: Request, exc) -> JSONResponse:
    """入力の型・形が違う（SEC-405）。

    ★FastAPI 既定の 422 と、その detail（どの型を期待したか）を外に出さない。
      8.2 の ERR-1002「形式が正しくありません」に寄せる。
    """
    fields = []
    for e in getattr(exc, "errors", lambda: [])():
        loc = [str(x) for x in e.get("loc", []) if x not in ("body", "query", "path")]
        if loc:
            fields.append(".".join(loc))
    return error_response("ERR-1002", {"fields": fields} if fields else None)
