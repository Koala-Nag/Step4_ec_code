// SCR-B15 拠点管理｜拠点の登録（AP-B04 POST・F-809）。R-32。
// ★運用管理者だけ（2.4）。倉庫は EC販売可を固定（サーバが TRUE にする）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { listLocations } from "@/lib/api/catalog";
import { createLocationAction } from "@/lib/actions/promo";
import { SubmitButton } from "@/app/submit-button";
import { errText, one } from "@/lib/view/admin-labels";
import { LOCATION_ERR, LocationFields } from "../location-form";

export const dynamic = "force-dynamic";

export default async function NewLocationPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  let me, prefs;
  try {
    me = (await adminMe()).data;
    prefs = (await listLocations()).data.prefectures;         // ★都道府県の選択肢（47）
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    throw e;
  }
  if (me.role !== 1) {
    return <main className="wrap"><h1 className="h1">拠点の登録</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
  }
  const f = one(sp.field);

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/admin/locations">拠点管理</Link> ／ 拠点の登録</p>
      <h1 className="h1">拠点の登録</h1>
      {errText(one(sp.err)) ? <p className="err">{f && LOCATION_ERR[f] ? `${LOCATION_ERR[f]}：` : ""}{errText(one(sp.err))}</p> : null}
      <form action={createLocationAction} className="gridform">
        <label>拠点コード<input name="location_code" maxLength={10} required placeholder="T011" /></label>
        <label>区分
          <select name="kind" defaultValue="2">
            <option value="2">店舗</option>
            <option value="1">倉庫</option>
          </select>
        </label>
        <LocationFields loc={null} prefectures={prefs} />
        <label><input type="checkbox" name="ec_saleable" value="1" /> ECの出荷元にする（EC販売可。倉庫は常に可）</label>
        <SubmitButton pending="登録しています…">登録する</SubmitButton>
      </form>
    </main>
  );
}
