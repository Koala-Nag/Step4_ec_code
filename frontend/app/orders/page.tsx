// SCR-08 購入履歴（AP-304。串の⑩）。
//
// ★ログインが要る。未ログインは ERR-1101 が返るので、ログイン画面へ送る。
// ★キャンセルできるかは画面で決めない。サーバの `cancellable` に従う（BR-17f・IT-101）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, listMyOrders } from "@/lib/api/client";
import { cancelMyOrderAction } from "@/lib/actions/order";
import { yen } from "@/lib/view/format";
import { orderStatusLabel } from "@/lib/view/order-status";

export const dynamic = "force-dynamic";

export default async function OrdersPage() {
  let orders;
  try {
    orders = (await listMyOrders()).data.orders;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/login");
    throw e;
  }

  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/products">商品一覧</Link> ／ 購入履歴
      </p>
      <h1 className="h1">購入履歴</h1>

      {orders.length === 0 ? (
        <p className="empty">ご注文はまだありません。<Link href="/products">商品を探す</Link></p>
      ) : (
        <table className="orders">
          <thead>
            <tr><th>注文番号</th><th>ご注文日</th><th>状態</th><th>支払総額</th><th></th></tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.order_no}>
                <td><code>{o.order_no}</code></td>
                <td>{o.ordered_at.slice(0, 10)}</td>
                <td><span className="badge">{orderStatusLabel(o.status)}</span></td>
                <td className="num">{yen(o.total_amount)}</td>
                <td>
                  <Link href={`/orders/${o.order_no}/detail`}>{o.repayable ? "お支払い手続きへ" : "詳細"}</Link>
                  {/* ★キャンセルのボタンは cancellable のときだけ。
                      出荷指示が出たら消える（BR-17f）。判定はサーバ（IT-101・102） */}
                  {o.cancellable ? (
                    <form action={cancelMyOrderAction} className="inline">
                      <input type="hidden" name="order_no" value={o.order_no} />
                      <button type="submit" className="mini">キャンセル</button>
                    </form>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
