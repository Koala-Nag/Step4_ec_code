# -*- coding: utf-8 -*-
"""販売設定（F-308・FT-01・T-30 `sales_config`）の決まりごと。R-33。

★このモジュールは repository も external も import しない（設計 2.2）。

★T-30「1行に全設定を持ち、適用開始日で版を重ねる」。
  いま効いている値 ＝ 適用開始日が今日以前で最大の行。
  ★直に UPDATE しない。新しい版（行）を足す。
★適用開始日を過去にできない。過去にすると「その日から効いていた」ことになり、
  確定済みの注文（BR-17 で値を保存してある）と、設定の履歴が食い違う。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str            # "rate" | "yen" | "int"
    min: int = 1
    max: int = 100_000
    unit: str = ""
    used: bool = True    # ★読む処理があるか。無いものは画面に「いまは使っていません」と出す（R-33）


# ★sales_config の列を全部（お知らせの3列は下で別に扱う）。並びは画面の並び
FIELDS: list[Field] = [
    Field("tax_rate", "消費税率", "rate", unit="（0〜1。10% は 0.100）"),
    Field("shipping_fee", "送料", "yen", min=0, max=99_999, unit="円"),
    Field("free_shipping_line", "送料無料ライン（割引後の商品合計）", "yen", min=0, max=9_999_999, unit="円"),
    Field("return_limit_days", "返品の申請期限（出荷日から）", "int", max=365, unit="日"),
    Field("return_ship_back_days", "返送期限（承認から）", "int", max=365, unit="日"),
    Field("arrival_assume_days", "到着とみなす日数（出荷から）", "int", max=60, unit="日"),
    Field("stagnant_days", "滞留在庫とみなす日数（最終EC出荷日から）", "int", max=3650, unit="日"),
    Field("cart_keep_days", "カートの保持期間", "int", max=365, unit="日"),   # ★B-04 が読む（R-36）
    Field("unpaid_cancel_hour", "支払い待ちの自動キャンセル", "int", max=720, unit="時間", used=False),
    Field("auth_timeout_min", "認証中の期限", "int", max=1440, unit="分"),
    Field("session_idle_min", "セッションの無操作時間", "int", max=1440, unit="分"),
    Field("reset_url_valid_min", "パスワード再設定URLの有効期限", "int", max=1440, unit="分"),
    Field("confirm_url_valid_min", "会員登録の確認URLの有効期限", "int", max=1440, unit="分"),
    Field("login_fail_limit", "ログイン失敗の許容回数", "int", max=100, unit="回"),
    Field("login_lock_min", "ログインのロック時間", "int", max=1440, unit="分"),
    Field("error_digest_min", "エラー通知のまとめ時間", "int", max=1440, unit="分"),
    Field("pickup_limit_days", "店舗受取の引き取り期限", "int", max=60, unit="日", used=False),
    Field("shortage_judge_hour", "欠品保留の判断期限", "int", max=720, unit="時間", used=False),
]
NOTICE_TEXT_MAX = 200


def parse(values: dict, today: date) -> tuple[dict, str | None]:
    """画面・APIから来た値を検査して、列の値にする。(値, "項目:理由") を返す。"""
    out: dict = {}
    try:
        eff = date.fromisoformat(str(values.get("effective_from", "")).strip())
    except ValueError:
        return {}, "effective_from:format"
    if eff < today:
        return {}, "effective_from:past"          # ★過去にできない
    out["effective_from"] = eff

    for f in FIELDS:
        raw = values.get(f.name)
        if raw is None or str(raw).strip() == "":
            return {}, f"{f.name}:empty"
        if f.kind == "rate":
            try:
                v = Decimal(str(raw).strip())
            except InvalidOperation:
                return {}, f"{f.name}:format"
            if not (Decimal("0") <= v <= Decimal("1")) or v != v.quantize(Decimal("0.001")):
                return {}, f"{f.name}:range"       # DECIMAL(4,3)
            out[f.name] = v
            continue
        if isinstance(raw, bool):
            return {}, f"{f.name}:format"
        try:
            v = int(str(raw).strip())
        except ValueError:
            return {}, f"{f.name}:format"
        if not (f.min <= v <= f.max):
            return {}, f"{f.name}:range"
        out[f.name] = v

    text_ = (values.get("notice_text") or "").strip()
    if len(text_) > NOTICE_TEXT_MAX:
        return {}, "notice_text:too_long"
    out["notice_text"] = text_ or None
    for k in ("notice_from", "notice_to"):
        v = (values.get(k) or "").strip()
        if not v:
            out[k] = None
            continue
        try:
            out[k] = datetime.fromisoformat(v)
        except ValueError:
            return {}, f"{k}:format"
    if out["notice_from"] and out["notice_to"] and out["notice_to"] < out["notice_from"]:
        return {}, "notice_to:range"
    return out, None


def changed(before: dict, after: dict) -> list[str]:
    """画面に「何が変わるか」を出すため。★値の比較だけ（型は列の型にそろえて渡す）。"""
    return [f.name for f in FIELDS if str(before.get(f.name)) != str(after.get(f.name))]
