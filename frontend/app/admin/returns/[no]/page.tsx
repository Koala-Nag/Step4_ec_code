// SCR-B10 返品受付｜詳細（AP-B24〜B30。F-503a〜e・F-504）。R-31。
//
// ★設計「SCR-B10 は、この5つの状態を1画面で進める」。
// ★どのボタンを出すかは API の can（役割 × 状態）。★出すのは親切で、判定は各 POST が自分でする（4.1.2）。
// ★返金額は画面で計算しない。API の refund_preview（保存済みの按分から計算）を出して、押させる。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { adminGetReturn } from "@/lib/api/returns";
import {
  approveReturnAction, disposalReturnAction, inspectReturnAction, receiveReturnAction,
  refundReturnAction, rejectReturnAction, restockReturnAction,
} from "@/lib/actions/returns";
import { SubmitButton } from "@/app/submit-button";
import { ROLE_LABEL, errText, one } from "@/lib/view/admin-labels";
import { yen } from "@/lib/view/format";

export const dynamic = "force-dynamic";

const STEPS: [number, string][] = [[1, "申請中"], [3, "返送待ち"], [4, "受領"], [5, "検品済"], [6, "返金済"]];

export default async function AdminReturnPage({
  params,
  searchParams,
}: {
  params: Promise<{ no: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { no } = await params;
  const sp = await searchParams;
  let me, r;
  try {
    me = (await adminMe()).data;
    r = (await adminGetReturn(no)).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 404) notFound();
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">返品受付</h1><p className="err">{errText(e.code)}</p></main>;
    }
    throw e;
  }
  const hidden = <input type="hidden" name="return_no" value={r.return_no} />;
  const uninspected = r.lines.filter((l) => l.inspect_result === null);
  const failedOpen = r.lines.filter((l) => l.inspect_result === 2 && l.disposal === null);

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/admin/returns">返品受付</Link> ／ {r.return_no}</p>
      <h1 className="h1"><code>{r.return_no}</code> <span className="badge">{r.status_label}</span></h1>
      <p className="note">{me.name}（{ROLE_LABEL[me.role]}）</p>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}

      {r.status === 2 ? (
        <p className="err">却下しました。理由：{r.reject_reason}</p>
      ) : (
        <ol style={{ display: "flex", gap: 8, listStyle: "none", padding: 0, flexWrap: "wrap" }}>
          {STEPS.map(([s, label]) => (
            <li key={s} className={`badge ${r.status >= s ? "in" : "out"}`} aria-current={r.status === s ? "step" : undefined}>{label}</li>
          ))}
        </ol>
      )}

      <table className="sum info">
        <tbody>
          <tr><th>注文番号</th><td><code>{r.order_no}</code></td></tr>
          <tr><th>お客様</th><td>{r.orderer_name}{r.orderer_email ? <><br /><small>{r.orderer_email}</small></> : null}</td></tr>
          <tr><th>申請日時</th><td>{r.applied_at.slice(0, 16)}</td></tr>
          <tr><th>返送先</th><td>{r.warehouse.name}（BR-19。出荷元にかかわらず倉庫）</td></tr>
          {r.decided_at ? <tr><th>承認・却下</th><td>{r.decided_at.slice(0, 16)}</td></tr> : null}
          {r.return_deadline ? <tr><th>返送期限</th><td>{r.return_deadline}／送料：{r.return_fee_bearer_label}の負担</td></tr> : null}
          {r.received_at ? <tr><th>受領</th><td>{r.received_at.slice(0, 16)}（{r.receiver}）</td></tr> : null}
          {r.refunded_at ? <tr><th>返金</th><td>{yen(r.refund_total)}{r.shipping_refund ? `（うち送料 ${yen(r.shipping_refund)}）` : ""} ／ {r.refunded_at.slice(0, 16)}</td></tr> : null}
        </tbody>
      </table>

      <h2 className="h2">明細</h2>
      <table className="orders">
        <thead><tr><th>商品</th><th>返品数</th><th>理由</th><th>検品</th><th>在庫・処分</th>{r.status === 6 ? <th>返金額</th> : null}</tr></thead>
        <tbody>
          {r.lines.map((l) => (
            <tr key={l.line_no}>
              <td>{l.product_name}（{l.color_name} / {l.size_name}）<br /><small>行{l.line_no} {l.sku_code} ／ 注文 {l.line_qty}点 × {yen(l.unit_price)}</small></td>
              <td className="num">{l.qty}</td>
              <td>{l.reason}{l.reason_text ? <><br /><small>{l.reason_text}</small></> : null}</td>
              <td>
                {l.inspect_result === null ? "未" : (
                  <><span className={`badge ${l.inspect_result === 1 ? "in" : "out"}`}>{l.inspect_result === 1 ? "合格" : "不合格"}</span>
                    {l.inspect_note ? <><br /><small>{l.inspect_note}</small></> : null}
                    <br /><small>{l.inspector}</small></>
                )}
              </td>
              <td>
                {l.inspect_result === 1 ? (l.restocked_at ? `倉庫の在庫に戻した（${l.restocker}）` : "まだ在庫に戻していない") : null}
                {l.inspect_result === 2 ? (l.disposal_label ?? "扱い未定") : null}
              </td>
              {r.status === 6 ? <td className="num">{yen(l.refund_amount)}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>

      {/* ---------------- F-503a 承認・却下（サポート）---------------- */}
      {r.can.approve ? (
        <section className="cancelbox">
          <h2 className="h2" style={{ marginTop: 0 }}>承認する</h2>
          <p className="note">★未使用・タグ付きかは人が判断します（BR-18a）。期限はシステムが確認済みです。</p>
          <form action={approveReturnAction}>
            {hidden}
            <fieldset>
              <legend>返送送料の負担（BR-20）</legend>
              <label><input type="radio" name="fee_bearer" value="customer" defaultChecked /> お客様（お客様のご都合）</label>{" "}
              <label><input type="radio" name="fee_bearer" value="company" /> 当店（不良・誤出荷）</label>
            </fieldset>
            <SubmitButton pending="承認しています…">承認して返送のご案内を送る</SubmitButton>
          </form>
          <form action={rejectReturnAction} style={{ marginTop: 12 }}>
            {hidden}
            <label>却下の理由（お客様にお送りします）<br />
              <textarea name="reason" rows={2} maxLength={200} style={{ width: "100%" }} />
            </label>
            <button type="submit" className="btn sub">却下する</button>
          </form>
        </section>
      ) : null}

      {/* ---------------- F-503b 受領（倉庫）---------------- */}
      {r.can.receive ? (
        <form action={receiveReturnAction} className="cancelbox">
          {hidden}
          <h2 className="h2" style={{ marginTop: 0 }}>返送品を受け取った</h2>
          <label>担当者名 <input name="staff_name" required maxLength={50} /></label>{" "}
          <SubmitButton pending="記録しています…">受領を記録する</SubmitButton>
        </form>
      ) : null}

      {/* ---------------- F-503c 検品（倉庫。明細ごと）---------------- */}
      {r.can.inspect && uninspected.length > 0 ? (
        <form action={inspectReturnAction} className="cancelbox">
          {hidden}
          <h2 className="h2" style={{ marginTop: 0 }}>検品の結果</h2>
          <p className="note">明細ごとに記録できます。すべての明細を記録すると「検品済」になります。不合格は理由が必要です。</p>
          <table className="orders">
            <tbody>
              {uninspected.map((l) => (
                <tr key={l.line_no}>
                  <td>行{l.line_no} {l.product_name}（{l.color_name} / {l.size_name}） {l.qty}点</td>
                  <td>
                    <label><input type="radio" name={`result_${l.line_no}`} value="pass" /> 合格</label>{" "}
                    <label><input type="radio" name={`result_${l.line_no}`} value="fail" /> 不合格</label>
                  </td>
                  <td><input name={`note_${l.line_no}`} placeholder="理由（不合格のとき必須）" maxLength={200} aria-label={`行${l.line_no} の理由`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <label>担当者名 <input name="staff_name" required maxLength={50} /></label>{" "}
          <SubmitButton pending="記録しています…">検品の結果を記録する</SubmitButton>
        </form>
      ) : null}

      {/* ---------------- F-504 在庫戻入（倉庫）---------------- */}
      {r.can.restock ? (
        <form action={restockReturnAction} className="cancelbox">
          {hidden}
          <h2 className="h2" style={{ marginTop: 0 }}>在庫に戻す</h2>
          <p className="note">検品に合格した商品を、{r.warehouse.name}のバックヤード在庫に戻します（BR-19・BR-22）。</p>
          <label>担当者名 <input name="staff_name" required maxLength={50} /></label>{" "}
          <SubmitButton pending="戻しています…">合格品を在庫に戻す</SubmitButton>
        </form>
      ) : null}

      {/* ---------------- F-503e 不合格品の処分指示（サポート）---------------- */}
      {r.can.disposal && failedOpen.length > 0 ? (
        <form action={disposalReturnAction} className="cancelbox">
          {hidden}
          <h2 className="h2" style={{ marginTop: 0 }}>不合格品の扱い</h2>
          {failedOpen.map((l) => (
            <p key={l.line_no}>
              行{l.line_no} {l.product_name}（{l.inspect_note}）：{" "}
              <label><input type="radio" name={`disposal_${l.line_no}`} value="return" /> お客様へ返送</label>{" "}
              <label><input type="radio" name={`disposal_${l.line_no}`} value="discard" /> 廃棄</label>
            </p>
          ))}
          <SubmitButton pending="記録しています…">扱いを記録する</SubmitButton>
        </form>
      ) : null}

      {/* ---------------- F-503d 返金（サポート）---------------- */}
      {r.can.refund && r.refund_preview ? (
        <form action={refundReturnAction} className="cancelbox">
          {hidden}
          <h2 className="h2" style={{ marginTop: 0 }}>返金する</h2>
          <table className="sum">
            <tbody>
              <tr><th>合格した商品</th><td className="num">{yen(r.refund_preview.items)}</td></tr>
              <tr><th>送料（全明細の返品のときだけ。BR-21b）</th><td className="num">{yen(r.refund_preview.shipping_refund)}</td></tr>
              <tr className="total"><th>返金額</th><td className="num">{yen(r.refund_preview.refund_total)}</td></tr>
            </tbody>
          </table>
          <p className="note">
            ★割引は注文のときに明細へ按分した額を差し引いています（BR-21）。これまでの返金 {yen(r.refund_preview.already_refunded)}。
            {r.refund_preview.capped ? "★支払総額を超えるため頭打ちにしています。" : ""}
            {r.refund_preview.refund_total === 0 ? "合格した商品が無いため、返金なしで手続きを閉じます。" : ""}
          </p>
          <SubmitButton pending="返金しています…">{r.refund_preview.refund_total > 0 ? `${yen(r.refund_preview.refund_total)} を返金する` : "返金なしで閉じる"}</SubmitButton>
        </form>
      ) : null}
    </main>
  );
}
