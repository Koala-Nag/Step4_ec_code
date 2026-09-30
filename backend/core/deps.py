# -*- coding: utf-8 -*-
"""リクエストの入口の決めごと（設計 4.1.2）。

    ② フロント層はバックエンドへの全リクエストに X-Internal-Auth と X-Session-Id を付ける
    ④ X-Internal-Auth が無い／合わない → 403 / ERR-1103。★本文を出さない

★ブラウザは Next.js しか呼ばない。CORS は設定しない（足すと直接叩く経路が開く）。
"""
from __future__ import annotations

import hmac

from fastapi import Depends, Header

from core.db import get_db as get_db_dep

from core.config import INTERNAL_AUTH_TOKEN
from core.errors import AppError


def require_internal_auth(
    x_internal_auth: str | None = Header(default=None),
) -> None:
    """サーバ間認証。値の比較は hmac.compare_digest で行う（時間差で漏らさない）。"""
    if not x_internal_auth or not hmac.compare_digest(x_internal_auth, INTERNAL_AUTH_TOKEN):
        raise AppError("ERR-1103")


def cart_key(x_cart_key: str | None = Header(default=None)) -> str | None:
    """カートキー（T-19）。★セッションIDとは別に発行する（09-06 決定）。

    セッションは60分で切れる（SEC-309）が、カートの保持は30日（F-301）。
    セッションIDを流用すると1時間でカートが消えて、要件を満たさない。
    フロント層が別の Cookie で30日持たせ、その値をこのヘッダで渡す。
    """
    return x_cart_key


def session_id(x_session_id: str | None = Header(default=None)) -> str | None:
    """セッションID。★フロント層は中身を解釈しない。ここでも今回は素通しでよい。

    この串（R-13）では会員機能がまだ無いので、受け取るだけ。
    毎回 session テーブルを引き直す決め（4.1.2 ③）は、会員が要る画面から効かせる。
    """
    return x_session_id


# ------------------------------------------------------------
# 会員・運営者（R-21）
# ------------------------------------------------------------
def _session_or_401(db, sid: str | None) -> dict:
    """★毎回 session テーブルを引き直す（4.1.2 ③）。

    ★「無い」と「切れている」を区別しない。どちらも ERR-1101。
      区別すると「そのセッションは在った」を教えることになる。
    """
    from repository import auth as auth_repo

    row = auth_repo.load_session(db, sid)
    if row is None:
        raise AppError("ERR-1101")
    return row


def current_member(
    db=Depends(get_db_dep),
    x_session_id: str | None = Header(default=None),
) -> dict:
    """ログイン必須（4.2 の「会員」）。"""
    from repository import auth as auth_repo

    row = _session_or_401(db, x_session_id)
    if row["user_kind"] != auth_repo.USER_MEMBER or not row["member_id"]:
        # ★運営者のセッションで客のAPIに入れない（SEC-706 の裏返し）
        raise AppError("ERR-1101")
    return {"member_id": row["member_id"], "session_id": row["session_id"]}


def current_operator(
    db=Depends(get_db_dep),
    x_session_id: str | None = Header(default=None),
) -> dict:
    """運営者のみ（4.3）。★客のセッションでは入れない（SEC-706）。"""
    from repository import auth as auth_repo

    row = _session_or_401(db, x_session_id)
    if row["user_kind"] != auth_repo.USER_OPERATOR or not row["operator_id"]:
        raise AppError("ERR-1101")
    op = auth_repo.find_operator(db, row["operator_id"])
    if not op or not op["is_active"]:
        raise AppError("ERR-1101")
    return {**op, "session_id": row["session_id"]}
