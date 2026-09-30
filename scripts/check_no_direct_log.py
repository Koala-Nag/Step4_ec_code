# -*- coding: utf-8 -*-
"""N-15 の静的検査（設計 8.6・10.4 の6段目）。

★「出してよい項目の一覧」を文書の表だけで済ませると、守れたかどうかは目でしか確かめられない。
  8.6 は「ログ出力の入口を1つの関数にする」と決めた。★それを機械で確かめる。

落とす条件
    ・core/applog.py 以外で logging を直接呼んでいる（getLogger / log.info など）
    ・print( を書いている（本番の標準出力に素通しになる）

★DBもサーバも要らない。数秒で終わる。
"""
from __future__ import annotations

import ast
import pathlib
import sys

# ★アプリの repo の根は ec/（09-10 決定）。ここは ec/scripts/
BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"
# ★ここだけが出口。増やすときは 8.6 に理由を書いてから
EXEMPT = {"core/applog.py"}
SKIP_DIRS = {".venv", "__pycache__", "tests", "mock"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def rel(p: pathlib.Path) -> str:
    return p.relative_to(BACKEND).as_posix()


def check(path: pathlib.Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "print":
            bad.append(f"{rel(path)}:{node.lineno} print( を書いている")
        if isinstance(f, ast.Attribute) and f.attr in LOG_METHODS | {"getLogger", "basicConfig"}:
            text = lines[node.lineno - 1].strip()
            if "logging." in text or "log." in text:
                bad.append(f"{rel(path)}:{node.lineno} {text[:70]}")
    return bad


def main() -> int:
    if not BACKEND.exists():
        print(f"[NG] {BACKEND} が無い")
        return 1
    bad: list[str] = []
    for p in sorted(BACKEND.rglob("*.py")):
        if set(p.relative_to(BACKEND).parts) & SKIP_DIRS:
            continue
        if rel(p) in EXEMPT:
            continue
        bad += check(p)
    if bad:
        print("[NG] applog.emit を通さないログ出力がある（設計 8.6・N-15）")
        for b in bad:
            print(f"     {b}")
        return 1
    print("[OK] ログ出力はすべて core/applog.py を通っている（N-15）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
