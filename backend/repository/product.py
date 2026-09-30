# -*- coding: utf-8 -*-
"""商品のDBアクセス（AP-101 / AP-102）。

★SQLは ORM で組む。文字列連結しない（N-32）。
  検索キーワードも after も、すべて束縛変数として渡る（SEC-501・502・504a）。

★在庫の候補拠点の条件は BR-05c の（a）3条件（設計 3.2.2 ⑥）。
  検証4・検証5 と同じ式を、ここで1か所にまとめる。
"""
from __future__ import annotations

from sqlalchemy import text as sqltext
from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from repository.models import (
    Color,
    EcExclusion,
    Location,
    Product,
    ProductImage,
    Size,
    Sku,
    Stock,
)

# 一覧・詳細で共有する。★片方だけ直すと suspended の考慮が漏れる（R-02 ③の指摘）
_SECTION_BACKYARD = 1


def _candidate_location_clause():
    """BR-05c（a）候補拠点の条件（設計 3.2.2 ⑥）。数量の条件（b）は含めない。"""
    return and_(
        Stock.section == _SECTION_BACKYARD,
        Location.ec_saleable.is_(True),
        Location.suspended.is_(False),
    )


def _in_stock_exists(product_code_col):
    """その商品が、候補拠点のどこかで1点でも売れるか（2値。設計 9.2.1b）。

    ★合計しない。EXISTS で「あるか」だけ見る。
      合計すると同時20人で 16.4 秒、EXISTS なら 72 ミリ秒（R-08 の実測）。
    """
    exclusion = (
        select(EcExclusion.product_code)
        .where(
            EcExclusion.product_code == product_code_col,
            EcExclusion.location_code == Location.location_code,
        )
        .exists()
    )
    return (
        select(Sku.sku_code)
        .join(Stock, Stock.sku_code == Sku.sku_code)
        .join(Location, Location.location_code == Stock.location_code)
        .where(
            Sku.product_code == product_code_col,
            _candidate_location_clause(),
            Stock.qty > Stock.reserved_qty,   # ★引き算をしない（設計 3.2.2 ①）
            ~exclusion,
        )
        .exists()
    )


# ------------------------------------------------------------
# AP-101  商品一覧
# ------------------------------------------------------------
SORTS = {
    # 並びは API 側で固定する（4.1.7）。クライアントに任意の並びを指定させない
    "new": (Product.created_at.desc(), Product.product_code.desc()),
    "price_asc": (Product.price.asc(), Product.product_code.asc()),
    "price_desc": (Product.price.desc(), Product.product_code.asc()),
}


def _apply_keyset(stmt: Select, sort: str, after_value, after_code: str) -> Select:
    """キーセット方式の続きから引く（4.1.7・9.2.1c）。★OFFSET を使わない。"""
    if sort == "new":
        return stmt.where(
            (Product.created_at < after_value)
            | ((Product.created_at == after_value) & (Product.product_code < after_code))
        )
    if sort == "price_asc":
        return stmt.where(
            (Product.price > after_value)
            | ((Product.price == after_value) & (Product.product_code > after_code))
        )
    return stmt.where(
        (Product.price < after_value)
        | ((Product.price == after_value) & (Product.product_code > after_code))
    )


def list_products(
    db: Session,
    *,
    limit: int,
    sort: str,
    category: str | None = None,
    keyword: str | None = None,
    size: str | None = None,
    color: str | None = None,
    in_stock_only: bool = False,
    after_value=None,
    after_code: str | None = None,
) -> list[dict]:
    in_stock = _in_stock_exists(Product.product_code)

    stmt = select(
        Product.product_code,
        Product.name,
        Product.price,
        Product.category_code,
        Product.created_at,
        in_stock.label("in_stock"),
    ).where(Product.is_published.is_(True))

    if category:
        stmt = stmt.where(Product.category_code == category)

    if keyword:
        # ★ORM が束縛変数にする。文字列連結しない（SEC-501・502）
        #   LIKE のメタ文字は、検索語として素直に扱えるようにエスケープする
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # ★商品名だけでなく商品コードでも探せる（FR-102）。
        #   ★店頭の値札に印刷されているのは商品コード。
        #     「店で見た服をあとでECで買う」が要求の入口なので、
        #     ここが効かないと値札を持っている客がたどり着けない（R-24 の AT-102）。
        # ★商品コードは ascii_bin、検索語は utf8mb4。そのまま LIKE で混ぜると
        #   ERROR 1270 Illegal mix of collations で落ちる。
        #   ★CONVERT で照合順序をそろえてから比べる。
        #     値は必ず束縛変数で渡す（文字列連結しない。N-32・SEC-501）。
        stmt = stmt.where(
            Product.name.like(f"%{escaped}%", escape="\\")
            | sqltext("CONVERT(product.product_code USING utf8mb4) "
                      "LIKE :kw_code ESCAPE '\\\\'").bindparams(kw_code=f"%{escaped}%")
        )

    if size:
        stmt = stmt.where(
            select(Sku.sku_code)
            .where(Sku.product_code == Product.product_code, Sku.size_code == size)
            .exists()
        )

    if color:
        stmt = stmt.where(
            select(Sku.sku_code)
            .where(Sku.product_code == Product.product_code, Sku.color_code == color)
            .exists()
        )

    if in_stock_only:
        stmt = stmt.where(in_stock)

    if after_value is not None and after_code is not None:
        stmt = _apply_keyset(stmt, sort, after_value, after_code)

    stmt = stmt.order_by(*SORTS[sort]).limit(limit)
    return [dict(r._mapping) for r in db.execute(stmt).all()]


def count_products(
    db: Session,
    *,
    cap: int,
    sort: str,
    category: str | None = None,
    keyword: str | None = None,
    size: str | None = None,
    color: str | None = None,
    in_stock_only: bool = False,
) -> int:
    """件数。★cap 件で打ち切る（設計 9.2.1d・R-16 の実測）。

    COUNT(*) は EXISTS の打ち切りを消してしまう。絞り込みなしなら 0ms でも、
    在庫の EXISTS が付くと商品の数だけ EXISTS がまわり、20並列で p95 10.6 秒になった。
    LIMIT cap で内側を止めれば、EXISTS は最大 cap 回しかまわらない（同 377 ms）。
    """
    in_stock = _in_stock_exists(Product.product_code)
    inner = select(Product.product_code).where(Product.is_published.is_(True))
    if category:
        inner = inner.where(Product.category_code == category)
    if keyword:
        escaped = keyword.replace("\\", "\\\\").replace("%", "\%").replace("_", "\_")
        # ★件数を数える側にも同じ条件を掛ける（10.2.6。入口が2つある）
        inner = inner.where(
            Product.name.like(f"%{escaped}%", escape="\\")
            | sqltext("CONVERT(product.product_code USING utf8mb4) "
                      "LIKE :kw_code ESCAPE '\\\\'").bindparams(kw_code=f"%{escaped}%")
        )
    if size:
        inner = inner.where(
            select(Sku.sku_code)
            .where(Sku.product_code == Product.product_code, Sku.size_code == size)
            .exists()
        )
    if color:
        inner = inner.where(
            select(Sku.sku_code)
            .where(Sku.product_code == Product.product_code, Sku.color_code == color)
            .exists()
        )
    if in_stock_only:
        inner = inner.where(in_stock)
    sub = inner.limit(cap).subquery()
    return int(db.execute(select(func.count()).select_from(sub)).scalar() or 0)


def sizes_for(db: Session, product_codes: list[str]) -> dict[str, list[dict]]:
    """一覧のカードに出すサイズ展開（09-05 決定）。

    ★行ごとに引き直さない。20件ぶんを1回で引く（N-06・9.2.2）。
      sku はもう引いているので、追加のクエリは1本だけで済む。
    """
    if not product_codes:
        return {}
    stmt = (
        select(Sku.product_code, Sku.size_code, Size.name, Size.sort_no)
        .join(Size, Size.size_code == Sku.size_code)
        .where(Sku.product_code.in_(product_codes))
        .distinct()
        .order_by(Sku.product_code, Size.sort_no)
    )
    out: dict[str, list[dict]] = {}
    for code, size_code, name, _ in db.execute(stmt).all():
        out.setdefault(code, []).append({"size_code": size_code, "name": name})
    return out


def images_for(db: Session, product_codes: list[str]) -> dict[str, list[dict]]:
    """★一覧の行ごとに引き直さない。20件ぶんを1回で引く（N-06・9.2.2）。"""
    if not product_codes:
        return {}
    stmt = (
        select(ProductImage.product_code, ProductImage.color_code, ProductImage.url)
        .where(ProductImage.product_code.in_(product_codes))
        .order_by(ProductImage.product_code, ProductImage.color_code, ProductImage.sort_no)
    )
    out: dict[str, list[dict]] = {}
    for code, color, url in db.execute(stmt).all():
        out.setdefault(code, []).append({"color_code": color, "url": url})
    return out


# ------------------------------------------------------------
# AP-102  商品詳細
# ------------------------------------------------------------
def get_product(db: Session, product_code: str) -> dict | None:
    stmt = select(
        Product.product_code,
        Product.name,
        Product.price,
        Product.category_code,
        Product.material,
        Product.description,
    ).where(Product.product_code == product_code, Product.is_published.is_(True))
    row = db.execute(stmt).first()
    return dict(row._mapping) if row else None


def sku_availability(db: Session, product_code: str) -> list[dict]:
    """SKUごとの販売可能数（3値の材料）。

    ★1商品ぶんなので合計してよい（設計 9.2.1b）。5SKU × 32拠点＝約160行。
      一覧で同じことをすると1万商品ぶんになるので、そちらは EXISTS にしてある。
    """
    exclusion = (
        select(EcExclusion.product_code)
        .where(
            EcExclusion.product_code == product_code,
            EcExclusion.location_code == Location.location_code,
        )
        .exists()
    )
    # ★負にしないための GREATEST は SQL 側で書く（設計 3.2.2 ①。UNSIGNED の引き算を避ける）
    saleable = func.sum(
        func.greatest(
            func.cast(Stock.qty, __import__("sqlalchemy").Integer)
            - func.cast(Stock.reserved_qty, __import__("sqlalchemy").Integer),
            0,
        )
    )
    stmt = (
        select(
            Sku.sku_code,
            Sku.color_code,
            Sku.size_code,
            Color.name.label("color_name"),
            Size.name.label("size_name"),
            Size.sort_no.label("size_sort"),
            Color.sort_no.label("color_sort"),
            func.coalesce(saleable, 0).label("saleable_qty"),
        )
        .select_from(Sku)
        .join(Color, Color.color_code == Sku.color_code)
        .join(Size, Size.size_code == Sku.size_code)
        .outerjoin(
            Stock,
            and_(Stock.sku_code == Sku.sku_code, Stock.section == _SECTION_BACKYARD),
        )
        .outerjoin(
            Location,
            and_(
                Location.location_code == Stock.location_code,
                Location.ec_saleable.is_(True),
                Location.suspended.is_(False),
                ~exclusion,
            ),
        )
        .where(Sku.product_code == product_code, Location.location_code.isnot(None) | Stock.sku_code.is_(None))
        .group_by(
            Sku.sku_code, Sku.color_code, Sku.size_code,
            Color.name, Size.name, Size.sort_no, Color.sort_no,
        )
        .order_by(Color.sort_no, Size.sort_no)
    )
    return [dict(r._mapping) for r in db.execute(stmt).all()]


def images_of(db: Session, product_code: str) -> list[dict]:
    stmt = (
        select(ProductImage.color_code, ProductImage.url)
        .where(ProductImage.product_code == product_code)
        .order_by(ProductImage.color_code, ProductImage.sort_no)
    )
    return [{"color_code": c, "url": u} for c, u in db.execute(stmt).all()]


def categories(db: Session) -> list[dict]:
    from repository.models import Category

    stmt = (
        select(Category.category_code, Category.name, Category.parent_code)
        .where(Category.is_active.is_(True))
        .order_by(Category.sort_no)
    )
    return [dict(r._mapping) for r in db.execute(stmt).all()]
