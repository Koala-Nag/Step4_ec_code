# -*- coding: utf-8 -*-
"""8.2 のエラーコード表と backend/core/errors.py を突き合わせる（設計 10.2.11。R-28）。

★決めごと｜どちらか片方にしか無いコードがあれば失敗。HTTP の番号が違っても失敗。
  「表にある」は「実装されている」の証明にならない（ERR-1208 は表にあったのに誰も投げていなかった）。
  「実装にある」は「決まっている」の証明にならない（R-24 でクーポンを独自採番してぶつかった）。

★CI は設計仕様書を読めない（ec/ の外にある）。
  そこで 8.2 の表を docs/error-codes.md に写し、CI はそれと突き合わせる。
  ★写しが古いまま残るのを防ぐため、設計仕様書が手元にあるとき（ci-local.sh）は
    「写し ＝ 設計仕様書の 8.2」も確かめる。ずれていたら失敗し、--sync で写し直す。

使い方（ec/ で）
    python scripts/check_error_codes.py            突き合わせ（CI・手元）
    python scripts/check_error_codes.py --sync     設計仕様書の 8.2 から docs/error-codes.md を作り直す

★errors.py は import しない（fastapi が要る）。ast で辞書の中身だけ読む。
"""
from __future__ import annotations

import ast
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(ROOT, "docs", "error-codes.md")
ERRORS_PY = os.path.join(ROOT, "backend", "core", "errors.py")
BACKEND = os.path.join(ROOT, "backend")

ROW = re.compile(r"^\|\s*\**(ERR-\d{4})\**\s*\|(.*)\|\s*$")


def design_doc() -> str | None:
    hits = sorted(glob.glob(os.path.join(os.path.dirname(ROOT), "設計仕様書_*.md")))
    return hits[-1] if hits else None


def extract_8_2(text: str) -> list[str]:
    """設計仕様書から 8.2 節の表の行（ERR- で始まる行）だけを取り出す。"""
    start = text.index("### 8.2 ")
    end = text.index("\n### 8.3", start)
    rows = []
    for line in text[start:end].splitlines():
        if ROW.match(line.strip()):
            rows.append(line.strip())
    return rows


def parse_rows(rows: list[str]) -> dict[str, int | None]:
    """{コード: HTTP}。★10xx は表に HTTP の列が無い → 400。廃止の行は含めない。"""
    out: dict[str, int | None] = {}
    for line in rows:
        m = ROW.match(line)
        code = m.group(1)
        cells = [c.strip().strip("*").strip() for c in m.group(2).split("|")]
        if any("廃止" in c for c in cells[:1]):
            continue
        http = next((int(c) for c in cells if re.fullmatch(r"\d{3}", c)), None)
        out[code] = http if http is not None else (400 if code.startswith("ERR-10") else None)
    return out


def read_errors_py() -> tuple[dict[str, str], dict[str, int]]:
    tree = ast.parse(io.open(ERRORS_PY, encoding="utf-8").read())
    found: dict[str, dict] = {}
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id in ("MESSAGES", "STATUS"):
            found[target.id] = ast.literal_eval(node.value)
    return found["MESSAGES"], found["STATUS"]


def raised_codes() -> set[str]:
    """backend のどこかで文字列として現れるコード（errors.py 以外）。★参考表示だけ。"""
    seen: set[str] = set()
    for path in glob.glob(os.path.join(BACKEND, "**", "*.py"), recursive=True):
        if ".venv" in path or os.sep + "tests" + os.sep in path:
            continue
        codes = re.findall(r"ERR-\d{4}", io.open(path, encoding="utf-8").read())
        if path.endswith(os.path.join("core", "errors.py")):
            # ★errors.py は表（MESSAGES・STATUS）に1回ずつ現れる。3回目からが「投げている」（ERR-1401 など）
            seen |= {c for c in set(codes) if codes.count(c) > 2}
        else:
            seen |= set(codes)
    return seen


def main() -> int:
    doc = design_doc()
    if "--sync" in sys.argv:
        if not doc:
            print("[NG] 設計仕様書が見つからない（ec/ の1つ上に 設計仕様書_*.md）")
            return 1
        rows = extract_8_2(io.open(doc, encoding="utf-8").read())
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        io.open(SNAPSHOT, "w", encoding="utf-8", newline="\n").write(
            "# エラーコード一覧（設計仕様書 8.2 の写し）\n\n"
            "**★これは設計仕様書 8.2 の写し。直すときは 8.2 が先。**\n\n"
            "★手で直さない。`python scripts/check_error_codes.py --sync` で作り直す（10.2.11）。\n"
            "★CI はこの写しと backend/core/errors.py を突き合わせる。\n\n"
            + "\n".join(rows) + "\n")
        print(f"[OK] {len(rows)} 行を写した ← {os.path.basename(doc)}")
        return 0

    ng = 0
    snap_rows = [l.strip() for l in io.open(SNAPSHOT, encoding="utf-8") if ROW.match(l.strip())]
    if doc:
        if snap_rows != extract_8_2(io.open(doc, encoding="utf-8").read()):
            print("[NG] docs/error-codes.md が設計仕様書の 8.2 と違う。--sync で写し直す")
            ng = 1
    else:
        print("  ※ 設計仕様書が手元に無い（CI）。写しとだけ突き合わせる")

    table = parse_rows(snap_rows)
    messages, status = read_errors_py()
    impl = set(messages)
    only_table = sorted(set(table) - impl)
    only_impl = sorted(impl - set(table))
    if only_table:
        print(f"[NG] 表にあるが errors.py に無い: {only_table}")
        ng = 1
    if only_impl:
        print(f"[NG] errors.py にあるが表に無い（★表に足してから実装する）: {only_impl}")
        ng = 1
    for code in sorted(set(table) & impl):
        if table[code] is not None and status.get(code) != table[code]:
            print(f"[NG] {code} の HTTP が違う: 表 {table[code]} ／ errors.py {status.get(code)}")
            ng = 1
    missing_status = sorted(c for c in impl if c not in status)
    if missing_status:
        print(f"[NG] STATUS に無い: {missing_status}")
        ng = 1

    unused = sorted(set(table) - raised_codes())
    if unused:
        # ★失敗にはしない。Should 以降の機能のコードは、まだ投げる場所が無い
        print(f"  ※ 表にあるが、まだどこからも投げていない（参考）: {unused}")
    if ng == 0:
        print(f"[OK] 8.2 の {len(table)} コードと errors.py が一致（HTTP も一致）")
    return ng


if __name__ == "__main__":
    sys.exit(main())
