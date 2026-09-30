# -*- coding: utf-8 -*-
"""N-15｜禁止項目がログに出ないことを試験で確かめる（設計 8.6）。

★8.6 が名指しで「試験を1本置き、CI で走らせる」と書いている項目。
★DBを立てない。
"""
from __future__ import annotations

import logging

from core import applog


def test_許可した項目だけが残る():
    got = applog.allowed({
        "order_no": "ORD-260910-ABCD1234",
        "request_id": "req-1",
        "password": "hunter2",
        "card_number": "4111111111111111",
        "client_token": "tok_abc",
        "session_id": "0123456789abcdef",
        "to_email": "a@example.com",
    })
    assert got == {"order_no": "ORD-260910-ABCD1234", "request_id": "req-1"}


def test_禁止項目を渡してもログに出ない(caplog):
    """★「出してはいけない一覧」ではなく「出してよい一覧」で作ってある。

    新しい禁止項目が増えても、追記を忘れたぶんが漏れる、ということが起きない。
    """
    marker = "CANARY-VALUE-9999"
    with caplog.at_level(logging.INFO, logger="ec"):
        applog.emit("test.event", order_no="ORD-1",
                    **{k: marker for k in applog.FORBIDDEN_EXAMPLES})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ORD-1" in text
    assert marker not in text


def test_例外は種別と発生位置だけで文言を出さない(caplog):
    """★例外の文言には、渡された値がそのまま混ざる（8.6）。"""
    try:
        raise ValueError("カード番号 4111111111111111 が不正です")
    except ValueError as e:
        with caplog.at_level(logging.ERROR, logger="ec"):
            applog.emit_exception("unhandled", e, order_no="ORD-2")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ValueError" in text          # 種別は出す
    assert "test_applog.py:" in text     # 発生位置も出す
    assert "4111111111111111" not in text
    assert "不正です" not in text


def test_共通項目のインスタンス名が必ず入る(caplog):
    with caplog.at_level(logging.INFO, logger="ec"):
        applog.emit("test.event")
    assert "instance" in caplog.records[0].getMessage()
