# -*- coding: utf-8 -*-
"""AP-T07 止める仕組みの操作口（FT-07。設計 10.2.1）。

★APP_ENV が staging / local のときだけ生やす。本番では 404（設計 2.3・N-31）。
★役割は運用管理者のみ（1227行目）。この串では認証がまだ無いので、
  サーバ間認証（X-Internal-Auth）だけを要求している。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictStr
from sqlalchemy.orm import Session

from core.db import get_db
from core.deps import require_internal_auth
from core.errors import AppError
from external import mailer
from testing import fault, pause

router = APIRouter(prefix="/testing", tags=["testing"])


class PauseBody(BaseModel):
    point: StrictStr
    # arm=止める / release=解除 / clear=消す
    action: StrictStr


@router.put("/pause", dependencies=[Depends(require_internal_auth)])
def set_pause(body: PauseBody, db: Session = Depends(get_db)) -> dict:
    if body.point not in pause.POINTS:
        raise AppError("ERR-1004", {"field": "point", "allowed": list(pause.POINTS)})
    if body.action == "arm":
        pause.arm(db, body.point)
    elif body.action == "release":
        pause.release(db, body.point)
    elif body.action == "clear":
        pause.clear(db, body.point)
    else:
        raise AppError("ERR-1004", {"field": "action"})
    return {"data": {"point": body.point, "action": body.action, "hits": pause.hits(db)}}


@router.get("/pause/hits", dependencies=[Depends(require_internal_auth)])
def get_hits(db: Session = Depends(get_db)) -> dict:
    """★その地点に着いたかを返す。試験側はこれを見てから次を投入する。"""
    return {"data": {"hits": pause.hits(db)}}


class MailScenario(BaseModel):
    scenario: StrictStr


@router.put("/mail/scenario", dependencies=[Depends(require_internal_auth)])
def set_mail_scenario(body: MailScenario) -> dict:
    """AP-T06 メールの挙動を指定する（FT-06）。

    ★9.8 の「3回とも失敗」を作れるようにするため。
    """
    if body.scenario not in mailer.SCENARIOS:
        raise AppError("ERR-1004", {"field": "scenario", "allowed": list(mailer.SCENARIOS)})
    mailer.set_scenario(body.scenario)
    return {"data": {"scenario": body.scenario}}


@router.get("/mail", dependencies=[Depends(require_internal_auth)])
def list_mail(
    db: Session = Depends(get_db),
    to_email: str | None = None,
    msg_kind: str | None = None,
    limit: int = 20,
) -> dict:
    """AP-T04 送ったメールを見る（FT-04）。★本番でも使う。

    ★本文まで返す。宛先も返す。
      「送ったつもり」を確かめる口なので、中身が見えないと意味がない。
      そのぶん、この口は運用管理者だけが使える（権限表 2.4）。
    """
    from sqlalchemy import text as _t

    sql = ("SELECT id, msg_kind, to_email, subject, body, status, attempt_count, "
           "       result, sent_at, next_retry_at "
           "  FROM sent_mail WHERE 1=1")
    params: dict = {"lim": max(1, min(limit, 100))}
    if to_email:
        sql += " AND to_email = :to"
        params["to"] = to_email
    if msg_kind:
        sql += " AND msg_kind = :k"
        params["k"] = msg_kind
    sql += " ORDER BY id DESC LIMIT :lim"
    rows = db.execute(_t(sql), params).all()
    return {"data": {"mails": [dict(r._mapping) for r in rows]}}


class FaultBody(BaseModel):
    point: StrictStr
    # arm=仕掛ける / clear=消す
    action: StrictStr


@router.put("/fault", dependencies=[Depends(require_internal_auth)])
def set_fault(body: FaultBody, db: Session = Depends(get_db)) -> dict:
    """AP-T08 わざと落とす（FT-08。設計 10.2.1）。

    ★IT-407 が確かめたいのは「コミットの直後に落ちたとき、DBに何が残っているか」。
      落ちる場所が1行ずれると、確かめたいものが変わる。だから地点を名前で決める。
    """
    if body.point not in fault.POINTS:
        raise AppError("ERR-1004", {"field": "point", "allowed": list(fault.POINTS)})
    if body.action == "arm":
        fault.arm(db, body.point)
    elif body.action == "clear":
        fault.clear(db, body.point)
    else:
        raise AppError("ERR-1004", {"field": "action"})
    return {"data": {"point": body.point, "action": body.action, "armed": fault.armed(db)}}


@router.get("/fault", dependencies=[Depends(require_internal_auth)])
def get_fault(db: Session = Depends(get_db)) -> dict:
    return {"data": {"armed": fault.armed(db)}}
