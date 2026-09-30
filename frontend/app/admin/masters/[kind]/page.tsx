// SCR-B14 マスタ管理（AP-B03・F-709）。
//
// ★使われているマスタは削除できず、無効化のみ（F-709）。削除ボタンは出すが、判定は API（ERR-1217）。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { listMaster, listSizeMap } from "@/lib/api/catalog";
import {
  addSizeMapAction,
  createMasterAction,
  deleteMasterAction,
  toggleMasterAction,
  updateMasterAction,
} from "@/lib/actions/catalog";
import { errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

const KINDS: Record<string, { label: string; sort: boolean; parent?: boolean; hint: string }> = {
  colors: { label: "色", sort: true, hint: "BK" },
  sizes: { label: "サイズ", sort: true, hint: "XS" },
  "common-sizes": { label: "共通サイズ", sort: true, hint: "CS6" },
  categories: { label: "カテゴリ", sort: true, parent: true, hint: "KNIT" },
  "item-types": { label: "アイテム種別", sort: false, hint: "KNIT_T" },
};

export default async function MastersPage({
  params,
  searchParams,
}: {
  params: Promise<{ kind: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { kind } = await params;
  const sp = await searchParams;
  const def = KINDS[kind];
  if (!def) notFound();

  let items, cats, sizeMap, commons;
  try {
    await adminMe();
    items = (await listMaster(kind)).data.items;
    cats = def.parent ? (await listMaster("categories")).data.items : [];
    sizeMap = kind === "sizes" ? (await listSizeMap()).data.size_map : [];
    commons = kind === "sizes" ? (await listMaster("common-sizes")).data.items : [];
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">マスタ管理</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }

  return (
    <main className="wrap">
      <h1 className="h1">マスタ管理｜{def.label}</h1>
      <p className="tabs">
        {Object.entries(KINDS).map(([k, v]) => (
          k === kind ? <strong key={k}>{v.label}</strong> : <Link key={k} href={`/admin/masters/${k}`}>{v.label}</Link>
        ))}
      </p>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}

      <form action={createMasterAction} className="rowform" style={{ margin: "12px 0 20px" }}>
        <input type="hidden" name="kind" value={kind} />
        <input name="code" required placeholder={`コード（例 ${def.hint}）`} />
        <input name="name" required placeholder="名前" />
        {def.sort ? <input name="sort_no" type="number" placeholder="並び順" style={{ width: 90 }} /> : null}
        {def.parent ? (
          <select name="parent_code" defaultValue="">
            <option value="">（大分類）</option>
            {cats.filter((c) => !c.parent_code).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        ) : null}
        <button type="submit" className="mini">登録</button>
      </form>

      <table className="orders">
        <thead>
          <tr><th>コード</th><th>名前・並び順</th>{def.parent ? <th>親</th> : null}<th>状態</th><th>使用</th><th></th></tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.code} className={m.is_active ? "" : "inactive"}>
              <td><code>{m.code}</code></td>
              <td>
                <form action={updateMasterAction} className="rowform">
                  <input type="hidden" name="kind" value={kind} />
                  <input type="hidden" name="code" value={m.code} />
                  <input name="name" defaultValue={m.name} required />
                  {def.sort ? <input name="sort_no" type="number" defaultValue={m.sort_no ?? 0} style={{ width: 70 }} /> : null}
                  <button type="submit" className="mini">保存</button>
                </form>
              </td>
              {def.parent ? <td>{m.parent_code ?? "—"}</td> : null}
              <td>{m.is_active ? "有効" : <strong>無効</strong>}</td>
              <td>{m.used ? "使われている" : "—"}</td>
              <td style={{ whiteSpace: "nowrap" }}>
                <form action={toggleMasterAction} className="inline">
                  <input type="hidden" name="kind" value={kind} />
                  <input type="hidden" name="code" value={m.code} />
                  <input type="hidden" name="to" value={m.is_active ? "0" : "1"} />
                  <button type="submit" className="mini">{m.is_active ? "無効にする" : "有効にする"}</button>
                </form>
                <form action={deleteMasterAction} className="inline">
                  <input type="hidden" name="kind" value={kind} />
                  <input type="hidden" name="code" value={m.code} />
                  <button type="submit" className="mini">削除</button>
                </form>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {kind === "sizes" ? (
        <>
          <h2 className="h2">サイズ対応（表記サイズ → 共通サイズ）</h2>
          <p className="note">★SKU を作るには、そのサイズに共通サイズの対応が要ります（F-109 の絞り込みに使う）。</p>
          <form action={addSizeMapAction} className="rowform">
            <select name="size_code">{items.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}</select>
            →
            <select name="common_size_code">{commons.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}</select>
            <button type="submit" className="mini">足す</button>
          </form>
          <p className="note">{sizeMap.map((x) => `${x.size_code}→${x.common_size_code}`).join("　")}</p>
        </>
      ) : null}
    </main>
  );
}
