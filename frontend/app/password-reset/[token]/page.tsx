// 再設定URLを開いた画面。
//
// ★トークンはパスに入っている。クエリ文字列ではない（8.6・SEC-208）。
//   ?token=… にすると、アクセスログとリファラに残る。
import { passwordResetConfirmAction } from "@/lib/actions/auth";

export const dynamic = "force-dynamic";

export default async function PasswordResetConfirmPage({
  params,
  searchParams,
}: {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { token } = await params;
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;

  return (
    <main className="wrap narrow">
      <h1>新しいパスワード</h1>
      {/* ★期限切れも使用済みも同じ文言（N-25・SEC-207） */}
      {err === "ERR-1004" ? (
        <p className="err">このURLは使えません。もう一度お手続きください。</p>
      ) : null}
      {err === "ERR-1003" ? <p className="err">パスワードは8〜128文字で入力してください</p> : null}

      <form action={passwordResetConfirmAction} className="form">
        <input type="hidden" name="token" value={token} />
        <label>
          新しいパスワード（8〜128文字）
          <input type="password" name="password" required minLength={8} maxLength={128}
                 autoComplete="new-password" />
        </label>
        <button type="submit">変更する</button>
      </form>
    </main>
  );
}
