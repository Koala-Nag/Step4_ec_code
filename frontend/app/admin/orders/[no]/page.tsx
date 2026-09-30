// SCR-B05 注文詳細（AP-B11）＋ キャンセル（B14）・再引当（B15）・部分キャンセルと返金（B16）。R-26。
//
// ★どのボタンを出すかはサーバの `actions` に従う。API が受ける条件と同じ関数から取っている（IT-101・102）。
// ★金額も「取消か返金か」も画面では決めない。押したあとにサーバが返した結果を出すだけ（BR-17d・N-35）。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError, adminGetOrder, adminMe } from "@/lib/api/client";
import {
  addMemoAction,
  adminCancelAction,
  partialCancelAction,
  reallocateAction,
} from "@/lib/actions/admin";
import { yen } from "@/lib/view/format";
import { orderStatusLabel } from "@/lib/view/order-status";

export const dynamic = "force-dynamic";

// 運営の言葉（要件 5.3）。★客の言葉（order-status.ts）とは別
const ORDER_STATUS_ADMIN: Record<number, string> = {
  1: "認証中", 2: "与信中", 3: "支払い待ち", 4: "引当中", 5: "引当済", 6: "出荷指示済",
  7: "欠品保留", 8: "一部出荷済", 9: "出荷済", 10: "完了", 11: "キャンセル済",
};
const SHIPMENT_STATUS_ADMIN: Record<number, string> = {
  1: "指示済", 2: "出荷済", 3: "到着済", 4: "店舗到着", 5: "引渡済", 6: "欠品", 7: "キャンセル",
};
const TX_KIND: Record<number, string> = {
  1: "認証", 2: "与信", 3: "売上確定", 4: "返金", 5: "取消", 6: "照会", 7: "与信不要",
};
const TX_STATUS: Record<number, string> = {
  1: "成功", 2: "失敗", 3: "処理中", 4: "要実行", 5: "実行中", 6: "取消不要",
};
const ALLOC: Record<number, string> = { 0: "未引当", 1: "引当済", 2: "解放済" };

export default async function AdminOrderDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ no: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { no } = await params;
  const sp = await searchParams;
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k]![0] : (sp[k] as string | undefined));

  let me, o;
  try {
    me = (await adminMe()).data;
    o = (await adminGetOrder(no)).data;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  const shorts = o.shipments.filter((s) => s.status === 6);

  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/admin/orders">注文一覧</Link> ／ {o.order_no}
      </p>
      <h1 className="h1">
        <code>{o.order_no}</code>{" "}
        <span className="badge">{ORDER_STATUS_ADMIN[o.status] ?? o.status}</span>
      </h1>
      <p className="note">
        {me.name}（役割 {me.role}） ／ 客に見える表示：「{orderStatusLabel(o.status)}」
      </p>

      {one("cancelled") ? <p className="ok">注文をキャンセルしました（引当を解放し、与信の取消を積みました。MSG-07）。</p> : null}
      {one("realloc") ? <p className="ok">他の拠点に引き当て直し、新しい出荷を作りました（出荷指示済へ）。</p> : null}
      {one("realloc_ng") ? <p className="err">再引当できませんでした：{one("realloc_ng")}。部分キャンセルと返金を選んでください。</p> : null}
      {one("partial") !== undefined ? <p className="ok">欠品分を取り消しました。お返しする金額 {yen(Number(one("partial")))}（MSG-05 の続報を積みました）。</p> : null}
      {one("memo") ? <p className="ok">対応メモを残しました。</p> : null}
      {one("err") ? <p className="err">この操作は行えませんでした（{one("err")}）</p> : null}

      {shorts.length > 0 ? (
        <>
          <h2 className="h2">★欠品の報告があります</h2>
          <table className="orders">
            <thead><tr><th>出荷</th><th>拠点</th><th>明細</th><th>実在庫数</th><th>報告者</th><th>報告日時</th></tr></thead>
            <tbody>
              {shorts.map((s) => (
                <tr key={s.id}>
                  <td>#{s.id}</td><td>{s.from_location_code}</td>
                  <td>{s.line_nos.join("・")}</td>
                  <td className="num">{s.short_actual_qty ?? "—"}</td>
                  <td>{s.short_reporter ?? "—"}</td>
                  <td>{s.short_at?.slice(0, 16) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}

      <div className="actions">
        {o.actions.reallocate ? (
          <form action={reallocateAction}>
            <input type="hidden" name="order_no" value={o.order_no} />
            <p className="note"><strong>再引当</strong>（F-912）｜欠品の明細を他の拠点から出す</p>
            <button type="submit" className="btn sub">他の拠点に引き当て直す</button>
          </form>
        ) : null}
        {o.actions.partial_cancel ? (
          <form action={partialCancelAction}>
            <input type="hidden" name="order_no" value={o.order_no} />
            <p className="note">
              <strong>部分キャンセルと返金</strong>（F-911）｜欠品の明細を取り消す。
              金額と「取消か返金か」はサーバが決める（BR-21a・BR-17d）
            </p>
            <button type="submit" className="btn sub">欠品分を取り消して返金する</button>
          </form>
        ) : null}
        {o.actions.cancel ? (
          <form action={adminCancelAction}>
            <input type="hidden" name="order_no" value={o.order_no} />
            <p className="note"><strong>注文のキャンセル</strong>（F-904）｜出荷指示の前だけ（BR-17f）</p>
            <button type="submit" className="btn sub">この注文をキャンセルする</button>
          </form>
        ) : null}
      </div>

      {/* ★対応メモ（F-908）。追記だけ（直さない・消さない）。書けるかはサーバが返す（2.4） */}
      <h2 className="h2">対応メモ</h2>
      {o.can_add_memo ? (
        <form action={addMemoAction} className="memoform">
          <input type="hidden" name="order_no" value={o.order_no} />
          <textarea name="body" rows={3} maxLength={500} required placeholder="対応の内容（500文字まで）" />
          <button type="submit" className="btn sub">メモを残す</button>
        </form>
      ) : null}
      {o.memos.length === 0 ? (
        <p className="note">まだ対応メモはありません。</p>
      ) : (
        <ul className="memos">
          {o.memos.map((m) => (
            <li key={m.id}>
              <small>{m.at.slice(0, 16)}　{m.operator_name ?? m.operator_id}</small>
              <p>{m.body}</p>
            </li>
          ))}
        </ul>
      )}

      <h2 className="h2">明細</h2>
      <table className="orders">
        <thead><tr><th>行</th><th>商品</th><th>数量</th><th>単価</th><th>割引の按分</th><th>引当</th></tr></thead>
        <tbody>
          {o.lines.map((l) => (
            <tr key={l.line_no}>
              <td>{l.line_no}</td>
              <td>{l.product_name}<br /><small>{l.sku_code}</small></td>
              <td className="num">{l.qty}</td>
              <td className="num">{yen(l.unit_price)}</td>
              <td className="num">{yen(l.allocated_discount)}</td>
              <td>{ALLOC[l.alloc_status] ?? l.alloc_status}{l.alloc_location_code ? ` ／ ${l.alloc_location_code}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <table className="sum">
        <tbody>
          <tr><th>商品合計</th><td className="num">{yen(o.item_total)}</td></tr>
          <tr><th>割引</th><td className="num">−{yen(o.discount_amount)}</td></tr>
          <tr><th>送料</th><td className="num">{yen(o.shipping_fee)}</td></tr>
          <tr className="total"><th>支払総額</th><td className="num">{yen(o.total_amount)}</td></tr>
        </tbody>
      </table>

      <h2 className="h2">出荷</h2>
      <table className="orders">
        <thead><tr><th>出荷</th><th>拠点</th><th>状態</th><th>明細</th><th>発送予定日</th><th>追跡番号</th></tr></thead>
        <tbody>
          {o.shipments.map((s) => (
            <tr key={s.id}>
              <td>#{s.id}</td><td>{s.from_location_code}</td>
              <td><span className="badge">{SHIPMENT_STATUS_ADMIN[s.status] ?? s.status}</span></td>
              <td>{s.line_nos.join("・")}</td>
              <td>{s.planned_ship_date}</td>
              <td>{s.tracking_no ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="h2">決済取引</h2>
      <table className="orders">
        <thead><tr><th>種別</th><th>状態</th><th>金額</th><th>出荷</th><th>応答</th></tr></thead>
        <tbody>
          {o.payments.map((p, i) => (
            <tr key={i}>
              <td>{TX_KIND[p.tx_kind] ?? p.tx_kind}</td>
              <td>{TX_STATUS[p.status] ?? p.status}</td>
              <td className="num">{yen(p.amount)}</td>
              <td>{p.shipment_id ? `#${p.shipment_id}` : "—"}</td>
              <td><small>{p.response_code ?? "—"}</small></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="h2">状態の履歴</h2>
      <table className="orders">
        <thead><tr><th>日時</th><th>変化</th><th>理由</th></tr></thead>
        <tbody>
          {o.status_log.map((l, i) => (
            <tr key={i}>
              <td>{l.at.slice(0, 19)}</td>
              <td>{l.from ? ORDER_STATUS_ADMIN[l.from] : "—"} → {ORDER_STATUS_ADMIN[l.to]}</td>
              <td><small>{l.reason ?? ""}</small></td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
