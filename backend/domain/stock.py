# -*- coding: utf-8 -*-
"""在庫の見せ方の判断（BR-25・設計 9.2.1b）。

★このモジュールは repository も external も import しない（設計 2.2）。
  DBを立てずに単体テストが書けるようにするため。
"""
from __future__ import annotations

from enum import Enum

# BR-25。閾値をここ以外に書かない
LOW_STOCK_MAX = 3


class StockLabel(str, Enum):
    """商品詳細で出す3値（BR-25）。"""

    IN_STOCK = "in_stock"      # 在庫あり
    LOW = "low"                # 残りわずか（1〜3点）
    OUT = "out"                # 品切れ（0点）


def label_from_qty(saleable_qty: int) -> StockLabel:
    """販売可能数から3値を決める。★商品詳細でだけ使う（F-203）。

    一覧では使わない。一覧は2値（下の in_stock）。
    合計を出すと同時20人で 16.4 秒かかることを実測した（R-08）。
    """
    if saleable_qty <= 0:
        return StockLabel.OUT
    if saleable_qty <= LOW_STOCK_MAX:
        return StockLabel.LOW
    return StockLabel.IN_STOCK


def list_label(saleable_qty: int) -> StockLabel:
    """商品一覧で出す2値（9.2.1b・F-104）。★「残りわずか」を出さない。

    一覧で3値にすると販売可能数の合計が要る。同時20人で 16.4 秒かかることを実測した（R-08）。
    一覧は「あるか無いか」だけを EXISTS で見る。
    """
    return StockLabel.IN_STOCK if saleable_qty > 0 else StockLabel.OUT


def is_selectable(saleable_qty: int) -> bool:
    """0点のサイズは選べない（F-203）。"""
    return saleable_qty > 0


def saleable(qty: int, reserved_qty: int) -> int:
    """販売可能数。★引き算の結果は負にしない（設計 3.2.2 ①）。

    SQL側で INT UNSIGNED 同士を引くと ERROR 1690 で落ちるため、
    SQLでは引き算をせず、読んだ値をここで引く。
    """
    return max(qty - reserved_qty, 0)


# ------------------------------------------------------------
# 一覧のカードの「新着」バッジ（画面の型 1.3 ⑥。R-28）
# ------------------------------------------------------------
NEW_DAYS = 14


def is_new(created_at, now) -> bool:
    """登録から14日以内なら新着。★判定はサーバ（画面で日付を計算しない。N-35 と同じ考え方）。

    ★GU 調査で「新着だけ採る」と決めた。ベストセラー・値下げは採らない（セールは凍結）。
    """
    if created_at is None:
        return False
    return (now - created_at).days < NEW_DAYS


# ------------------------------------------------------------
# F-807 滞留在庫（R-30）
# ------------------------------------------------------------
STAGNANT_DAYS = 60       # 最終販売日から60日以上
STAGNANT_MIN_QTY = 3     # 在庫数が3点以上


def is_stagnant(last_sold_at, qty: int, today, days: int = STAGNANT_DAYS) -> bool:
    """★要件 F-807「最終販売日から60日以上経過し、在庫数が3点以上」。60日ちょうど・3点ちょうどは含む。

    ★最終販売日が無い（一度も売れていない）行は含めない。
      「60日以上経過」を数える起点が無いので、滞留とは判定できない（別の扱いを決める必要がある）。
    """
    if last_sold_at is None:
        return False
    return (today - last_sold_at).days >= days and qty >= STAGNANT_MIN_QTY
