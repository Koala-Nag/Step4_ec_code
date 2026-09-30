// SCR-B09 クーポン管理｜編集（AP-B32 PATCH・F-1001）。R-32。
// ★コードは変えない（注文と利用履歴が参照している）。★注文ずみの割引額は変わらない（BR-17）。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { listCoupons } from "@/lib/api/promo";
import { editCouponAction } from "@/lib/actions/promo";
import { SubmitButton } from "@/app/submit-button";
import { errText, one } from "@/lib/view/admin-labels";
import { COUPON_FIELD, CouponFields, couponLabel } from "../coupon-form";

export const dynamic = "force-dynamic";

export default async function CouponEditPage({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { code } = await params;
  const sp = await searchParams;
  let d;
  try {
    d = (await listCoupons()).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">クーポン管理</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }
  const c = d.coupons.find((x) => x.coupon_code === decodeURIComponent(code));
  if (!c) notFound();
  const f = one(sp.field);

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/admin/coupons">クーポン管理</Link> ／ {c.coupon_code}</p>
      <h1 className="h1"><code>{c.coupon_code}</code> {c.name} <span className="badge">{couponLabel(c)}</span></h1>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{f && COUPON_FIELD[f] ? `${COUPON_FIELD[f]}：` : ""}{errText(one(sp.err))}</p> : null}
      <p className="note">使われた回数：{c.used_count}。★注文ずみの割引額は変わりません（BR-17）。</p>
      <form action={editCouponAction} className="gridform">
        <input type="hidden" name="coupon_code" value={c.coupon_code} />
        <CouponFields c={c} categories={d.categories} />
        <SubmitButton pending="保存しています…">保存する</SubmitButton>
      </form>
    </main>
  );
}
