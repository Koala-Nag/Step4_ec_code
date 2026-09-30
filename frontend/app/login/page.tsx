// SCR ログイン（AP-502）。
//
// ★失敗の文言は1種類しか持たない（8.3.1 ③・ERR-1104）。
//   「メールアドレスが未登録です」を出した瞬間、N-26 が破れる。
import Link from "next/link";

import { loginAction } from "@/lib/actions/auth";

export const dynamic = "force-dynamic";

const MESSAGES: Record<string, string> = {
  "ERR-1104": "メールアドレスまたはパスワードが違います",
  "ERR-1003": "パスワードは8〜128文字で入力してください",
  "ERR-1401": "エラーが発生しました。しばらくしてからお試しください",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;

  return (
    <main className="wrap narrow">
      <h1>ログイン</h1>

      {sp.registered ? <p className="ok">会員登録が完了しました。ログインしてください。</p> : null}
      {sp.reset ? <p className="ok">パスワードを変更しました。</p> : null}
      {err ? <p className="err">{MESSAGES[err] ?? MESSAGES["ERR-1401"]}</p> : null}

      <form action={loginAction} className="form">
        <label>
          メールアドレス
          <input type="email" name="email" required autoComplete="email" />
        </label>
        <label>
          パスワード
          <input type="password" name="password" required autoComplete="current-password" />
        </label>
        <button type="submit">ログイン</button>
      </form>

      <p className="links">
        <Link href="/register">会員登録</Link>
        ／
        <Link href="/password-reset">パスワードをお忘れの方</Link>
      </p>
    </main>
  );
}
