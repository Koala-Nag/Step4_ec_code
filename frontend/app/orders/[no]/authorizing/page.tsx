// 決済代行から戻ってきたところ。AP-301a を呼ぶ（与信 → 引当）。
//
// ★auth_result は「入力」であって判定ではない（7.2.2）。
//   そのままサーバへ渡し、サーバが与信を投げて確かめる。
import { redirect } from "next/navigation";

import { ApiError, authorizeOrder } from "@/lib/api/client";

export const dynamic = "force-dynamic";

type SP = { [k: string]: string | string[] | undefined };
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default async function Authorizing({
  params,
  searchParams,
}: {
  params: Promise<{ no: string }>;
  searchParams: Promise<SP>;
}) {
  const { no } = await params;
  const sp = await searchParams;

  let to: string;
  try {
    const res = await authorizeOrder(no, {
      auth_result: one(sp.auth_result) ?? null,
      auth_ref: one(sp.auth_ref) ?? null,
    });
    // ★2拠点に分かれたことを完了画面にも伝える（AT-131・FR-306）。
    //   ★メールには出ていたが、画面に出していなかった（R-24 で見つけた）。
    //     要求は「完了画面と確認メールに」なので、片方だけでは足りない。
    const shipments = (res.data as { shipments?: number }).shipments ?? 1;
    to = `/orders/${no}/complete?result=${encodeURIComponent(res.data.result)}`
       + (shipments >= 2 ? `&shipments=${shipments}` : "");
  } catch (e) {
    const code = e instanceof ApiError ? e.code : "ERR-1401";
    to = `/orders/${no}/complete?result=error&err=${encodeURIComponent(code)}`;
  }
  redirect(to);
}
