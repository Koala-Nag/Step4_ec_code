# -*- coding: utf-8 -*-
"""FT-07 止める仕組み（設計 10.2.1）。検証環境だけ。

★「秒数を手で数える試験」は再現しない。
  試験側は「その地点に着いたか」を `pause_hit`（E-42）で観測してから次を投入する。

★止める場所は repository/ のトランザクションの中。
  domain/ で止めても、手順6の先勝ち（行ロックの取り合い）は再現できない。

★APP_ENV != staging では pause_point() は何もせずに返る（設計 10.2.1）。
  それでもテーブルは本番にも作る（環境でスキーマを変えない）。
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.config import APP_ENV

# 止められる地点。★名前は勝手に増やさない。増やすなら設計 10.2.1 に足す
POINTS = (
    "before_stock_update",   # 手順6の条件付きUPDATEの直前（IT-405・IT-406）
    "before_coupon_update",  # クーポンの全体上限の直前（IT-413）
)

# 待ちの上限。試験が固まらないように必ず切る
MAX_WAIT_SECONDS = 30


def enabled() -> bool:
    return APP_ENV in ("staging", "local")


def arm(db: Session, point: str) -> None:
    """その地点で止めるように仕掛ける。"""
    db.execute(
        text("INSERT INTO pause_hit (point_name, hit_at, released_at) VALUES (:p, NULL, NULL) "
             "ON DUPLICATE KEY UPDATE hit_at = NULL, released_at = NULL"),
        {"p": point},
    )
    db.commit()


def release(db: Session, point: str) -> None:
    db.execute(
        text("UPDATE pause_hit SET released_at = :t WHERE point_name = :p"),
        {"p": point, "t": datetime.now()},
    )
    db.commit()


def clear(db: Session, point: str | None = None) -> None:
    if point:
        db.execute(text("DELETE FROM pause_hit WHERE point_name = :p"), {"p": point})
    else:
        db.execute(text("DELETE FROM pause_hit"))
    db.commit()


def hits(db: Session) -> list[dict]:
    rows = db.execute(
        text("SELECT point_name, hit_at, released_at FROM pause_hit ORDER BY point_name")
    ).all()
    return [
        {
            "point_name": r.point_name,
            "arrived": r.hit_at is not None,
            "released": r.released_at is not None,
            "hit_at": r.hit_at.isoformat() if r.hit_at else None,
        }
        for r in rows
    ]


def pause_point(db: Session, point: str) -> None:
    """その地点で、解除されるまで待つ。

    ★到達したことを別の接続から見えるように記録してから待つ。
      ここが「秒数を数えない」の要。試験側は hits を見て、着いてから次を投入する。

    ★記録は別の接続で行う。いま開いているトランザクションで書くと、
      コミットするまで試験側から見えず、待っているあいだ永久に見えない。
    """
    if not enabled():
        return

    from core.db import SessionLocal

    marker = SessionLocal()
    try:
        armed = marker.execute(
            text("SELECT hit_at, released_at FROM pause_hit WHERE point_name = :p"), {"p": point}
        ).first()
        if armed is None:
            return                      # 仕掛けられていない。素通り
        if armed.released_at is not None:
            return                      # すでに解除済み

        marker.execute(
            text("UPDATE pause_hit SET hit_at = :t WHERE point_name = :p AND hit_at IS NULL"),
            {"p": point, "t": datetime.now()},
        )
        marker.commit()                 # ★ここで見えるようにする

        deadline = time.time() + MAX_WAIT_SECONDS
        while time.time() < deadline:
            row = marker.execute(
                text("SELECT released_at FROM pause_hit WHERE point_name = :p"), {"p": point}
            ).first()
            marker.commit()             # ★毎回コミットしないと同じ読み取りを見続ける
            if row is None or row.released_at is not None:
                return
            time.sleep(0.05)
    finally:
        marker.close()
