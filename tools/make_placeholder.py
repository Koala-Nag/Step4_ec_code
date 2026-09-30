# -*- coding: utf-8 -*-
"""
make_placeholder.py
    商品画像のプレースホルダを 50商品 × 4色 = 200枚 生成する。
    （商品画像の仕様 8.2 ①／HANDOFF R-10 ②）

    狙い
      実物の画像を待たずに、一覧も詳細も「画像がある」状態で動かす。
      実物ができたら import_images.py が同じ名前で上書きする。DBは触らない。

    色をベタ塗りにする理由
      色と画像の紐づけが間違っていたら一目で分かる（FR-201 が確かめたいのはそこ）。

    使い方（ec/ で）
        python tools/make_placeholder.py
        python tools/make_placeholder.py --force     # 既にあるものも作り直す
        python tools/make_placeholder.py --check     # 作らずに、seed と過不足が無いかだけ見る
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow が要る:  pip install Pillow")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources_md  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "products"
SOURCES = ROOT / "assets" / "SOURCES.md"
SEED_IMAGE = ROOT / "db" / "seed" / "05_product_image.sql"

WIDTH, HEIGHT = 900, 1200
QUALITY = 85

# 色コードは4つだけ（仕様 1.2）
COLORS: dict[str, tuple[str, tuple[int, int, int]]] = {
    "BK": ("ブラック", (26, 26, 26)),
    "WH": ("ホワイト", (245, 245, 245)),
    "NV": ("ネイビー", (31, 56, 100)),
    "BE": ("ベージュ", (217, 199, 167)),
}

PRODUCTS = [f"P{n:04d}" for n in range(1, 51)]

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def load_font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def text_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """背景の明るさで文字色を決める。

    仕様には「白抜き」とあるが、ホワイトとベージュでは白い文字が消えてしまい、
    「色と画像の対応を一目で確かめる」という目的を果たせない。
    そこで明るい地のときだけ濃い文字にする（HANDOFF R-10 の報告に明記した）。
    """
    luminance = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (24, 24, 24) if luminance > 140 else (255, 255, 255)


def draw_one(product: str, color_code: str, dest: Path) -> None:
    color_name, rgb = COLORS[color_code]
    fg = text_color(rgb)

    img = Image.new("RGB", (WIDTH, HEIGHT), rgb)
    d = ImageDraw.Draw(img)

    # 3:4 であることが目で分かるように、内側に枠を1本置く
    margin = 40
    d.rectangle([margin, margin, WIDTH - margin, HEIGHT - margin], outline=fg, width=3)

    f_big = load_font(96)
    f_mid = load_font(56)
    f_small = load_font(34)

    lines = [
        (product, f_big),
        (f"{color_code}  {color_name}", f_mid),
        (f"{WIDTH}x{HEIGHT}  placeholder", f_small),
    ]
    heights = []
    for text, font in lines:
        box = d.textbbox((0, 0), text, font=font)
        heights.append(box[3] - box[1])
    gap = 36
    total = sum(heights) + gap * (len(lines) - 1)
    y = (HEIGHT - total) // 2

    for (text, font), h in zip(lines, heights):
        box = d.textbbox((0, 0), text, font=font)
        x = (WIDTH - (box[2] - box[0])) // 2 - box[0]
        d.text((x, y - box[1]), text, font=font, fill=fg)
        y += h + gap

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=QUALITY, optimize=True)


def expected_from_seed() -> set[str]:
    """05_product_image.sql が指しているファイル名を集める。"""
    if not SEED_IMAGE.exists():
        return set()
    text = SEED_IMAGE.read_text(encoding="utf-8")
    return set(re.findall(r"products/([A-Za-z0-9_]+\.jpg)", text))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="既にあるものも作り直す")
    ap.add_argument("--check", action="store_true", help="作らずに、seed との過不足だけ見る")
    args = ap.parse_args()

    planned = [(p, c) for p in PRODUCTS for c in COLORS]
    names = {f"{p}_{c}_1.jpg" for p, c in planned}

    if not args.check:
        made = skipped = 0
        for product, color_code in planned:
            dest = OUT_DIR / f"{product}_{color_code}_1.jpg"
            if dest.exists() and not args.force:
                skipped += 1
                continue
            draw_one(product, color_code, dest)
            made += 1
        print(f"  生成 {made} 枚 / 既存を残した {skipped} 枚 → {OUT_DIR}")

        # SOURCES.md に行を用意する。すでに『差し替え済み』の行は触らない
        added = sources_md.ensure(
            SOURCES, sorted(names), "自動生成（make_placeholder.py）", date.today().isoformat()
        )
        print(f"  SOURCES.md に {added} 行を追加（差し替え済みの行はそのまま）")

    # seed と突き合わせる
    seed_names = expected_from_seed()
    rc = 0
    if seed_names:
        missing_file = sorted(n for n in seed_names if not (OUT_DIR / n).exists())
        not_in_seed = sorted(names - seed_names)
        no_row = sorted(seed_names - names)
        if missing_file:
            print(f"  [NG] seed にあるのに実体が無い: {len(missing_file)} 件  例 {missing_file[:3]}")
            rc = 1
        if no_row:
            print(f"  [NG] seed にあるが生成対象外: {len(no_row)} 件  例 {no_row[:3]}")
            rc = 1
        if not_in_seed:
            print(f"  [NG] 生成したが seed に行が無い: {len(not_in_seed)} 件  例 {not_in_seed[:3]}")
            rc = 1
        if rc == 0:
            print(f"  [OK] seed の {len(seed_names)} 行と、実体のファイルが1対1で対応している")
    else:
        print("  （05_product_image.sql が見つからないので突き合わせは省略）")

    if OUT_DIR.exists():
        files = list(OUT_DIR.glob("*.jpg"))
        total = sum(f.stat().st_size for f in files)
        if files:
            print(f"  合計 {len(files)} 枚 / {total/1024/1024:.1f} MB / 1枚あたり平均 {total/len(files)/1024:.0f} KB")
    return rc


if __name__ == "__main__":
    sys.exit(main())
