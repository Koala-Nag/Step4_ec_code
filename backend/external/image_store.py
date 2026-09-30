# -*- coding: utf-8 -*-
"""商品画像の置き場（F-703。R-27）。

★DB には相対パス（products/P0001_BK_1.jpg）だけを持つ（3.2 T-11）。
  表示するときに IMAGE_BASE_URL を前に付ける。

★いまは手元の ec/assets/ に書く（main.py が /assets で配っている）。
  本番は Blob（設計 2.1）。★置き場が変わっても、呼ぶ側（api/catalog.py）は
  save / delete の2つしか知らない。差し替えるのはこのファイルだけ。
"""
from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


def save(relpath: str, data: bytes) -> None:
    p = (ASSETS / relpath).resolve()
    # ★assets の外に書かない（相対パスは api 側で組み立てるが、念のため）
    if ASSETS.resolve() not in p.parents:
        raise ValueError("outside assets")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)


def delete(relpath: str) -> None:
    p = (ASSETS / relpath).resolve()
    if ASSETS.resolve() in p.parents and p.exists():
        p.unlink()
