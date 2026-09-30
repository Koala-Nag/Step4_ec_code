# -*- coding: utf-8 -*-
"""出荷指示の組み立てと、注文状態の導出（設計 6.3・要件 5.3・BR-08b）。

★このモジュールは repository も external も import しない（設計 2.2）。
  「どう分けるか」「どの状態になるか」は、DBを読まなくても決まる。
  読んだ結果を引数で渡す。

★発送予定日の計算は domain/shipping_date.py（R-20 で書いた）。ここでは呼ばない。
  「いつ出すか」と「どう分けるか」は別の判断なので、混ぜない。
"""
from __future__ import annotations

from dataclasses import dataclass

# 出荷の状態（DDL の shipment.status のコメントと同じ並び）
SHIP_INSTRUCTED = 1   # 指示済
SHIP_SHIPPED = 2      # 出荷済
SHIP_ARRIVED = 3      # 到着済
SHIP_AT_STORE = 4     # 店舗到着
SHIP_HANDED = 5       # 引渡済
SHIP_SHORT = 6        # 欠品
SHIP_CANCELLED = 7    # キャンセル

# 届け先区分（BR-08b）
DEST_CUSTOMER = 1     # 客の住所
DEST_STORE = 2        # 受取店

# 注文の状態（5.4）
ORDER_ALLOCATED = 5        # 引当済
ORDER_INSTRUCTED = 6       # 出荷指示済
ORDER_SHORT_HOLD = 7       # 欠品保留
ORDER_PARTIAL_SHIPPED = 8  # 一部出荷済
ORDER_SHIPPED = 9          # 出荷済
ORDER_DONE = 10            # 完了
ORDER_CANCELLED = 11       # キャンセル済

# 受け取り方法（orders.receive_method）
RECEIVE_SHIP = 1
RECEIVE_PICKUP = 2


@dataclass(frozen=True)
class AllocatedLine:
    """引当済の注文明細。手順1で読んだものをそのまま渡す。"""

    line_no: int
    sku_code: str
    qty: int
    alloc_location_code: str


@dataclass(frozen=True)
class Destination:
    """出荷の届け先。★作った時点の値を写して持つ（E-24）。

    あとで住所帳や拠点を編集しても、過去の出荷は変わらない。
    """

    kind: int
    name: str
    zip: str
    pref_code: str
    address: str
    tel: str
    # ★受取店のときだけ入る。出荷元と同じかどうかを見るために持つ（下の is_pickup_at_origin）
    location_code: str | None = None


@dataclass(frozen=True)
class ShipmentPlan:
    """1つの出荷。手順2〜3の結果。"""

    from_location_code: str
    dest: Destination
    lines: list[AllocatedLine]

    @property
    def is_pickup_at_origin(self) -> bool:
        """★出荷元＝受取店。取り置き（F-406）で進める出荷。

        ★それでも出荷は作る（6.3 手順3）。作らないと 5.3 の
          「出荷指示済 → 出荷済」を通れず、MSG-11 も送れない。
        """
        return (self.dest.kind == DEST_STORE
                and self.from_location_code == self.dest.location_code)


def plan_shipments(
    lines: list[AllocatedLine],
    *,
    receive_method: int,
    customer: Destination,
    pickup_store: Destination | None,
) -> list[ShipmentPlan]:
    """手順1〜3。引当拠点でまとめて、届け先を決める。

    ★1〜2グループにしかならない（BR-07 で拠点を2つまでに抑えてあるため）。
      ここでは数を前提にせず、来たぶんだけ分ける。★前提を二重に書かない。

    ★BR-08b。店舗受取なら、どの拠点から出しても届け先は受取店。
      出荷の作り方・発送のしかたは通常の出荷と同じで、届け先だけが違う。
    """
    if receive_method == RECEIVE_PICKUP and pickup_store is None:
        raise ValueError("店舗受取なのに受取店が無い")

    dest = customer if receive_method == RECEIVE_SHIP else pickup_store
    assert dest is not None

    groups: dict[str, list[AllocatedLine]] = {}
    for l in lines:
        groups.setdefault(l.alloc_location_code, []).append(l)

    # ★拠点コードの昇順で作る。作る順を決めておかないと、
    #   同じ注文を2回処理したときに出荷IDの並びが変わって、試験が揺れる
    return [
        ShipmentPlan(from_location_code=loc, dest=dest, lines=sorted(ls, key=lambda x: x.line_no))
        for loc, ls in sorted(groups.items())
    ]


def order_status_from_shipments(statuses: list[int]) -> int:
    """5.3 の導出表。★注文の状態は出荷の状態から決める。持ち回さない。

    | すべて到着済または引渡済     | 完了 |
    | すべて出荷済                 | 出荷済 |
    | 一部が出荷済、残りが指示済   | 一部出荷済 |
    | すべて欠品                   | 欠品保留 |
    | 一部が出荷済、残りが欠品     | 欠品分をキャンセル済出荷として除外し、残りがすべて出荷済なら出荷済 |
    | すべてキャンセル             | キャンセル済 |

    ★「欠品」と「キャンセル」を分けて扱う（R-26 で直した）。

      欠品（6）   報告されたが、まだ受注担当が決めていない。★未解決
      キャンセル（7） F-911 で取り消し済み。★決着している

      5.3 の5行目は「欠品分を**キャンセル済出荷として除外し**」——除外されるのは
      F-911 でキャンセルになった出荷であって、報告されただけの欠品ではない。
      ★以前は欠品もキャンセルと同じく除外していたので、
        [出荷済, 欠品（未解決）] が「出荷済」になっていた。
        残り1点が宙に浮いたまま、客には「発送済み」と見える形だった。
      → 未解決の欠品は「まだ出していない出荷」として数える。
    """
    if not statuses:
        return ORDER_INSTRUCTED

    if all(s == SHIP_CANCELLED for s in statuses):
        return ORDER_CANCELLED

    # ★決着したキャンセルだけを除く。未解決の欠品は残す
    live = [s for s in statuses if s != SHIP_CANCELLED]

    if all(s == SHIP_SHORT for s in live):
        return ORDER_SHORT_HOLD            # ★全出荷が欠品のときだけ（6.4 手順3）

    DONE = (SHIP_ARRIVED, SHIP_HANDED)
    OUT = (SHIP_SHIPPED, SHIP_ARRIVED, SHIP_AT_STORE, SHIP_HANDED)

    if all(s in DONE for s in live):
        return ORDER_DONE
    if all(s in OUT for s in live):
        return ORDER_SHIPPED
    if any(s in OUT for s in live):
        # ★出したものがあり、まだ出していない（指示済・未解決の欠品）ものもある
        return ORDER_PARTIAL_SHIPPED
    return ORDER_INSTRUCTED


def can_cancel(order_status: int) -> bool:
    """客がキャンセルできるか（BR-17f）。

    ★判定は注文の状態で行う。経過時間では判定しない。
      「注文から30分以内」のような形にすると、30分以内でも出荷指示が出ていれば
      止められないのに、画面ではボタンが出る——という食い違いが生まれる。

    ★画面がボタンを出す条件も、AP-303 が受ける条件も、この1つの関数から取る
      （IT-101・102）。★片方だけを緩めない。
    """
    return order_status < ORDER_INSTRUCTED and order_status != ORDER_CANCELLED


def tracking_required(dest_kind: int) -> bool:
    """★客の住所宛は追跡番号が必須、取り置きは空でよい（E-24）。"""
    return dest_kind == DEST_CUSTOMER


def capture_amount(*, total_amount: int, this_items_after_discount: int, shipping_fee: int,
                   already_captured: int, is_first: bool) -> int:
    """分割出荷のときの売上確定の金額（設計 6.3.1「分割出荷のときの金額」。R-27 で変更）。

        各出荷の売上確定額  その出荷の明細の「金額 − 割引の按分額」の合計（6.3.1 ①）
        送料                ★最初に確定する出荷に載せる（6.3.1 ②）
        合計                必ず与信額（支払総額）以下

    ★「最初」は IDでも発送順の数え上げでもなく、
      「この注文に売上確定がまだ1件も無い状態で、いま確定しようとしている」かどうか。

    ★以前は「最後に確定する出荷」に送料と「残り」を載せていた。
      BR-21a（一部欠品では送料を返さない）が入ったあとは、
      最後の出荷が欠品で取り消されると送料が宙に浮いた（R-26 で実測 550円）。
      最初に載せれば、一部欠品 → 送料は取ってある／全欠品 → 確定が起きず取消に送料が入る。

    ★「残り」を取らない。明細ごとの額を足すだけにしたので、
      欠品の出荷の代金を別の出荷が取る形（R-26 の不具合2）が、式の上で起きなくなった。
    """
    amount = max(this_items_after_discount, 0) + (max(shipping_fee, 0) if is_first else 0)
    return min(amount, max(total_amount - max(already_captured, 0), 0))
