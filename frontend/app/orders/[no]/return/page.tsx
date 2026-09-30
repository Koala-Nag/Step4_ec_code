// SCR-11 返品申請（F-502・AP-401）。R-31。
//
// ★会員は購入履歴の注文詳細から、ゲストは照会画面（SCR-13）を通った注文詳細から来る（F-502）。
// ★申請できる数と期限は AP-305 がサーバの時刻で決めて返す。画面は計算しない（BR-18）。
// ★返金額は出さない。検品が終わるまで決まらない（設計 4.5 ⑦）。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError, getMyOrder } from "@/lib/api/client";
import { applyReturnAction } from "@/lib/actions/returns";
import { SubmitButton } from "@/app/submit-button";
import { RETURN_POLICY as R, RETURN_ERR } from "@/lib/view/returns";

export const dynamic = "force-dynamic";

const REASONS: [string, string][] = [
  ["size", "サイズが合わない"], ["image", "イメージと違う"], ["defect", "不良"],
  ["wrong_item", "注文と違う商品が届いた"], ["other", "その他"],
];

export default async function ReturnApplyPage({
  params,
  searchParams,
}: {
  params: Promise<{ no: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { no } = await params;
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;
  let o;
  try {
    o = (await getMyOrder(no)).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect(`/orders/lookup?order_no=${encodeURIComponent(no)}`);
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const back = `/orders/${encodeURIComponent(o.order_no)}/detail`;
  const lines = o.returnable.lines;

  return (
    <main className="wrap">
      <p className="crumb">
        {o.viewer === "guest" ? <Link href="/orders/lookup">ご注文の照会</Link> : <Link href="/orders">購入履歴</Link>}
        {" ／ "}<Link href={back}>{o.order_no}</Link> ／ 返品の申請
      </p>
      <h1 className="h1">返品の申請</h1>
      {err ? <p className="err">{RETURN_ERR[err] ?? `申請できませんでした（${err}）`}</p> : null}

      {!o.returnable.can_apply ? (
        <>
          <p className="note">この注文には、いま返品を申請できる商品がありません。</p>
          <p><Link href={back}>注文の詳細に戻る</Link></p>
        </>
      ) : (
        <form action={applyReturnAction}>
          <input type="hidden" name="order_no" value={o.order_no} />
          <h2 className="h2">返品する商品と数</h2>
          <table className="orders">
            <thead><tr><th>商品</th><th>申請の期限</th><th>返品する数</th></tr></thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.line_no}>
                  <td>{l.product_name}（{l.color_name} / {l.size_name}）<br /><small>{l.sku_code}</small></td>
                  <td>
                    {l.deadline ? `${l.deadline} まで` : "お届け前"}
                    {l.applied_qty > 0 ? <><br /><small>申請済み {l.applied_qty}点</small></> : null}
                  </td>
                  <td>
                    {l.returnable_qty > 0 ? (
                      <select name={`qty_${l.line_no}`} defaultValue="0" aria-label={`${l.product_name} の返品する数`}>
                        {Array.from({ length: l.returnable_qty + 1 }, (_, i) => (
                          <option key={i} value={i}>{i === 0 ? "返品しない" : `${i}点`}</option>
                        ))}
                      </select>
                    ) : (
                      <small className="note">{!l.within_deadline && l.deadline ? "期限を過ぎています" : l.deadline ? "申請済みです" : "まだお届けしていません"}</small>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2 className="h2">返品の理由</h2>
          <fieldset className="reasons">
            {REASONS.map(([v, label], i) => (
              <label key={v} style={{ display: "block", margin: "4px 0" }}>
                <input type="radio" name="reason_code" value={v} defaultChecked={i === 0} /> {label}
              </label>
            ))}
          </fieldset>
          <label style={{ display: "block", marginTop: 8 }}>
            くわしい理由（「その他」を選んだときは必ずご記入ください。200文字まで）
            <textarea name="reason_text" rows={3} maxLength={200} style={{ width: "100%" }} />
          </label>

          <h2 className="h2">返品の条件</h2>
          <table className="sum policy">
            <tbody>
              <tr><th>期限</th><td>{R.deadline}</td></tr>
              <tr><th>条件</th><td>{R.condition}<br /><small>{R.conditionNote}</small></td></tr>
              <tr><th>返送先</th><td>{R.destination}（承認のあと、メールでご案内します）</td></tr>
              <tr><th>返送送料</th><td>{R.shippingFee}</td></tr>
              <tr><th>返金</th><td>{R.refund}</td></tr>
            </tbody>
          </table>
          <p style={{ marginTop: 16 }}>
            <SubmitButton pending="申請しています…">返品を申請する</SubmitButton>
          </p>
          <p><Link href={back}>申請せずに注文の詳細に戻る</Link></p>
        </form>
      )}
    </main>
  );
}
