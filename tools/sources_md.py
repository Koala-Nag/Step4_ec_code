# -*- coding: utf-8 -*-
"""
sources_md.py
    assets/SOURCES.md（画像の出どころと状態の記録）を読み書きする小さな道具。
    （商品画像の仕様 6章・8.4）

    make_placeholder.py と import_images.py の両方が触るので、
    表の読み書きを1か所に置いて、書式がずれないようにする。

    表の形
        | ファイル | 状態 | 出どころ | 日付 |
"""
from __future__ import annotations

from pathlib import Path

HEADER = "| ファイル | 状態 | 出どころ | 日付 |"
SEP = "|---|---|---|---|"

PLACEHOLDER = "プレースホルダ"
REPLACED = "差し替え済み"

PREAMBLE = """# 画像の出どころ

**この表は `tools/make_placeholder.py` と `tools/import_images.py` が更新する。手で直してもよい。**

**★画面（F-703 画像追加）から登録した画像は、道具を通らないので、この表に載らない（R-38・R-39）。**
**表に載っているものが、リポジトリの持ち物。** 画面から増えた画像は試験の残りなので、**リポジトリには入れない**。
★**表の行数と `assets/products/` の枚数が合っているか**を、コミットの前に見る。

**なぜ残すか。** 「この画像は本物ですか」と聞かれたときに答えられるようにするため。
**AI生成であることは隠さない。** 素材を集められない制約の中で、どう埋めたかの説明になる。

**人物が写っているものは使わない**（肖像の許諾が別問題になる）。
フリー素材を混ぜる場合は、出どころとライセンス名もこの表に書く。

"""


def read(path: Path) -> dict[str, dict[str, str]]:
    """SOURCES.md を {ファイル名: {状態, 出どころ, 日付}} で返す。無ければ空。"""
    rows: dict[str, dict[str, str]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or line in (HEADER, SEP):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        name = cells[0].strip("`")
        if not name.endswith(".jpg"):
            continue
        rows[name] = {"状態": cells[1], "出どころ": cells[2], "日付": cells[3]}
    return rows


def write(path: Path, rows: dict[str, dict[str, str]]) -> None:
    lines = [PREAMBLE, HEADER, SEP]
    for name in sorted(rows):
        r = rows[name]
        lines.append(f"| `{name}` | {r['状態']} | {r['出どころ']} | {r['日付']} |")

    done = sum(1 for r in rows.values() if r["状態"] == REPLACED)
    lines.append("")
    lines.append(f"**{len(rows)} 枚中 {done} 枚が差し替え済み / 残り {len(rows) - done} 枚。**")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def upsert(path: Path, name: str, state: str, origin: str, date: str) -> None:
    """1行だけ更新する。既にある行は状態・出どころ・日付を上書きする。"""
    rows = read(path)
    rows[name] = {"状態": state, "出どころ": origin, "日付": date}
    write(path, rows)


def ensure(path: Path, names: list[str], origin: str, date: str) -> int:
    """名前の一覧に対して、まだ無い行を『プレースホルダ』で足す。

    すでに『差し替え済み』の行は触らない（作り直しで実績を消さないため）。
    足した件数を返す。
    """
    rows = read(path)
    added = 0
    for name in names:
        if name not in rows:
            rows[name] = {"状態": PLACEHOLDER, "出どころ": origin, "日付": date}
            added += 1
    write(path, rows)
    return added
