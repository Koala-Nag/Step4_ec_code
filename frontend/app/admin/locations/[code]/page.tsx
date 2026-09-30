// SCR-B15 拠点管理｜拠点の編集（AP-B04 PATCH・F-809）。R-32。
//
// ★締め時刻・営業曜日・休業日を変えると、これから作る出荷指示の発送予定日が変わる（BR-23）。
//   ★作ってある出荷の予定日は変えない（出荷指示の作成時に確定して保存してある）。
// ★拠点コードと区分は変えない（出荷・在庫・運営者が参照している）。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { getLocation } from "@/lib/api/promo";
import { editLocationAction, holidayAction } from "@/lib/actions/promo";
import { SubmitButton } from "@/app/submit-button";
import { errText, one } from "@/lib/view/admin-labels";
import { LOCATION_ERR, LocationFields } from "../location-form";

export const dynamic = "force-dynamic";

export default async function LocationEditPage({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { code } = await params;
  const sp = await searchParams;
  let d;
  try {
    d = (await getLocation(code)).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 404) notFound();
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">拠点</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }
  const f = one(sp.field);
  const ro = !d.can_edit;

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/admin/locations">拠点管理</Link> ／ {d.location_code}</p>
      <h1 className="h1"><code>{d.location_code}</code> {d.name} <span className="badge">{d.kind === 1 ? "倉庫" : "店舗"}</span></h1>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{f && LOCATION_ERR[f] ? `${LOCATION_ERR[f]}：` : ""}{errText(one(sp.err))}</p> : null}
      <p className="note">
        EC販売：{d.ec_saleable ? "可" : "不可"} ／ 一時停止：{d.suspended ? "停止中" : "営業中"}（切り替えは <Link href="/admin/locations">拠点管理</Link> の一覧で）
        {ro ? " ／ 参照のみ" : ""}
      </p>

      <form action={editLocationAction} className="gridform">
        <input type="hidden" name="location_code" value={d.location_code} />
        <LocationFields loc={d} prefectures={d.prefectures} disabled={ro} />
        {!ro ? <SubmitButton pending="保存しています…">保存する</SubmitButton> : null}
      </form>

      <h2 className="h2">休業日</h2>
      <p className="note">営業する曜日でも、この日は発送しません（BR-23）。</p>
      {d.holidays.length === 0 ? <p className="meta">登録された休業日はありません。</p> : (
        <ul>
          {d.holidays.map((h) => (
            <li key={h}>
              {h}{" "}
              {!ro ? (
                <form action={holidayAction} className="inline">
                  <input type="hidden" name="location_code" value={d.location_code} />
                  <input type="hidden" name="remove" value={h} />
                  <button type="submit" className="mini">外す</button>
                </form>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {!ro ? (
        <form action={holidayAction} className="rowform">
          <input type="hidden" name="location_code" value={d.location_code} />
          <input type="date" name="holiday" required aria-label="休業日" />
          <button type="submit" className="btn sub">休業日を追加する</button>
        </form>
      ) : null}
    </main>
  );
}
