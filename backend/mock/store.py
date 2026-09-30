# -*- coding: utf-8 -*-
"""ダミー決済APIの記憶（検証環境だけ）。

★ワーカを2以上にする（設計 7.2.3）ので、プロセスの中に持てない。
  1つだとダミーAPIを待っているあいだに自分自身が塞がって止まるため、
  ワーカは複数になる。そのとき冪等キーの記録がプロセスごとに分かれると、
  「2回目を実行しない」が偶然そのワーカに当たったときしか効かない。

★DBのテーブルは足さない。ダミーは検証環境だけのものなので、
  スキーマ（db/ddl/）を汚さない。ファイル1本で共有する。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

STORE_PATH = Path(os.getenv("MOCK_STORE_PATH", tempfile.gettempdir())) / "ec_mock_gateway.json"
LOCK_PATH = STORE_PATH.with_suffix(".lock")

_EMPTY: dict[str, Any] = {
    # AP-T03 が指定する挙動（FT-03）
    "scenario": "success",
    # 冪等キー → 応答（7.2.1。2回目を実行しない）
    "idempotent": {},
    # 取引ID → 状態
    "transactions": {},
    # 受け取った通知ID（重複対策）
    "seen_notifications": [],
    # 呼ばれた回数。★「2回目を実行していない」の証拠に使う
    "call_count": {},
    # 与信ごとの 与信額・確定・取消・返金（★断る条件の突き合わせ。7.2.3・R-27）
    "ledger": {},
}


class _FileLock:
    """粗いが確実なロック。ワーカ間で直列化できればよい。"""

    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self.fd: int | None = None

    def __enter__(self) -> "_FileLock":
        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    # 取れないまま進むより、壊れたと分かるほうがよい
                    raise TimeoutError(f"ダミーAPIのロックが取れない: {self.path}")
                time.sleep(0.01)

    def __exit__(self, *exc: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def _read() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return json.loads(json.dumps(_EMPTY))
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_EMPTY))


def _write(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STORE_PATH)   # 差し替えは不可分に


def read() -> dict[str, Any]:
    with _FileLock(LOCK_PATH):
        return _read()


def update(fn) -> Any:
    """読んで・変えて・書くまでを1つのロックの中で行う。

    ★冪等キーの判定と記録を分けて行うと、そのあいだに2本目が入る。
      「見てから書くまでの隙間」は、引当（6.2.1）とまったく同じ問題。
    """
    with _FileLock(LOCK_PATH):
        data = _read()
        result = fn(data)
        _write(data)
        return result


def reset(scenario: str = "success") -> None:
    """挙動を切り替える（AP-T03）。★与信の台帳（ledger）だけは消さない（R-27）。

    ★本物の決済代行は、こちらが試験の都合で挙動を変えても、通した与信を忘れない。
      台帳まで消すと、切り替える前に通した与信の取消が「知らない取引」で断られ、
      B-09 の再送が永久に通らなくなる（R-27 の回帰で踏んだ）。
    """
    with _FileLock(LOCK_PATH):
        keep = _read().get("ledger", {})
        data = json.loads(json.dumps(_EMPTY))
        data["scenario"] = scenario
        data["ledger"] = keep
        _write(data)
