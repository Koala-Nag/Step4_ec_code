# -*- coding: utf-8 -*-
"""AP-T08 わざと落とす仕組み（FT-08。設計 10.2.1）。検証環境だけ。

★IT-407 が確かめたいのは「コミットの直後に落ちたとき、DBに何が残っているか」。
  ★落ちる場所が1行ずれると、確かめたいものが変わってしまう。
    コミットの手前で落ちれば何も残らないし、外部を呼んだあとで落ちれば
    「送ったのに記録が無い」という別の話になる。
  → 落とす地点を名前で決めておく。

★仕掛けは pause（E-42）と同じで DB に置く（10.2.1 の30）。
  プロセスの中に持つと、ワーカが2以上あるとき別のワーカが処理して当たらない。

★1回で消える（armed → 1回落ちたら解除）。
  残ると、そのあとの試験が全部落ちて原因が分からなくなる。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.config import APP_ENV

# 落とせる地点。★勝手に増やさない。増やすなら設計 10.2.1 に足す
POINTS = (
    "after_ship_commit",     # 6.3.1 のコミット直後・手順5の直前（IT-407）
    "capture_send",          # 手順5（売上確定の送信）そのものを失敗させる（IT-408）
)

# ★pause_hit（E-42）を使い回す。point_name に "fault:" を付けて区別する
_PREFIX = "fault:"


class InjectedFault(RuntimeError):
    """わざと起こした失敗。★本物の例外と見分けがつく名前にする。"""


def enabled() -> bool:
    return APP_ENV in ("staging", "local")


def arm(db: Session, point: str) -> None:
    db.execute(
        text("INSERT INTO pause_hit (point_name, hit_at, released_at) VALUES (:p, NULL, NULL) "
             "ON DUPLICATE KEY UPDATE hit_at = NULL, released_at = NULL"),
        {"p": _PREFIX + point},
    )
    db.commit()


def clear(db: Session, point: str | None = None) -> None:
    if point:
        db.execute(text("DELETE FROM pause_hit WHERE point_name = :p"), {"p": _PREFIX + point})
    else:
        db.execute(text("DELETE FROM pause_hit WHERE point_name LIKE :p"), {"p": _PREFIX + "%"})
    db.commit()


def armed(db: Session) -> list[str]:
    rows = db.execute(text("SELECT point_name, hit_at FROM pause_hit WHERE point_name LIKE :p"),
                      {"p": _PREFIX + "%"}).all()
    return [f"{r.point_name[len(_PREFIX):]}{'(発火済)' if r.hit_at else ''}" for r in rows]


def fire(db: Session, point: str) -> None:
    """その地点が仕掛けられていたら例外を投げる。★投げる前に解除する（1回だけ）。

    ★解除を別のトランザクションでやらない。ここは呼び出し側の db をそのまま使う。
      仕掛けを消す UPDATE がロールバックで巻き戻ると、次も落ちて試験が固まる——
      と思ったが、逆。★消すのを先にコミットしてから投げる。
    """
    if not enabled():
        return
    n = db.execute(
        text("UPDATE pause_hit SET hit_at = NOW(3) "
             " WHERE point_name = :p AND hit_at IS NULL"),
        {"p": _PREFIX + point},
    ).rowcount
    db.commit()          # ★先に「使った」を確定させる。残ると次の試験まで落ち続ける
    if n:
        raise InjectedFault(point)
