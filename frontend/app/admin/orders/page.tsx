// AP-B10 注文一覧 ＋ AP-B12 出荷指示（F-903a。串の⑦）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminListOrders, adminMe } from "@/lib/api/client";
import { instructAction } from "@/lib/actions/admin";
import { yen } from "@/lib/view/format";
import { orderStatusLabel } from "@/lib/view/order-status";

export const dynamic = "force-dynamic";

// 5.4。★引当済（5）のときだけ出荷指示を出せる
const ALLOCATED = 5;

export default async function AdminOrdersPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;

  let me, orders;
  try {
    me = (await adminMe()).data;
    orders = (await adminListOrders()).data.orders;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      redirect("/admin/login");
    }
    throw e;
  }

  return (
    <main className="wrap">
      <h1 className="h1">注文一覧</h1>
      <p className="note">{me.name}（役割 {me.role}{me.location_code ? ` / ${me.location_code}` : ""}）</p>
      {err ? <p className="err">この操作は行えませんでした（{err}）</p> : null}

      <table className="orders">
        <thead>
          <tr><th>注文番号</th><th>状態</th><th>支払総額</th><th>ご注文日</th><th>出荷指示</th></tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.order_no}>
              <td><Link href={`/admin/orders/${o.order_no}`}><code>{o.order_no}</code></Link></td>
              <td><span className="badge">{orderStatusLabel(o.status)}</span></td>
              <td className="num">{yen(o.total_amount)}</td>
              <td>{String(o.created_at).slice(0, 10)}</td>
              <td>
                {/* ★ボタンを隠すのは親切であって、権限ではない。
                    出せない注文に出しても、APIが 409 で断る（4.1.2） */}
                {o.status === ALLOCATED ? (
                  <form action={instructAction}>
                    <input type="hidden" name="order_no" value={o.order_no} />
                    <button type="submit" className="mini">出荷指示を作る</button>
                  </form>
                ) : (
                  <span className="can">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
