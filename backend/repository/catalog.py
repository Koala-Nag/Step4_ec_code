# -*- coding: utf-8 -*-
"""運営が入力するもの（運営者・マスタ・商品・SKU・画像・払い出し）の読み書き。R-27。

★DBに触るのはこの層だけ（設計 2.2）。通してよい値かは domain/catalog.py。
★値はすべて束縛変数で渡す（N-32）。★表名・列名だけは domain/catalog.MASTERS の固定値から取る
  （画面から来た文字列を SQL に入れない）。
"""
from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from domain import catalog as cg

SECTION_BACKYARD, SECTION_FLOOR = 1, 2
REASON_MANUAL, REASON_FLOOR = 1, 3      # stock_change_log.reason


class Duplicate(Exception):
    """一意制約に当たる（ERR-1216）。"""


class InUse(Exception):
    """使われているので消せない（F-709。ERR-1217）。"""


def op_log(db: Session, operator_id: str, target: str, action: str) -> None:
    db.execute(text("INSERT INTO operation_log (operator_id, target, action) VALUES (:p, :t, :a)"),
               {"p": operator_id, "t": target[:100], "a": action[:100]})


# ============================================================
# 拠点（選択肢に使う）
# ============================================================
def locations(db: Session) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(
        "SELECT location_code, name, kind, ec_saleable, suspended, pref_code, "
        "       TIME_FORMAT(cutoff_time, '%H:%i') AS cutoff_time, business_days FROM location "
        " ORDER BY kind, location_code")).all()]


def location_kind(db: Session, location_code: str | None) -> int | None:
    if not location_code:
        return None
    r = db.execute(text("SELECT kind FROM location WHERE location_code = :l"),
                   {"l": location_code}).first()
    return int(r.kind) if r else None


# ============================================================
# F-1302  運営者
# ============================================================
def list_operators(db: Session) -> list[dict]:
    # ★password_hash は選ばない（画面に出す理由が無い）
    return [dict(r._mapping) for r in db.execute(text(
        "SELECT operator_id, name, email, role, location_code, is_active FROM operator "
        " ORDER BY role, operator_id")).all()]


def create_operator(db: Session, *, operator_id: str, name: str, email: str,
                    password_hash: str, role: int, location_code: str | None, by: str) -> None:
    dup = db.execute(text("SELECT 1 FROM operator WHERE operator_id = :i OR email = :e"),
                     {"i": operator_id, "e": email}).first()
    if dup:
        raise Duplicate()
    db.execute(text(
        "INSERT INTO operator (operator_id, name, email, password_hash, role, location_code, is_active) "
        "VALUES (:i, :n, :e, :h, :r, :l, TRUE)"),
        {"i": operator_id, "n": name, "e": email, "h": password_hash, "r": role, "l": location_code})
    op_log(db, by, f"operator/{operator_id}", f"AP-B34 登録 role={role} loc={location_code or '-'}")
    db.commit()


def get_operator(db: Session, operator_id: str) -> dict | None:
    r = db.execute(text("SELECT operator_id, name, email, role, location_code, is_active "
                        "  FROM operator WHERE operator_id = :i"), {"i": operator_id}).first()
    return dict(r._mapping) if r else None


def update_operator(db: Session, operator_id: str, fields: dict, *, by: str) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in fields)          # ★キーは api 側で固定の集合に限っている
    db.execute(text(f"UPDATE operator SET {sets} WHERE operator_id = :id"),
               {**fields, "id": operator_id})
    if fields.get("is_active") is False:
        # ★無効にしたら、いま開いているセッションも消す（次のリクエストから入れない）
        db.execute(text("DELETE FROM session WHERE operator_id = :id"), {"id": operator_id})
    shown = {k: ("***" if k == "password_hash" else v) for k, v in fields.items()}
    op_log(db, by, f"operator/{operator_id}", f"AP-B34 変更 {shown}")
    db.commit()


# ============================================================
# F-709  マスタ
# ============================================================
def list_master(db: Session, kind: str) -> list[dict]:
    m = cg.MASTERS[kind]
    cols = [m.key + " AS code", "name", "is_active"]
    if m.has_sort:
        cols.append("sort_no")
    if m.has_parent:
        cols.append("parent_code")
    order = "sort_no, " + m.key if m.has_sort else m.key
    rows = [dict(r._mapping) for r in db.execute(
        text(f"SELECT {', '.join(cols)} FROM {m.table} ORDER BY {order}")).all()]
    for r in rows:
        r["used"] = master_in_use(db, kind, r["code"])
    return rows


def master_in_use(db: Session, kind: str, code: str) -> bool:
    for table, col in cg.MASTER_USAGE[kind]:
        if db.execute(text(f"SELECT 1 FROM {table} WHERE {col} = :c LIMIT 1"), {"c": code}).first():
            return True
    return False


def create_master(db: Session, kind: str, *, code: str, name: str, sort_no: int | None,
                  parent_code: str | None, by: str) -> None:
    m = cg.MASTERS[kind]
    if db.execute(text(f"SELECT 1 FROM {m.table} WHERE {m.key} = :c"), {"c": code}).first():
        raise Duplicate()
    cols, vals = [m.key, "name", "is_active"], [":code", ":name", "TRUE"]
    params: dict = {"code": code, "name": name}
    if m.has_sort:
        cols.append("sort_no"); vals.append(":sort"); params["sort"] = int(sort_no or 0)
    if m.has_parent:
        cols.append("parent_code"); vals.append(":parent"); params["parent"] = parent_code
    db.execute(text(f"INSERT INTO {m.table} ({', '.join(cols)}) VALUES ({', '.join(vals)})"), params)
    op_log(db, by, f"master/{kind}/{code}", f"AP-B03 登録 {name}")
    db.commit()


def update_master(db: Session, kind: str, code: str, fields: dict, *, by: str) -> int:
    m = cg.MASTERS[kind]
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    n = db.execute(text(f"UPDATE {m.table} SET {sets} WHERE {m.key} = :code"),
                   {**fields, "code": code}).rowcount
    op_log(db, by, f"master/{kind}/{code}", f"AP-B03 変更 {fields}")
    db.commit()
    return n


def delete_master(db: Session, kind: str, code: str, *, by: str) -> int:
    """★使われていれば消さない。無効化のみ（F-709）。"""
    m = cg.MASTERS[kind]
    if master_in_use(db, kind, code):
        raise InUse()
    n = db.execute(text(f"DELETE FROM {m.table} WHERE {m.key} = :c"), {"c": code}).rowcount
    op_log(db, by, f"master/{kind}/{code}", "AP-B03 削除")
    db.commit()
    return n


def exists_active(db: Session, kind: str, code: str | None) -> bool:
    if not code:
        return False
    m = cg.MASTERS[kind]
    return db.execute(text(f"SELECT 1 FROM {m.table} WHERE {m.key} = :c AND is_active"),
                      {"c": code}).first() is not None


def list_size_map(db: Session) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(
        "SELECT size_code, common_size_code FROM size_map ORDER BY size_code, common_size_code")).all()]


def add_size_map(db: Session, size_code: str, common_size_code: str, *, by: str) -> None:
    if db.execute(text("SELECT 1 FROM size_map WHERE size_code = :s AND common_size_code = :c"),
                  {"s": size_code, "c": common_size_code}).first():
        raise Duplicate()
    db.execute(text("INSERT INTO size_map (size_code, common_size_code) VALUES (:s, :c)"),
               {"s": size_code, "c": common_size_code})
    op_log(db, by, f"master/size-map/{size_code}", f"AP-B03 対応 {size_code}→{common_size_code}")
    db.commit()


# ============================================================
# F-701〜705  商品
# ============================================================
def list_products(db: Session, keyword: str | None = None) -> list[dict]:
    sql = ("SELECT p.product_code, p.name, p.price, p.category_code, p.is_published, p.updated_at, "
           "       (SELECT COUNT(*) FROM sku s WHERE s.product_code = p.product_code) AS sku_count, "
           "       (SELECT COUNT(*) FROM product_image i WHERE i.product_code = p.product_code) AS image_count "
           "  FROM product p")
    params: dict = {}
    if keyword:
        esc = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += (" WHERE p.name LIKE :kw ESCAPE '\\\\' "
                "    OR CONVERT(p.product_code USING utf8mb4) LIKE :kw ESCAPE '\\\\'")
        params["kw"] = f"%{esc}%"
    sql += " ORDER BY p.product_code DESC LIMIT 200"
    return [dict(r._mapping) for r in db.execute(text(sql), params).all()]


def get_product(db: Session, code: str) -> dict | None:
    r = db.execute(text(
        "SELECT product_code, name, category_code, item_type_code, material, description, price, "
        "       is_published, created_at, updated_at FROM product WHERE product_code = :c"),
        {"c": code}).first()
    return dict(r._mapping) if r else None


def create_product(db: Session, fields: dict, *, by: str) -> None:
    if db.execute(text("SELECT 1 FROM product WHERE product_code = :c"),
                  {"c": fields["product_code"]}).first():
        raise Duplicate()
    # ★作った時点では非公開（SKU も画像も無いまま客に見せない）
    db.execute(text(
        "INSERT INTO product (product_code, name, category_code, item_type_code, material, "
        "                     description, price, is_published) "
        "VALUES (:product_code, :name, :category_code, :item_type_code, :material, :description, "
        "        :price, FALSE)"), fields)
    op_log(db, by, f"product/{fields['product_code']}", f"AP-B02 登録 price={fields['price']}")
    db.commit()


def update_product(db: Session, code: str, fields: dict, *, by: str, before: dict) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(text(f"UPDATE product SET {sets} WHERE product_code = :code"), {**fields, "code": code})
    # ★価格と公開状態は、前の値も残す（あとで「いつ誰が変えたか」を追えるように。N-14）
    changes = []
    for k in fields:
        if k in ("price", "is_published") and before.get(k) != fields[k]:
            changes.append(f"{k}:{before.get(k)}→{fields[k]}")
        elif k not in ("price", "is_published"):
            changes.append(k)
    op_log(db, by, f"product/{code}", "AP-B02 変更 " + " ".join(changes))
    db.commit()


def skus_of(db: Session, code: str) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(
        "SELECT s.sku_code, s.color_code, s.size_code, s.common_size_code, c.name AS color_name, "
        "       z.name AS size_name "
        "  FROM sku s JOIN color c ON c.color_code = s.color_code "
        "  JOIN size z ON z.size_code = s.size_code "
        " WHERE s.product_code = :c ORDER BY c.sort_no, z.sort_no"), {"c": code}).all()]


def stocks_of(db: Session, code: str) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(
        "SELECT st.sku_code, st.location_code, st.section, st.qty, st.reserved_qty "
        "  FROM stock st JOIN sku s ON s.sku_code = st.sku_code "
        " WHERE s.product_code = :c ORDER BY st.sku_code, st.location_code, st.section"),
        {"c": code}).all()]


def common_size_for(db: Session, size_code: str) -> str | None:
    r = db.execute(text(
        "SELECT m.common_size_code FROM size_map m JOIN common_size c "
        "    ON c.common_size_code = m.common_size_code "
        " WHERE m.size_code = :s ORDER BY c.sort_no LIMIT 1"), {"s": size_code}).first()
    return r.common_size_code if r else None


def create_skus(db: Session, code: str, made: list[cg.NewSku], common: dict[str, str],
                stocks: list[dict], *, by: str) -> None:
    """★1つのトランザクション。一意制約（uq_sku_combo）に当たったら全部取り消す。"""
    from sqlalchemy.exc import IntegrityError

    try:
        for m in made:
            db.execute(text(
                "INSERT INTO sku (sku_code, product_code, color_code, size_code, common_size_code) "
                "VALUES (:k, :p, :c, :s, :cs)"),
                {"k": m.sku_code, "p": code, "c": m.color_code, "s": m.size_code,
                 "cs": common[m.size_code]})
        # ★在庫は (location_code, sku_code) の昇順で書く（6.2.3）
        for st in sorted(stocks, key=lambda x: x["location_code"]):
            for m in sorted(made, key=lambda x: x.sku_code):
                db.execute(text(
                    "INSERT INTO stock (sku_code, location_code, section, qty, reserved_qty) "
                    "VALUES (:k, :l, :sec, :q, 0)"),
                    {"k": m.sku_code, "l": st["location_code"], "sec": SECTION_BACKYARD,
                     "q": int(st["qty"])})
        op_log(db, by, f"product/{code}",
               f"AP-B02 SKU一括 {len(made)}件 在庫={[(s['location_code'], s['qty']) for s in stocks]}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Duplicate()


def set_stocks(db: Session, code: str, items: list[dict], *, by: str) -> None:
    """拠点ごとの在庫数（F-702）。★引当済数を下回る値にはしない（ERR-1208・9.9）。"""
    try:
        for it in sorted(items, key=lambda x: (x["location_code"], x["sku_code"])):
            cur = db.execute(text(
                "SELECT qty, reserved_qty FROM stock WHERE sku_code = :k AND location_code = :l "
                "   AND section = :sec FOR UPDATE"),
                {"k": it["sku_code"], "l": it["location_code"], "sec": SECTION_BACKYARD}).first()
            q = int(it["qty"])
            if cur is None:
                db.execute(text("INSERT INTO stock (sku_code, location_code, section, qty, reserved_qty) "
                                "VALUES (:k, :l, :sec, :q, 0)"),
                           {"k": it["sku_code"], "l": it["location_code"], "sec": SECTION_BACKYARD, "q": q})
                before = 0
            else:
                if q < int(cur.reserved_qty):
                    raise ValueError("ERR-1208")
                n = db.execute(text(
                    "UPDATE stock SET qty = :q WHERE sku_code = :k AND location_code = :l "
                    "   AND section = :sec AND reserved_qty <= :q"),
                    {"q": q, "k": it["sku_code"], "l": it["location_code"], "sec": SECTION_BACKYARD}).rowcount
                if n == 0:
                    raise ValueError("ERR-1208")
                before = int(cur.qty)
            if before != q:
                db.execute(text(
                    "INSERT INTO stock_change_log (sku_code, location_code, section, reason, qty_before, "
                    "  qty_after, note, operator_id) VALUES (:k, :l, :sec, :r, :b, :a, :n, :op)"),
                    {"k": it["sku_code"], "l": it["location_code"], "sec": SECTION_BACKYARD,
                     "r": REASON_MANUAL, "b": before, "a": q, "n": "F-702 商品画面から", "op": by})
        op_log(db, by, f"product/{code}", f"AP-B02 在庫 {len(items)}件")
        db.commit()
    except Exception:
        db.rollback()
        raise


# ---- 画像（F-703）----
def images_of(db: Session, code: str) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(
        "SELECT color_code, sort_no, url FROM product_image WHERE product_code = :c "
        " ORDER BY color_code, sort_no"), {"c": code}).all()]


def image_count(db: Session, code: str) -> int:
    return int(db.execute(text("SELECT COUNT(*) n FROM product_image WHERE product_code = :c"),
                          {"c": code}).first().n)


def next_image_sort(db: Session, code: str, color: str) -> int:
    return int(db.execute(text(
        "SELECT COALESCE(MAX(sort_no), 0) + 1 n FROM product_image "
        " WHERE product_code = :p AND color_code = :c"), {"p": code, "c": color}).first().n)


def add_image(db: Session, code: str, color: str, sort_no: int, url: str, *, by: str) -> None:
    db.execute(text("INSERT INTO product_image (product_code, color_code, sort_no, url) "
                    "VALUES (:p, :c, :s, :u)"), {"p": code, "c": color, "s": sort_no, "u": url})
    op_log(db, by, f"product/{code}", f"AP-B02 画像 {color}#{sort_no}")
    db.commit()


def delete_image(db: Session, code: str, color: str, sort_no: int, *, by: str) -> str | None:
    r = db.execute(text("SELECT url FROM product_image WHERE product_code = :p AND color_code = :c "
                        "   AND sort_no = :s"), {"p": code, "c": color, "s": sort_no}).first()
    if not r:
        return None
    db.execute(text("DELETE FROM product_image WHERE product_code = :p AND color_code = :c "
                    "   AND sort_no = :s"), {"p": code, "c": color, "s": sort_no})
    op_log(db, by, f"product/{code}", f"AP-B02 画像削除 {color}#{sort_no}")
    db.commit()
    return r.url


def move_image(db: Session, code: str, color: str, sort_no: int, direction: str, *, by: str) -> bool:
    """並び順を隣と入れ替える。★主キーに sort_no が入っているので、いったん退避してから入れ替える。"""
    op = "<" if direction == "up" else ">"
    order = "DESC" if direction == "up" else "ASC"
    nb = db.execute(text(
        f"SELECT sort_no FROM product_image WHERE product_code = :p AND color_code = :c "
        f"   AND sort_no {op} :s ORDER BY sort_no {order} LIMIT 1 FOR UPDATE"),
        {"p": code, "c": color, "s": sort_no}).first()
    if not nb:
        db.rollback()
        return False
    other = int(nb.sort_no)
    q = ("UPDATE product_image SET sort_no = :to WHERE product_code = :p AND color_code = :c "
         "   AND sort_no = :fr")
    db.execute(text(q), {"p": code, "c": color, "fr": sort_no, "to": -1})
    db.execute(text(q), {"p": code, "c": color, "fr": other, "to": sort_no})
    db.execute(text(q), {"p": code, "c": color, "fr": -1, "to": other})
    op_log(db, by, f"product/{code}", f"AP-B02 画像並び {color} {sort_no}⇔{other}")
    db.commit()
    return True


# ============================================================
# F-808  店頭への払い出し
# ============================================================
def backyard_of(db: Session, sku_code: str, location_code: str) -> dict | None:
    r = db.execute(text("SELECT qty, reserved_qty FROM stock WHERE sku_code = :k AND location_code = :l "
                        "   AND section = :sec"),
                   {"k": sku_code, "l": location_code, "sec": SECTION_BACKYARD}).first()
    return dict(r._mapping) if r else None


def move_to_floor(db: Session, *, sku_code: str, location_code: str, qty: int, staff_name: str,
                  operator_id: str) -> dict | None:
    """バックヤード → 店頭。★1つのトランザクション。

    ★条件付きUPDATE。引当済の数量は払い出せない（WHERE qty >= reserved_qty + :q）。
      読んでから書くまでに引当が入っても、ここで 0件になって止まる（6.2.2 と同じ形）。
    ★(sku, location, section) の順に 1 → 2 で触る（6.2.3 の在庫の順序の中で、区分の昇順）。
    """
    before = db.execute(text("SELECT qty FROM stock WHERE sku_code = :k AND location_code = :l "
                             "   AND section = :sec FOR UPDATE"),
                        {"k": sku_code, "l": location_code, "sec": SECTION_BACKYARD}).first()
    if before is None:
        db.rollback()
        return None
    n = db.execute(text(
        "UPDATE stock SET qty = qty - :q WHERE sku_code = :k AND location_code = :l AND section = :sec "
        "   AND qty >= reserved_qty + :q"),
        {"q": qty, "k": sku_code, "l": location_code, "sec": SECTION_BACKYARD}).rowcount
    if n == 0:
        db.rollback()
        return None
    floor = db.execute(text("SELECT qty FROM stock WHERE sku_code = :k AND location_code = :l "
                            "   AND section = :sec FOR UPDATE"),
                       {"k": sku_code, "l": location_code, "sec": SECTION_FLOOR}).first()
    floor_before = int(floor.qty) if floor else 0
    db.execute(text(
        "INSERT INTO stock (sku_code, location_code, section, qty, reserved_qty) VALUES (:k, :l, :sec, :q, 0) "
        "ON DUPLICATE KEY UPDATE qty = qty + :q"),
        {"k": sku_code, "l": location_code, "sec": SECTION_FLOOR, "q": qty})
    for sec, b, a in ((SECTION_BACKYARD, int(before.qty), int(before.qty) - qty),
                      (SECTION_FLOOR, floor_before, floor_before + qty)):
        db.execute(text(
            "INSERT INTO stock_change_log (sku_code, location_code, section, reason, qty_before, qty_after, "
            "  note, operator_id, staff_name) VALUES (:k, :l, :sec, :r, :b, :a, :n, :op, :st)"),
            {"k": sku_code, "l": location_code, "sec": sec, "r": REASON_FLOOR, "b": b, "a": a,
             "n": f"F-808 店頭へ {qty}点", "op": operator_id, "st": staff_name[:50]})
    op_log(db, operator_id, f"stock/{location_code}/{sku_code}", f"AP-B08 店頭へ {qty}点 担当={staff_name}")
    db.commit()
    return {"backyard_before": int(before.qty), "backyard_after": int(before.qty) - qty,
            "floor_before": floor_before, "floor_after": floor_before + qty}


def floor_history(db: Session, location_code: str | None, limit: int = 30) -> list[dict]:
    sql = ("SELECT sku_code, location_code, section, qty_before, qty_after, staff_name, created_at "
           "  FROM stock_change_log WHERE reason = :r")
    params: dict = {"r": REASON_FLOOR, "lim": limit}
    if location_code is not None:
        sql += " AND location_code = :l"
        params["l"] = location_code
    sql += " AND section = 2 ORDER BY id DESC LIMIT :lim"
    return [dict(r._mapping) for r in db.execute(text(sql), params).all()]


# ============================================================
# F-809・F-806  拠点のEC販売可と、商品×拠点の除外（R-30）
# ============================================================
def get_location(db: Session, code: str) -> dict | None:
    r = db.execute(text("SELECT location_code, name, kind, ec_saleable, suspended FROM location "
                        " WHERE location_code = :l"), {"l": code}).first()
    return dict(r._mapping) if r else None


def update_location(db: Session, code: str, fields: dict, *, by: str, before: dict) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(text(f"UPDATE location SET {sets} WHERE location_code = :code"), {**fields, "code": code})
    op_log(db, by, f"location/{code}",
           "AP-B04 " + " ".join(f"{k}:{int(bool(before.get(k)))}→{int(bool(v))}" for k, v in fields.items()))
    db.commit()


def exclusions(db: Session, product_code: str | None = None) -> list[dict]:
    sql = ("SELECT e.product_code, e.location_code, p.name AS product_name, l.name AS location_name "
           "  FROM ec_exclusion e JOIN product p ON p.product_code = e.product_code "
           "  JOIN location l ON l.location_code = e.location_code")
    params: dict = {}
    if product_code:
        sql += " WHERE e.product_code = :p"
        params["p"] = product_code
    sql += " ORDER BY e.product_code, e.location_code"
    return [dict(r._mapping) for r in db.execute(text(sql), params).all()]


def add_exclusion(db: Session, product_code: str, location_code: str, *, by: str) -> bool:
    """★不可にする＝行を追加（3.2.2 ②）。すでにあれば何もしない（2回押しても1行）。"""
    n = db.execute(text("INSERT IGNORE INTO ec_exclusion (product_code, location_code) VALUES (:p, :l)"),
                   {"p": product_code, "l": location_code}).rowcount
    op_log(db, by, f"ec-exclusion/{product_code}/{location_code}", f"AP-B05 不可にする（{'追加' if n else '既にある'}）")
    db.commit()
    return bool(n)


def remove_exclusion(db: Session, product_code: str, location_code: str, *, by: str) -> bool:
    """★可に戻す＝行を削除（3.2.2 ②）。可否の列は持たない。"""
    n = db.execute(text("DELETE FROM ec_exclusion WHERE product_code = :p AND location_code = :l"),
                   {"p": product_code, "l": location_code}).rowcount
    op_log(db, by, f"ec-exclusion/{product_code}/{location_code}", f"AP-B05 可に戻す（{'削除' if n else '無かった'}）")
    db.commit()
    return bool(n)


# ============================================================
# F-807  滞留在庫の抽出（R-30）
# ============================================================
def stagnant_days(db: Session) -> int:
    """F-807 の日数（FT-01）。★販売設定から読む。無ければ既定の60日。"""
    from domain import stock as stock_domain

    row = db.execute(text("SELECT stagnant_days FROM sales_config WHERE effective_from <= CURDATE() "
                          " ORDER BY effective_from DESC LIMIT 1")).first()
    return int(row.stagnant_days) if row else stock_domain.STAGNANT_DAYS


def stagnant_stocks(db: Session, *, days: int, min_qty: int) -> list[dict]:
    """★バックヤード（区分1）だけ。ECで売れるのはバックヤードの在庫なので（BR-01・BR-24b）。

    ★最終販売日が無い行は出さない（domain/stock.is_stagnant と同じ条件）。
    ★その行が「いまECで売れるか」を並べて返す——抽出した次の操作（EC販売可への切替）を選ぶため。
    """
    rows = db.execute(text(
        "SELECT st.location_code, l.name AS location_name, l.kind, l.ec_saleable, l.suspended, "
        "       st.sku_code, s.product_code, p.name AS product_name, c.name AS color_name, z.name AS size_name, "
        "       st.qty, st.reserved_qty, st.last_sold_at, DATEDIFF(CURDATE(), st.last_sold_at) AS days, "
        "       EXISTS(SELECT 1 FROM ec_exclusion e WHERE e.product_code = s.product_code "
        "              AND e.location_code = st.location_code) AS excluded "
        "  FROM stock st "
        "  JOIN location l ON l.location_code = st.location_code "
        "  JOIN sku s ON s.sku_code = st.sku_code "
        "  JOIN product p ON p.product_code = s.product_code "
        "  JOIN color c ON c.color_code = s.color_code "
        "  JOIN size z ON z.size_code = s.size_code "
        " WHERE st.section = 1 AND st.qty >= :q "
        "   AND st.last_sold_at IS NOT NULL AND st.last_sold_at <= CURDATE() - INTERVAL :d DAY "
        " ORDER BY days DESC, st.qty DESC, st.location_code, st.sku_code LIMIT 500"),
        {"q": min_qty, "d": days}).all()
    return [dict(r._mapping) for r in rows]


# ============================================================
# F-809  拠点の登録・編集（R-32）
# ============================================================
def prefectures(db: Session) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(
        "SELECT pref_code, name FROM prefecture ORDER BY pref_code")).all()]


def location_detail(db: Session, code: str) -> dict | None:
    r = db.execute(text(
        "SELECT location_code, kind, name, pref_code, zip, address, tel, business_days, "
        "       TIME_FORMAT(cutoff_time, '%H:%i') AS cutoff_time, suspended, ec_saleable "
        "  FROM location WHERE location_code = :l"), {"l": code}).first()
    if not r:
        return None
    hol = [str(h.holiday) for h in db.execute(text(
        "SELECT holiday FROM location_holiday WHERE location_code = :l ORDER BY holiday"), {"l": code}).all()]
    return {**dict(r._mapping), "holidays": hol}


def create_location(db: Session, f: dict, *, by: str) -> bool:
    """★重複は INSERT IGNORE の件数で決める（読んでから書かない）。"""
    n = db.execute(text(
        "INSERT IGNORE INTO location (location_code, kind, name, pref_code, zip, address, tel, "
        "  business_days, cutoff_time, suspended, ec_saleable) "
        "VALUES (:location_code, :kind, :name, :pref_code, :zip, :address, :tel, :business_days, "
        "        :cutoff_time, :suspended, :ec_saleable)"), f).rowcount
    if n:
        op_log(db, by, f"location/{f['location_code']}", f"AP-B04 登録 kind={f['kind']}")
    db.commit()
    return bool(n)


def edit_location(db: Session, code: str, fields: dict, *, by: str) -> None:
    """切替（ec_saleable・suspended）以外の項目。★締め時刻を変えても、作った出荷の予定日は変えない（BR-23）。"""
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(text(f"UPDATE location SET {sets} WHERE location_code = :code"), {**fields, "code": code})
    op_log(db, by, f"location/{code}", "AP-B04 編集 " + ",".join(sorted(fields)))
    db.commit()


def add_holiday(db: Session, code: str, day: str, *, by: str) -> bool:
    n = db.execute(text("INSERT IGNORE INTO location_holiday (location_code, holiday) VALUES (:l, :d)"),
                   {"l": code, "d": day}).rowcount
    op_log(db, by, f"location/{code}", f"AP-B04 休業日を追加 {day}")
    db.commit()
    return bool(n)


def remove_holiday(db: Session, code: str, day: str, *, by: str) -> bool:
    n = db.execute(text("DELETE FROM location_holiday WHERE location_code = :l AND holiday = :d"),
                   {"l": code, "d": day}).rowcount
    op_log(db, by, f"location/{code}", f"AP-B04 休業日を削除 {day}")
    db.commit()
    return bool(n)
