# -*- coding: utf-8 -*-
"""返品と返金（設計 6.5・要件 BR-18〜22・5.3「返品の状態」）。R-31。

★DBに触るのはこの層だけ（設計 2.2）。期限・遷移・返金額の判断は domain/returns.py。

★状態を進めるのは、どれも条件付きUPDATE（WHERE status = いまの状態）。
  読んでから書くまでのあいだに別の人が進めていたら、更新件数0で ERR-1205。★やり直さない。

★「送る」は外、「積む」は中（R-22 の提案42）。
  返金は「要実行」で積んでコミットし、送るのは外（api/money_back.send_now。だめなら B-09）。
  メールも同じトランザクションで積む。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from domain import refund as refund_domain
from domain import returns as rd
from domain import shipping
from repository import cancellation as cancel_repo

SECTION_BACKYARD = 1
STOCK_REASON_RESTOCK = 4       # stock_change_log.reason 4=在庫戻入 F-504
OUT = (shipping.SHIP_SHIPPED, shipping.SHIP_ARRIVED, shipping.SHIP_AT_STORE, shipping.SHIP_HANDED)


def new_return_no() -> str:
    """RET-YYMMDD-XXXXXXXX（19文字。注文番号と同じ形）。"""
    return f"RET-{datetime.now():%y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def db_now(db: Session) -> datetime:
    """★判定にはサーバの時刻を使う（BR-18）。出荷日時と同じ時計（DB）で比べる。"""
    return db.execute(text("SELECT NOW(3) AS n")).first().n


def limit_days(db: Session) -> int:
    """BR-18 の日数。★販売設定（FT-01）から読む。無ければ既定の17日。"""
    row = db.execute(text("SELECT return_limit_days FROM sales_config "
                          " WHERE effective_from <= CURDATE() ORDER BY effective_from DESC LIMIT 1")).first()
    return int(row.return_limit_days) if row else rd.RETURN_LIMIT_DAYS


def ship_back_days(db: Session) -> int:
    """返送期限の日数（MSG-12）。★販売設定（FT-01）から読む。無ければ既定の7日（R-32）。"""
    row = db.execute(text("SELECT return_ship_back_days FROM sales_config "
                          " WHERE effective_from <= CURDATE() ORDER BY effective_from DESC LIMIT 1")).first()
    return int(row.return_ship_back_days) if row else rd.RETURN_SHIP_BACK_DAYS


def return_warehouse(db: Session) -> dict:
    """返送先（BR-19）。★出荷元にかかわらず倉庫に固定する。"""
    row = db.execute(text("SELECT location_code, name, zip, address, tel FROM location "
                          " WHERE kind = 1 ORDER BY location_code LIMIT 1")).first()
    return dict(row._mapping)


# ============================================================
# 申請できる明細（BR-18）
# ============================================================
def shipped_lines(db: Session, order_no: str) -> tuple[dict[int, rd.ShippedLine], dict[int, dict]]:
    """明細ごとに「届いた数・起算・申請済の数」を読む。

    ★起算（6.5.1）
      配送      その明細が乗った出荷の出荷日（shipped_at）。分割出荷なら出荷ごとに違う
      店舗受取  引渡日（handed_at）。★店舗に届いただけ（店舗到着）では起算しない
    ★欠品で取り消した出荷（キャンセル）・未解決の欠品・指示済は「届いていない」。
    """
    head = db.execute(text("SELECT receive_method FROM orders WHERE order_no = :o"),
                      {"o": order_no}).first()
    pickup = head is not None and int(head.receive_method) == shipping.RECEIVE_PICKUP
    info = {int(r.line_no): dict(r._mapping) for r in db.execute(
        text("SELECT ol.line_no, ol.sku_code, ol.qty, ol.unit_price, ol.allocated_discount, "
             "       p.name AS product_name, c.name AS color_name, z.name AS size_name "
             "  FROM order_line ol JOIN sku s ON s.sku_code = ol.sku_code "
             "  JOIN product p ON p.product_code = s.product_code "
             "  JOIN color c ON c.color_code = s.color_code JOIN size z ON z.size_code = s.size_code "
             " WHERE ol.order_no = :o ORDER BY ol.line_no"), {"o": order_no}).all()}
    shipped: dict[int, tuple[int, datetime | None]] = {}
    for r in db.execute(
            text("SELECT sl.line_no, sl.qty, s.status, s.shipped_at, s.handed_at "
                 "  FROM shipment_line sl JOIN shipment s ON s.id = sl.shipment_id "
                 " WHERE s.order_no = :o AND s.status IN :out").bindparams(bindparam("out", expanding=True)),
            {"o": order_no, "out": list(OUT)}).all():
        if pickup:
            if int(r.status) != shipping.SHIP_HANDED or r.handed_at is None:
                continue
            start = r.handed_at
        else:
            start = r.shipped_at
        q, st = shipped.get(int(r.line_no), (0, None))
        shipped[int(r.line_no)] = (q + int(r.qty), max([x for x in (st, start) if x], default=None))
    applied = {int(r.line_no): int(r.q) for r in db.execute(
        text("SELECT rl.line_no, SUM(rl.qty) AS q FROM return_line rl "
             "  JOIN return_req rr ON rr.return_no = rl.return_no "
             " WHERE rl.order_no = :o AND rr.status <> :rej GROUP BY rl.line_no"),
        {"o": order_no, "rej": rd.REJECTED}).all()}
    lines = {n: rd.ShippedLine(n, shipped.get(n, (0, None))[0], applied.get(n, 0),
                               shipped.get(n, (0, None))[1]) for n in info}
    return lines, info


def returnable_view(db: Session, order_no: str) -> dict:
    """注文詳細（AP-305）に載せる「返品できるか」。★画面が期限を計算しない（ボタンを出す条件もここ）。"""
    lines, info = shipped_lines(db, order_no)
    now, days = db_now(db), limit_days(db)
    out = []
    for n, l in lines.items():
        dl = rd.deadline(l.start, days) if l.start else None
        ok = l.start is not None and rd.within_deadline(l.start, now, days)
        out.append({"line_no": n, "shipped_qty": l.shipped_qty, "applied_qty": l.applied_qty,
                    "returnable_qty": rd.returnable_qty(l) if ok else 0,
                    "deadline": dl.strftime("%Y-%m-%d %H:%M") if dl else None,
                    "within_deadline": ok,
                    "product_name": info[n]["product_name"], "color_name": info[n]["color_name"],
                    "size_name": info[n]["size_name"], "sku_code": info[n]["sku_code"]})
    return {"limit_days": days, "lines": out,
            "can_apply": any(x["returnable_qty"] > 0 for x in out)}


# ============================================================
# AP-401  返品申請（F-502）
# ============================================================
def apply(db: Session, *, order_no: str, asked: dict[int, int], reason_kind: int,
          reason_text: str | None) -> str:
    """★注文を FOR UPDATE で押さえてから数え直す。
      同じ明細への申請が2本同時に来ても、2本目は「申請済の数」を見て超過になる（数を超えて受けない）。
    """
    try:
        if db.execute(text("SELECT order_no FROM orders WHERE order_no = :o FOR UPDATE"),
                      {"o": order_no}).first() is None:
            raise ValueError("ERR-1215")
        lines, _ = shipped_lines(db, order_no)
        err = rd.check_application(lines, asked, db_now(db), limit_days(db))
        if err:
            raise ValueError(err)
        no = new_return_no()
        db.execute(text("INSERT INTO return_req (return_no, order_no, status) VALUES (:r, :o, :s)"),
                   {"r": no, "o": order_no, "s": rd.APPLIED})
        for line_no, q in sorted(asked.items()):
            db.execute(
                text("INSERT INTO return_line (return_no, order_no, line_no, qty, reason_kind, reason_text) "
                     "VALUES (:r, :o, :n, :q, :k, :t)"),
                {"r": no, "o": order_no, "n": line_no, "q": q, "k": reason_kind,
                 "t": (reason_text or "").strip() or None})
        db.commit()
        return no
    except Exception:
        db.rollback()
        raise


# ============================================================
# 読む
# ============================================================
def get(db: Session, return_no: str) -> dict | None:
    h = db.execute(
        text("SELECT rr.*, o.member_id, o.orderer_name, o.orderer_email, o.receive_method, "
             "       o.total_amount, o.shipping_fee, o.discount_amount "
             "  FROM return_req rr JOIN orders o ON o.order_no = rr.order_no "
             " WHERE rr.return_no = :r"), {"r": return_no}).first()
    if not h:
        return None
    lines = db.execute(
        text("SELECT rl.*, ol.sku_code, ol.qty AS line_qty, ol.unit_price, ol.allocated_discount, "
             "       p.name AS product_name, c.name AS color_name, z.name AS size_name "
             "  FROM return_line rl "
             "  JOIN order_line ol ON ol.order_no = rl.order_no AND ol.line_no = rl.line_no "
             "  JOIN sku s ON s.sku_code = ol.sku_code JOIN product p ON p.product_code = s.product_code "
             "  JOIN color c ON c.color_code = s.color_code JOIN size z ON z.size_code = s.size_code "
             " WHERE rl.return_no = :r ORDER BY rl.line_no"), {"r": return_no}).all()
    return {**dict(h._mapping), "lines": [dict(l._mapping) for l in lines]}


def list_for_orders(db: Session, order_nos: list[str]) -> list[dict]:
    if not order_nos:
        return []
    return [dict(r._mapping) for r in db.execute(
        text("SELECT rr.return_no, rr.order_no, rr.status, rr.applied_at, rr.refund_total, rr.refunded_at, "
             "       (SELECT COALESCE(SUM(qty), 0) FROM return_line rl WHERE rl.return_no = rr.return_no) AS qty "
             "  FROM return_req rr WHERE rr.order_no IN :os ORDER BY rr.applied_at DESC")
        .bindparams(bindparam("os", expanding=True)), {"os": order_nos}).all()]


def list_admin(db: Session, *, statuses: list[int] | None, return_no: str | None,
               order_no: str | None, date_from: str | None, date_to: str | None,
               warehouse_view: bool) -> tuple[list[dict], dict[int, int]]:
    """AP-B24。★状態ごとの件数を先頭に出す（F-507）。件数は一覧と同じ絞り（状態以外）で数える。

    warehouse_view  倉庫スタッフの見え方（F-507「返送待ちと受領だけ」）。
                    ★それに加えて、検品に合格したのにまだ在庫に戻していないものも見せる（F-504 を倉庫がやるため）
    """
    where, p = ["1=1"], {}
    if return_no:
        where.append("rr.return_no = :rn"); p["rn"] = return_no
    if order_no:
        where.append("rr.order_no = :on"); p["on"] = order_no
    if date_from:
        where.append("rr.applied_at >= :df"); p["df"] = date_from
    if date_to:
        where.append("rr.applied_at < DATE_ADD(:dt, INTERVAL 1 DAY)"); p["dt"] = date_to
    if warehouse_view:
        where.append(f"(rr.status IN ({rd.AWAITING}, {rd.RECEIVED}) OR (rr.status IN ({rd.INSPECTED}, {rd.REFUNDED}) "
                     f" AND EXISTS (SELECT 1 FROM return_line x WHERE x.return_no = rr.return_no "
                     f"             AND x.inspect_result = {rd.PASS} AND x.restocked_at IS NULL)))")
    base = " AND ".join(where)
    counts = {int(r.status): int(r.n) for r in db.execute(
        text(f"SELECT rr.status, COUNT(*) n FROM return_req rr WHERE {base} GROUP BY rr.status"), p).all()}
    sql = (f"SELECT rr.return_no, rr.order_no, rr.status, rr.applied_at, rr.refund_total, o.orderer_name, "
           f"       (SELECT COALESCE(SUM(qty), 0) FROM return_line rl WHERE rl.return_no = rr.return_no) AS qty, "
           f"       (SELECT COUNT(*) FROM return_line rl WHERE rl.return_no = rr.return_no "
           f"          AND rl.inspect_result = {rd.PASS} AND rl.restocked_at IS NULL) AS restock_pending "
           f"  FROM return_req rr JOIN orders o ON o.order_no = rr.order_no WHERE {base}")
    if statuses:
        sql += " AND rr.status IN :sts"
    sql += " ORDER BY rr.applied_at DESC LIMIT 200"
    stmt = text(sql).bindparams(bindparam("sts", expanding=True)) if statuses else text(sql)
    rows = [dict(r._mapping) for r in db.execute(stmt, {**p, **({"sts": statuses} if statuses else {})}).all()]
    return rows, counts


# ============================================================
# 状態を進める（共通）
# ============================================================
def _move(db: Session, return_no: str, action: str, sets: str = "", params: dict | None = None) -> int:
    cur = db.execute(text("SELECT status FROM return_req WHERE return_no = :r FOR UPDATE"),
                     {"r": return_no}).first()
    if cur is None:
        raise ValueError("ERR-1215")
    to = rd.transition(action, int(cur.status))
    n = db.execute(text(f"UPDATE return_req SET status = :to{(', ' + sets) if sets else ''} "
                        f" WHERE return_no = :r AND status = :fr"),
                   {**(params or {}), "to": to, "r": return_no, "fr": int(cur.status)}).rowcount
    if n == 0:
        raise ValueError("ERR-1205")
    return to


def _lines_text(lines: list[dict]) -> list[str]:
    return [f"・{l['product_name']}（{l['color_name']} / {l['size_name']}） {l['qty']}点" for l in lines]


# ============================================================
# AP-B25  承認・却下（F-503a・MSG-12・MSG-13）
# ============================================================
def approve(db: Session, *, return_no: str, fee_bearer: int, operator_id: str, order_url: str) -> dict:
    try:
        r = get(db, return_no)
        if not r:
            raise ValueError("ERR-1215")
        today = db.execute(text("SELECT CURDATE() d")).first().d
        dl = rd.return_deadline(today, ship_back_days(db))
        _move(db, return_no, "approve",
              "decided_at = NOW(3), decided_by = :op, return_fee_bearer = :fb, return_deadline = :dl",
              {"op": operator_id, "fb": fee_bearer, "dl": dl})
        wh = return_warehouse(db)
        cancel_repo.enqueue_mail(
            db, msg_kind="MSG-12", to_email=str(r["orderer_email"]), subject="返品を承認しました",
            body="\n".join([f"{r['orderer_name']} 様", "", "返品のお申し込みを承認しました。",
                            "下記の返送先へ、商品をお送りください。", "",
                            f"返品受付番号：{return_no}", f"注文番号：{r['order_no']}", ""]
                           + _lines_text(r["lines"]) + ["",
                            f"返送先：{wh['name']}　〒{wh['zip']} {wh['address']}　TEL {wh['tel']}",
                            f"返送期限：{dl:%Y年%m月%d日}",
                            f"返送送料のご負担：{rd.FEE_BEARER_LABEL[fee_bearer]}",
                            "", f"返品の状況：{order_url}"]))
        cancel_repo.op_log(db, operator_id, f"return/{return_no}",
                           f"AP-B25 承認 送料負担={rd.FEE_BEARER_LABEL[fee_bearer]}")
        db.commit()
        return {"return_no": return_no, "status": rd.AWAITING, "return_deadline": str(dl)}
    except Exception:
        db.rollback()
        raise


def reject(db: Session, *, return_no: str, reason: str, operator_id: str, order_url: str) -> dict:
    try:
        r = get(db, return_no)
        if not r:
            raise ValueError("ERR-1215")
        _move(db, return_no, "reject", "decided_at = NOW(3), decided_by = :op, reject_reason = :why",
              {"op": operator_id, "why": reason})
        cancel_repo.enqueue_mail(
            db, msg_kind="MSG-13", to_email=str(r["orderer_email"]), subject="返品をお受けできませんでした",
            body="\n".join([f"{r['orderer_name']} 様", "", "返品のお申し込みを、お受けできませんでした。", "",
                            f"返品受付番号：{return_no}", f"注文番号：{r['order_no']}", "",
                            f"理由：{reason}", "", f"ご注文の詳細：{order_url}"]))
        cancel_repo.op_log(db, operator_id, f"return/{return_no}", f"AP-B25 却下 {reason}")
        db.commit()
        return {"return_no": return_no, "status": rd.REJECTED}
    except Exception:
        db.rollback()
        raise


# ============================================================
# AP-B26  受領（F-503b）
# ============================================================
def receive(db: Session, *, return_no: str, staff_name: str, operator_id: str) -> dict:
    try:
        _move(db, return_no, "receive", "received_at = NOW(3), receiver = :who", {"who": staff_name})
        cancel_repo.op_log(db, operator_id, f"return/{return_no}", f"AP-B26 受領 {staff_name}")
        db.commit()
        return {"return_no": return_no, "status": rd.RECEIVED}
    except Exception:
        db.rollback()
        raise


# ============================================================
# AP-B27  検品（F-503c）
# ============================================================
def inspect(db: Session, *, return_no: str, results: list[dict], staff_name: str,
            operator_id: str) -> dict:
    """★明細ごとに記録する。全明細の記録が終わった時点で「検品済」（要件 5.3）。
    ★一度記録した明細は書き換えない（在庫に戻したあとで結果が変わると、戻した数の根拠が消える）。
    """
    try:
        cur = db.execute(text("SELECT status FROM return_req WHERE return_no = :r FOR UPDATE"),
                         {"r": return_no}).first()
        if cur is None:
            raise ValueError("ERR-1215")
        if int(cur.status) != rd.RECEIVED:
            raise ValueError("ERR-1205")
        have = {int(l.line_no): l for l in db.execute(
            text("SELECT line_no, inspect_result FROM return_line WHERE return_no = :r"), {"r": return_no}).all()}
        for x in results:
            if x["line_no"] not in have:
                raise ValueError("ERR-1004")
            if have[x["line_no"]].inspect_result is not None:
                raise ValueError("ERR-1205")
        for x in results:
            db.execute(text("UPDATE return_line SET inspect_result = :res, inspect_note = :note, "
                            "       inspected_at = NOW(3), inspector = :who "
                            " WHERE return_no = :r AND line_no = :n AND inspect_result IS NULL"),
                       {"res": x["result"], "note": x.get("note"), "who": staff_name,
                        "r": return_no, "n": x["line_no"]})
        left = db.execute(text("SELECT COUNT(*) n FROM return_line WHERE return_no = :r AND inspect_result IS NULL"),
                          {"r": return_no}).first().n
        status = rd.RECEIVED
        if int(left) == 0:
            status = _move(db, return_no, "inspect")
        cancel_repo.op_log(db, operator_id, f"return/{return_no}",
                           f"AP-B27 検品 {[(x['line_no'], x['result']) for x in results]} {staff_name}")
        db.commit()
        return {"return_no": return_no, "status": status, "remaining_lines": int(left)}
    except Exception:
        db.rollback()
        raise


# ============================================================
# AP-B30  在庫戻入（F-504・BR-19・BR-22）
# ============================================================
def restock(db: Session, *, return_no: str, staff_name: str, operator_id: str) -> dict:
    """★合格した明細だけを、倉庫のバックヤード在庫に足す。★出荷元が店舗でも倉庫に戻す（BR-19）。
    ★「まだ戻していない」行だけを、条件付きUPDATEで「戻した」にしてから足す（二重に戻さない）。
    """
    try:
        cur = db.execute(text("SELECT status FROM return_req WHERE return_no = :r FOR UPDATE"),
                         {"r": return_no}).first()
        if cur is None:
            raise ValueError("ERR-1215")
        if int(cur.status) not in (rd.INSPECTED, rd.REFUNDED):
            raise ValueError("ERR-1205")
        wh = return_warehouse(db)["location_code"]
        lines = db.execute(
            text("SELECT rl.line_no, rl.qty, ol.sku_code FROM return_line rl "
                 "  JOIN order_line ol ON ol.order_no = rl.order_no AND ol.line_no = rl.line_no "
                 " WHERE rl.return_no = :r AND rl.inspect_result = :pass AND rl.restocked_at IS NULL"),
            {"r": return_no, "pass": rd.PASS}).all()
        if not lines:
            raise ValueError("ERR-1205")          # 戻すものが無い（不合格だけ／戻し済み）
        done = []
        for l in sorted(lines, key=lambda x: x.sku_code):        # ★6.2.3（在庫は location, sku の昇順）
            n = db.execute(text("UPDATE return_line SET restocked_at = NOW(3), restocker = :who "
                                " WHERE return_no = :r AND line_no = :n AND restocked_at IS NULL"),
                           {"who": staff_name, "r": return_no, "n": l.line_no}).rowcount
            if n == 0:
                continue
            before = db.execute(text("SELECT qty FROM stock WHERE sku_code = :s AND location_code = :loc "
                                     "   AND section = :sec FOR UPDATE"),
                                {"s": l.sku_code, "loc": wh, "sec": SECTION_BACKYARD}).first()
            b = int(before.qty) if before else 0
            db.execute(text("INSERT INTO stock (sku_code, location_code, section, qty, reserved_qty) "
                            "VALUES (:s, :loc, :sec, :q, 0) ON DUPLICATE KEY UPDATE qty = qty + :q"),
                       {"s": l.sku_code, "loc": wh, "sec": SECTION_BACKYARD, "q": int(l.qty)})
            db.execute(text("INSERT INTO stock_change_log (sku_code, location_code, section, reason, "
                            "  qty_before, qty_after, note, operator_id, staff_name) "
                            "VALUES (:s, :loc, :sec, :rsn, :b, :a, :note, :op, :st)"),
                       {"s": l.sku_code, "loc": wh, "sec": SECTION_BACKYARD, "rsn": STOCK_REASON_RESTOCK,
                        "b": b, "a": b + int(l.qty), "note": f"return/{return_no}", "op": operator_id,
                        "st": staff_name[:50]})
            done.append({"line_no": int(l.line_no), "sku_code": l.sku_code, "qty": int(l.qty),
                         "qty_before": b, "qty_after": b + int(l.qty)})
        cancel_repo.op_log(db, operator_id, f"return/{return_no}", f"AP-B30 在庫戻入 {wh} {staff_name}")
        db.commit()
        return {"return_no": return_no, "location_code": wh, "restocked": done}
    except Exception:
        db.rollback()
        raise


# ============================================================
# AP-B28  不合格品の処分指示（F-503e・BR-22）
# ============================================================
def disposal(db: Session, *, return_no: str, choices: dict[int, int], operator_id: str) -> dict:
    try:
        cur = db.execute(text("SELECT status FROM return_req WHERE return_no = :r FOR UPDATE"),
                         {"r": return_no}).first()
        if cur is None:
            raise ValueError("ERR-1215")
        if int(cur.status) not in (rd.INSPECTED, rd.REFUNDED):
            raise ValueError("ERR-1205")
        have = {int(l.line_no): l for l in db.execute(
            text("SELECT line_no, inspect_result, disposal FROM return_line WHERE return_no = :r"),
            {"r": return_no}).all()}
        for n in choices:
            if n not in have:
                raise ValueError("ERR-1004")
            if have[n].inspect_result != rd.FAIL or have[n].disposal is not None:
                raise ValueError("ERR-1205")      # ★合格品には指示しない／一度決めたら変えない
        for n, d in choices.items():
            db.execute(text("UPDATE return_line SET disposal = :d WHERE return_no = :r AND line_no = :n "
                            "   AND disposal IS NULL"), {"d": d, "r": return_no, "n": n})
        cancel_repo.op_log(db, operator_id, f"return/{return_no}", f"AP-B28 処分指示 {choices}")
        db.commit()
        return {"return_no": return_no, "disposal": choices}
    except Exception:
        db.rollback()
        raise


def _refund_calc(db: Session, r: dict) -> dict:
    """返金額の計算（BR-21・BR-21b・6.5.2）。★書かない。承認前の画面の「返金額の確認」と、実行の両方が使う。"""
    order_no = r["order_no"]
    before = {int(x.line_no): int(x.q) for x in db.execute(
        text("SELECT rl.line_no, SUM(rl.qty) q FROM return_line rl JOIN return_req rr ON rr.return_no = rl.return_no "
             " WHERE rl.order_no = :o AND rr.status = :done AND rl.inspect_result = :pass "
             " GROUP BY rl.line_no"), {"o": order_no, "done": rd.REFUNDED, "pass": rd.PASS}).all()}
    per_line, returned = {}, dict(before)
    for l in r["lines"]:
        n = int(l["line_no"])
        if l["inspect_result"] is None or int(l["inspect_result"]) != rd.PASS:
            per_line[n] = 0
            continue
        per_line[n] = rd.refund_for_qty(unit_price=int(l["unit_price"]), line_qty=int(l["line_qty"]),
                                        allocated_discount=int(l["allocated_discount"]),
                                        before_qty=before.get(n, 0), qty=int(l["qty"]))
        returned[n] = returned.get(n, 0) + int(l["qty"])

    lines, _ = shipped_lines(db, order_no)
    live = {n: l.shipped_qty for n, l in lines.items() if l.shipped_qty > 0}
    ship_back = int(r["shipping_fee"]) if rd.all_lines_returned(returned, live) else 0
    asked = sum(per_line.values())
    already = cancel_repo.refunded_total(db, order_no)
    total = refund_domain.refund_amount(
        [refund_domain.AllocatedLine(0, asked, 0)] if asked else [],
        total_amount=int(r["total_amount"]), already_refunded=already,
        shipping_refund=ship_back) if (asked or ship_back) else 0
    return {"lines": per_line, "items": asked, "shipping_refund": min(ship_back, total),
            "refund_total": total, "already_refunded": already, "returned": returned,
            "capped": total < asked + ship_back}


def refund_preview(db: Session, return_no: str) -> dict | None:
    r = get(db, return_no)
    if not r:
        return None
    c = _refund_calc(db, r)
    c.pop("returned")
    return c


# ============================================================
# AP-B29  返金の実行（F-503d・BR-21・BR-21b・MSG-08）
# ============================================================
def refund(db: Session, *, return_no: str, operator_id: str, order_url: str) -> dict:
    """★合格した明細の合計を1回で返す（要件 5.3。明細ごとに返金のタイミングを分けない）。
    ★不合格だけなら0円で閉じる（設計 6.5 の図）。

    返金額
      明細    domain/returns.refund_for_qty（保存済みの按分額を使う。★割り直さない。6.5.2）
      送料    注文のすべての明細が返品された時点で返す（BR-21b。★送料無料の再判定はしない）
      頭打ち  返金の累計が支払総額を超えない（BR-21。取消・欠品の返金も累計に入れる）
    """
    try:
        cur = db.execute(text("SELECT order_no, status FROM return_req WHERE return_no = :r FOR UPDATE"),
                         {"r": return_no}).first()
        if cur is None:
            raise ValueError("ERR-1215")
        if int(cur.status) != rd.INSPECTED:
            raise ValueError("ERR-1205")
        order_no = cur.order_no
        head = db.execute(text("SELECT order_no, orderer_name, orderer_email, total_amount, shipping_fee "
                               "  FROM orders WHERE order_no = :o FOR UPDATE"), {"o": order_no}).first()
        # ★売上確定が済んでいないと、返す代金が決済代行側にまだ無い（返金は確定額までしか通らない。7.2.3）
        pending = db.execute(text("SELECT 1 FROM payment_tx WHERE order_no = :o AND tx_kind = :cap "
                                  "   AND status IN (3, 4, 5) LIMIT 1"),
                             {"o": order_no, "cap": cancel_repo.TX_CAPTURE}).first()
        if pending:
            raise ValueError("ERR-1209")

        r = get(db, return_no)
        c = _refund_calc(db, r)
        per_line, total, ship_back = c["lines"], c["refund_total"], c["shipping_refund"]
        returned = c["returned"]

        tx_id = cancel_repo.queue_money_back(db, order_no=order_no, amount=total,
                                             kind=refund_domain.KIND_REFUND, return_no=return_no)
        for n, a in per_line.items():
            db.execute(text("UPDATE return_line SET refund_amount = :a WHERE return_no = :r AND line_no = :n"),
                       {"a": a, "r": return_no, "n": n})
        _move(db, return_no, "refund", "refund_total = :t, shipping_refund = :s, refunded_at = NOW(3)",
              {"t": total, "s": ship_back})
        if any(v > 0 for v in returned.values()):
            db.execute(text("UPDATE orders SET partial_returned = TRUE WHERE order_no = :o"), {"o": order_no})

        passed = [l for l in r["lines"] if int(l["inspect_result"]) == rd.PASS]
        failed = [l for l in r["lines"] if int(l["inspect_result"]) == rd.FAIL]
        body = [f"{head.orderer_name} 様", "",
                "返品の返金が完了しました。" if total else "返品の手続きが完了しました。", "",
                f"返品受付番号：{return_no}", f"注文番号：{order_no}",
                f"返金額：{total:,} 円" + (f"（うち送料 {ship_back:,} 円）" if ship_back else ""),
                "返金先：ご注文時のクレジットカード" if total else "返金はありません。"]
        if passed:
            body += ["", "返金の対象になった商品"] + _lines_text(passed)
        if failed:
            # ★9.10「返金は行わない。理由を客に伝える」
            body += ["", "検品の結果、返金の対象にならなかった商品"] + [
                f"{t}　理由：{l['inspect_note'] or ''}" for t, l in zip(_lines_text(failed), failed)]
        body += ["", f"ご注文の詳細：{order_url}"]
        cancel_repo.enqueue_mail(db, msg_kind="MSG-08", to_email=str(head.orderer_email),
                                 subject="返金が完了しました" if total else "返品の手続きが完了しました",
                                 body="\n".join(body))
        cancel_repo.op_log(db, operator_id, f"return/{return_no}",
                           f"AP-B29 返金 {total} 送料={ship_back} 明細={per_line}")
        db.commit()
        return {"return_no": return_no, "status": rd.REFUNDED, "refund_total": total,
                "shipping_refund": ship_back, "lines": per_line, "tx_id": tx_id}
    except Exception:
        db.rollback()
        raise
