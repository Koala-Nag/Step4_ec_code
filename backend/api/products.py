# -*- coding: utf-8 -*-
"""AP-101 商品一覧 / AP-102 商品詳細（設計 4.2）。

★この層は「受けて・渡して・形を整える」だけ。
  在庫の見せ方の判断は domain/、SQL は repository/ に置く（設計 2.2）。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.config import COUNT_CAP, IMAGE_BASE_URL, PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX
from core.db import get_db
from core.deps import require_internal_auth, session_id
from api.schemas import ErrorResponse, ProductDetailResponse, ProductListResponse
from core.errors import AppError
from domain.stock import is_new, is_selectable, label_from_qty
from repository import product as repo

router = APIRouter(prefix="/products", tags=["products"])

# 商品コードは ascii の20文字以内（db/ddl の VARCHAR(20) ascii_bin）
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
SORTS = ("new", "price_asc", "price_desc")


def _image_url(relative: str) -> str:
    """R-12 で決めた。DBは相対パスを持ち、ここでベースURLを前置する。"""
    return f"{IMAGE_BASE_URL.rstrip('/')}/{relative.lstrip('/')}"


def _parse_after(after: str | None, sort: str) -> tuple[Any, str | None]:
    """`after` を厳しく検査する（SEC-504a）。

    ★`after` は「前ページの最後の値」がそのまま WHERE と ORDER BY に載るので、
      他の入力と経路が違う。ここで弾けなければ、その先はORMの束縛変数に入るだけで、
      SQLとしては壊れないが、意味の壊れた問い合わせになる。
      形が合わないものは 400 / ERR-1003 にして、その場で止める。
    """
    if after is None or after == "":
        return None, None

    if "," not in after:
        raise AppError("ERR-1003", {"field": "after"})

    raw_value, raw_code = after.rsplit(",", 1)
    if not CODE_RE.match(raw_code):
        raise AppError("ERR-1003", {"field": "after"})

    if sort == "new":
        try:
            value: Any = datetime.fromisoformat(raw_value)
        except ValueError:
            raise AppError("ERR-1003", {"field": "after"}) from None
    else:
        if not re.fullmatch(r"\d{1,10}", raw_value):
            raise AppError("ERR-1003", {"field": "after"})
        value = int(raw_value)

    return value, raw_code


def _next_after(rows: list[dict], sort: str, limit: int) -> str | None:
    if len(rows) < limit:
        return None
    last = rows[-1]
    if sort == "new":
        return f"{last['created_at'].isoformat()},{last['product_code']}"
    return f"{last['price']},{last['product_code']}"


@router.get(
    "",
    dependencies=[Depends(require_internal_auth)],
    response_model=ProductListResponse,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_products(
    db: Session = Depends(get_db),
    _sid: str | None = Depends(session_id),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    sort: str = Query(default="new"),
    category: str | None = Query(default=None, max_length=20),
    keyword: str | None = Query(default=None, max_length=100),
    size: str | None = Query(default=None, max_length=10),
    color: str | None = Query(default=None, max_length=10),
    in_stock: bool = Query(default=False),
    after: str | None = Query(default=None, max_length=64),
) -> dict:
    """AP-101。★在庫は2値。合計しない（設計 9.2.1b・R-08 の実測）。"""
    if sort not in SORTS:
        raise AppError("ERR-1004", {"field": "sort"})
    if category and not CODE_RE.match(category):
        raise AppError("ERR-1004", {"field": "category"})

    after_value, after_code = _parse_after(after, sort)

    rows = repo.list_products(
        db,
        limit=limit,
        sort=sort,
        category=category,
        keyword=keyword,
        size=size,
        color=color,
        in_stock_only=in_stock,
        after_value=after_value,
        after_code=after_code,
    )

    codes = [r["product_code"] for r in rows]
    images = repo.images_for(db, codes)
    sizes = repo.sizes_for(db, codes)

    # ★件数は cap で打ち切って数える。COUNT(*) は EXISTS の打ち切りを消すため（9.2.1d）
    total = repo.count_products(
        db,
        cap=COUNT_CAP + 1,
        sort=sort,
        category=category,
        keyword=keyword,
        size=size,
        color=color,
        in_stock_only=in_stock,
    )
    capped = total > COUNT_CAP
    if capped:
        total = COUNT_CAP

    data = []
    now = datetime.now()
    for r in rows:
        imgs = images.get(r["product_code"], [])
        data.append(
            {
                "product_code": r["product_code"],
                "name": r["name"],
                "price": r["price"],
                "category_code": r["category_code"],
                # ★2値。商品詳細の3値と混ぜない
                "in_stock": bool(r["in_stock"]),
                "image_url": _image_url(imgs[0]["url"]) if imgs else None,
                "size_range": [x["name"] for x in sizes.get(r["product_code"], [])],
                "is_new": is_new(r.get("created_at"), now),
            }
        )

    return {
        "data": data,
        "page": {
            "limit": limit,
            "sort": sort,
            "next_after": _next_after(rows, sort, limit),
            "total": total,
            "total_capped": capped,
        },
    }


@router.get(
    "/{product_code}",
    dependencies=[Depends(require_internal_auth)],
    response_model=ProductDetailResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_product(
    product_code: str,
    db: Session = Depends(get_db),
    _sid: str | None = Depends(session_id),
) -> dict:
    """AP-102。★ここだけ BR-25 の3値（設計 9.2.1b）。"""
    if not CODE_RE.match(product_code):
        # 形が違う時点で 404。存在するかどうかも答えない（8.2 ERR-1215）
        raise AppError("ERR-1215")

    p = repo.get_product(db, product_code)
    if p is None:
        raise AppError("ERR-1215")

    images = repo.images_of(db, product_code)
    image_by_color: dict[str, str] = {}
    for img in images:
        image_by_color.setdefault(img["color_code"], _image_url(img["url"]))

    colors: dict[str, dict] = {}
    sizes: dict[str, dict] = {}
    variants = []
    for row in repo.sku_availability(db, product_code):
        qty = int(row["saleable_qty"] or 0)
        colors.setdefault(
            row["color_code"],
            {
                "color_code": row["color_code"],
                "name": row["color_name"],
                "image_url": image_by_color.get(row["color_code"]),
            },
        )
        sizes.setdefault(
            row["size_code"],
            {"size_code": row["size_code"], "name": row["size_name"], "sort": row["size_sort"]},
        )
        variants.append(
            {
                "sku_code": row["sku_code"],
                "color_code": row["color_code"],
                "size_code": row["size_code"],
                # ★3値。domain が決める。ここでは呼ぶだけ
                "stock_label": label_from_qty(qty).value,
                # ★0点のサイズは選べない（F-203）
                "selectable": is_selectable(qty),
            }
        )

    return {
        "data": {
            "product_code": p["product_code"],
            "name": p["name"],
            "price": p["price"],
            "category_code": p["category_code"],
            "material": p["material"],
            "description": p["description"],
            "colors": list(colors.values()),
            "sizes": sorted(sizes.values(), key=lambda s: s["sort"]),
            "variants": variants,
        }
    }
