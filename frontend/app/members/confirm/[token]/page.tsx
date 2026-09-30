// 確認URLを開いた画面（AP-501a）。★ここで会員ができる（8.3.1）。
import { confirmAction } from "@/lib/actions/auth";

export const dynamic = "force-dynamic";

export default async function ConfirmPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <main className="wrap narrow">
      <h1>会員登録の確認</h1>
      <p>下のボタンを押すと登録が完了します。</p>
      <form action={confirmAction} className="form">
        <input type="hidden" name="token" value={token} />
        <button type="submit">登録を完了する</button>
      </form>
    </main>
  );
}
