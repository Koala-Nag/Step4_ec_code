# -*- coding: utf-8 -*-
"""引当の割り付け（設計 6.2.1 の手順1〜6）。

★このモジュールは repository も external も import しない（設計 2.2）。
  手順1〜5 はメモリの中の計算で、DBを1行も更新しない。
  DBに触れるのは手順6の1回だけ——その手順6の「指示」を作るのがここ。

★R-03 で verify_split_alloc.sh として確かめた手順を、そのままコードにしている。
  検証8〜13（判定9項目）が通った手順と同じもの。
"""
from __future__ import annotations

from dataclasses import dataclass

# BR-07。使った拠点がこれ以上になったら倉庫だけで組み直す
MAX_LOCATIONS = 2
KIND_WAREHOUSE = 1


@dataclass(frozen=True)
class Candidate:
    """手順1で読む在庫の行。★数量の条件（b）は付けずに読む（3.2.2 ⑥）。"""

    sku_code: str
    location_code: str
    kind: int          # 1=倉庫 2=店舗
    step: int          # 優先段（1=受取店 2=同一都道府県 3=同一ブロック 4=それ以外）
    qty: int
    reserved_qty: int

    @property
    def saleable(self) -> int:
        # ★負にしない（3.2.2 ①）。SQL側で引き算をしないので、ここで引く
        return max(self.qty - self.reserved_qty, 0)


@dataclass(frozen=True)
class OrderLine:
    line_no: int
    sku_code: str
    qty: int


@dataclass(frozen=True)
class Assignment:
    line_no: int
    sku_code: str
    location_code: str
    qty: int


@dataclass(frozen=True)
class UpdateInstruction:
    """手順6が発行する条件付きUPDATEの指示。

    ★同じ 拠点×SKU への更新は1本にまとめてある。
    ★location_code, sku_code の昇順に並べてある（9.4 のデッドロック回避）。
    """

    location_code: str
    sku_code: str
    add_qty: int


class AllocationFailed(Exception):
    """引当失敗（9.2）。★やり直さない（6.2.2）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def sort_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """手順2。BR-05 の3キーで並べる。

    ① 優先段（近さ）② 拠点区分（倉庫が先）③ 拠点コードの昇順
    ★これは「選ぶ順序」。「書く順序」（手順6）とは別物（6.2.2）。
    """
    return sorted(candidates, key=lambda c: (c.step, c.kind, c.location_code))


def _greedy(
    lines: list[OrderLine], candidates: list[Candidate], *, warehouse_only: bool
) -> list[Assignment] | None:
    """手順3。明細を1つずつ、足りる最初の拠点に割る（BR-06。1明細1拠点）。

    ★割り付けるたびに、その拠点×SKUの「手元の残数」を減らしてから次へ進む。
      減らさないと、同じ在庫を2つの明細に二重に割り当てる。
    """
    remain: dict[tuple[str, str], int] = {
        (c.sku_code, c.location_code): c.saleable for c in candidates
    }
    out: list[Assignment] = []
    for line in lines:
        picked = None
        for c in candidates:
            if c.sku_code != line.sku_code:
                continue
            if warehouse_only and c.kind != KIND_WAREHOUSE:
                continue
            key = (c.sku_code, c.location_code)
            if remain.get(key, 0) >= line.qty:
                remain[key] -= line.qty          # ★ここが抜けると二重割当
                picked = c.location_code
                break
        if picked is None:
            return None
        out.append(Assignment(line.line_no, line.sku_code, picked, line.qty))
    return out


def allocate(lines: list[OrderLine], candidates: list[Candidate]) -> list[Assignment]:
    """手順1〜5。★DBは1行も更新しない。

    手順4で使った拠点が3か所以上なら、手順5で倉庫だけで組み直す（BR-07）。
    組み直しの前に解放するものは無い（まだ何も書いていないため）。
    """
    ordered = sort_candidates(candidates)

    assigned = _greedy(lines, ordered, warehouse_only=False)
    if assigned is None:
        raise AllocationFailed("手順3で割り付けられない明細がある（BR-06：1明細を複数拠点に分割しない）")

    used = {a.location_code for a in assigned}
    if len(used) <= MAX_LOCATIONS:
        return assigned

    redone = _greedy(lines, ordered, warehouse_only=True)
    if redone is None:
        raise AllocationFailed("手順5で倉庫だけでは全明細を割れない（BR-07）")
    return redone


def build_updates(assignments: list[Assignment]) -> list[UpdateInstruction]:
    """手順6の指示を作る。

    ★同じ 拠点×SKU への更新は1本にまとめる。
    ★location_code, sku_code の昇順に並べる（9.4）。
      「選ぶ順序（BR-05）」と「書く順序」を混同すると、どちらかが壊れる。
    """
    merged: dict[tuple[str, str], int] = {}
    for a in assignments:
        merged[(a.location_code, a.sku_code)] = merged.get((a.location_code, a.sku_code), 0) + a.qty
    return [
        UpdateInstruction(loc, sku, qty)
        for (loc, sku), qty in sorted(merged.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    ]
