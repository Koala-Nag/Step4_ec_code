// AP-B19 出荷一覧 ＋ AP-B20 発送の記録（F-805。串の⑧）。
//
// ★自拠点のぶんしか出ない。画面が絞っているのではなく、APIが拠点の引数を持たない（N-28a）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminListShipments, adminMe } from "@/lib/api/client";
import { shipAction, shortageAction } from "@/lib/actions/admin";
import { shipmentStatusLabel } from "@/lib/view/order-status";

export const dynamic = "force-dynamic";

const INSTRUCTED = 1;
const DEST_STORE = 2;

export default async function AdminShipmentsPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;
  const orderNo = (Array.isArray(sp.order_no) ? sp.order_no[0] : sp.order_no) || undefined;

  let me, res;
  try {
    me = (await adminMe()).data;
    res = (await adminListShipments(orderNo)).data;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      redirect("/admin/login");
    }
    throw e;
  }

  return (
    <main className="wrap">
      <h1 className="h1">出荷一覧</h1>
      <p className="note">
        {me.name}（役割 {me.role}） ／ 表示範囲：
        {/* ★`all` は内部の値。人が読む場所に内部の呼び名を出さない（5.4 と同じ・R-23） */}
        <strong>{res.scope === "all" ? "全拠点" : res.scope}</strong>
        {res.scope !== "all" ? "（自拠点のみ。N-28a）" : ""}
      </p>
      {sp.instructed ? <p className="ok">出荷指示を作りました。</p> : null}
      {orderNo ? <p className="note">注文 <code>{orderNo}</code> の出荷だけ表示しています。<Link href="/admin/shipments">すべての出荷を見る</Link></p> : null}

      {/* ★注文番号で絞る（R-34）。出荷がたまると一覧は件数で切れるので、探せる口を置く */}
      <form method="get" action="/admin/shipments" className="rowform" style={{ margin: "8px 0 16px" }}>
        <input name="order_no" placeholder="注文番号で絞る" defaultValue={orderNo ?? ""} aria-label="注文番号" />
        <button type="submit" className="btn sub">絞り込む</button>
        {orderNo ? <Link href="/admin/shipments" className="mini">絞り込みを外す</Link> : null}
      </form>
      {sp.shipped ? <p className="ok">発送を記録しました。</p> : null}
      {sp.short ? <p className="ok">欠品を報告しました。受注担当が再引当かキャンセルを判断します。</p> : null}
      {err ? <p className="err">記録できませんでした（{err}）</p> : null}

      <table className="orders">
        <thead>
          <tr>
            <th>出荷</th><th>注文番号</th><th>届け先</th><th>発送予定日</th>
            <th>状態</th><th>発送の記録</th>
          </tr>
        </thead>
        <tbody>
          {res.shipments.map((s) => (
            <tr key={s.id}>
              <td>#{s.id}<br /><small>{s.from_location_code}</small></td>
              <td><code>{s.order_no}</code></td>
              <td>
                {s.dest_name}
                <br />
                <small>
                  {s.dest_kind === DEST_STORE ? "受取店（BR-08b）" : "客の住所"}
                  ／ {s.dest_zip}
                </small>
              </td>
              <td>{s.planned_ship_date}</td>
              <td>
                <span className="badge">{shipmentStatusLabel(s.status)}</span>
                {s.tracking_no ? <><br /><small>{s.tracking_no}</small></> : null}
              </td>
              <td>
                {s.status === INSTRUCTED ? (
                  <form action={shipAction} className="shipform">
                    <input type="hidden" name="shipment_id" value={s.id} />
                    <input name="carrier" placeholder="配送会社" defaultValue="ヤマト運輸" />
                    {/* ★客の住所宛は追跡番号が必須、取り置きは空でよい（E-24） */}
                    <input
                      name="tracking_no"
                      placeholder={s.dest_kind === DEST_STORE ? "（取り置きは空でよい）" : "追跡番号"}
                      required={s.dest_kind !== DEST_STORE}
                    />
                    {/* ★拠点のアカウントは共有。誰がやったかは手入力に頼る（2.4） */}
                    <input name="staff_name" placeholder="担当者名" required />
                    <button type="submit" className="mini">発送を記録</button>
                  </form>
                ) : null}
                {s.status === INSTRUCTED ? (
                  // AP-B21 欠品の報告（F-805・BR-04a）。
                  // ★棚で見つからなかったとき。明細ごとに実在庫数を入れる。担当者と理由を残す
                  <details className="shortbox">
                    <summary>棚に無い（欠品を報告）</summary>
                    <form action={shortageAction} className="shipform">
                      <input type="hidden" name="shipment_id" value={s.id} />
                      {s.lines.map((l) => (
                        <label key={l.line_no} className="shortline">
                          <input type="hidden" name="line_no" value={l.line_no} />
                          {l.product_name}（{l.sku_code}）× {l.qty} ／ 実在庫数
                          <input type="number" name={`actual_${l.line_no}`} min={0}
                                 defaultValue={0} required />
                        </label>
                      ))}
                      <input name="staff_name" placeholder="担当者名" required />
                      <input name="reason" placeholder="理由（例：棚に見当たらない）" required />
                      <button type="submit" className="mini">欠品を報告</button>
                    </form>
                  </details>
                ) : (
                  <span className="can">{s.staff_name ? `${s.staff_name} が記録` : "—"}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
