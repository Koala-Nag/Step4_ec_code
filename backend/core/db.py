# -*- coding: utf-8 -*-
"""DB接続。ORM を使い、SQLは文字列連結で組まない（N-32）。"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from core.config import DATABASE_URL, DB_SSL, DB_SSL_CA, DB_TIME_ZONE

def _connect_args() -> dict:
    """TLS（R-35）。★Azure Database for MySQL は必須。手元の Docker では付けない。

    ★DB_SSL_CA を指定すればその証明書で検証し、空なら PyMySQL 既定の検証で TLS を張る。
    """
    if not DB_SSL:
        return {}
    return {"ssl": {"ca": DB_SSL_CA} if DB_SSL_CA else {}}


# ★つなぎ先で既定が違うものを、この接続だけそろえる（R-35・R-37）。
#   ★サーバのパラメータは触らない（共有サーバでは他の人に効いてしまう）。
#   ★接続を作り直しても必ず流れる（プールが新しい接続を開くたびに走る）。
NEEDED_SQL_MODES = ("NO_ENGINE_SUBSTITUTION",)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True,
                       connect_args=_connect_args())


@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, _record) -> None:
    """時刻帯と sql_mode を、つないだ直後にそろえる。

    ★sql_mode は「丸ごと置き換えない」。いま効いているものに足りないぶんだけ足す——
      置き換えると、つなぎ先が持っていた他の既定（STRICT など）まで落としてしまう。
    """
    with dbapi_conn.cursor() as cur:
        if DB_TIME_ZONE:
            # ★アプリ側で時刻を足し引きしない。DB に JST で話させる（Azure の既定は UTC）
            cur.execute("SET time_zone = %s", (DB_TIME_ZONE,))
        cur.execute("SELECT @@SESSION.sql_mode")
        current = (cur.fetchone()[0] or "").split(",")
        missing = [m for m in NEEDED_SQL_MODES if m not in current]
        if missing:
            cur.execute("SET SESSION sql_mode = %s", (",".join([m for m in current if m] + missing),))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
