// 返品申請の状態（F-507・AP-402）。R-31。
//
// ★会員は購入履歴から、ゲストは照会画面を通った注文から（F-507「客も自分の申請の状態を見られる」）。
// ★5つの状態を並べて、いまどこかを見せる（要件 5.3「返品の状態」）。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { getMyReturn } from "@/lib/api/returns";
import { yen } from "@/lib/view/format";

export const dynamic = "force-dynamic";

const STEPS: [number, string][] = [[1, "申請中"], [3, "返送待ち"], [4, "受領"], [5, "検品済"], [6, "返金済"]];

export default async function MyReturnPage({
  params,
  searchParams,
}: {
  params: Promise<{ no: string; rn: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { no, rn } = await params;
  const sp = await searchParams;
  let r;
  try {
    r = (await getMyReturn(rn)).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect(`/orders/lookup?order_no=${encodeURIComponent(no)}`);
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  if (r.order_no !== no) notFound();
  const back = `/orders/${encodeURIComponent(r.order_no)}/detail`;
  const rejected = r.status === 2;

  return (
    <main className="wrap">
      <p className="crumb"><Link href={back}>{r.order_no}</Link> ／ 返品 {r.return_no}</p>
      <h1 className="h1">返品 <code>{r.return_no}</code> <span className="badge">{r.status_label}</span></h1>
      {sp.applied ? (
        <p className="ok">返品を申請しました。内容を確認のうえ、承認または理由をメールでお知らせします。</p>
      ) : null}

      {rejected ? (
        <p className="err">この返品はお受けできませんでした。理由：{r.reject_reason}</p>
      ) : (
        <ol className="steps" style={{ display: "flex", gap: 8, listStyle: "none", padding: 0, flexWrap: "wrap" }}>
          {STEPS.map(([s, label]) => {
            const done = r.status >= s;
            return (
              <li key={s} className={`badge ${done ? "in" : "out"}`} aria-current={r.status === s ? "step" : undefined}>
                {label}
              </li>
            );
          })}
        </ol>
      )}

      {r.status === 3 ? (
        <table className="sum info">
          <tbody>
            <tr><th>返送先</th><td>当社倉庫（承認のメールに住所を記載しています）</td></tr>
            <tr><th>返送期限</th><td>{r.return_deadline}</td></tr>
            <tr><th>返送送料</th><td>{r.return_fee_bearer}のご負担</td></tr>
          </tbody>
        </table>
      ) : null}

      <table className="orders">
        <thead><tr><th>商品</th><th>数</th><th>理由</th><th>検品の結果</th>{r.status === 6 ? <th>返金額</th> : null}</tr></thead>
        <tbody>
          {r.lines.map((l) => (
            <tr key={l.line_no}>
              <td>{l.product_name}（{l.color_name} / {l.size_name}）</td>
              <td className="num">{l.qty}</td>
              <td>{l.reason}{l.reason_text ? <><br /><small>{l.reason_text}</small></> : null}</td>
              <td>{l.inspect_result ?? "—"}{l.inspect_note ? <><br /><small>{l.inspect_note}</small></> : null}</td>
              {r.status === 6 ? <td className="num">{yen(l.refund_amount ?? 0)}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
      {r.status === 6 ? (
        <table className="sum">
          <tbody>
            {r.shipping_refund ? <tr><th>送料</th><td className="num">{yen(r.shipping_refund)}</td></tr> : null}
            <tr className="total"><th>返金額</th><td className="num">{yen(r.refund_total ?? 0)}</td></tr>
          </tbody>
        </table>
      ) : null}
      <p style={{ marginTop: 16 }}><Link href={back}>注文の詳細に戻る</Link></p>
    </main>
  );
}
