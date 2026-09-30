# -*- coding: utf-8 -*-
"""つなぎ先の空のデータベースに、ddl/ と seed/ を流す（R-36 ②）。

★手元は docker-entrypoint が流してくれるが、Azure の共有サーバでは自分で流す。
★流す順は ddl/ → seed/（ファイル名の順）。ddl/03 が移行の台帳に「何番相当か」を入れる（2.2.1）。
★このあとバックエンドを起動すると、起動時の移行（GET_LOCK）が「もう当たっている」と判断して何もしない。

使い方（ec/ で）
    ENV_FILE=.env.azure backend/.venv/Scripts/python scripts/db_bootstrap.py           … ddl と seed
    ENV_FILE=.env.azure backend/.venv/Scripts/python scripts/db_bootstrap.py --ddl-only

★秘密は出さない（ホスト名もパスワードも出力しない）。
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

import pymysql                                    # noqa: E402
from dotenv import load_dotenv                    # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / os.getenv("ENV_FILE", ".env"), override=True)

ca = os.getenv("DB_SSL_CA", "").strip()
if ca and not pathlib.Path(ca).is_absolute():
    ca = str(ROOT / ca)
ssl = ({"ca": ca} if ca else {}) if os.getenv("DB_SSL", "0") == "1" else None

conn = pymysql.connect(
    host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME", "ec_koala"), charset="utf8mb4", ssl=ssl,
    client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS, autocommit=True,
)

files = sorted((ROOT / "db" / "ddl").glob("*.sql"))
if "--ddl-only" not in sys.argv:
    files += sorted((ROOT / "db" / "seed").glob("*.sql"))

with conn.cursor() as cur:
    for f in files:
        sql = f.read_text(encoding="utf-8")
        cur.execute(sql)
        while cur.nextset():                      # ★複数文なので、最後まで読み切る
            pass
        print(f"  流した: db/{f.parent.name}/{f.name}")

with conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()")
    tables = cur.fetchone()[0]
    cur.execute("SELECT GROUP_CONCAT(version ORDER BY version) FROM schema_migration")
    vers = cur.fetchone()[0]
print(f"テーブル数: {tables} / 台帳: {vers}")
conn.close()
