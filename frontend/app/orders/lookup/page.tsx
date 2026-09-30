// SCR-13 ゲスト注文の照会（AP-306・F-313・N-27。R-29）。
//
// ★注文番号とメールアドレスの2つが一致したときだけ、その注文1件を見られる（再決済・キャンセルもここから）。
// ★一致しないときは、注文があるかどうかも言わない（ERR-1107。8.2）。
// ★全画面共通のフッタから来られる（要件 5.1 SCR-13）。メールの URL だけを入口にしない。
import Link from "next/link";

import { lookupAction } from "@/lib/actions/order";
import { SubmitButton } from "@/app/submit-button";

export const dynamic = "force-dynamic";
export const metadata = { title: "ご注文の照会" };

export default async function LookupPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
  const err = one(sp.err);
  const orderNo = one(sp.order_no) ?? "";

  return (
    <main className="wrap narrow">
      <p className="crumb"><Link href="/">トップ</Link> ／ ご注文の照会</p>
      <h1>ご注文の照会</h1>
      <p className="note">会員登録をせずにご注文いただいた方は、注文番号とご注文のときのメールアドレスで、ご注文の状況を確かめられます。お支払いのやり直しやキャンセルもこちらから行えます。</p>
      {err === "ERR-1107" ? (
        <p className="err">注文番号またはメールアドレスが一致しません。</p>
      ) : err === "ERR-1101" ? (
        <p className="err">画面を開き直してから、もう一度お試しください。</p>
      ) : err ? (
        <p className="err">エラーが発生しました。時間をおいてお試しください。</p>
      ) : null}
      <form action={lookupAction} className="form">
        <label>
          注文番号
          <input name="order_no" defaultValue={orderNo} placeholder="ORD-260913-XXXXXXXX" required autoComplete="off" />
        </label>
        <label>
          メールアドレス
          <input name="email" type="email" required autoComplete="email" />
        </label>
        <SubmitButton pending="確認しています…">照会する</SubmitButton>
      </form>
      <p className="note">注文番号は、ご注文確定のメールに書かれています。</p>
      <p className="note">会員の方は <Link href="/login">ログイン</Link> して、購入履歴からご確認ください。</p>
    </main>
  );
}
