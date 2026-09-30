// AP-B01 運営者ログイン。
// ★客のログイン画面とは別。運営者は AP-502 では入れない（SEC-706）。
import { adminLoginAction } from "@/lib/actions/admin";

export const dynamic = "force-dynamic";

export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;
  return (
    <main className="wrap narrow">
      <h1 className="h1">運営者ログイン</h1>
      {/* ★文言は1種類だけ（8.3.1 ③） */}
      {err ? <p className="err">メールアドレスまたはパスワードが違います</p> : null}
      <form action={adminLoginAction} className="form">
        <label>メールアドレス<input type="email" name="email" required /></label>
        <label>パスワード<input type="password" name="password" required /></label>
        <button type="submit">ログイン</button>
      </form>
    </main>
  );
}
