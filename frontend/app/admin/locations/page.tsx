// SCR-B15 拠点管理（AP-B04・F-809）。R-30。
//
// ★拠点ごとの「EC販売可」と「一時停止」を切り替える（BR-05c の①③）。
// ★倉庫は EC販売可を外せない（要件 F-806）。ボタンを出さず、APIも断る（ERR-1004）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { listLocations } from "@/lib/api/catalog";
import { toggleLocationAction } from "@/lib/actions/catalog";
import { ROLE_LABEL, errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function LocationsPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  let me, locs;
  try {
    me = (await adminMe()).data;
    locs = (await listLocations()).data.locations;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">拠点管理</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }
  const canEdit = me.role === 1;   // ★表示の出し分けだけ。判定は API（2.4 F-809：運用管理者だけ可）
  const confirmCode = one(sp.confirm);
  const confirmLoc = canEdit && confirmCode ? locs.find((l) => l.location_code === confirmCode && l.kind === 1 && !l.suspended) : undefined;

  return (
    <main className="wrap">
      <h1 className="h1">拠点管理</h1>
      <p className="note">{me.name}（{ROLE_LABEL[me.role]}）{canEdit ? "" : " ／ 参照のみ"}</p>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}
      <p className="note">
        ★ECの出荷元になれるのは「EC販売可」で「一時停止していない」拠点だけ（BR-05c）。商品ごとに外したいときは、
        <Link href="/admin/products">商品</Link>の画面の「EC販売（拠点ごと）」で切り替えます。
        売れ残りを探すときは <Link href="/admin/stocks/stagnant">滞留在庫</Link>。
      </p>
      {canEdit ? <p><Link className="btn sub" href="/admin/locations/new">拠点を登録する</Link></p> : null}

      {/* ★倉庫を止める前に、もう一度押させる（R-30 の回答3・GU調査 3.3「取り返せない押し間違いには確認を挟む」） */}
      {confirmLoc ? (
        <div className="cancelbox" role="alertdialog" aria-labelledby="stopwh">
          <p id="stopwh"><strong>{confirmLoc.name}（{confirmLoc.location_code}）を一時停止しますか？</strong></p>
          <p className="err">この拠点を止めると、ECで買える商品がほとんど無くなります。</p>
          <form action={toggleLocationAction} className="inline" style={{ marginLeft: 0 }}>
            <input type="hidden" name="location_code" value={confirmLoc.location_code} />
            <input type="hidden" name="field" value="suspended" />
            <input type="hidden" name="to" value="1" />
            <button type="submit" className="btn">それでも一時停止にする</button>
          </form>{" "}
          <Link href="/admin/locations" className="btn sub">やめる</Link>
        </div>
      ) : null}

      <table className="orders">
        <thead><tr><th>拠点</th><th>区分</th><th>締め時刻</th><th>EC販売</th><th>一時停止</th></tr></thead>
        <tbody>
          {locs.map((l) => {
            const ec = Boolean(l.ec_saleable); const sus = Boolean(l.suspended); const wh = l.kind === 1;
            return (
              <tr key={l.location_code}>
                <td><Link href={`/admin/locations/${encodeURIComponent(l.location_code)}`}><code>{l.location_code}</code> {l.name}</Link></td>
                <td>{wh ? "倉庫" : "店舗"}</td>
                <td>{l.cutoff_time}</td>
                <td>
                  <span className={`badge ${ec ? "in" : "out"}`}>{ec ? "可" : "不可"}</span>{" "}
                  {canEdit && !wh ? (
                    <form action={toggleLocationAction} className="inline">
                      <input type="hidden" name="location_code" value={l.location_code} />
                      <input type="hidden" name="field" value="ec_saleable" />
                      <input type="hidden" name="to" value={ec ? "0" : "1"} />
                      <button type="submit" className="mini">{ec ? "不可にする" : "可にする"}</button>
                    </form>
                  ) : wh ? <small className="note">倉庫は固定</small> : null}
                </td>
                <td>
                  <span className={`badge ${sus ? "out" : "in"}`}>{sus ? "停止中" : "営業中"}</span>{" "}
                  {canEdit && wh && !sus ? (
                    // ★倉庫を止めるときだけ、いったん確認を出す（押しただけでは止めない）
                    <Link href={`/admin/locations?confirm=${encodeURIComponent(l.location_code)}`} className="mini">一時停止にする</Link>
                  ) : canEdit ? (
                    <form action={toggleLocationAction} className="inline">
                      <input type="hidden" name="location_code" value={l.location_code} />
                      <input type="hidden" name="field" value="suspended" />
                      <input type="hidden" name="to" value={sus ? "0" : "1"} />
                      <button type="submit" className="mini">{sus ? "再開する" : "一時停止にする"}</button>
                    </form>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </main>
  );
}
