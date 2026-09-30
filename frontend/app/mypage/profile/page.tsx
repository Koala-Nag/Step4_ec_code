// SCR-09 会員情報（AP-504・F-605）。R-32。
//
// ★変えられるのは氏名と電話番号（F-605「氏名・連絡先」）。メールアドレスは変えない（確認メールの往復が要る）。
// ★電話番号のハイフンはサーバが除く（要件 6.3）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { getProfile } from "@/lib/api/mypage";
import { updateProfileAction } from "@/lib/actions/mypage";
import { SubmitButton } from "@/app/submit-button";

export const dynamic = "force-dynamic";

const ERR: Record<string, string> = {
  "ERR-1001": "氏名と電話番号を入力してください",
  "ERR-1002": "電話番号は数字10〜11桁で入力してください",
  "ERR-1003": "氏名は50文字以内で入力してください",
};

export default async function ProfilePage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;
  let me;
  try {
    me = (await getProfile()).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/login");
    throw e;
  }

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/products">商品一覧</Link> ／ 会員情報</p>
      <h1 className="h1">会員情報</h1>
      {sp.ok ? <p className="ok">会員情報を変更しました。</p> : null}
      {err ? <p className="err">{ERR[err] ?? `変更できませんでした（${err}）`}</p> : null}
      <form action={updateProfileAction} className="gridform">
        <label>メールアドレス<input value={me.email} disabled readOnly /></label>
        <label>氏名<input name="name" defaultValue={me.name ?? ""} maxLength={50} required /></label>
        <label>電話番号<input name="tel" defaultValue={me.tel ?? ""} inputMode="tel" required /></label>
        <SubmitButton pending="変更しています…">変更する</SubmitButton>
      </form>
      <p className="note">メールアドレスの変更は受け付けていません。</p>
      <p><Link href="/orders">購入履歴</Link> ／ <Link href="/mypage/favorites">お気に入り</Link></p>
    </main>
  );
}
