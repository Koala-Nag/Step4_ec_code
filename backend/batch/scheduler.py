# -*- coding: utf-8 -*-
"""定期処理を回す（設計 6.6.0。R-35）。

★バックエンドのプロセスの中で回す。外に別のリソースを置かない。
  理由は 6.6.0（① 二重起動は batch_lock で設計済み ② 閉域化で外から叩けなくなる
  ③ Always On がある ④ リソースを増やさない）。

★ここが持ってよいのは「時計」だけ。
  「前回いつ流したか」も「いま動いているか」も DB（batch_lock）にある。
  ★プロセスに状態を持つと、ワーカが2つあるだけで食い違う（8.4 と同じ理由）。

★二重には新しい仕掛けを足さない。ワーカ2つが同じ時刻に起こしても、
  batch_lock の条件付きUPDATE で片方だけが動く（6.6.1）。

★1回が長引いても、次の回とは重ならない。
  1つの仕事につきループが1本で、★終わってから次の間隔を待つ（間隔は「実行の間隔」であって時刻表ではない）。

★BATCH_SCHEDULER=0 で止まる。試験のときに勝手に動かれると再現できない。
"""
from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from batch import jobs
from core import applog

MINUTE = 60


@dataclass(frozen=True)
class Job:
    batch_id: str
    every_seconds: int
    run: Callable[[Session], jobs.Result]
    note: str


# ★設計 6.6 の表の間隔。
#   ★B-01（セール）と B-03（再入荷通知）は 09-01 の凍結で対象外。
#   ★B-02（公開予約）と B-05（支払い待ちの自動キャンセル）は「作らない」と決めたので無い（R-36 の回答2）
JOBS: list[Job] = [
    Job("B-04", 60 * MINUTE, jobs.b04_clean_carts, "保持期間を過ぎたカート明細を消す"),
    Job("B-06", 24 * 60 * MINUTE, jobs.b06_complete_orders, "出荷から3日で到着済に／全部届いた注文を完了に"),
    Job("B-07", 10 * MINUTE, jobs.b07_expire_authenticating, "認証中の期限切れを支払い待ちに"),
    Job("B-08", 1 * MINUTE, jobs.b08_confirm_payments, "処理中・照会要の決済を確定する"),
    Job("B-09", 10 * MINUTE, jobs.b09_retry_void, "取消・返金の再送（3回で打ち切り）"),
    Job("B-10", 10 * MINUTE, jobs.b10_retry_capture, "売上確定の再送（打ち切らない）"),
    Job("B-11", 1 * MINUTE, jobs.b11_send_mail, "未送信・失敗のメールを送る"),
    Job("B-12", 24 * 60 * MINUTE, jobs.b12_heartbeat, "生存通知"),
    Job("B-13", 5 * MINUTE, jobs.b13_auto_instruct, "引当済の注文に出荷指示を作る"),
]

BY_ID = {j.batch_id: j for j in JOBS}


def enabled() -> bool:
    """★既定は動く。BATCH_SCHEDULER=0 のときだけ止まる。"""
    return os.getenv("BATCH_SCHEDULER", "1") != "0"


def run_once(batch_id: str) -> jobs.Result:
    """1回だけ回す。★スケジューラも手動実行（AP-T02）も、ここを通る（10.2.6）。"""
    from core.db import SessionLocal

    job = BY_ID[batch_id]
    db = SessionLocal()
    try:
        return job.run(db)
    finally:
        db.close()


async def _loop(job: Job) -> None:
    # ★起動直後に全部が同時に走らないよう、最初だけ少しずらす（ワーカ2つが同時に起きるため）
    await asyncio.sleep(random.uniform(1.0, min(15.0, job.every_seconds)))
    while True:
        try:
            # ★DBを触るのは別スレッド（同期のSQLAlchemyなので、イベントループを止めない）
            res = await asyncio.to_thread(run_once, job.batch_id)
            if res.ran and (res.processed or res.notes):
                applog.emit("batch.done", batch_id=job.batch_id, count=res.processed)
        except asyncio.CancelledError:
            raise
        except Exception as e:                      # noqa: BLE001
            # ★1回落ちてもループは止めない。止めると、以後その仕事だけ永久に動かない
            applog.emit_exception("batch.crashed", e, batch_id=job.batch_id)
        await asyncio.sleep(job.every_seconds)      # ★終わってから次の間隔を待つ（重ならない）


class Scheduler:
    """起動時に立てて、終了時に止める。"""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def start(self) -> None:
        if not enabled():
            applog.emit("batch.scheduler_disabled")
            return
        for job in JOBS:
            self.tasks.append(asyncio.create_task(_loop(job), name=f"batch:{job.batch_id}"))
        applog.emit("batch.scheduler_started", count=len(self.tasks))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):     # noqa: BLE001
                pass
        self.tasks.clear()
