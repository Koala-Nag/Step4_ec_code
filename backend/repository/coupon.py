# -*- coding: utf-8 -*-
"""クーポンの読み書き（BR-16a・設計 6.2.3）。

★全体上限は「条件付きUPDATEの更新件数」で決める。在庫とまったく同じ形。
  ★読んでから書かない。読んだ時点の used_count で判定すると、
    ちょうど最後の1枚を2人が取り合ったときに両方通る。
"""
from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from domain.coupon import Coupon


def find(db: Session, coupon_code: str) -> Coupon | None:
    row = db.execute(
        text("SELECT coupon_code, discount_type, discount_value, start_at, end_at, "
             "       min_amount, total_limit, used_count, per_member_limit "
             "  FROM coupon WHERE coupon_code = :c"),
        {"c": coupon_code},
    ).first()
    if not row:
        return None
    m = row._mapping
    return Coupon(
        coupon_code=m["coupon_code"], discount_type=int(m["discount_type"]),
        discount_value=int(m["discount_value"]), start_at=m["start_at"], end_at=m["end_at"],
        min_amount=int(m["min_amount"]),
        total_limit=None if m["total_limit"] is None else int(m["total_limit"]),
        used_count=int(m["used_count"]),
        per_member_limit=None if m["per_member_limit"] is None else int(m["per_member_limit"]),
    )


def member_used_count(db: Session, coupon_code: str, member_id: str | None) -> int:
    """BR-16a。会員あたりの上限は、その会員の利用履歴の件数で判定する。"""
    if not member_id:
        return 0
    row = db.execute(
        text("SELECT COUNT(*) c FROM coupon_use WHERE coupon_code = :c AND member_id = :m"),
        {"c": coupon_code, "m": member_id},
    ).first()
    return int(row.c)


def consume(db: Session, coupon_code: str) -> bool:
    """★全体上限の先勝ち（BR-16a）。更新できたら True。

    ★引き算をしない・読んでから書かない。1本のUPDATEで「空いているか」と
      「1つ使う」を同時にやる。更新件数が0なら、他が先に取った。
    ★呼び出し側は同じトランザクションの中で呼ぶ（6.2.3 の①）。
    """
    n = db.execute(
        text("UPDATE coupon SET used_count = used_count + 1 "
             " WHERE coupon_code = :c "
             "   AND (total_limit IS NULL OR used_count < total_limit)"),
        {"c": coupon_code},
    ).rowcount
    return int(n) == 1


def record_use(db: Session, *, coupon_code: str, member_id: str | None,
               order_no: str, discount: int) -> None:
    db.execute(
        text("INSERT INTO coupon_use (coupon_code, member_id, order_no, discount) "
             "VALUES (:c, :m, :o, :d)"),
        {"c": coupon_code, "m": member_id, "o": order_no, "d": discount},
    )


def release(db: Session, order_no: str) -> int:
    """BR-16a の後半。★キャンセルされたら利用済回数を戻し、E-29 の行を消す。

    ★戻すほうも条件付きにする。0 を下回らせない
      （UNSIGNED なので、下回ると ERROR 1690 で落ちる。3.2.2 ①と同じ話）。
    """
    rows = db.execute(
        text("SELECT coupon_code FROM coupon_use WHERE order_no = :o"), {"o": order_no}
    ).all()
    for r in rows:
        db.execute(
            text("UPDATE coupon SET used_count = used_count - 1 "
                 " WHERE coupon_code = :c AND used_count >= 1"),
            {"c": r.coupon_code},
        )
    db.execute(text("DELETE FROM coupon_use WHERE order_no = :o"), {"o": order_no})
    return len(rows)


def eligible_total(db: Session, coupon_code: str, lines: list[tuple[str, int]]) -> int:
    """BR-12。★対象を限定したクーポンは、対象商品の明細金額の合計に適用する（R-32）。

    lines  [(sku_code, 明細金額)]。判定は domain/coupon.eligible_total。
    """
    from domain import coupon as cd

    targets = [(int(r.target_kind), r.target_id) for r in db.execute(
        text("SELECT target_kind, target_id FROM coupon_target WHERE coupon_code = :c"),
        {"c": coupon_code}).all()]
    if not lines:
        return 0
    info = {r.sku_code: r for r in db.execute(
        text("SELECT s.sku_code, p.product_code, p.category_code, c.parent_code "
             "  FROM sku s JOIN product p ON p.product_code = s.product_code "
             "  JOIN category c ON c.category_code = p.category_code "
             " WHERE s.sku_code IN :skus").bindparams(bindparam("skus", expanding=True)),
        {"skus": [sku for sku, _ in lines]}).all()}
    return cd.eligible_total(targets, [
        cd.TargetLine(amount, info[sku].product_code, info[sku].category_code, info[sku].parent_code)
        for sku, amount in lines if sku in info])


def targets_of(db: Session, coupon_code: str) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(
        text("SELECT target_kind, target_id FROM coupon_target WHERE coupon_code = :c ORDER BY id"),
        {"c": coupon_code}).all()]
