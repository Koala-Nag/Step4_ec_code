# -*- coding: utf-8 -*-
"""パスワードの決まりごと（要件定義書 N-22・6.1 の入力仕様）。

★このモジュールは repository も external も import しない（設計 2.2）。
  ★bcrypt もここでは呼ばない。ハッシュ化は core/security.py。
  ここにあるのは「通してよい文字列か」の判断だけなので、DBも外部ライブラリも要らない。

N-22  パスワードを bcrypt でハッシュ化する。最低8文字
6.1   8〜128文字
"""
from __future__ import annotations

MIN_LENGTH = 8
MAX_LENGTH = 128


def policy_error(password: str) -> str | None:
    """通れば None、駄目なら理由の符号を返す。

    ★例外にしない。呼び出し側が ERR-1003 に変換する。
    ★文字種の縛りは入れない（要件が定めていない）。
      「記号を1つ以上」のような縛りは、長さより弱いうえに、
      客が同じ変形（末尾に ! を足す）をするので実質1文字ぶんしか増えない。
    """
    if not password:
        return "empty"
    # ★数えるのは文字数（要件 6.1 が「8〜128文字」と書いているため）
    if len(password) < MIN_LENGTH:
        return "too_short"
    if len(password) > MAX_LENGTH:
        return "too_long"
    # ★bcrypt の72バイト制限には、ここでは触れない。
    #   要件 N-22・6.1 は「8〜128文字」と決めている。
    #   日本語なら25文字、絵文字なら19文字で72バイトを超えるので、
    #   ここでバイト数を見て弾くと「128文字まで」と言いながら25文字で断ることになる。
    #   ★core/security.py が SHA-256 で先に潰してから bcrypt に渡すので、
    #     長さの制限は文字数だけでよい（切り捨ても起きない）。
    return None


def is_acceptable(password: str) -> bool:
    return policy_error(password) is None


def normalize_email(email: str) -> str:
    """照合に使う形。★大文字小文字だけそろえる。

    ★ドットやプラスを落とす正規化はしない。
      Gmail では同じでも、他のサーバでは別のアドレスなので、
      落とすと「別人のアドレスで登録できる」ことがある。
    """
    return email.strip().lower()
