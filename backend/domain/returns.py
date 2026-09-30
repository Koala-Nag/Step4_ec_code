# -*- coding: utf-8 -*-
"""返品（要件定義書 BR-18〜22・5.3「返品の状態」・設計 6.5）。

★このモジュールは repository も external も import しない（設計 2.2）。
  期限・状態の進め方・返金額は、DBを読まなくても決まる。読んだ結果を引数で渡す。

★システムが機械的に判定するのは、BR-18 の期限だけ（BR-18a）。
  未使用・タグ付きかどうかは、承認（F-503a）と検品（F-503c）で人が判断する。
  ★却下の条件をコード化しない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# ============================================================
# 状態（DDL の return_req.status のコメントと同じ並び。要件 5.3）
# ============================================================
APPLIED = 1       # 申請中
REJECTED = 2      # 却下
AWAITING = 3      # 返送待ち
RECEIVED = 4      # 受領
INSPECTED = 5     # 検品済
REFUNDED = 6      # 返金済

STATUS_LABEL = {APPLIED: "申請中", REJECTED: "却下", AWAITING: "返送待ち",
                RECEIVED: "受領", INSPECTED: "検品済", REFUNDED: "返金済"}

# ★遷移はこの表だけ。表に無い組み合わせは ERR-1205（5.3 の定義外）。
#   ★飛び越し（申請中 → 受領 など）も、戻し（受領 → 返送待ち）も、表に無いので通らない。
TRANSITIONS: dict[str, tuple[int, int]] = {
    "approve": (APPLIED, AWAITING),     # F-503a
    "reject": (APPLIED, REJECTED),      # F-503a
    "receive": (AWAITING, RECEIVED),    # F-503b
    "inspect": (RECEIVED, INSPECTED),   # F-503c（全明細の記録が終わったとき）
    "refund": (INSPECTED, REFUNDED),    # F-503d
}


def transition(action: str, current: int) -> int:
    """次の状態。★できなければ ValueError("ERR-1205")。"""
    fr, to = TRANSITIONS[action]
    if current != fr:
        raise ValueError("ERR-1205")
    return to


# ============================================================
# 理由（要件 6.3「返品の理由」・設計 4.5 ⑦ AP-401）
# ============================================================
REASONS = {"size": 1, "image": 2, "defect": 3, "wrong_item": 4, "other": 5}
REASON_LABEL = {1: "サイズが合わない", 2: "イメージと違う", 3: "不良", 4: "誤出荷", 5: "その他"}
REASON_TEXT_MAX = 200

# 検品（return_line.inspect_result）と、不合格の扱い（return_line.disposal）
PASS, FAIL = 1, 2
DISPOSAL = {"return": 1, "discard": 2}
DISPOSAL_LABEL = {1: "客へ返送", 2: "廃棄"}

# 返送送料の負担者（BR-20。★判定はシステムがせず、承認のときにサポートが選ぶ。6.5.3）
FEE_BEARER = {"customer": 1, "company": 2}
FEE_BEARER_LABEL = {1: "お客様", 2: "当店"}


def reason_error(reason_code: str, reason_text: str | None) -> tuple[str, str] | None:
    """理由の入力の誤り。(ERRコード, 項目) か None。"""
    if reason_code not in REASONS:
        return ("ERR-1004", "reason_code")
    t = (reason_text or "").strip()
    if len(t) > REASON_TEXT_MAX:
        return ("ERR-1003", "reason_text")
    if reason_code == "other" and not t:
        return ("ERR-1001", "reason_text")      # ★「その他」は自由記述が必須（6.3）
    return None


# ============================================================
# BR-18  申請できるか（設計 6.5.1）
# ============================================================
RETURN_LIMIT_DAYS = 17     # ★既定値。実際は sales_config.return_limit_days（FT-01）を渡す


def deadline(start: datetime | date, limit_days: int = RETURN_LIMIT_DAYS) -> datetime:
    """期限 ＝ 起算日の 00:00:00 ＋ 17日。

    起算は「その明細が乗った出荷の出荷日」（配送）／「引渡日」（店舗受取）。
    ★時刻は切り捨てて日で数える。出荷が 9/1 23:59 でも 9/1 00:00 起算（BR-18「出荷日の00:00」）。
    """
    d = start.date() if isinstance(start, datetime) else start
    return datetime.combine(d, time()) + timedelta(days=limit_days)


def within_deadline(start: datetime | date, now: datetime,
                    limit_days: int = RETURN_LIMIT_DAYS) -> bool:
    """★ちょうどは可、1秒でも過ぎたら不可（BR-18）。now はサーバの時刻（ブラウザの時刻は使わない）。"""
    return now <= deadline(start, limit_days)


@dataclass(frozen=True)
class ShippedLine:
    """返品の対象になりうる明細。repository が読んで渡す。"""

    line_no: int
    shipped_qty: int           # 届いた数（配送は出荷済以降、店舗受取は引渡済の出荷に乗った数）
    applied_qty: int           # すでに申請した数（却下を除く）
    start: datetime | None     # 起算（出荷日／引渡日）。まだ届いていなければ None


def returnable_qty(l: ShippedLine) -> int:
    return max(l.shipped_qty - l.applied_qty, 0)


def check_application(lines: dict[int, ShippedLine], asked: dict[int, int], now: datetime,
                      limit_days: int = RETURN_LIMIT_DAYS) -> str | None:
    """申請を受けてよいか。誤りなら ERR コード、よければ None。

    ★判定の順番に意味がある。
      無い明細（ERR-1004）→ 届いていない（ERR-1205）→ 期限切れ（ERR-1204）→ 数の超過（ERR-1003）
      「期限切れ」を数より先に見る。期限を過ぎた明細を、数を減らせば通るように見せない。
    ★1つの申請に複数明細を含められる（F-502）。★1明細でも期限を過ぎていれば、申請ごと受けない
      （一部だけ受けると、客は何が受け付けられたか分からない）。
    """
    if not asked:
        return "ERR-1001"
    for line_no, q in asked.items():
        if line_no not in lines:
            return "ERR-1004"
        if q < 1:
            return "ERR-1003"
    for line_no in asked:
        if lines[line_no].start is None or lines[line_no].shipped_qty <= 0:
            return "ERR-1205"
    for line_no in asked:
        if not within_deadline(lines[line_no].start, now, limit_days):
            return "ERR-1204"
    for line_no, q in asked.items():
        if q > returnable_qty(lines[line_no]):
            return "ERR-1003"
    return None


# ============================================================
# BR-21・BR-21b  返金額（設計 6.5.2）
# ============================================================
def refund_for_qty(*, unit_price: int, line_qty: int, allocated_discount: int,
                   before_qty: int, qty: int) -> int:
    """この申請で返す、1明細ぶんの額。

    明細の返金額 ＝ 明細金額 − order_line.allocated_discount（6.5.2。保存済みの値を引くだけ）

    ★6.5.2 は「明細を丸ごと返す」形で書いてある。★1明細のうち一部の数だけ返すと、
      按分額をどう割るかが決まっていない。★ここでまた割り算をすると、分けて返したときに
      6.5.2 が避けた「端数が申請回数ぶん多重に引かれる」が1明細の中で起きる。
    → ★累計で数える。「その明細を c 点返し終えた時点までに返す額」を
        F(c) ＝ 単価×c − floor(按分額×c ÷ 注文数)
      とし、今回の額は F(before + qty) − F(before)。
      c ＝ 注文数 で F ＝ 明細金額 − 按分額 になるので、★何回に分けても合計は必ず 6.5.2 と一致する。
    """
    def f(c: int) -> int:
        c = max(min(c, line_qty), 0)
        return unit_price * c - (allocated_discount * c // line_qty if line_qty else 0)

    return max(f(before_qty + qty) - f(before_qty), 0)


def all_lines_returned(returned_qty: dict[int, int], live_line_qty: dict[int, int]) -> bool:
    """BR-21b「注文のすべての明細が返品された」か。

    live_line_qty  届いた明細と数（欠品で取り消した明細は入れない。BR-21a で別に返している）
    returned_qty   返金まで終わった（検品に合格した）数。★不合格は返品されていない扱い
    """
    if not live_line_qty:
        return False
    return all(returned_qty.get(n, 0) >= q for n, q in live_line_qty.items())


RETURN_SHIP_BACK_DAYS = 7  # ★既定値。実際は sales_config.return_ship_back_days（FT-01。R-32）


def return_deadline(decided: date, days: int = RETURN_SHIP_BACK_DAYS) -> date:
    """MSG-12 の返送期限。承認から◯日（R-31 の回答1）。★過ぎても判定しない（目安）。"""
    return decided + timedelta(days=days)
