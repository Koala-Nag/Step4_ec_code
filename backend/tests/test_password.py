# -*- coding: utf-8 -*-
"""パスワードの決まりごと（N-22）。★DBを立てない。"""
from __future__ import annotations

import pytest

from domain import password as pw


@pytest.mark.parametrize("value,expected", [
    ("Abcd123!", None),          # 8文字ちょうど
    ("Abcd12!", "too_short"),    # 7文字
    ("A" * 128, None),           # 128文字ちょうど
    ("A" * 129, "too_long"),     # 129文字
    ("", "empty"),
])
def test_長さの境目(value, expected):
    assert pw.policy_error(value) == expected


def test_日本語でも128文字まで通る():
    """★要件 N-22・6.1 は「8〜128文字」。バイト数ではなく文字数で決めている。

    ★bcrypt は72バイトを超えたぶんを黙って切るので、そのまま渡すと
      日本語は25文字で切られる（3バイト×25＝75バイト）。
      「128文字まで入る」と言いながら実際は先頭25文字しか見ていない、になる。
    ★core/security.py が SHA-256 で先に潰してから渡すので、ここは文字数だけ見る。
    """
    assert pw.policy_error("あ" * 25) is None          # 75バイト。切られない
    assert pw.policy_error("あ" * 128) is None
    assert pw.policy_error("あ" * 129) == "too_long"


def test_メールアドレスは大文字小文字だけそろえる():
    assert pw.normalize_email("  Taro@Example.COM ") == "taro@example.com"


def test_ドットやプラスは落とさない():
    """★Gmail では同じでも、他のサーバでは別のアドレス。

    落とすと「別人のアドレスで登録できる」ことがある。
    """
    assert pw.normalize_email("a.b+tag@example.com") == "a.b+tag@example.com"
