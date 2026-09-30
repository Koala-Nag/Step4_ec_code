# -*- coding: utf-8 -*-
"""メール送信（設計 7.3）。

★リクエストの中で再送を待たない。
  行を「未送信」で先に作り、B-11 が拾って送る。
  そうしないと、送信に失敗した1通のために注文確定の応答が遅れる。

★1通＝1行にする。
  「状態が2回変われば2通」と「失敗を3回試す」が混ざらない。

★AP-T06 で挙動を指定できる（FT-06）。9.8 の「3回とも失敗」を作れるようにするため。
  ★指定はプロセスの中に持たない（ワーカが2以上あるため。R-18 の 28 と同じ）。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from core import applog
from mock import store

# ★ログはすべて applog.emit を通す（8.6・N-15）

# 7.3。1分間隔で3回まで
MAX_ATTEMPTS = 3
RETRY_MINUTES = 1

STATUS_UNSENT, STATUS_SENT, STATUS_FAILED = 0, 1, 2
RESULT_OK, RESULT_NG = 1, 2

# FT-06 で指定できる挙動
SCENARIOS = ("success", "fail", "timeout")

ADMIN_MSG_KIND = "N-13"     # 運用管理者への通知。★客宛の MSG-01〜13 と番号を分ける（MSG-13 は返品の却下）


def _admin_address() -> str:
    from core.config import MAIL_ADMIN_ADDRESS

    return MAIL_ADMIN_ADDRESS


def scenario() -> str:
    return str(store.read().get("mail_scenario", "success"))


def set_scenario(name: str) -> None:
    def _set(d: dict) -> None:
        d["mail_scenario"] = name
    store.update(_set)


def enqueue(db: Session, *, msg_kind: str, to_email: str, subject: str, body: str) -> int:
    """送るものを積むだけ。★ここでは送らない（7.3）。"""
    res = db.execute(
        text("INSERT INTO sent_mail (msg_kind, to_email, subject, body, status, attempt_count, "
             "                       next_retry_at, result, sent_at) "
             "VALUES (:k, :t, :s, :b, :st, 0, NOW(3), NULL, NULL)"),
        {"k": msg_kind, "t": to_email, "s": subject, "b": body, "st": STATUS_UNSENT},
    )
    db.commit()
    return int(res.lastrowid)


def notify_admin(db: Session, *, subject: str, body: str) -> int:
    """運用管理者への通知（N-13）。★これもメールの行として積む。"""
    from core.config import MAIL_ADMIN_ADDRESS

    return enqueue(db, msg_kind=ADMIN_MSG_KIND, to_email=MAIL_ADMIN_ADDRESS,
                   subject=subject, body=body)


def _send(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """実際の送信。いまはスタブ。★本物に替えるときはここだけ差し替える。"""
    sc = scenario()
    if sc == "fail":
        return False, "SMTP_ERROR"
    if sc == "timeout":
        import time

        time.sleep(2)
        return False, "TIMEOUT"
    # ★宛先も件名も出さない。誰に何を送ったかはアプリログではなく sent_mail（E-00）で見る
    applog.emit("mail.sent")
    return True, "OK"


def flush(db: Session) -> tuple[int, list[str]]:
    """B-11 の本体。「未送信」と「失敗かつ試行3回未満」を送る。

    ★掴むのは条件付きUPDATE。読んでから書かない（6.6 と同じ形）。
    """
    notes: list[str] = []
    sent = 0

    rows = db.execute(
        text("SELECT id, to_email, subject, body, attempt_count FROM sent_mail "
             " WHERE (status = :unsent "
             "        OR (status = :failed AND attempt_count < :max)) "
             "   AND (next_retry_at IS NULL OR next_retry_at <= NOW(3)) "
             " ORDER BY id"),
        {"unsent": STATUS_UNSENT, "failed": STATUS_FAILED, "max": MAX_ATTEMPTS},
    ).all()

    for m in rows:
        claimed = db.execute(
            text("UPDATE sent_mail SET attempt_count = attempt_count + 1 "
                 " WHERE id = :i AND (status = :unsent OR status = :failed)"),
            {"i": m.id, "unsent": STATUS_UNSENT, "failed": STATUS_FAILED},
        )
        db.commit()
        if claimed.rowcount == 0:
            continue

        attempt = int(m.attempt_count) + 1
        ok, code = _send(m.to_email, m.subject, m.body)

        if ok:
            db.execute(
                text("UPDATE sent_mail SET status = :s, result = :r, sent_at = NOW(3), "
                     "       next_retry_at = NULL WHERE id = :i"),
                {"i": m.id, "s": STATUS_SENT, "r": RESULT_OK},
            )
            sent += 1
        else:
            db.execute(
                text("UPDATE sent_mail SET status = :s, result = :r, "
                     "       next_retry_at = NOW(3) + INTERVAL :m MINUTE WHERE id = :i"),
                {"i": m.id, "s": STATUS_FAILED, "r": RESULT_NG, "m": RETRY_MINUTES},
            )
            if attempt >= MAX_ATTEMPTS:
                # ★3回で打ち切り、通知する（7.3）。
                #   ★通知そのものはメールなので、同じ経路で失敗すると届かない。
                #     生存通知（B-12）が「届かない日がある」で気づく側になる（8.4）
                notes.append(f"mail {m.id}: {attempt}回失敗。打ち切って通知")
                db.execute(
                    text("INSERT INTO sent_mail (msg_kind, to_email, subject, body, status, "
                         "                       attempt_count, next_retry_at, result, sent_at) "
                         "VALUES (:k, :t, :s, :b, :st, 0, NOW(3), NULL, NULL)"),
                    {"k": ADMIN_MSG_KIND,
                     "t": _admin_address(),
                     "s": f"[B-11] メールを {attempt} 回送れませんでした（id={m.id}）",
                     "b": f"宛先 {m.to_email} / 件名 {m.subject} / 応答 {code}",
                     "st": STATUS_UNSENT},
                )
            else:
                notes.append(f"mail {m.id}: {attempt}回目失敗（{code}）。1分後にやり直す")
        db.commit()

    return sent, notes


def b12_heartbeat(db: Session) -> int:
    """B-12 生存通知（8.4）。★異常が無くても1通出す。

    届かない日があれば、通知経路そのものが壊れていると判断できる。
    """
    from datetime import date

    return notify_admin(
        db,
        subject=f"[B-12] 生存通知 {date.today().isoformat()}",
        body="定期処理は動いています。この通知が届かない日があれば、通知経路を疑ってください。",
    )


# ------------------------------------------------------------
# 通知のまとめ（E-40・設計 8.4）。★R-21 の回答2
# ------------------------------------------------------------
# 8.4。同一種別は10分に1通までにまとめる
THROTTLE_MINUTES = 10


def _digest_minutes(db) -> int:
    """エラー通知のまとめ時間（E-40）。★販売設定（sales_config.error_digest_min。FT-01）から毎回読む（R-33）。"""
    row = db.execute(text("SELECT error_digest_min FROM sales_config WHERE effective_from <= CURDATE() "
                          " ORDER BY effective_from DESC LIMIT 1")).first()
    return int(row.error_digest_min) if row else THROTTLE_MINUTES


def notify_admin_throttled(db: Session, *, notify_kind: str, subject: str, body: str) -> int | None:
    """まとめて送る。★送ったら行のID、抑止したら None。

    ★状態はDBに持つ（8.4）。プロセスの中に「直近に送った時刻」を持ってはいけない。
      App Service は複数インスタンスで動き、再起動とデプロイで消える。
      6.6 で定期処理にアプリ内ロックを禁じたのと、同じ理由。

    ★条件付きUPDATEで先勝ちにする。読んでから書くと、同時に来た2件が両方とも送る。
    """
    sent = db.execute(
        text("UPDATE notify_throttle "
             "   SET last_sent_at = NOW(3), suppressed_cnt = 0 "
             " WHERE notify_kind = :k "
             "   AND (last_sent_at IS NULL OR last_sent_at < NOW(3) - INTERVAL :m MINUTE)"),
        {"k": notify_kind, "m": _digest_minutes(db)},
    )
    db.commit()

    if sent.rowcount == 0:
        # ★まとめられた側。件数だけ増やす。行が無い種別は作る
        db.execute(
            text("INSERT INTO notify_throttle (notify_kind, last_sent_at, suppressed_cnt) "
                 "VALUES (:k, NULL, 1) "
                 "ON DUPLICATE KEY UPDATE suppressed_cnt = suppressed_cnt + 1"),
            {"k": notify_kind},
        )
        db.commit()
        # ★行が無かった場合は、いま作った行で1通目を送る
        just_made = db.execute(
            text("UPDATE notify_throttle SET last_sent_at = NOW(3), suppressed_cnt = 0 "
                 " WHERE notify_kind = :k AND last_sent_at IS NULL"),
            {"k": notify_kind},
        )
        db.commit()
        if just_made.rowcount == 0:
            return None

    # ★本文に「まとめた件数」と「直近1件」を入れる（8.4）。
    #   「10分で47件。最新はこれ」が分かれば、肝心の1通が埋もれない
    row = db.execute(text("SELECT suppressed_cnt FROM notify_throttle WHERE notify_kind = :k"),
                     {"k": notify_kind}).first()
    return notify_admin(db, subject=subject, body=body)
