# -*- coding: utf-8 -*-
"""FastAPI の入口。

★CORS は設定しない（設計 4.1.1・N-29）。
  ブラウザは同一オリジンの Next.js しか呼ばない。CORS を足すと、
  ブラウザから直接バックエンドを叩く経路がそこで開いてしまう。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api import admin, auth, backoffice, cart, catalog, mypage, orders, products, promo, returns, testing as testing_api, webhooks
from batch import scheduler
from mock import router as mock_router
from core import applog
from core.config import APP_ENV
from fastapi.exceptions import RequestValidationError

from core.errors import (
    AppError,
    app_error_handler,
    unhandled_handler,
    validation_handler,
)

# ★ログの出口は core/applog.py の1本だけ（8.6・N-15）
applog.configure()


def _run_startup_migration() -> None:
    """起動時の移行（設計 2.2.1）。★ここで1回だけ。

    ★複数インスタンスが同時に起動しても、後発が ERROR 1060／1061 で落ちない。
      GET_LOCK で排他し、★ロックを取ってから台帳を読み直す（2.2.1 ②）。

    ★失敗したら起動を止める。中途半端なスキーマでリクエストを受けない。
      App Service が再起動して拾い直す。

    ★AUTO_MIGRATE=0 で止められる。移行を流したくない環境（試験など）のため。
    """
    import os

    if os.getenv("AUTO_MIGRATE", "1") != "1":
        applog.emit("migrate.skipped", reason_code="disabled")
        return
    from core.db import engine
    from core.migrate import run

    res = run(engine)
    if res["applied"]:
        applog.emit("migrate.applied", count=len(res["applied"]))


_run_startup_migration()

# N-31。本番では /docs と /openapi.json を出さない
_docs = None if APP_ENV == "production" else "/docs"
_openapi = None if APP_ENV == "production" else "/openapi.json"

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """定期処理のスケジューラを、このプロセスの中で回す（設計 6.6.0。R-35）。

    ★外に別のリソース（WebJob・cron）を置かない。閉域化しても動く（2.2.1 と同じ理由）。
    ★二重起動は batch_lock に任せる（6.6.1）。ワーカが2つでも、同じ回は片方だけ動く。
    ★BATCH_SCHEDULER=0 で立てない（試験のとき勝手に動かれると再現できない）。
    """
    sch = scheduler.Scheduler()
    sch.start()
    try:
        yield
    finally:
        await sch.stop()


app = FastAPI(
    title="EC バックエンド",
    version="0.1.0",
    docs_url=_docs,
    redoc_url=None,
    openapi_url=_openapi,
    lifespan=_lifespan,
)

app.add_exception_handler(AppError, app_error_handler)
# ★型が違う入力は 400 / ERR-1002 にする。FastAPI 既定の 422 を外に出さない（SEC-405）
app.add_exception_handler(RequestValidationError, validation_handler)
app.add_exception_handler(Exception, unhandled_handler)

app.include_router(products.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(webhooks.router)
# R-21。会員と運営者の認証
app.include_router(auth.router)
app.include_router(auth.members)
app.include_router(auth.me)
app.include_router(admin.router)
app.include_router(catalog.router)
app.include_router(returns.router)
app.include_router(mypage.favorites)
app.include_router(mypage.reviews)
app.include_router(mypage.profile)
app.include_router(promo.router)
app.include_router(backoffice.router)
app.include_router(returns.admin_router)

# ★ダミー決済API（7.2.3）と FT-07 の操作口（10.2.1）。検証環境だけ。
#   本番では生やさない＝直接URLを叩かれても 404（設計 2.3・N-31）
# ★include_in_schema=False（R-21 の回答1）。
#   これを付けると APP_ENV に関係なく openapi.json が変わらない。
#   ★環境変数の値で生成物が変わる形そのものを消している。
#   付けないと CI（10.4 の3段目）が「型の生成が最新か」で毎回落ちる。
#   口は local では生えているので、試験からは叩ける（4.4）。
if APP_ENV != "production":
    app.include_router(mock_router.router, include_in_schema=False)
    app.include_router(testing_api.router, include_in_schema=False)

# 開発中だけ、画像をここから配る。Blob へ移すまでの間に合わせ（設計 2.1）
_assets = Path(__file__).resolve().parent.parent / "assets"
if _assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")


@app.get("/healthz")
def healthz() -> dict:
    return {"data": {"status": "ok", "env": APP_ENV}}
