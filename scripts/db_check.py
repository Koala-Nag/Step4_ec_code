# -*- coding: utf-8 -*-
"""つなぎ先のMySQLが、こちらの前提どおりかを見る（R-35 ②）。

★見るのは4つ（依頼の「見たいのはこの4つ」）。
  ① time_zone        Azure の既定は UTC。BR-18（返品17日）と BR-23（締め時刻）が9時間ずれる
  ② 文字集合・照合順序 サーバ既定が違うと日本語が二重エンコードになる（R-07 で1回踏んだ）
  ③ sql_mode         引当のSQLを「引き算しない」形にした理由（3.2.2 ①）。STRICT が要る
  ④ 台帳             ddl/ と migrations/ が流れているか（2.2.1）

使い方（ec/ で）
    backend/.venv/Scripts/python scripts/db_check.py                 … .env の接続先
    ENV_FILE=.env.azure backend/.venv/Scripts/python scripts/db_check.py  … 別の接続先

★秘密は出さない。ホストとユーザ名も出さない（値の比較だけを出す）。
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv           # noqa: E402
from sqlalchemy import create_engine, event, text   # noqa: E402
from sqlalchemy.engine import URL as SAURL   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / os.getenv("ENV_FILE", ".env"), override=True)

NAME = os.getenv("DB_NAME", "ec_koala")
# ★パスワードを接続文字列に埋め込まない（設計 2.3a。R-36）。記号が入っていても壊れない
URL = SAURL.create("mysql+pymysql", username=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
                   host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", "3306")),
                   database=NAME, query={"charset": "utf8mb4"})
ARGS: dict = {}
tz = os.getenv("DB_TIME_ZONE", "").strip()
if os.getenv("DB_SSL", "0") == "1":
    ca = os.getenv("DB_SSL_CA", "").strip()
    if ca and not pathlib.Path(ca).is_absolute():
        ca = str(ROOT / ca)          # ★相対パスは ec/ から解く
    ARGS["ssl"] = {"ca": ca} if ca else {}      # ★上書きしない（時刻帯の指定を消さない）

WANT = {
    "time_zone": "+09:00",
    "character_set_database": "utf8mb4",
    "collation_database": "utf8mb4_0900_ai_ci",
}
WANT_IN_SQL_MODE = ("STRICT_TRANS_TABLES", "ONLY_FULL_GROUP_BY", "NO_ZERO_DATE")

engine = create_engine(URL, pool_pre_ping=True, future=True, connect_args=ARGS)


@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, _record) -> None:
    """★アプリ（backend/core/db.py）と同じことをする。確認の道具だけ違う接続をしない。"""
    with dbapi_conn.cursor() as cur:
        if tz:
            cur.execute("SET time_zone = %s", (tz,))
        cur.execute("SELECT @@SESSION.sql_mode")
        cur_modes = (cur.fetchone()[0] or "").split(",")
        missing = [m for m in ("NO_ENGINE_SUBSTITUTION",) if m not in cur_modes]
        if missing:
            cur.execute("SET SESSION sql_mode = %s", (",".join([m for m in cur_modes if m] + missing),))
rc = 0
with engine.connect() as c:
    row = c.execute(text(
        "SELECT VERSION() v, @@time_zone tz, @@system_time_zone stz, @@sql_mode sm, "
        "       @@character_set_server css, @@collation_server cos, "
        "       @@character_set_database csd, @@collation_database cod")).first()
    vals = {"version": row.v, "time_zone": row.tz, "system_time_zone": row.stz,
            "character_set_server": row.css, "collation_server": row.cos,
            "character_set_database": row.csd, "collation_database": row.cod}
    tables = c.execute(text("SELECT COUNT(*) n FROM information_schema.tables "
                            " WHERE table_schema = :d"), {"d": NAME}).first().n
    try:
        vers = [r.version for r in c.execute(text("SELECT version FROM schema_migration ORDER BY version")).all()]
    except Exception:                                   # noqa: BLE001
        vers = []
    ssl_cipher = c.execute(text("SHOW STATUS LIKE 'Ssl_cipher'")).first()

print(f"データベース : {NAME}")
print(f"TLS          : {'あり（' + ssl_cipher[1] + '）' if ssl_cipher and ssl_cipher[1] else 'なし'}")
for k, v in vals.items():
    mark = ""
    if k in WANT:
        ok = str(v) == WANT[k]
        mark = "  [OK]" if ok else f"  [NG] 期待 {WANT[k]}"
        rc |= 0 if ok else 1
    print(f"{k:24}: {v}{mark}")
missing = [m for m in WANT_IN_SQL_MODE if m not in (vals.get("sql_mode") or str(row.sm))]
print(f"{'sql_mode':24}: {row.sm}")
print(f"{'  必須のモード':24}: {'[OK] 全部ある' if not missing else '[NG] 足りない ' + ','.join(missing)}")
rc |= 0 if not missing else 1
print(f"{'テーブル数':24}: {tables}")
print(f"{'移行の台帳':24}: {', '.join(vers) if vers else '（まだ無い）'}")
sys.exit(rc)
