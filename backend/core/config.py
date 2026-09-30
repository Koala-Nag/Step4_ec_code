# -*- coding: utf-8 -*-
"""設定は環境変数で与える。ソースに値を書かない（N-38・設計 2.3）。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


def _req(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"環境変数 {name} が無い（.env.example を見て .env を作る）")
    return v


APP_ENV = os.getenv("APP_ENV", "local")

DB_HOST = _req("DB_HOST", "127.0.0.1")
DB_PORT = _req("DB_PORT", "3306")
DB_NAME = _req("DB_NAME", "ec")
DB_USER = _req("DB_USER", "root")
DB_PASSWORD = _req("DB_PASSWORD", "localonly")

# ★TLS。Azure Database for MySQL は必須（R-35）。手元の Docker は 0 のまま。
#   ★コードに「Azure なら」の分岐を作らない。接続の引数だけを .env で変える
DB_SSL = os.getenv("DB_SSL", "0") == "1"
# ★接続ごとの時刻帯（R-36）。Azure の既定は UTC で、BR-18（返品17日）と BR-23（締め時刻）が9時間ずれる。
#   ★共有サーバのパラメータは触らない（他の受講生に影響する）。この接続だけ JST にする。
#   空なら何もしない（手元の Docker は既に +09:00）。
DB_TIME_ZONE = os.getenv("DB_TIME_ZONE", "").strip()

_ca = os.getenv("DB_SSL_CA", "").strip()
# ★相対パスは ec/ から解く。起動した場所で証明書を見失わないため（R-36）
DB_SSL_CA = str((Path(__file__).resolve().parent.parent.parent / _ca)) if _ca and not Path(_ca).is_absolute() else _ca

# ★パスワードを接続文字列に埋め込まない（設計 2.3a。R-36）。
#   ★SQL の束縛変数（N-32・SEC-501）と同じ形——「値」を、構文を持つ文字列に混ぜない。
#     講座側が決めたパスワードには記号（@ : / ? # % & ' " \）が入りうる。
#     文字列に混ぜると、@ でホストが切れ、? でクエリが始まり、# 以降が捨てられる。
#   ★URL.create に値として渡すと、SQLAlchemy が用途に応じて自分で逃がす。
DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT),
    database=DB_NAME,
    query={"charset": "utf8mb4"},
)


def database_url_safe() -> str:
    """ログや画面に出すとき用。★パスワードは伏せられる（SQLAlchemy の既定）。"""
    return DATABASE_URL.render_as_string(hide_password=True)

# R-12 で決めた。product_image.url は相対パスなので、表示時にこれを前置する
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "http://localhost:8000/assets")

# --- 決済代行（IF-01。設計 7.2）------------------------------
# ★切り替えは宛先URLを変えるだけ。コードの分岐にしない（7.2.3）
#   手元・検証   http://127.0.0.1:8010/mock-gateway   （自作のダミーAPI。★別プロセス）
#   本番         決済代行のURL
#
# ★ダミーAPIは本体と別のプロセスで動かす（10.2.4・R-24 の回答1）。
#   同じプロセスに載せていたとき、POST /orders が自分自身を呼ぶ形になり、
#   120回中8回 ReadTimeout が出ていた（R-23 で場所を特定）。
#   ★本番ではこの形が無いので、検証環境にしか無い雑音だった。
PAYMENT_BASE_URL = os.getenv("PAYMENT_BASE_URL", "http://127.0.0.1:8010/mock-gateway")
# 7.2.4。★ダミーも本物と同じ鍵で署名する
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "dev-webhook-secret")

# --- メール（7.3）--------------------------------------------
MAIL_FROM_ADDRESS = os.getenv("MAIL_FROM_ADDRESS", "no-reply@example.com")
# N-13 の通知先（運用管理者）。8.4 の生存通知もここへ
MAIL_ADMIN_ADDRESS = os.getenv("MAIL_ADMIN_ADDRESS", "admin@example.com")

# 4.1.2 ②。フロント層 → バックエンドの全リクエストに付ける
INTERNAL_AUTH_TOKEN = os.getenv("INTERNAL_AUTH_TOKEN", "dev-internal-token")

# 3Dセキュアから戻ってくる先（ブラウザが行く。当社を通らない）
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

# 4.1.7。一覧の既定と上限
PAGE_LIMIT_DEFAULT = 20
PAGE_LIMIT_MAX = 100

# 4.1.4・9.2.1d。件数はここで打ち切る。超えたら「100件以上」と出す。
# ★在庫で絞っているかどうかで経路を変えない（09-06 決定）。どちらでも 20並列 377ms で足りる
COUNT_CAP = 100
