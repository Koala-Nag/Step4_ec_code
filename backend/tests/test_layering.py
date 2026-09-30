# -*- coding: utf-8 -*-
"""層の約束を、目でなく試験で守る（設計 2.2・10.1）。

★単体テスト仕様書 0.2 が「本書は、その約束が本当に果たされているかの答え合わせでもある」
  と書いている。ここがその答え合わせ。

★domain/ が repository や external を import した瞬間、
  この章の試験は全部「DBを立てないと動かないもの」に変わる。
  そうなってから気づくと、書き直す量が大きい。
"""
from __future__ import annotations

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = ("repository", "external", "api", "batch", "payment", "mock", "core", "sqlalchemy",
             "fastapi", "httpx", "pymysql")


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


def test_domainは外部に依存しない():
    bad: list[str] = []
    for f in sorted((BACKEND / "domain").glob("*.py")):
        for mod in sorted(_imports(f) & set(FORBIDDEN)):
            bad.append(f"{f.name} が {mod} を import している")
    assert not bad, "\n".join(bad)


def test_domainのファイルはDBを立てずに読み込める():
    """import しただけで接続しにいく作りになっていないこと。"""
    import importlib

    for name in ("allocation", "pricing", "stock", "shipping_date", "refund"):
        importlib.import_module(f"domain.{name}")
