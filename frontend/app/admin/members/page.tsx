// SCR-B08 会員の照会｜検索（AP-B31・F-609）。R-33。
// ★参照だけ。★メールアドレスは完全一致（部分一致だと総当たりで引ける）。条件なしでは出さない。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { searchMembers } from "@/lib/api/backoffice";
import { one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function MembersPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const q = { email: one(sp.email), name: one(sp.name), member_id: one(sp.member_id) };
  let d;
  try {
    d = (await searchMembers(q)).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">会員の照会</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }

  return (
    <main className="wrap">
      <h1 className="h1">会員の照会</h1>
      <p className="note">参照のみです。会員情報の変更は、会員ご本人の画面で行います。</p>
      <form method="get" action="/admin/members" className="rowform" style={{ margin: "8px 0 16px" }}>
        <input name="email" type="email" placeholder="メールアドレス（完全一致）" defaultValue={q.email ?? ""} aria-label="メールアドレス" />
        <input name="name" placeholder="氏名（一部でも可）" defaultValue={q.name ?? ""} aria-label="氏名" />
        <input name="member_id" placeholder="会員ID" defaultValue={q.member_id ?? ""} aria-label="会員ID" />
        <button type="submit" className="btn sub">探す</button>
      </form>

      {!d.searched ? (
        <p className="empty">メールアドレス・氏名・会員IDのどれかを入れて探してください。</p>
      ) : d.members.length === 0 ? (
        <p className="empty">該当する会員はいません。</p>
      ) : (
        <table className="orders">
          <thead><tr><th>会員ID</th><th>氏名</th><th>メールアドレス</th><th>状態</th><th>登録日</th><th>注文</th></tr></thead>
          <tbody>
            {d.members.map((m) => (
              <tr key={m.member_id}>
                <td><Link href={`/admin/members/${encodeURIComponent(m.member_id)}`}><code>{m.member_id}</code></Link></td>
                <td>{m.name ?? "—"}</td>
                <td>{m.email ?? "（退会済み）"}</td>
                <td><span className={`badge ${m.status === 1 ? "in" : "out"}`}>{m.status_label}</span></td>
                <td>{m.created_at}</td>
                <td className="num">{m.order_count}件</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
