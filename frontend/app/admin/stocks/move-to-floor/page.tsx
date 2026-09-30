// SCR-B16 店頭への払い出し登録（AP-B08・F-808・AT-210）。
//
// ★店舗スタッフの「自拠点」だけ（2.4。運用管理者は参照）。拠点は選ばせない——ログインした店舗で決まる（N-28a）。
// ★引当済の数量は払い出せない。上限は販売可能数（qty − reserved_qty）。判定は API。
import { redirect } from "next/navigation";

import { ApiError, adminListStocks, adminMe } from "@/lib/api/client";
import { floorPage } from "@/lib/api/catalog";
import { moveToFloorAction } from "@/lib/actions/catalog";
import { ROLE_LABEL, errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function MoveToFloorPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const sku = one(sp.sku);
  let me, page, stocks;
  try {
    me = (await adminMe()).data;
    page = (await floorPage()).data;
    stocks = (await adminListStocks(sku)).data.stocks;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">店頭への払い出し</h1><p className="err">この操作は行えません（ERR-1102）。店頭への払い出しは店舗スタッフの操作です。</p></main>;
    }
    throw e;
  }
  const backyard = stocks.filter((s) => s.section === 1);
  const floor = new Map(stocks.filter((s) => s.section === 2).map((s) => [`${s.location_code}/${s.sku_code}`, s.qty]));

  return (
    <main className="wrap">
      <h1 className="h1">店頭への払い出し</h1>
      <p className="note">
        {me.name}（{ROLE_LABEL[me.role]}） ／ 表示範囲：<strong>{page.scope === "all" ? "全拠点" : page.scope}</strong>
        {page.can_move ? "" : " ／ 参照のみ"}
      </p>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}

      <form method="get" className="rowform" style={{ margin: "10px 0" }}>
        <input name="sku" defaultValue={sku ?? ""} placeholder="SKUコードで絞る（P0051-BK-M）" />
        <button type="submit" className="mini">絞る</button>
      </form>

      <table className="orders">
        <thead>
          <tr><th>SKU</th><th>バックヤード 在庫</th><th>引当済</th><th>払い出せる数（販売可能数）</th><th>店頭</th><th>払い出す</th></tr>
        </thead>
        <tbody>
          {backyard.map((s) => (
            <tr key={`${s.location_code}-${s.sku_code}`}>
              <td><code>{s.sku_code}</code><br /><small>{s.location_code}</small></td>
              <td className="num">{s.qty}</td>
              <td className="num">{s.reserved_qty}</td>
              <td className="num"><strong>{s.saleable_qty}</strong></td>
              <td className="num">{floor.get(`${s.location_code}/${s.sku_code}`) ?? 0}</td>
              <td>
                {page.can_move ? (
                  <form action={moveToFloorAction} className="rowform">
                    <input type="hidden" name="sku_code" value={s.sku_code} />
                    <input type="number" name="qty" min={1} defaultValue={1} style={{ width: 64 }} required />
                    {/* ★店舗のアカウントは共有。誰がやったかは手入力（2.4） */}
                    <input name="staff_name" placeholder="担当者名" required style={{ width: 110 }} />
                    <button type="submit" className="mini">店頭へ</button>
                  </form>
                ) : <span className="can">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="h2">最近の払い出し</h2>
      <table className="orders">
        <thead><tr><th>日時</th><th>拠点</th><th>SKU</th><th>店頭の数</th><th>担当者</th></tr></thead>
        <tbody>
          {page.history.map((h, i) => (
            <tr key={i}>
              <td>{h.created_at.slice(0, 19)}</td><td>{h.location_code}</td><td><code>{h.sku_code}</code></td>
              <td className="num">{h.qty_before} → {h.qty_after}</td><td>{h.staff_name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
