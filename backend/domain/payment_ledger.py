# -*- coding: utf-8 -*-
"""ダミーの決済代行が「断る条件」（設計 7.2.3。R-27）。

★このモジュールは repository も external も import しない（設計 2.2）。

★ダミーは、本物が断る条件を1つは断る。
  R-26 まで、ダミーは取消の額を与信の残りと突き合わせていなかった。
  そのため「与信を超える取消」を黙って通し、6.3.1 ① の不具合（割引前の売上確定）が
  検証環境で見つからなかった。★本物なら落ちるものが、検証環境では通っていた。

入れるのは「金額と状態の整合」だけ（7.2.3）。認証の細部・カードの検証・不正検知は入れない。

    与信の残り   = 与信額 − 売上確定の合計 − 取消の合計
    売上確定     残りを超えたら断る／同じ出荷（reference）に2回目は断る
    取消         残りを超えたら断る（★確定したぶんは取消では戻せない。返金になる）
    返金         売上確定の合計 − 返金の合計 を超えたら断る
    知らない取引 断る（与信していないものは、確定も取消もできない）

★「同じ与信に2回売上確定を断る」を、そのまま読むと分割出荷（BR-07。与信1回・確定2回）が
  通らない。★「同じ出荷に2回」と読んで、出荷を reference で渡す。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

CAPTURE, VOID, REFUND = "capture", "void", "refund"

# 断るときの応答コード
EXCEEDS_REMAINING = "EXCEEDS_REMAINING"       # 与信の残りを超える
EXCEEDS_CAPTURED = "EXCEEDS_CAPTURED"         # 確定した額を超える返金
DUPLICATE_CAPTURE = "DUPLICATE_CAPTURE"       # 同じ出荷に2回目の売上確定
UNKNOWN_TRANSACTION = "UNKNOWN_TRANSACTION"   # 与信していない取引
INVALID_AMOUNT = "INVALID_AMOUNT"


@dataclass(frozen=True)
class Authorization:
    authorized: int
    captured: int = 0
    voided: int = 0
    refunded: int = 0
    capture_refs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def remaining(self) -> int:
        """まだ確定も取消もされていない与信の額。"""
        return self.authorized - self.captured - self.voided

    @property
    def refundable(self) -> int:
        return self.captured - self.refunded


def refuse_reason(op: str, auth: Authorization | None, amount: int,
                  reference: str | None = None) -> str | None:
    """断るなら理由コードを、通すなら None を返す。★状態は変えない。"""
    if auth is None:
        return UNKNOWN_TRANSACTION
    if amount <= 0:
        return INVALID_AMOUNT
    if op == CAPTURE:
        if reference and reference in auth.capture_refs:
            return DUPLICATE_CAPTURE
        return EXCEEDS_REMAINING if amount > auth.remaining else None
    if op == VOID:
        return EXCEEDS_REMAINING if amount > auth.remaining else None
    if op == REFUND:
        return EXCEEDS_CAPTURED if amount > auth.refundable else None
    return INVALID_AMOUNT


def apply(op: str, auth: Authorization, amount: int,
          reference: str | None = None) -> Authorization:
    """通したあとの状態。★refuse_reason が None のときだけ呼ぶ。"""
    if op == CAPTURE:
        refs = auth.capture_refs + ((reference,) if reference else ())
        return replace(auth, captured=auth.captured + amount, capture_refs=refs)
    if op == VOID:
        return replace(auth, voided=auth.voided + amount)
    if op == REFUND:
        return replace(auth, refunded=auth.refunded + amount)
    raise ValueError(op)


def to_dict(auth: Authorization) -> dict:
    return {"authorized": auth.authorized, "captured": auth.captured, "voided": auth.voided,
            "refunded": auth.refunded, "capture_refs": list(auth.capture_refs)}


def from_dict(d: dict | None) -> Authorization | None:
    if not d:
        return None
    return Authorization(int(d["authorized"]), int(d.get("captured", 0)),
                         int(d.get("voided", 0)), int(d.get("refunded", 0)),
                         tuple(d.get("capture_refs", ())))
