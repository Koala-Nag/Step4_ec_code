// SCR-B09 クーポン管理（AP-B32・F-1001）。R-32。
// ★運用管理者だけ（2.4）。作ったクーポンは、会員がカートでコードを入れて使う（AP-204）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { listCoupons } from "@/lib/api/promo";
import { createCouponAction } from "@/lib/actions/promo";
import { SubmitButton } from "@/app/submit-button";
import { errText, one } from "@/lib/view/admin-labels";
import { COUPON_FIELD, CouponFields, couponLabel } from "./coupon-form";

export const dynamic = "force-dynamic";

export default async function CouponsPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
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
  const f = one(sp.field);
  const now = new Date();
  const names = Object.fromEntries(d.categories.map((c) => [c.code, c.name]));

  return (
    <main className="wrap">
      <h1 className="h1">クーポン管理</h1>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{f && COUPON_FIELD[f] ? `${COUPON_FIELD[f]}：` : ""}{errText(one(sp.err))}</p> : null}

      <table className="orders">
        <thead><tr><th>コード</th><th>名前・割引</th><th>対象</th><th>期間</th><th>最低金額</th><th>利用</th></tr></thead>
        <tbody>
          {d.coupons.map((c) => {
            const active = new Date(c.start_at) <= now && now <= new Date(c.end_at);
            return (
              <tr key={c.coupon_code}>
                <td><Link href={`/admin/coupons/${encodeURIComponent(c.coupon_code)}`}><code>{c.coupon_code}</code></Link></td>
                <td>{c.name}<br /><small>{couponLabel(c)}</small></td>
                <td>{c.target_kind === "all" ? "全商品" : c.target_kind === "category"
                  ? c.target_ids.map((t) => names[t] ?? t).join("・") : c.target_ids.join("・")}</td>
                <td><span className={`badge ${active ? "in" : "out"}`}>{active ? "期間中" : "期間外"}</span><br /><small>{c.start_at.replace("T", " ")} 〜 {c.end_at.replace("T", " ")}</small></td>
                <td className="num">{c.min_amount.toLocaleString()}円</td>
                <td className="num">{c.used_count}{c.total_limit !== null ? ` / ${c.total_limit}` : ""}<br /><small>1人 {c.per_member_limit ?? "無制限"}</small></td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2 className="h2">クーポンを作る</h2>
      <form action={createCouponAction} className="gridform">
        <label>コード<input name="coupon_code" maxLength={20} required placeholder="SPRING10" /></label>
        <CouponFields c={null} categories={d.categories} />
        <SubmitButton pending="作っています…">作る</SubmitButton>
      </form>
    </main>
  );
}
