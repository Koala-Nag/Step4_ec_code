// SCR-B08 会員の照会｜詳細（AP-B31・F-609）。R-33。
// ★会員情報と注文履歴を参照するだけ。パスワードは出さない（API も返さない）。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { getMember } from "@/lib/api/backoffice";
import { yen } from "@/lib/view/format";
import { orderStatusLabel } from "@/lib/view/order-status";

export const dynamic = "force-dynamic";

export default async function MemberDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let m;
  try {
    m = (await getMember(id)).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 404) notFound();
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">会員の照会</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/admin/members">会員の照会</Link> ／ {m.member_id}</p>
      <h1 className="h1"><code>{m.member_id}</code> {m.name ?? "—"} <span className={`badge ${m.status === 1 ? "in" : "out"}`}>{m.status_label}</span></h1>
      <table className="sum info">
        <tbody>
          <tr><th>メールアドレス</th><td>{m.email ?? "（退会済み）"}</td></tr>
          <tr><th>電話番号</th><td>{m.tel ?? "—"}</td></tr>
          <tr><th>店舗会員ID</th><td>{m.shop_member_id ?? "—"}</td></tr>
          <tr><th>登録日時</th><td>{m.created_at}</td></tr>
          <tr><th>更新日時</th><td>{m.updated_at}</td></tr>
          {m.locked_until ? <tr><th>ログインのロック</th><td>{m.locked_until} まで</td></tr> : null}
        </tbody>
      </table>

      {m.addresses.length ? (
        <>
          <h2 className="h2">住所帳</h2>
          <ul>{m.addresses.map((a, i) => <li key={i}>{a.name} 〒{a.zip} {a.address} {a.tel}</li>)}</ul>
        </>
      ) : null}

      <h2 className="h2">注文履歴（{m.orders.length}件）</h2>
      {m.orders.length === 0 ? <p className="empty">注文はありません。</p> : (
        <table className="orders">
          <thead><tr><th>注文番号</th><th>注文日時</th><th>受け取り</th><th>状態</th><th>支払総額</th></tr></thead>
          <tbody>
            {m.orders.map((o) => (
              <tr key={o.order_no}>
                <td>{m.can_open_order ? <Link href={`/admin/orders/${encodeURIComponent(o.order_no)}`}><code>{o.order_no}</code></Link> : <code>{o.order_no}</code>}</td>
                <td>{o.ordered_at}</td>
                <td>{o.receive_method === 2 ? "店舗受取" : "配送"}</td>
                <td><span className="badge">{orderStatusLabel(o.status)}</span></td>
                <td className="num">{yen(o.total_amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
