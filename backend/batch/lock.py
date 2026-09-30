# -*- coding: utf-8 -*-
"""定期処理の実行ロック（E-38 `batch_lock`。設計 6.6.1）。

★期限（`expires_at`）を持つ。落ちたプロセスのロックを次回が奪えるようにするため。
  期限が無いと、途中で落ちた定期処理は再起動しても永久に動かない。

★取るのも解放するのも条件付きUPDATE1本。
  「読んで、空いていたら書く」にすると、そのあいだに2本目が入る。
  引当（6.2.1 手順6）とまったく同じ形。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def acquire(db: Session, batch_id: str, *, holder: str, ttl_minutes: int = 30) -> bool:
    """取れたら True。★更新件数で判定する。読んでから書かない。

    取れる条件は2つのどちらか。
      ・空いている（status = 0）
      ・実行中だが期限を過ぎている（落ちたプロセスのぶん。6.6.1）
    """
    res = db.execute(
        text(
            "UPDATE batch_lock "
            "   SET holder = :h, acquired_at = NOW(3), "
            "       expires_at = NOW(3) + INTERVAL :ttl MINUTE, status = 1 "
            " WHERE batch_id = :b "
            "   AND (status = 0 OR expires_at IS NULL OR expires_at < NOW(3))"
        ),
        {"b": batch_id, "h": holder, "ttl": ttl_minutes},
    )
    db.commit()
    return res.rowcount == 1


def release(db: Session, batch_id: str, *, holder: str) -> bool:
    """解放。★自分が持っているときだけ解放する。

    奪われたあとに自分が解放すると、奪った側のロックを消してしまう。
    """
    res = db.execute(
        text(
            "UPDATE batch_lock SET holder = NULL, expires_at = NULL, status = 0 "
            " WHERE batch_id = :b AND holder = :h AND status = 1"
        ),
        {"b": batch_id, "h": holder},
    )
    db.commit()
    return res.rowcount == 1


def state(db: Session, batch_id: str) -> dict | None:
    row = db.execute(
        text("SELECT batch_id, holder, acquired_at, expires_at, status "
             "FROM batch_lock WHERE batch_id = :b"),
        {"b": batch_id},
    ).first()
    return dict(row._mapping) if row else None


class held:
    """with 文で使う。取れなければ入らない。

        with held(db, "B-08", holder=me) as got:
            if not got:
                return          # 他が動いている
            ...
    """

    def __init__(self, db: Session, batch_id: str, *, holder: str, ttl_minutes: int = 30) -> None:
        self.db = db
        self.batch_id = batch_id
        self.holder = holder
        self.ttl = ttl_minutes
        self.got = False

    def __enter__(self) -> bool:
        self.got = acquire(self.db, self.batch_id, holder=self.holder, ttl_minutes=self.ttl)
        return self.got

    def __exit__(self, *exc: object) -> None:
        if self.got:
            release(self.db, self.batch_id, holder=self.holder)
