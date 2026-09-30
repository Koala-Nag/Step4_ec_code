// SCR-B10 返品受付｜一覧（AP-B24・F-507）。R-31。
//
// ★状態ごとの件数を先頭に出す（F-507）。件数を押すとその状態に絞る。
// ★倉庫スタッフには「返送待ち」「受領」と、在庫に戻していない合格品だけ（F-507・F-504）。絞るのは API。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { adminListReturns } from "@/lib/api/returns";
import { ROLE_LABEL, errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function AdminReturnsPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const q = {
    status: one(sp.status), return_no: one(sp.return_no), order_no: one(sp.order_no),
    date_from: one(sp.date_from), date_to: one(sp.date_to),
  };
  let me, d;
  try {
    me = (await adminMe()).data;
    d = (await adminListReturns(q)).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && (e.status === 403 || e.status === 400)) {
      return <main className="wrap"><h1 className="h1">返品受付</h1><p className="err">{errText(e.code)}</p></main>;
    }
    throw e;
  }
  const link = (status?: number) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...q, status: status ? String(status) : undefined })) if (v) p.set(k, v);
    const s = p.toString();
    return `/admin/returns${s ? `?${s}` : ""}`;
  };

  return (
    <main className="wrap">
      <h1 className="h1">返品受付</h1>
      <p className="note">{me.name}（{ROLE_LABEL[me.role]}）{d.scope === "warehouse" ? " ／ 返送待ち・受領と、在庫に戻していない合格品だけ表示（F-507）" : ""}</p>

      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {/* ★状態ごとの件数（F-507）。0件の状態も並べる */}
      <p className="counts" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Link href={link()} className={`badge ${q.status ? "out" : "in"}`}>すべて {d.counts.reduce((a, c) => a + c.count, 0)}</Link>
        {d.counts.map((c) => (
          <Link key={c.status} href={link(c.status)} className={`badge ${q.status === String(c.status) ? "in" : "out"}`}>
            {c.label} {c.count}
          </Link>
        ))}
      </p>

      <form className="rowform" method="get" action="/admin/returns" style={{ margin: "8px 0 16px" }}>
        {q.status ? <input type="hidden" name="status" value={q.status} /> : null}
        <input name="return_no" placeholder="受付番号" defaultValue={q.return_no ?? ""} />
        <input name="order_no" placeholder="注文番号" defaultValue={q.order_no ?? ""} />
        <label>申請日 <input type="date" name="date_from" defaultValue={q.date_from ?? ""} /></label>
        〜 <input type="date" name="date_to" defaultValue={q.date_to ?? ""} aria-label="申請日（まで）" />
        <button type="submit" className="btn sub">絞り込む</button>
      </form>

      {d.returns.length === 0 ? (
        <p className="empty">該当する返品申請はありません。</p>
      ) : (
        <table className="orders">
          <thead><tr><th>受付番号</th><th>注文番号</th><th>お客様</th><th>申請日</th><th>数</th><th>状態</th></tr></thead>
          <tbody>
            {d.returns.map((r) => (
              <tr key={r.return_no}>
                <td><Link href={`/admin/returns/${encodeURIComponent(r.return_no)}`}>{r.return_no}</Link></td>
                <td><code>{r.order_no}</code></td>
                <td>{r.orderer_name}</td>
                <td>{r.applied_at.slice(0, 16)}</td>
                <td className="num">{r.qty}</td>
                <td>
                  <span className="badge">{r.status_label}</span>
                  {r.restock_pending > 0 && r.status >= 5 ? <><br /><small>在庫に戻していない合格品 {r.restock_pending}件</small></> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
