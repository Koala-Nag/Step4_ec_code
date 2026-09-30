// AP-B06 在庫一覧（F-801・AT-208）。
//
// ★倉庫と各店舗の「在庫数・引当済数・販売可能数」の3つを出す。
//   ★販売可能数はサーバが計算して返す（引き算を画面でやらない。N-35 と同じ考え方）。
// ★自拠点のみの役割には、拠点を指定する引数がそもそも無い（N-28a）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminListStocks, adminMe } from "@/lib/api/client";

export const dynamic = "force-dynamic";

export default async function AdminStocksPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const sku = Array.isArray(sp.sku) ? sp.sku[0] : sp.sku;

  let me, res;
  try {
    me = (await adminMe()).data;
    res = (await adminListStocks(sku)).data;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      redirect("/admin/login");
    }
    throw e;
  }

  return (
    <main className="wrap">
      <h1 className="h1">在庫一覧</h1>
      <p className="note"><Link href="/admin/stocks/stagnant">滞留在庫を抽出する（最終EC出荷日から60日以上・3点以上）</Link></p>
      <p className="note">
        {me.name}（役割 {me.role}） ／ 表示範囲：
        <strong>{res.scope === "all" ? "全拠点" : res.scope}</strong>
        {res.scope !== "all" ? "（自拠点のみ。N-28a）" : ""}
      </p>

      <form method="get" className="form" style={{ maxWidth: 320 }}>
        <label>
          SKUコードで絞る
          <input name="sku" defaultValue={sku ?? ""} placeholder="P0001-BK-M" />
        </label>
        <button type="submit" className="mini">絞る</button>
      </form>

      <table className="orders">
        <thead>
          <tr>
            <th>拠点</th><th>SKU</th><th>区分</th>
            <th>在庫数</th><th>引当済数</th><th>販売可能数</th>
          </tr>
        </thead>
        <tbody>
          {res.stocks.map((s) => (
            <tr key={`${s.location_code}-${s.sku_code}-${s.section}`}>
              <td>{s.location_code}</td>
              <td><code>{s.sku_code}</code></td>
              {/* stock.section 1=バックヤード 2=店頭（BR-01） */}
              <td>{s.section === 1 ? "バックヤード" : "店頭"}</td>
              <td className="num">{s.qty}</td>
              <td className="num">{s.reserved_qty}</td>
              {/* ★ECで売れるのはこの数（BR-01）。0 なら品切れとして扱う */}
              <td className="num"><strong>{s.saleable_qty}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
