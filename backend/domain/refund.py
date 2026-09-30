# -*- coding: utf-8 -*-
"""返金額の按分（要件定義書 BR-21・設計 6.5.2）。

★このモジュールは repository も external も import しない（設計 2.2）。

BR-21
    明細の返金額＝明細金額 −（注文の割引額を明細金額の比で按分した額）
    按分は円未満切り捨て。
    端数（注文の割引額と、按分額の合計との差）は、行番号が最大の明細に寄せる。
    返金額の累計が注文の支払総額を超えないようにする。

★2つに分かれている。ここがこのモジュールの肝。

    allocate_discount()  注文確定のときに1回だけ回す。結果を order_line に保存する
    refund_amount()      返品申請のたびに回す。★保存された値を読むだけ。割り直さない

  ★返品のたびに割り直すと、3回に分けて申請したときに合計が1円ずれる（UT-502）。
    「その申請に含まれる明細のうち」で端数を寄せると、申請の分け方で端数の行き先が変わり、
    全部返したときの合計が注文の割引額と一致しなくなるため。
    だから注文確定時に、注文の全明細に対して1回だけ割る（設計 6.5.2）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    """按分に要るぶんだけ。"""

    line_no: int
    amount: int              # BR-11 明細金額（税込単価 × 数量）


@dataclass(frozen=True)
class AllocatedLine:
    line_no: int
    amount: int
    allocated_discount: int  # ★注文確定時に決めて order_line に保存する値


def allocate_discount(lines: list[Line], order_discount: int) -> list[AllocatedLine]:
    """注文の割引額を、明細金額の比で按分する。★注文確定のときに1回だけ。

    ・按分は円未満切り捨て
    ・端数は行番号が最大の明細に寄せる
    """
    total = sum(l.amount for l in lines)
    discount = max(min(order_discount, total), 0)
    if total <= 0 or discount == 0:
        # ★割引が無ければ按分の計算に入らない（UT-505）
        return [AllocatedLine(l.line_no, l.amount, 0) for l in lines]

    each = {l.line_no: l.amount * discount // total for l in lines}   # 切り捨て
    remainder = discount - sum(each.values())
    last = max(l.line_no for l in lines)                              # ★行番号が最大の明細へ
    each[last] += remainder
    return [AllocatedLine(l.line_no, l.amount, each[l.line_no]) for l in lines]


def line_refund(line: AllocatedLine) -> int:
    """1明細の返金額。★保存された按分額を引くだけ。割り直さない。"""
    return max(line.amount - line.allocated_discount, 0)


def refund_amount(
    lines: list[AllocatedLine],
    *,
    total_amount: int,
    already_refunded: int = 0,
    shipping_refund: int = 0,
) -> int:
    """この申請の返金額。★累計が支払総額を超えないよう頭打ちにする（BR-21）。

    shipping_refund は BR-21b（全明細が返品された時点で送料を返す）のぶん。
    ここでは「返すと決まった額」を受け取るだけで、返すかどうかは判断しない。
    """
    asked = sum(line_refund(l) for l in lines) + max(shipping_refund, 0)
    room = max(total_amount - max(already_refunded, 0), 0)
    return min(asked, room)


# ============================================================
# 欠品・キャンセルで「いくら・どうやって」戻すか（BR-17c・BR-17d・BR-21a。R-26）
# ============================================================
KIND_VOID = "void"        # 取消（売上確定の前。与信を取り消す）
KIND_REFUND = "refund"    # 返金（売上確定の後。確定した代金を返す）


def money_back_kind(*, captured: bool) -> str:
    """BR-17c・BR-17d。★売上確定の前なら取消、後なら返金。

    ★ここを混ぜると、二重に返すか、返らないかのどちらかになる。
      確定前に「返金」を送ると、まだ取っていない代金を返そうとして弾かれるか、
      与信だけが残って枠を押さえ続ける。
      確定後に「取消」を送ると、取った代金はそのまま残る——客にお金が戻らない。
    """
    return KIND_REFUND if captured else KIND_VOID


def shortage_refund(
    short_lines: list[AllocatedLine],
    *,
    all_lines_short: bool,
    shipping_fee: int,
    total_amount: int,
    already_refunded: int = 0,
) -> int:
    """欠品分の返金額（BR-21a）。

    BR-21a  欠品によるキャンセルは客に非がないため、その明細の金額に加え、
            全明細が欠品した場合は送料も返す。
            一部が欠品した場合、送料無料ラインを割り込んでも後から送料を請求しない。

    ★「その明細の金額」は、割引の按分を引いた額として読む（＝客が実際に払った額）。
      ★割引前の明細金額で返すと、割引のぶん払った以上を返してしまう。
        確かめ方｜全明細が欠品したとき、
          「明細金額−按分」の合計 ＋ 送料 ＝ 支払総額          ← ちょうど全額
          「明細金額（割引前）」の合計 ＋ 送料 ＝ 支払総額＋割引額  ← 払った以上
        全額返金がちょうど支払総額になるのは、按分を引いた読み方だけ。

    ★一部欠品のときに送料を足さないのは「後から送料を請求しない」の裏返し——
      送料は取ったまま、減額もしない。
    """
    lines_back = sum(line_refund(l) for l in short_lines)
    shipping_back = max(shipping_fee, 0) if all_lines_short else 0
    return refund_amount(
        [AllocatedLine(0, lines_back, 0)] if lines_back else [],
        total_amount=total_amount,
        already_refunded=already_refunded,
        shipping_refund=shipping_back,
    )
