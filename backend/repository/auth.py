# -*- coding: utf-8 -*-
"""会員・運営者・セッションの読み書き（設計 3.2・4.1.2）。

★DBに触るのはこの層だけ（設計 2.2）。判断は domain/ と api/ に置く。

★ロックのカウントは条件付きUPDATEで進める（6.6.2 と同じ形）。
  読んでから書くと、同時に10回叩かれたときに数え落とす。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# F-301。1明細の数量の上限。★同じ値をここに書き写さない
from domain.pricing import MAX_QTY_PER_LINE

# N-23。10回失敗で30分。★値は販売設定（sales_config。FT-01）から読む。ここは設定が無いときの既定値（R-33）
MAX_FAILED = 10
LOCK_MINUTES = 30
# N-23 の後半。IP単位。1つのIPから同じ窓のあいだに何回まで失敗してよいか
IP_MAX_FAILED = 50
IP_WINDOW_MINUTES = 10

# N-24。無操作60分でセッションを無効にする
SESSION_IDLE_MINUTES = 60

# N-25。再設定URLは60分
RESET_MINUTES = 60
# 8.3.1。会員登録の確認URLも同じ扱いにする
CONFIRM_MINUTES = 60

USER_GUEST, USER_MEMBER, USER_OPERATOR = 1, 2, 3


def _cfg(db: Session, column: str, default: int) -> int:
    """期限値を販売設定から読む（FT-01・NFR-11）。★プロセスに持たない。毎回 DB の「いま効いている版」。"""
    from repository import settings as settings_repo

    return settings_repo.value(db, column, default)
MEMBER_ACTIVE, MEMBER_LOCKED, MEMBER_WITHDRAWN = 1, 2, 3


# ------------------------------------------------------------
# 会員
# ------------------------------------------------------------
def find_member_by_email(db: Session, email: str) -> dict | None:
    row = db.execute(
        text("SELECT member_id, email, password_hash, name, status, failed_count, locked_until "
             "  FROM member WHERE email = :e"),
        {"e": email},
    ).first()
    return dict(row._mapping) if row else None


def find_member(db: Session, member_id: str) -> dict | None:
    row = db.execute(
        text("SELECT member_id, email, name, tel, status FROM member WHERE member_id = :m"),
        {"m": member_id},
    ).first()
    return dict(row._mapping) if row else None


def next_member_id(db: Session) -> str:
    """M0001 形式。★連番だが、これは外に出さない内部のID。

    客に見える注文番号（7.2.1）と違い、推測されて困るものではない。
    """
    row = db.execute(text("SELECT COALESCE(MAX(CAST(SUBSTRING(member_id,2) AS UNSIGNED)),0) n "
                          "  FROM member WHERE member_id LIKE 'M%'")).first()
    return f"M{int(row.n) + 1:04d}"


def create_member(db: Session, *, member_id: str, email: str, password_hash: str,
                  name: str | None = None) -> None:
    db.execute(
        text("INSERT INTO member (member_id, email, password_hash, name, status) "
             "VALUES (:m, :e, :p, :n, :s)"),
        {"m": member_id, "e": email, "p": password_hash, "n": name, "s": MEMBER_ACTIVE},
    )


def set_member_password(db: Session, member_id: str, password_hash: str) -> None:
    # ★パスワードを変えたら失敗回数もロックも落とす（本人が入れたのだから）
    db.execute(
        text("UPDATE member SET password_hash = :p, failed_count = 0, locked_until = NULL "
             " WHERE member_id = :m"),
        {"m": member_id, "p": password_hash},
    )


# ------------------------------------------------------------
# ロック（N-23）。★会員も運営者も同じ形
# ------------------------------------------------------------
def is_locked(row: dict, now: datetime) -> bool:
    lu = row.get("locked_until")
    return bool(lu and lu > now)


def _table_of(user_kind: int) -> tuple[str, str]:
    return ("member", "member_id") if user_kind == USER_MEMBER else ("operator", "operator_id")


def record_failure(db: Session, user_kind: int, user_id: str) -> None:
    """失敗を1つ数える。★10回に達したらロック期限を入れる。

    ★読んでから書かない。1本のUPDATEで数えて、同じ文の中で判定する。
    """
    tbl, key = _table_of(user_kind)
    db.execute(
        text(f"UPDATE {tbl} "
             f"   SET failed_count = failed_count + 1, "
             f"       locked_until = CASE WHEN failed_count + 1 >= :max "
             f"                           THEN NOW(3) + INTERVAL :min MINUTE "
             f"                           ELSE locked_until END "
             f" WHERE {key} = :id"),
        {"id": user_id, "max": _cfg(db, "login_fail_limit", MAX_FAILED),
         "min": _cfg(db, "login_lock_min", LOCK_MINUTES)},
    )
    db.commit()


def record_success(db: Session, user_kind: int, user_id: str) -> None:
    tbl, key = _table_of(user_kind)
    db.execute(text(f"UPDATE {tbl} SET failed_count = 0, locked_until = NULL WHERE {key} = :id"),
               {"id": user_id})
    db.commit()


def ip_rate_exceeded(db: Session, src_ip: str | None) -> bool:
    """N-23 の後半。★アカウント単位のロックでは、未登録アドレスの総当たりを止められない。"""
    if not src_ip:
        return False
    row = db.execute(
        text("SELECT failed_count, window_start FROM login_attempt WHERE src_ip = :ip"),
        {"ip": src_ip},
    ).first()
    if not row:
        return False
    if row.window_start < datetime.now() - timedelta(minutes=IP_WINDOW_MINUTES):
        return False              # 窓が過ぎている。次の失敗で作り直される
    return int(row.failed_count) >= IP_MAX_FAILED


def record_ip_failure(db: Session, src_ip: str | None) -> None:
    if not src_ip:
        return
    db.execute(
        text("INSERT INTO login_attempt (src_ip, window_start, failed_count) "
             "VALUES (:ip, NOW(3), 1) "
             "ON DUPLICATE KEY UPDATE "
             # ★窓が過ぎていたら数え直す。過ぎていなければ足す
             "  failed_count = IF(window_start < NOW(3) - INTERVAL :w MINUTE, 1, failed_count + 1), "
             "  window_start = IF(window_start < NOW(3) - INTERVAL :w MINUTE, NOW(3), window_start)"),
        {"ip": src_ip, "w": IP_WINDOW_MINUTES},
    )
    db.commit()


# ------------------------------------------------------------
# 運営者
# ------------------------------------------------------------
def find_operator_by_email(db: Session, email: str) -> dict | None:
    row = db.execute(
        text("SELECT operator_id, email, password_hash, name, role, location_code, is_active, "
             "       failed_count, locked_until FROM operator WHERE email = :e"),
        {"e": email},
    ).first()
    return dict(row._mapping) if row else None


def find_operator(db: Session, operator_id: str) -> dict | None:
    row = db.execute(
        text("SELECT operator_id, name, email, role, location_code, is_active "
             "  FROM operator WHERE operator_id = :o"),
        {"o": operator_id},
    ).first()
    return dict(row._mapping) if row else None


# ------------------------------------------------------------
# セッション（T-18・N-24）
# ------------------------------------------------------------
def create_session(db: Session, *, session_id: str, user_kind: int,
                   member_id: str | None = None, operator_id: str | None = None) -> None:
    db.execute(
        text("INSERT INTO session (session_id, user_kind, member_id, operator_id) "
             "VALUES (:s, :k, :m, :o)"),
        {"s": session_id, "k": user_kind, "m": member_id, "o": operator_id},
    )


def load_session(db: Session, session_id: str | None) -> dict | None:
    """★毎回引き直す（4.1.2 ③）。無操作60分を過ぎていたら無いものとして扱う。

    ★「無い」と「切れている」を呼び出し側で区別させない。どちらも ERR-1101。
    """
    if not session_id:
        return None
    row = db.execute(
        text("SELECT session_id, user_kind, member_id, operator_id, guest_order_no, last_access_at "
             "  FROM session "
             " WHERE session_id = :s AND last_access_at > NOW(3) - INTERVAL :m MINUTE"),
        {"s": session_id, "m": _cfg(db, "session_idle_min", SESSION_IDLE_MINUTES)},
    ).first()
    if not row:
        return None
    db.execute(text("UPDATE session SET last_access_at = NOW(3) WHERE session_id = :s"),
               {"s": session_id})
    db.commit()
    return dict(row._mapping)


def delete_session(db: Session, session_id: str) -> int:
    """ログアウト。★サーバ側で消す（SEC-307）。

    ★JWT を採らなかったのはここ。署名付きの札は、こちらの都合で無効にできない。
    """
    n = db.execute(text("DELETE FROM session WHERE session_id = :s"), {"s": session_id}).rowcount
    db.commit()
    return int(n)


def delete_sessions_of_member(db: Session, member_id: str) -> int:
    """パスワードを変えたら、その会員の他のセッションも切る。"""
    n = db.execute(text("DELETE FROM session WHERE member_id = :m"), {"m": member_id}).rowcount
    db.commit()
    return int(n)


# ------------------------------------------------------------
# 会員登録の確認（E-41・8.3.1）
# ------------------------------------------------------------
def create_confirm(db: Session, *, token: str, email: str, password_hash: str) -> None:
    db.execute(
        text("INSERT INTO member_confirm (token, email, password_hash, expires_at) "
             "VALUES (:t, :e, :p, NOW(3) + INTERVAL :m MINUTE)"),
        {"t": token, "e": email, "p": password_hash, "m": _cfg(db, "confirm_url_valid_min", CONFIRM_MINUTES)},
    )
    db.commit()


def take_confirm(db: Session, token: str, *, commit: bool = True) -> dict | None:
    """★使用済みにするのと読むのを1回のUPDATEでやる（先勝ち）。

    読んでから書くと、同じURLを2回同時に開いたときに会員が2つできる。
    ★commit=False なら、会員を作るのと同じトランザクションに入れる（R-28）。
      先にコミットすると、会員の INSERT が失敗したときにトークンだけ使用済みで残り、
      その人は二度と登録を終えられない。
    """
    n = db.execute(
        text("UPDATE member_confirm SET used = TRUE "
             " WHERE token = :t AND used = FALSE AND expires_at > NOW(3)"),
        {"t": token},
    ).rowcount
    if commit:
        db.commit()
    if n == 0:
        return None
    row = db.execute(text("SELECT token, email, password_hash FROM member_confirm WHERE token = :t"),
                     {"t": token}).first()
    return dict(row._mapping) if row else None


# ------------------------------------------------------------
# パスワード再設定（E-44・N-25）
# ------------------------------------------------------------
def create_reset(db: Session, *, token: str, member_id: str) -> None:
    db.execute(
        text("INSERT INTO password_reset (token, member_id, expires_at) "
             "VALUES (:t, :m, NOW(3) + INTERVAL :n MINUTE)"),
        {"t": token, "m": member_id, "n": _cfg(db, "reset_url_valid_min", RESET_MINUTES)},
    )
    db.commit()


def take_reset(db: Session, token: str) -> dict | None:
    """★期限切れと使用済みを、同じ1本のUPDATEで弾く（N-25）。"""
    n = db.execute(
        text("UPDATE password_reset SET used = TRUE "
             " WHERE token = :t AND used = FALSE AND expires_at > NOW(3)"),
        {"t": token},
    ).rowcount
    db.commit()
    if n == 0:
        return None
    row = db.execute(text("SELECT token, member_id FROM password_reset WHERE token = :t"),
                     {"t": token}).first()
    return dict(row._mapping) if row else None


def expire_reset_for_test(db: Session, token: str, minutes: int) -> None:
    """試験用（SEC-207）。★61分後を待たずに期限切れを作る。"""
    db.execute(text("UPDATE password_reset SET expires_at = NOW(3) - INTERVAL :m MINUTE "
                    " WHERE token = :t"), {"t": token, "m": minutes})
    db.commit()


# ------------------------------------------------------------
# カートの統合（BR-24a・T-19）
# ------------------------------------------------------------
def merge_cart(db: Session, *, guest_key: str | None, member_id: str) -> int:
    """ログインしたらゲストのカートを会員のカートへ寄せる。

    ★同じSKUが両方にあったら足す。★上限（F-301。99点）で頭打ちにする。
    ★寄せたあとゲストの行は消す。残すと、次に同じ端末を使った人に見える。
    """
    if not guest_key or guest_key == member_id:
        return 0
    # ★読み元に別名を付ける。付けないと ON DUPLICATE KEY UPDATE の cart.qty が
    #   「どちらの cart か」で ERROR 1052（ambiguous）になる。同じ表に入れているため
    moved = db.execute(
        text("INSERT INTO cart (cart_key, sku_code, user_kind, qty, added_at) "
             "SELECT :m, src.sku_code, :kind, src.qty, src.added_at "
             "  FROM cart AS src WHERE src.cart_key = :g "
             "ON DUPLICATE KEY UPDATE qty = LEAST(cart.qty + VALUES(qty), :maxqty), "
             "                        user_kind = :kind"),
        {"m": member_id, "g": guest_key, "kind": USER_MEMBER, "maxqty": MAX_QTY_PER_LINE},
    ).rowcount
    db.execute(text("DELETE FROM cart WHERE cart_key = :g"), {"g": guest_key})
    db.commit()
    return int(moved)


# ------------------------------------------------------------
# 認証イベント（E-39・8.6）
# ------------------------------------------------------------
EV_LOGIN_OK, EV_LOGIN_NG, EV_LOCK, EV_RESET = 1, 2, 3, 4


def record_auth_event(db: Session, *, event_kind: int, member_id: str | None = None,
                      operator_id: str | None = None, src_ip: str | None = None) -> None:
    """★パスワードは記録しない（DDL のコメントのとおり）。入れる箱も無い。"""
    db.execute(
        text("INSERT INTO auth_event (event_kind, member_id, operator_id, src_ip) "
             "VALUES (:k, :m, :o, :ip)"),
        {"k": event_kind, "m": member_id, "o": operator_id, "ip": src_ip},
    )
    db.commit()


# ------------------------------------------------------------
# F-313 ゲスト注文の照会（AP-306・N-27。R-29）
# ------------------------------------------------------------
def lookup_rate_exceeded(db: Session, src_ip: str | None) -> bool:
    """★BR-26 と同じ形。失敗だけを数える（成功は数えない）。表は login_attempt と分ける。"""
    if not src_ip:
        return False
    row = db.execute(
        text("SELECT failed_count, window_start FROM lookup_attempt WHERE src_ip = :ip"),
        {"ip": src_ip},
    ).first()
    if not row or row.window_start < datetime.now() - timedelta(minutes=IP_WINDOW_MINUTES):
        return False
    return int(row.failed_count) >= IP_MAX_FAILED


def record_lookup_failure(db: Session, src_ip: str | None) -> None:
    if not src_ip:
        return
    db.execute(
        text("INSERT INTO lookup_attempt (src_ip, window_start, failed_count) "
             "VALUES (:ip, NOW(3), 1) "
             "ON DUPLICATE KEY UPDATE "
             "  failed_count = IF(window_start < NOW(3) - INTERVAL :w MINUTE, 1, failed_count + 1), "
             "  window_start = IF(window_start < NOW(3) - INTERVAL :w MINUTE, NOW(3), window_start)"),
        {"ip": src_ip, "w": IP_WINDOW_MINUTES},
    )
    db.commit()


def find_guest_order(db: Session, order_no: str) -> dict | None:
    """★ゲストの注文だけ（会員の注文はログインして見る）。"""
    row = db.execute(
        text("SELECT order_no, orderer_email FROM orders WHERE order_no = :o AND member_id IS NULL"),
        {"o": order_no},
    ).first()
    return dict(row._mapping) if row else None


def grant_guest_order(db: Session, session_id: str, order_no: str) -> None:
    """★照会権は「その注文番号1件ぶん」だけ（N-27）。列が1つなので、2件目で上書きされる。

    ゲストのセッションはまだ表に無いことがあるので、無ければ作る（user_kind=1）。
    """
    db.execute(
        text("INSERT INTO session (session_id, user_kind, guest_order_no) VALUES (:s, :k, :o) "
             "ON DUPLICATE KEY UPDATE guest_order_no = :o, last_access_at = NOW(3)"),
        {"s": session_id, "k": USER_GUEST, "o": order_no},
    )
    db.commit()
