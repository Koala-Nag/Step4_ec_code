// SCR-B03 在庫一覧の中の「滞留在庫の抽出」（AP-B09・F-807）。R-30。
//
// ★要件 F-807「最終販売日から60日以上経過し、在庫数が3点以上ある拠点別SKU」。条件は画面から変えさせない。
// ★抽出したあとの使い道（値下げ・EC販売可への切替）は MD の判断。ここから EC販売可に切り替えられる（目的①の運用）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { getStagnant } from "@/lib/api/catalog";
import { exclusionAction, toggleLocationAction } from "@/lib/actions/catalog";
import { ROLE_LABEL, errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function StagnantPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  let me, d;
  try {
    me = (await adminMe()).data;
    d = (await getStagnant()).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">滞留在庫</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }
  const back = "/admin/stocks/stagnant";

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/admin/stocks">在庫一覧</Link> ／ 滞留在庫</p>
      <h1 className="h1">滞留在庫</h1>
      <p className="note">{me.name}（{ROLE_LABEL[me.role]}）／ 条件：最終EC出荷日から <strong>{d.days}日以上</strong>・在庫 <strong>{d.min_qty}点以上</strong>（バックヤード）／ {d.rows.length}件</p>
      {/* ★R-30 回答①：何を見ているかを名前で言う。POS は取り込んでいない（範囲外） */}
      <p className="note">★「最終EC出荷日」はECで出荷した日です。店頭での販売は含みません。</p>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}

      {d.rows.length === 0 ? (
        <p className="empty">条件に当てはまる在庫はありません。</p>
      ) : (
        <table className="orders">
          <thead>
            <tr><th>拠点</th><th>商品・SKU</th><th>在庫</th><th>最終EC出荷日</th><th>いまECで</th><th>ECに出す</th></tr>
          </thead>
          <tbody>
            {d.rows.map((r) => (
              <tr key={`${r.location_code}-${r.sku_code}`}>
                <td><code>{r.location_code}</code> {r.location_name}</td>
                <td>{r.product_name}（{r.color_name} / {r.size_name}）<br /><small><Link href={`/admin/products/${r.product_code}`}>{r.sku_code}</Link></small></td>
                <td className="num">{r.qty}{r.reserved_qty ? <><br /><small>引当 {r.reserved_qty}</small></> : null}</td>
                <td>{r.last_sold_at}<br /><small>{r.days}日前</small></td>
                <td>
                  <span className={`badge ${r.sellable_on_ec ? "in" : "out"}`}>{r.sellable_on_ec ? "売れる" : "売れない"}</span>
                  <br />
                  <small>{!r.ec_saleable ? "拠点がEC販売不可" : r.suspended ? "拠点が一時停止中" : r.excluded ? "この商品はこの拠点で除外" : ""}</small>
                </td>
                <td>
                  {/* ★理由ごとに次の操作が違う。BR-05c の3条件のどれで止まっているか */}
                  {!r.ec_saleable && d.can_switch_location ? (
                    <form action={toggleLocationAction}>
                      <input type="hidden" name="location_code" value={r.location_code} />
                      <input type="hidden" name="field" value="ec_saleable" />
                      <input type="hidden" name="to" value="1" />
                      <input type="hidden" name="back" value={back} />
                      <button type="submit" className="mini">この拠点をEC販売可にする</button>
                    </form>
                  ) : r.excluded && d.can_switch_exclusion ? (
                    <form action={exclusionAction}>
                      <input type="hidden" name="product_code" value={r.product_code} />
                      <input type="hidden" name="location_code" value={r.location_code} />
                      <input type="hidden" name="to" value="include" />
                      <input type="hidden" name="back" value={back} />
                      <button type="submit" className="mini">この商品の除外を外す</button>
                    </form>
                  ) : r.suspended ? (
                    <Link href="/admin/locations">拠点管理へ</Link>
                  ) : r.sellable_on_ec ? (
                    <span className="can">EC販売中</span>
                  ) : (
                    <span className="can">参照のみ</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
