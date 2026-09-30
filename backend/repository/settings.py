# -*- coding: utf-8 -*-
"""販売設定の読み書き（T-30 `sales_config`・F-308・FT-01）。R-33。

★プロセスの中にキャッシュを持たない（NFR-11・8.4）。毎回 DB から「いま効いている版」を読む。
  ワーカが2つ以上あると、キャッシュを持った側だけ古い値で動く。
★いま効いている版 ＝ 適用開始日が今日以前で最大の行（T-30）。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from domain import settings as sd

_COLS = ["effective_from"] + [f.name for f in sd.FIELDS] + ["notice_text", "notice_from", "notice_to"]


def current(db: Session) -> dict:
    row = db.execute(text(f"SELECT {', '.join(_COLS)} FROM sales_config WHERE effective_from <= CURDATE() "
                          " ORDER BY effective_from DESC LIMIT 1")).first()
    if row is None:
        # ★設定が無い環境では動かさない（repository/cart.sales_config と同じ考え方）
        raise RuntimeError("sales_config が空。seed/02_master.sql を流す")
    return dict(row._mapping)


def value(db: Session, column: str, default: int) -> int:
    """1列だけ読む（期限値を使う処理から呼ぶ）。★列名は domain の一覧にあるものだけ。"""
    if column not in _COLS:
        raise ValueError(column)
    row = db.execute(text(f"SELECT {column} FROM sales_config WHERE effective_from <= CURDATE() "
                          " ORDER BY effective_from DESC LIMIT 1")).first()
    return int(getattr(row, column)) if row else default


def versions(db: Session, limit: int = 20) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(
        f"SELECT {', '.join(_COLS)} FROM sales_config ORDER BY effective_from DESC LIMIT :n"), {"n": limit}).all()]


def save_version(db: Session, values: dict, *, by: str) -> bool:
    """新しい版を足す。★同じ適用開始日（今日・未来）の版がすでにあれば、その版を差し替える。

    ★差し替えてよいのは「今日以降」の版だけ（過去の版は parse で弾いてある）。
      今日の版を差し替えても、確定済みの注文は値を保存しているので変わらない（BR-17）。
    戻り値  True＝新しい行を足した／False＝同じ日の版を差し替えた
    """
    cols = _COLS
    n = db.execute(text(
        f"INSERT INTO sales_config ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON DUPLICATE KEY UPDATE {', '.join(f'{c} = VALUES({c})' for c in cols if c != 'effective_from')}"),
        values).rowcount
    db.execute(text("INSERT INTO operation_log (operator_id, target, action) VALUES (:p, :t, :a)"),
               {"p": by, "t": f"sales-config/{values['effective_from']}", "a": "AP-B33 " + ("追加" if n == 1 else "差し替え")})
    db.commit()
    return n == 1
