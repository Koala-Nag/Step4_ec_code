# -*- coding: utf-8 -*-
"""会員の認証（AP-501・501a・502・503・504。設計 4.2・8.3.1）。

★この串でいちばん気をつけたのは N-26（アドレスの登録有無を漏らさない）。
  8.3.1 が「応答を同じにするだけでは足りない。3つの経路から漏れる」と書いている。

    ① 応答時間   登録済みならハッシュ計算が走らない → 速く返る
    ② 後続の画面 確認手順が無いと「ログイン済み」と「作れない」で分かれる
    ③ ロックの区別 ロック中だけ別のコードを返すと、存在すると分かる

  ★3つとも塞いだ。やり方は下の各所に書いた。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, StrictStr
from sqlalchemy.orm import Session

from core import applog, security
from core.config import FRONTEND_BASE_URL
from core.db import get_db
from core.deps import cart_key, current_member, require_internal_auth, session_id
from core.errors import AppError
from domain import password as pw
from external import mailer
from repository import auth as repo

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_internal_auth)])
members = APIRouter(prefix="/members", tags=["auth"], dependencies=[Depends(require_internal_auth)])
me = APIRouter(prefix="/me", tags=["auth"], dependencies=[Depends(require_internal_auth)])


def _src_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ============================================================
# AP-501  会員登録の要求（確認メールを送るだけ。会員はまだ作らない）
# ============================================================
class RegisterBody(BaseModel):
    email: EmailStr
    password: StrictStr


@members.post("")
def register(body: RegisterBody, db: Session = Depends(get_db)) -> dict:
    """★登録済みでも未登録でも、同じ応答・同じ後続画面・同じ応答時間（N-26・8.3.1）。

    ★ここで会員を作らない。作るのは AP-501a（メール内のURLを開いたとき）。
      これで「未登録はログイン済み画面／登録済みは作れない画面」という
      後続の画面の違いが、原理的に生じなくなる。
    """
    if pw.policy_error(body.password):
        # ★これは漏れない。パスワードの形はアドレスと無関係
        raise AppError("ERR-1003", {"field": "password", "min": pw.MIN_LENGTH,
                                    "max": pw.MAX_LENGTH})
    email = pw.normalize_email(str(body.email))

    # ★どちらの枝でもハッシュ計算を1回行う。ここが応答時間をそろえている実体
    password_hash = security.hash_password(body.password)

    existing = repo.find_member_by_email(db, email)
    if existing:
        # ★登録済み。★確認メールは送らず、トークンも作らない。
        #   ただし「もう登録があります」という手掛かりも返さない。
        #   ★代わりに MSG-01b（心当たりが無ければ無視してください）を同じ相手に送る。
        #     本人には親切で、攻撃者には何も分からない（応答は下で同じものを返す）
        mailer.enqueue(
            db, msg_kind="MSG-01", to_email=email,
            subject="会員登録のお手続きについて",
            body=chr(10).join([
                "このメールアドレスはすでに登録されています。",
                "パスワードをお忘れの場合は、パスワードの再設定からお進みください。",
                "",
                f"{FRONTEND_BASE_URL}/password-reset",
                "",
                "お心当たりがない場合は、このメールを破棄してください。",
            ]),
        )
    else:
        token = security.new_token()
        repo.create_confirm(db, token=token, email=email, password_hash=password_hash)
        mailer.enqueue(
            db, msg_kind="MSG-01", to_email=email,
            subject="会員登録のご確認",
            body=chr(10).join([
                "以下のURLを開くと、会員登録が完了します。",
                "",
                # ★トークンはパスに置く。クエリ文字列に置かない（8.6・SEC-208）
                f"{FRONTEND_BASE_URL}/members/confirm/{token}",
                "",
                f"このURLは{repo._cfg(db, 'confirm_url_valid_min', repo.CONFIRM_MINUTES)}分で無効になります。",
            ]),
        )

    applog.emit("member.register_requested")
    # ★どちらの枝も、まったく同じ本文を返す
    return {"data": {"accepted": True, "message": "確認メールをお送りしました"}}


# ============================================================
# AP-501a  確認URLのトークンを受け取り、会員を作る
# ============================================================
class ConfirmBody(BaseModel):
    token: StrictStr


@members.post("/confirm")
def confirm(body: ConfirmBody, db: Session = Depends(get_db)) -> dict:
    """★トークンを使用済みにするのと、会員を作るのを1つのトランザクションにする（R-28）。

    ★会員IDは MAX+1 で採る。2人が同時に確認すると同じIDを取り合い、片方が主キーの重複で落ちる
      （R-28 の回帰で、2人同時の確認が約半分 500 になっていた）。
      そのときは全部取り消して（トークンも未使用に戻る）、IDを採り直す。
    """
    from sqlalchemy.exc import IntegrityError

    for _ in range(5):
        taken = repo.take_confirm(db, body.token, commit=False)
        if not taken:
            db.rollback()
            # 期限切れ・使用済み・でたらめ。★どれも同じ（区別すると総当たりの手掛かりになる）
            raise AppError("ERR-1004", {"field": "token"})

        # ★確認のあいだに、同じアドレスで別の登録が完了しているかもしれない
        if repo.find_member_by_email(db, taken["email"]):
            db.commit()                      # トークンは使用済みにしてよい（もう登録済み）
            raise AppError("ERR-1004", {"field": "token"})

        member_id = repo.next_member_id(db)
        try:
            repo.create_member(db, member_id=member_id, email=taken["email"],
                               password_hash=taken["password_hash"])
            db.commit()
        except IntegrityError:
            db.rollback()                    # ★トークンも未使用に戻る。IDを採り直す
            continue
        applog.emit("member.created")
        return {"data": {"member_id": member_id}}
    raise AppError("ERR-1401")


# ============================================================
# AP-502  ログイン・ログアウト
# ============================================================
class LoginBody(BaseModel):
    email: EmailStr
    password: StrictStr


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response,
          db: Session = Depends(get_db),
          cart: str | None = Depends(cart_key)) -> dict:
    """N-23・N-24・N-26。

    ★失敗の理由をここで分岐させない。3つとも ERR-1104 に落とす（8.3.1 ③）。
    ★どの枝でも bcrypt の照合を必ず1回通す（8.3.1 ①）。
    """
    ip = _src_ip(request)
    email = pw.normalize_email(str(body.email))

    if repo.ip_rate_exceeded(db, ip):
        # ★IP単位。アカウント単位のロックでは、未登録アドレスの総当たりを1回も止められない
        security.verify_dummy(body.password)          # ここも時間をそろえる
        raise AppError("ERR-1104")

    member = repo.find_member_by_email(db, email)

    if member is None:
        # ★未登録。★何もしないで返すと速い。捨てる照合を1回入れて時間をそろえる
        security.verify_dummy(body.password)
        repo.record_ip_failure(db, ip)
        repo.record_auth_event(db, event_kind=repo.EV_LOGIN_NG, src_ip=ip)
        raise AppError("ERR-1104")

    from datetime import datetime

    locked = repo.is_locked(member, datetime.now())
    ok = security.verify_password(body.password, member["password_hash"])
    # ★照合はロック中でも必ず走らせる。「ロック中は照合しない」にすると速く返る
    if locked or not ok or member["status"] != repo.MEMBER_ACTIVE:
        if not locked:
            repo.record_failure(db, repo.USER_MEMBER, member["member_id"])
        repo.record_ip_failure(db, ip)
        repo.record_auth_event(db, event_kind=repo.EV_LOCK if locked else repo.EV_LOGIN_NG,
                               member_id=member["member_id"], src_ip=ip)
        raise AppError("ERR-1104")

    # --- ここから成功 ---
    repo.record_success(db, repo.USER_MEMBER, member["member_id"])

    # ★セッションIDを再発行する（N-24・SEC-308。セッション固定攻撃）。
    #   ログイン前の値をそのまま使い続けると、攻撃者が先に配った値のまま
    #   会員として認証された状態になる
    new_sid = security.new_session_id()
    repo.create_session(db, session_id=new_sid, user_kind=repo.USER_MEMBER,
                        member_id=member["member_id"])
    db.commit()

    # ★ゲストのカートを会員のカートへ寄せる（BR-24a）
    moved = repo.merge_cart(db, guest_key=cart, member_id=member["member_id"])

    repo.record_auth_event(db, event_kind=repo.EV_LOGIN_OK,
                           member_id=member["member_id"], src_ip=ip)
    applog.emit("member.login")
    # ★Cookie を張るのはフロント層。ここは値を返すだけ（4.1.1 の層の分け）
    return {"data": {"session_id": new_sid, "member_id": member["member_id"],
                     "name": member.get("name"), "cart_merged": moved}}


@router.post("/logout")
def logout(db: Session = Depends(get_db), sid: str | None = Depends(session_id)) -> dict:
    """★サーバ側で無効にする（SEC-307）。

    ★これが JWT を採らなかった理由そのもの。
      署名付きの札は、期限が来るまでこちらの都合で無効にできない。
    """
    n = repo.delete_session(db, sid) if sid else 0
    applog.emit("member.logout", count=n)
    # ★消えていても成功を返す。「そのセッションは在った」を教えない
    return {"data": {"logged_out": True}}


# ============================================================
# AP-503  パスワード再設定
# ============================================================
class ResetRequestBody(BaseModel):
    email: EmailStr


@router.post("/password-reset")
def password_reset_request(body: ResetRequestBody, db: Session = Depends(get_db)) -> dict:
    """★応答からアドレスの登録有無が判別できない（N-26）。

    ★登録があってもなくても、同じ本文・同じ時間で返す。
    """
    email = pw.normalize_email(str(body.email))

    # ★分岐の前に、両方の枝で同じ重さの計算を1回通す（8.3.1・AP-501 と同じ形）。
    #   ★片方の枝にだけ入れると、逆向きにずれる。
    #     最初は「未登録の枝にだけ空回しを足す」と書いていて、
    #     登録済み 204ms / 未登録 392ms と、未登録のほうが遅くなった（R-21 で実測）。
    #     ★「速いほうが登録済み」でも「遅いほうが登録済み」でも、区別がつけば同じこと。
    security.verify_dummy(email)

    member = repo.find_member_by_email(db, email)

    if member and member["status"] == repo.MEMBER_ACTIVE:
        token = security.new_token()
        repo.create_reset(db, token=token, member_id=member["member_id"])
        mailer.enqueue(
            db, msg_kind="MSG-09", to_email=email,
            subject="パスワード再設定のご案内",
            body=chr(10).join([
                "以下のURLからパスワードを再設定してください。",
                "",
                # ★クエリ文字列に置かない（8.6・SEC-208）。
                #   ?token=… はアクセスログとリファラに残る
                f"{FRONTEND_BASE_URL}/password-reset/{token}",
                "",
                f"このURLは{repo._cfg(db, 'reset_url_valid_min', repo.RESET_MINUTES)}分で無効になります。一度使うと無効になります。",
            ]),
        )
    # ★未登録・退会済みのときは、トークンも作らずメールも積まない。
    #   ★それでも応答は上と同じ。重い計算は分岐の前で済ませてある

    applog.emit("member.password_reset_requested")
    return {"data": {"accepted": True, "message": "再設定用のメールをお送りしました"}}


class ResetConfirmBody(BaseModel):
    token: StrictStr
    password: StrictStr


@router.post("/password-reset/confirm")
def password_reset_confirm(body: ResetConfirmBody, db: Session = Depends(get_db)) -> dict:
    if pw.policy_error(body.password):
        raise AppError("ERR-1003", {"field": "password", "min": pw.MIN_LENGTH,
                                    "max": pw.MAX_LENGTH})
    taken = repo.take_reset(db, body.token)
    if not taken:
        # 期限切れ（61分後）も使用済み（2回目）も同じ（N-25・SEC-207）
        raise AppError("ERR-1004", {"field": "token"})

    repo.set_member_password(db, taken["member_id"], security.hash_password(body.password))
    db.commit()
    # ★パスワードを変えたら、その会員の既存のセッションを全部切る。
    #   盗まれていた場合、再設定しても入られたままになる
    repo.delete_sessions_of_member(db, taken["member_id"])
    repo.record_auth_event(db, event_kind=repo.EV_RESET, member_id=taken["member_id"])
    applog.emit("member.password_reset_done")
    return {"data": {"reset": True}}


# ============================================================
# AP-504  会員情報
# ============================================================
@me.get("")
def get_me(db: Session = Depends(get_db), member=Depends(current_member)) -> dict:
    row = repo.find_member(db, member["member_id"])
    if not row:
        raise AppError("ERR-1101")
    return {"data": {"member_id": row["member_id"], "email": row["email"],
                     "name": row["name"], "tel": row["tel"]}}
