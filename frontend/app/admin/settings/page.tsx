// SCR-B07 販売設定（AP-B33・F-308・FT-01）。R-33。
//
// ★版を重ねる（T-30）。保存すると「適用開始日」の新しい版ができ、その日から効く。直に書き換えない。
// ★適用開始日は今日より前にできない（API が断る）。
// ★確定した注文の金額は変わらない（BR-17）。これから計算するカート・注文にだけ効く。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { getSalesConfig } from "@/lib/api/backoffice";
import { saveSalesConfigAction } from "@/lib/actions/backoffice";
import { SubmitButton } from "@/app/submit-button";
import { errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function SalesConfigPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  let d;
  try {
    d = (await getSalesConfig()).data;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">販売設定</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }
  const c = d.current;
  const label = Object.fromEntries(d.fields.map((f) => [f.name, f.label]));
  const errField = one(sp.field);
  const changed = (one(sp.changed) ?? "").split(",").filter(Boolean);
  const ro = !d.can_edit;
  const show = (f: { kind: string; unit: string }, v: unknown) =>
    f.kind === "rate" ? `${Math.round(Number(v) * 1000) / 10}%` : f.kind === "yen" ? `${Number(v).toLocaleString()}円` : `${v}${f.unit}`;

  return (
    <main className="wrap">
      <h1 className="h1">販売設定</h1>
      <p className="note">
        いま効いている版：<strong>{c.effective_from}</strong> から ／ 今日 {d.today}
        {d.scheduled.length ? <> ／ 予定：{d.scheduled.map((s) => s.effective_from).join("、")} から</> : null}
      </p>
      {one(sp.ok) ? (
        <p className="ok">
          {one(sp.ok)} からの版を保存しました。{one(sp.now) === "1" ? "いまから効いています（再起動は要りません）。" : "その日から効きます。"}
          {changed.length ? `変えた項目：${changed.map((k) => label[k] ?? k).join("、")}。` : "値は変わっていません。"}
          ★すでに確定した注文の金額は変わりません（BR-17）。
        </p>
      ) : null}
      {errText(one(sp.err)) ? (
        <p className="err">{errField === "effective_from" ? "適用開始日は今日以降にしてください：" : errField ? `${label[errField] ?? errField}：` : ""}{errText(one(sp.err))}</p>
      ) : null}

      <form action={saveSalesConfigAction} className="gridform">
        <label>適用開始日（この日から効く。今日以降）
          <input type="date" name="effective_from" defaultValue={d.today} min={d.today} required disabled={ro} />
        </label>
        {d.fields.map((f) => (
          <label key={f.name}>
            {f.label}{f.unit ? ` ${f.unit}` : ""}
            {!f.used ? <small className="note">★いまは、この値を使う処理がありません（変えても何も起きません）</small> : null}
            <input name={f.name} defaultValue={String(c[f.name] ?? "")} required disabled={ro}
                   inputMode={f.kind === "rate" ? "decimal" : "numeric"} aria-invalid={errField === f.name || undefined} />
          </label>
        ))}
        <label className="wide">お知らせ帯の文言（N-02。空なら出さない。200文字まで）
          <input name="notice_text" defaultValue={String(c.notice_text ?? "")} maxLength={200} disabled={ro} />
        </label>
        <label>お知らせの表示開始<input type="datetime-local" name="notice_from" defaultValue={String(c.notice_from ?? "")} disabled={ro} /></label>
        <label>お知らせの表示終了<input type="datetime-local" name="notice_to" defaultValue={String(c.notice_to ?? "")} disabled={ro} /></label>
        {!ro ? <SubmitButton pending="保存しています…">この内容で版を保存する</SubmitButton> : null}
      </form>

      <h2 className="h2">版の一覧</h2>
      <div className="scrollx">
        <table className="orders">
          <thead>
            <tr><th>適用開始日</th>{d.fields.slice(0, 7).map((f) => <th key={f.name}>{f.label}</th>)}<th></th></tr>
          </thead>
          <tbody>
            {[...d.scheduled, ...d.history].map((v) => (
              <tr key={v.effective_from}>
                <td>{v.effective_from}</td>
                {d.fields.slice(0, 7).map((f) => <td key={f.name} className="num">{show(f, v[f.name])}</td>)}
                <td>
                  <span className={`badge ${v.effective_from === c.effective_from ? "in" : "out"}`}>
                    {v.effective_from === c.effective_from ? "いま効いている" : v.effective_from > d.today ? "予定" : "過去の版"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">期限値を変えたときに効くところ：<Link href="/admin/stocks/stagnant">滞留在庫</Link>・返品の申請期限と返送期限・ログインのロック・セッションの無操作時間 など。</p>
    </main>
  );
}
