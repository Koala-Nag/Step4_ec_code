// SCR-13 注文詳細（AP-305。串の⑩）。★状態と追跡番号が出る。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError, getMyOrder } from "@/lib/api/client";
import { cancelMyOrderAction, repayAction } from "@/lib/actions/order";
import { SubmitButton } from "@/app/submit-button";
import { yen } from "@/lib/view/format";
import { orderStatusLabel, shipmentStatusLabel } from "@/lib/view/order-status";
import { RETURN_POLICY as R } from "@/lib/view/returns";

export const dynamic = "force-dynamic";

export default async function OrderDetailPage({
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
    // ★会員でもなく、照会も通っていない → 照会画面へ（ゲストはここから入り直す。F-313）
    if (e instanceof ApiError && e.status === 401) redirect(`/orders/lookup?order_no=${encodeURIComponent(no)}`);
    // ★他人の注文も「無い」と同じ 404（8.2）。403 にすると在ることを教えてしまう
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  return (
    <main className="wrap">
      <p className="crumb">
        {o.viewer === "guest" ? <Link href="/orders/lookup">ご注文の照会</Link> : <Link href="/orders">購入履歴</Link>} ／ {o.order_no}
      </p>
      <h1 className="h1">
        <code>{o.order_no}</code> <span className="badge">{orderStatusLabel(o.status)}</span>
      </h1>
      {/* ★支払い待ち（与信NG）なら、ここからお支払い方法を変えて再度手続きできる（F-314）。
          ★MSG-03 のメールもこの画面を指している。押せる入口が無いと、メールの案内が行き止まりになる */}
      {o.repayable ? (
        <form action={repayAction} className="cancelbox" style={{ marginTop: 0, marginBottom: 16 }}>
          <input type="hidden" name="order_no" value={o.order_no} />
          <p style={{ margin: "0 0 8px" }}><strong>お支払いを確認できませんでした。</strong>お支払い方法を変えて、もう一度お手続きください。</p>
          <SubmitButton pending="決済の画面へ移動しています…">お支払い手続きへ進む</SubmitButton>
        </form>
      ) : null}
      {sp.cancelled ? (
        <p className="ok">ご注文をキャンセルしました。代金は請求されません。確認のメールをお送りしました。</p>
      ) : null}
      {err === "ERR-1205" ? (
        // ★ボタンを出したあとで発送の準備に入った（IT-102）。押せたのに黙って失敗させない
        <p className="err">発送の準備に入ったため、キャンセルできませんでした。</p>
      ) : err ? (
        <p className="err">キャンセルできませんでした（{err}）</p>
      ) : null}

      <table className="orders">
        <thead><tr><th>商品</th><th>数量</th><th>単価</th></tr></thead>
        <tbody>
          {o.lines.map((l) => (
            <tr key={l.line_no}>
              <td>{l.product_name}<br /><small>{l.sku_code}</small></td>
              <td className="num">{l.qty}</td>
              <td className="num">{yen(l.unit_price)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <table className="sum">
        <tbody>
          <tr><th>商品合計</th><td className="num">{yen(o.item_total)}</td></tr>
          <tr><th>送料</th><td className="num">{yen(o.shipping_fee)}</td></tr>
          <tr className="total"><th>支払総額</th><td className="num">{yen(o.total_amount)}</td></tr>
          <tr><th>（うち消費税）</th><td className="num">{yen(o.tax_amount)}</td></tr>
        </tbody>
      </table>

      <h2 className="h2">お届け先</h2>
      {/* ★注文したときの住所をそのまま出す（FR-401・AT-113）。
          ★あとで住所帳を直しても、この注文の届け先は変わらない */}
      <table className="sum info">
        <tbody>
          <tr><th>お名前</th><td>{o.ship_to.name}</td></tr>
          <tr><th>郵便番号</th><td>〒{o.ship_to.zip}</td></tr>
          <tr><th>ご住所</th><td>{o.ship_to.address}</td></tr>
          <tr><th>お電話</th><td>{o.ship_to.tel}</td></tr>
        </tbody>
      </table>

      <h2 className="h2">お届けの状況</h2>
      {o.shipments.length === 0 ? (
        <p className="note">発送の準備ができ次第、こちらに表示されます。</p>
      ) : (
        <table className="orders">
          <thead>
            <tr><th>状態</th><th>発送予定日</th><th>配送会社</th><th>追跡番号</th></tr>
          </thead>
          <tbody>
            {o.shipments.map((s) => (
              <tr key={s.id}>
                <td><span className="badge">{shipmentStatusLabel(s.status)}</span></td>
                <td>{s.planned_ship_date}</td>
                <td>{s.carrier ?? "—"}</td>
                {/* ★取り置きは追跡番号が空（E-24）。空欄ではなく理由を出す */}
                <td>{s.tracking_no ?? (s.dest_kind === 2 ? "店舗でのお受け取り" : "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* ★返品の条件（F-501）。静的ページと同じ文言（lib/view/returns.ts）。注文によって変わらない（設計 6.5） */}
      <h2 className="h2">返品について</h2>
      <table className="sum policy">
        <tbody>
          <tr><th>期限</th><td>{R.deadline}<br /><small>{R.deadlineNote}</small></td></tr>
          <tr><th>条件</th><td>{R.condition}</td></tr>
          <tr><th>返送先</th><td>{R.destination}</td></tr>
          <tr><th>返送送料</th><td>{R.shippingFee}</td></tr>
        </tbody>
      </table>
      <p className="note"><Link href="/about/returns">返品について（くわしく）</Link></p>

      {/* ★返品の申請（F-502）と状態（F-507）。R-31。
          ★ボタンを出す条件はサーバの can_apply（期限と届いた数。BR-18）。画面で期限を計算しない */}
      {o.returns.length > 0 ? (
        <table className="orders">
          <thead><tr><th>返品</th><th>申請日</th><th>数</th><th>状態</th></tr></thead>
          <tbody>
            {o.returns.map((x) => (
              <tr key={x.return_no}>
                <td><Link href={`/orders/${encodeURIComponent(o.order_no)}/returns/${encodeURIComponent(x.return_no)}`}>{x.return_no}</Link></td>
                <td>{x.applied_at.slice(0, 16)}</td>
                <td className="num">{x.qty}</td>
                <td><span className="badge">{x.status_label}</span>{x.refund_total !== null ? <><br /><small>返金 {yen(x.refund_total)}</small></> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {o.returnable.can_apply ? (
        <p style={{ marginTop: 8 }}>
          <Link className="btn sub" href={`/orders/${encodeURIComponent(o.order_no)}/return`}>返品を申請する</Link>
        </p>
      ) : o.shipments.some((s) => s.status >= 2 && s.status <= 5) ? (
        <p className="note">返品を申請できる商品はありません（期限を過ぎたか、すべて申請済みです）。</p>
      ) : null}

      {/* ★出荷指示が出たらキャンセルは消える（BR-17f）。判定はサーバ */}
      {o.cancellable ? (
        <form action={cancelMyOrderAction} className="cancelbox">
          <input type="hidden" name="order_no" value={o.order_no} />
          <p className="note">この注文はまだキャンセルできます（発送の準備に入るまで）。</p>
          <button type="submit" className="btn sub">この注文をキャンセルする</button>
        </form>
      ) : o.status === 11 ? null : (
        <p className="note">発送の準備に入ったため、キャンセルはできません。</p>
      )}
    </main>
  );
}
