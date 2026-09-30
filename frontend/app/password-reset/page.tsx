// SCR パスワード再設定の要求（AP-503）。★応答から登録の有無が分からない（N-26）。
import { passwordResetRequestAction } from "@/lib/actions/auth";

export const dynamic = "force-dynamic";

export default function PasswordResetPage() {
  return (
    <main className="wrap narrow">
      <h1>パスワードの再設定</h1>
      <form action={passwordResetRequestAction} className="form">
        <label>
          メールアドレス
          <input type="email" name="email" required autoComplete="email" />
        </label>
        <button type="submit">再設定用のメールを送る</button>
      </form>
    </main>
  );
}
