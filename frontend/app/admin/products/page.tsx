// SCR-B01 商品一覧（AP-B02・F-701）。★非公開の商品も出す（運営は全部見る）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { listAdminProducts, listMaster } from "@/lib/api/catalog";
import { createProductAction } from "@/lib/actions/catalog";
import { yen } from "@/lib/view/format";
import { ROLE_LABEL, errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function AdminProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const kw = one(sp.keyword);
  let me, products, cats, types;
  try {
    me = (await adminMe()).data;
    products = (await listAdminProducts(kw)).data.products;
    cats = (await listMaster("categories")).data.items;
    types = (await listMaster("item-types")).data.items;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">商品一覧</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }
  const canEdit = me.role === 1;   // ★表示の出し分けだけ。判定は API（2.4：F-701 は運用管理者だけ「可」）

  return (
    <main className="wrap">
      <h1 className="h1">商品一覧</h1>
      <p className="note">{me.name}（{ROLE_LABEL[me.role]}）{canEdit ? "" : " ／ 参照のみ"}</p>
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}

      {canEdit ? (
        <details className="shortbox" open={!!one(sp.err)}>
          <summary>商品を登録する（F-701）</summary>
          <form action={createProductAction} className="gridform">
            <label>商品コード<input name="product_code" required placeholder="P0100" /></label>
            <label>商品名<input name="name" required maxLength={100} /></label>
            <label>カテゴリ
              <select name="category_code" required>
                {cats.filter((c) => c.is_active && c.parent_code).map((c) => (
                  <option key={c.code} value={c.code}>{c.name}（{c.code}）</option>
                ))}
              </select>
            </label>
            <label>アイテム種別
              <select name="item_type_code" required>
                {types.filter((t) => t.is_active).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
              </select>
            </label>
            <label>素材<input name="material" maxLength={200} /></label>
            <label>通常価格（税込）<input name="price" type="number" min={1} required /></label>
            <label className="wide">説明<textarea name="description" maxLength={2000} rows={3} /></label>
            <button type="submit" className="btn">登録する（非公開で作ります）</button>
          </form>
        </details>
      ) : null}

      <form method="get" className="rowform" style={{ margin: "14px 0" }}>
        <input name="keyword" defaultValue={kw ?? ""} placeholder="商品名・商品コード" />
        <button type="submit" className="mini">探す</button>
      </form>

      <table className="orders">
        <thead><tr><th>商品コード</th><th>商品名</th><th>価格</th><th>SKU</th><th>画像</th><th>公開</th></tr></thead>
        <tbody>
          {products.map((p) => (
            <tr key={p.product_code} className={p.is_published ? "" : "inactive"}>
              <td><Link href={`/admin/products/${p.product_code}`}><code>{p.product_code}</code></Link></td>
              <td>{p.name}</td>
              <td className="num">{yen(p.price)}</td>
              <td className="num">{p.sku_count}</td>
              <td className="num">{p.image_count}</td>
              <td>{p.is_published ? "公開" : <strong>非公開</strong>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
