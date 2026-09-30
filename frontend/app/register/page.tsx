// SCR 会員登録（AP-501）。
//
// ★このページから「登録済みです」は返ってこない（N-26・8.3.1）。
//   送信すると、登録済みでも未登録でも同じ /register/sent に着く。
import { registerAction } from "@/lib/actions/auth";

export const dynamic = "force-dynamic";

export default async function RegisterPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;

  return (
    <main className="wrap narrow">
      <h1>会員登録</h1>
      {err === "ERR-1003" ? <p className="err">パスワードは8〜128文字で入力してください</p> : null}
      {err && err !== "ERR-1003" ? <p className="err">エラーが発生しました</p> : null}

      <form action={registerAction} className="form">
        <label>
          メールアドレス
          <input type="email" name="email" required autoComplete="email" />
        </label>
        <label>
          パスワード（8〜128文字）
          <input type="password" name="password" required minLength={8} maxLength={128}
                 autoComplete="new-password" />
        </label>
        <button type="submit">確認メールを送る</button>
      </form>

      <p className="note">
        ご入力のアドレスに確認メールをお送りします。メール内のURLを開くと登録が完了します。
      </p>
    </main>
  );
}
