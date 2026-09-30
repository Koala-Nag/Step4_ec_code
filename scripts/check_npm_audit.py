# -*- coding: utf-8 -*-
"""npm audit を「期限つきの除外つき」で判定する（設計 10.4・9.4a。R-21 の回答2）。

★10.4 は「high 以上が1件でも出たら CI を失敗させる」と決めている。
  そのままだと、据え置きにした1件のせいで CI が赤のまま止まる。
  ★赤が続くと、人はいずれ赤を無視するようになる。それがいちばん危ない。

★だから閾値は緩めない。除外するものを1件ずつ名指しし、★期限を付ける。
  期限を過ぎたら、除外そのものが失敗になる。放置できない形にしてある。

    npm audit --audit-level=critical   ← 採らない。全部の high が黙って通る
    この方式                            ← 名指しした1件だけ通る。期限が来たら落ちる

使い方（ec/ で）
    python scripts/check_npm_audit.py
終了コード 1 で CI を落とす。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import date

FRONTEND = pathlib.Path(__file__).resolve().parent.parent / "frontend"

# ★据え置きにしたもの。1件ずつ、理由と期限を書く（設計 10.3・9.4a）
#   ★「なぜ待てるのか」を書く。書けないものは待てない
ALLOWED: dict[str, dict[str, str]] = {
    "postcss": {
        "until": "2026-10-21",     # Week10。Week7（Azure デプロイ）が通ったあと
        "why": (
            "next 15.5.25 が同梱している版。直すには Next 16（メジャー）が要る。"
            "Week5 まで日が無く、メジャー更新で壊れると串の回帰確認からやり直しになる。"
            "postcss はビルド時にCSSを処理するだけで、実行時に攻撃者の入力を受けない。"
        ),
    },
    "next": {
        "until": "2026-10-21",
        "why": "上と同じ。postcss を同梱しているぶんが moderate として出る",
    },
}
# 落とす深刻度（10.4）
FAIL_LEVELS = {"high", "critical"}


def main() -> int:
    proc = subprocess.run(
        ["npm", "audit", "--omit=dev", "--json"],
        cwd=FRONTEND, capture_output=True, text=True, shell=True,
        # ★Windows の既定は cp932。npm の出す記号でこけるので UTF-8 と明示する
        encoding="utf-8", errors="replace",
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        print("[NG] npm audit の出力が読めない")
        print(proc.stdout[:500])
        return 1

    vulns = data.get("vulnerabilities", {})
    today = date.today().isoformat()
    blocking: list[str] = []
    waived: list[str] = []
    expired: list[str] = []

    for name, v in sorted(vulns.items()):
        sev = str(v.get("severity", ""))
        if sev not in FAIL_LEVELS and sev != "moderate":
            continue
        rule = ALLOWED.get(name)
        if rule is None:
            if sev in FAIL_LEVELS:
                blocking.append(f"{name} ({sev})")
            continue
        if today > rule["until"]:
            # ★期限切れ。除外そのものを失敗にする
            expired.append(f"{name} ({sev}) 据え置きの期限 {rule['until']} を過ぎている")
        else:
            waived.append(f"{name} ({sev}) 〜{rule['until']}｜{rule['why']}")

    for w in waived:
        print(f"[据え置き] {w}")
    for e in expired:
        print(f"[NG] {e}")
    for b in blocking:
        print(f"[NG] {b} は据え置きの一覧に無い")

    if expired or blocking:
        print("[NG] npm audit（設計 10.4。high 以上は落とす）")
        return 1
    print(f"[OK] npm audit｜落とすべきものは無い（据え置き {len(waived)} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
