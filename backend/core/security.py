# -*- coding: utf-8 -*-
"""パスワードのハッシュ化とトークン（要件 N-22・N-25・N-26、設計 8.3.1）。

★ここは `domain/` に置かない。bcrypt は外部ライブラリなので、
  置くと「DBを立てずに数秒で回る」約束（10.1）が bcrypt の速度に縛られる。
  ★通してよい文字列かの判断は domain/password.py にある。

★N-26 の肝は「応答時間をそろえる」こと（8.3.1）。
  未登録なら照合するハッシュが無いので、何もしないと速く返る。
  ★速いか遅いかだけで、そのアドレスが登録済みかどうかが分かってしまう。
  → 未登録でも同じ重さの照合を1回走らせる（verify_dummy）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

import bcrypt

# bcrypt の作業係数。★上げると強くなるが、ログインの応答も同じだけ遅くなる。
#   12 は手元で約 0.25 秒。N-23 の ±100ms は「条件どうしの差」なので、
#   絶対値が遅いこと自体は違反ではない。
COST = 12


def _prepared(password: str) -> bytes:
    """★bcrypt に渡す前に SHA-256 で潰す。

    ★bcrypt は72バイトを超えたぶんを黙って切る。
      要件 N-22・6.1 は「8〜128文字」と決めているが、
      日本語なら25文字、絵文字なら19文字で72バイトを超える。
      ★そのまま渡すと「128文字まで入る」と言いながら、実際は先頭72バイトしか
        照合していない——長くしたのに強くなっていない状態を、黙って作ることになる。

    ★切るのでも弾くのでもなく、先に固定長へ潰してから渡す。
      SHA-256 は32バイト、base64 にして44バイトなので、必ず72バイト以内に収まる。
      ★base64 にするのは、生のダイジェストに 0x00 が混じると
        bcrypt がそこで文字列を打ち切るため（C の文字列として扱う）。

    ★この形は Django の BCryptSHA256PasswordHasher と同じ。
      保存される値は今までどおり $2b$ 始まりなので、SEC-804 の見え方は変わらない。
    """
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


# ★未登録のアドレスに対して照合する相手。実在のパスワードではない。
#   「照合が必ず失敗する、正しい形のハッシュ」であればよい。
_DUMMY_HASH = bcrypt.hashpw(_prepared(secrets.token_hex(16)), bcrypt.gensalt(rounds=COST))

# 43文字 = 32バイトを base64url にした長さ。member_confirm.token / password_reset.token
TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    """N-22。★塩は bcrypt が1回ごとに作る。

    同じパスワードの2人が別の値になるのは、この塩のため（SEC-804）。
    """
    return bcrypt.hashpw(_prepared(password), bcrypt.gensalt(rounds=COST)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """照合。★ハッシュが無い（未登録・退会済み・外部認証のみ）ときも同じ時間かける。"""
    if not password_hash:
        verify_dummy(password)
        return False
    try:
        return bcrypt.checkpw(_prepared(password), password_hash.encode("ascii"))
    except ValueError:
        # 壊れたハッシュ（seed の $dummy$ など）。★形が違うだけで速く返さない
        verify_dummy(password)
        return False


def verify_dummy(password: str) -> None:
    """★N-26 のための空回し。捨てる結果を1回だけ計算する。

    ここを消すと、未登録のアドレスだけ数百ミリ秒速く返るようになり、
    応答の文言をいくらそろえても、時間で登録の有無が分かる（8.3.1）。
    """
    bcrypt.checkpw(_prepared(password), _DUMMY_HASH)


def new_token() -> str:
    """確認URL・再設定URLのトークン。★推測できない値にする（連番にしない）。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def new_session_id() -> str:
    """session.session_id は CHAR(64)（T-18）。フロント層の newSessionId() と同じ形。"""
    return secrets.token_hex(32)


def same_token(a: str | None, b: str | None) -> bool:
    """★1バイトずつ返る比較にしない。時間差で正解を探られる。"""
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)
