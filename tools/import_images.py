# -*- coding: utf-8 -*-
"""
import_images.py
    assets/incoming/ に置いた画像を、規約名か確かめたうえで
    assets/products/ へ 900x1200 の JPEG として上書きコピーする。
    （商品画像の仕様 8.2 ⑤・8.3／HANDOFF R-10 ④）

    決めごと
      * 規約外の名前は止める。推測して置かない
        （どこに入ったか分からなくなるほうが困る。仕様 8.3）
      * 3:4 でないものは切り取らない。余白を足して収める（服が切れるため）
      * 5MB を超える入力は弾く（N-36）
      * DBは触らない。ファイル名が同じなので product_image は1行も変わらない

    使い方（ec/ で）
        python tools/import_images.py
        python tools/import_images.py --dry-run     # 何が起きるか見るだけ
        python tools/import_images.py --keep        # 取り込んだあとも incoming/ に残す
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("Pillow が要る:  pip install Pillow")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources_md  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IN_DIR = ROOT / "assets" / "incoming"
OUT_DIR = ROOT / "assets" / "products"
SOURCES = ROOT / "assets" / "SOURCES.md"
SEED_IMAGE = ROOT / "db" / "seed" / "05_product_image.sql"

WIDTH, HEIGHT = 900, 1200
TARGET_BYTES = 500 * 1024          # 1枚 500KB 目安
MAX_INPUT_BYTES = 5 * 1024 * 1024  # 上限 5MB（N-36）
PAD_COLOR = (255, 255, 255)        # 余白は白（仕様 1「背景は白または淡いグレーの無地」）

NAME_RE = re.compile(r"^(P\d{4})_(BK|WH|NV|BE)_(\d+)\.(jpg|jpeg|png|webp)$")
ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".webp"}


def known_targets() -> set[str]:
    """05_product_image.sql が指しているファイル名。DBに行が無い画像は受け入れない。"""
    if not SEED_IMAGE.exists():
        return set()
    text = SEED_IMAGE.read_text(encoding="utf-8")
    return set(re.findall(r"products/([A-Za-z0-9_]+\.jpg)", text))


def fit_900x1200(img: Image.Image) -> Image.Image:
    """切り取らずに 900x1200 へ収める。足りないぶんは余白で埋める。"""
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB",):
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, PAD_COLOR)
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
    fitted = ImageOps.contain(img, (WIDTH, HEIGHT), Image.LANCZOS)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), PAD_COLOR)
    canvas.paste(fitted, ((WIDTH - fitted.width) // 2, (HEIGHT - fitted.height) // 2))
    return canvas


def save_under_target(img: Image.Image, dest: Path) -> tuple[int, int]:
    """500KB 目安に収まるまで品質を落として保存する。(バイト数, 品質) を返す。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for quality in (88, 85, 80, 75, 70, 65, 60):
        img.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)
        size = dest.stat().st_size
        if size <= TARGET_BYTES:
            return size, quality
    return dest.stat().st_size, 60


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="書き込まずに、何が起きるかだけ出す")
    ap.add_argument("--keep", action="store_true", help="取り込んだあとも incoming/ に残す")
    args = ap.parse_args()

    IN_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in IN_DIR.iterdir() if p.is_file())
    if not files:
        print(f"  assets/incoming/ は空。取り込むものが無い")
        return 0

    targets = known_targets()
    ok = 0
    rejected: list[tuple[str, str]] = []

    for src in files:
        name = src.name

        if src.suffix.lower() not in ALLOWED_SUFFIX:
            rejected.append((name, f"扱えない拡張子（{src.suffix}）"))
            continue

        m = NAME_RE.match(name)
        if not m:
            rejected.append((name, "規約外の名前。{商品コード}_{色コード}_{連番}.jpg の形にする"))
            continue

        size = src.stat().st_size
        if size > MAX_INPUT_BYTES:
            rejected.append((name, f"5MB を超えている（{size/1024/1024:.1f} MB）。N-36 で弾く"))
            continue

        product, color, seq, _ = m.groups()
        out_name = f"{product}_{color}_{int(seq)}.jpg"
        if targets and out_name not in targets:
            rejected.append((name, f"product_image に行が無い（{out_name}）。seed を先に足す"))
            continue

        try:
            with Image.open(src) as im:
                im.load()
                w, h = im.size
                fitted = fit_900x1200(im)
        except Exception as exc:
            rejected.append((name, f"画像として開けない（{exc}）"))
            continue

        dest = OUT_DIR / out_name
        note = "" if (w, h) == (WIDTH, HEIGHT) else f"  ← {w}x{h} から余白を足して収めた"

        if args.dry_run:
            print(f"  [取り込む] {name} → assets/products/{out_name}{note}")
            ok += 1
            continue

        out_size, quality = save_under_target(fitted, dest)
        sources_md.upsert(
            SOURCES, out_name, sources_md.REPLACED,
            "AI生成（Gemini）", date.today().isoformat(),
        )
        print(f"  [取り込んだ] {out_name}  {out_size/1024:.0f} KB (品質 {quality}){note}")
        if not args.keep:
            src.unlink()
        ok += 1

    print("")
    print(f"  取り込み {ok} 件 / 弾いた {len(rejected)} 件")
    if rejected:
        print("")
        print("  --- 弾いたもの（推測して置かない。名前を直してから入れ直す）---")
        for name, why in rejected:
            print(f"    {name}")
            print(f"      → {why}")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
