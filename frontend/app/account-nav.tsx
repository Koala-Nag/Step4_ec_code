// ヘッダ右側の出し分け（R-28 (b)）。
//
//              未ログイン            会員でログイン中              運営者でログイン中
//   右側      ログイン／会員登録     ◯◯ 様・購入履歴・ログアウト    運営画面・ログアウト
//   カート    出す                   出す                          出す
//
// ★ログインしているかどうかを Cookie の有無で決めない（4.1.2 ③）。毎回サーバに聞く。
// ★購入していない人に「購入履歴」を出さない（R-28 でいちばん直したかったところ）。
// ★運営メニューは、運営者のセッションのときだけ（客には運営画面の存在を見せない）。
import Link from "next/link";

import { adminMe, getMe } from "@/lib/api/client";
import { adminLogoutAction } from "@/lib/actions/admin";
import { logoutAction } from "@/lib/actions/auth";

async function who(): Promise<{ kind: "member"; name: string } | { kind: "operator"; name: string } | null> {
  try {
    const me = await getMe();
    return { kind: "member", name: me.data.name ?? me.data.email };
  } catch {
    // ERR-1101（未ログイン）はふつうの状態。★バックエンドに届かないときも、ヘッダで画面を落とさない
  }
  try {
    const op = await adminMe();
    return { kind: "operator", name: op.data.name };
  } catch {
    return null;
  }
}

export async function AccountNav() {
  const u = await who();

  return (
    <nav className="account" aria-label="アカウント">
      {u === null ? (
        <>
          <Link href="/login">ログイン</Link>
          <Link href="/register">会員登録</Link>
        </>
      ) : u.kind === "member" ? (
        <>
          {/* ★名前から会員情報へ（F-605。R-32） */}
          <Link href="/mypage/profile" className="who">{u.name} 様</Link>
          <Link href="/mypage/favorites">お気に入り</Link>
          <Link href="/orders">購入履歴</Link>
          <form action={logoutAction}>
            <button type="submit">ログアウト</button>
          </form>
        </>
      ) : (
        <>
          <Link href="/admin/orders" className="opmenu">運営画面</Link>
          <form action={adminLogoutAction}>
            <button type="submit">ログアウト</button>
          </form>
        </>
      )}
      <Link href="/cart" className="cartlink">カート</Link>
    </nav>
  );
}
