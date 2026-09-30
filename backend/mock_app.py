# -*- coding: utf-8 -*-
"""ダミー決済API だけを載せたアプリ（設計 7.2.3・10.2.4）。

★なぜ本体（main.py）から分けたか。

  R-23 で、`POST /orders` だけが `httpx.ReadTimeout` を起こすことを突き止めた。
  120回中8回（約2.3%）、8回とも `POST /orders`。★この口だけが持っている性質は1つ——
  **自分自身を HTTP で呼ぶ**（`issue_token` → `/mock-gateway/tokens`）。

      POST /orders  →  http://127.0.0.1:8000/mock-gateway/tokens   ← 同じ uvicorn

  ★本番ではこの形は無い。`PAYMENT_BASE_URL` が別のホストを指すため。
    つまり検証環境にしか無い雑音が、同時実行の試験すべてに乗り続けることになる。
    ★1回の判断で消えるものを、毎回ひとつずつ手で除ける形にしない（R-24 の回答1）。

★切り替えは宛先URLを変えるだけ（7.2.3）。この分離は、その決めごとの実地確認でもある。
  本体側のコードは1行も変えていない。`.env` の `PAYMENT_BASE_URL` を :8010 に向けただけ。

起動（ec/backend で）
    .venv/Scripts/python.exe -m uvicorn mock_app:app --port 8010
"""
from __future__ import annotations

from fastapi import FastAPI

from core import applog
from core.config import APP_ENV
from mock import router as mock_router

applog.configure()

# ★本番では立てない。検証環境だけの口（7.2.3・N-31）
_docs = None if APP_ENV == "production" else "/docs"

app = FastAPI(
    title="ダミー決済API（検証環境だけ）",
    version="0.1.0",
    docs_url=_docs,
    redoc_url=None,
    openapi_url=None if APP_ENV == "production" else "/openapi.json",
)

# ★本体と同じルータをそのまま載せる。中身は1行も変えていない
app.include_router(mock_router.router)


@app.get("/healthz")
def healthz() -> dict:
    return {"data": {"status": "ok", "role": "mock-gateway", "env": APP_ENV}}
