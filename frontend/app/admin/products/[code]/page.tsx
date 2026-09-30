// SCR-B02 商品登録・編集（AP-B02・F-701〜705）。
//
//   F-701 商品の編集   F-704 価格   F-705 公開・非公開
//   F-702 SKU の一括生成（色×サイズ）と、拠点ごとの在庫数
//   F-703 画像（色に紐づけ。1色に複数枚・並び順）
//
// ★どれも API が判定する。すでにある SKU は作らない（6.2.4）／在庫数は引当済数を下回らない（ERR-1208）
//   ／画像は中身で判定（N-36）。画面は選ばせて送るだけ。
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { getAdminProduct, listExclusions, listLocations, listMaster } from "@/lib/api/catalog";
import {
  bulkSkuAction,
  deleteImageAction,
  exclusionAction,
  moveImageAction,
  publishAction,
  putStocksAction,
  updateProductAction,
  uploadImageAction,
} from "@/lib/actions/catalog";
import { errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

const IMAGE_BASE = process.env.IMAGE_BASE_URL ?? "http://localhost:8000/assets";

export default async function AdminProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { code } = await params;
  const sp = await searchParams;
  let d, cats, types, colors, sizes, locs, excl: { location_code: string }[] | null;
  try {
    await adminMe();
    d = (await getAdminProduct(code)).data;
    [cats, types, colors, sizes, locs] = await Promise.all([
      listMaster("categories").then((r) => r.data.items),
      listMaster("item-types").then((r) => r.data.items),
      listMaster("colors").then((r) => r.data.items),
      listMaster("sizes").then((r) => r.data.items),
      listLocations().then((r) => r.data.locations).catch(() => []),
    ]);
    // ★F-806 は運用管理者だけ（2.4）。見られない役割では表を出さない
    excl = await listExclusions(code).then((r) => r.data.exclusions).catch(() => null);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 404) notFound();
    if (e instanceof ApiError && e.status === 403) {
      return <main className="wrap"><h1 className="h1">商品</h1><p className="err">この操作は行えません（ERR-1102）</p></main>;
    }
    throw e;
  }
  const p = d.product;
  const ro = !d.can_edit;
  const hidden = { name: "product_code", value: p.product_code, type: "hidden" } as const;
  const skuColors = [...new Set(d.skus.map((s) => s.color_code))];
  const stockOf = (sku: string, loc: string) =>
    d.stocks.find((s) => s.sku_code === sku && s.location_code === loc && s.section === 1);
  // ★在庫の表に出す拠点は「EC販売可」のもの（倉庫＋EC販売可の店舗）と、すでに在庫がある拠点
  const shownLocs = locs.filter((l) => l.ec_saleable || d.stocks.some((s) => s.location_code === l.location_code));

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/admin/products">商品一覧</Link> ／ {p.product_code}</p>
      <h1 className="h1">
        <code>{p.product_code}</code> {p.name}{" "}
        <span className="badge">{p.is_published ? "公開" : "非公開"}</span>
      </h1>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}
      {ro ? <p className="note">参照のみ（2.4：商品の登録・編集は運用管理者）</p> : null}
      <p className="note">
        <Link href={`/products/${p.product_code}`}>客側の商品詳細を開く</Link>
        {p.is_published ? "" : "（★非公開なので客側では「見つかりません」になります）"}
      </p>

      {/* ---------------- F-705 公開 ---------------- */}
      {!ro ? (
        <form action={publishAction} className="rowform" style={{ margin: "8px 0 16px" }}>
          <input {...hidden} />
          <input type="hidden" name="to" value={p.is_published ? "0" : "1"} />
          <button type="submit" className="btn sub">{p.is_published ? "非公開にする" : "公開する"}</button>
          <span className="note">★非公開にすると、客側の一覧・検索・詳細から消え、カートに残っていても注文できません</span>
        </form>
      ) : null}

      {/* ---------------- F-701・F-704 ---------------- */}
      <h2 className="h2">商品の情報・価格</h2>
      <form action={updateProductAction} className="gridform">
        <input {...hidden} />
        <label>商品名<input name="name" defaultValue={p.name} required maxLength={100} disabled={ro} /></label>
        <label>通常価格（税込）<input name="price" type="number" min={1} defaultValue={p.price} required disabled={ro} /></label>
        <label>カテゴリ
          <select name="category_code" defaultValue={p.category_code} disabled={ro}>
            {cats.filter((c) => c.parent_code && (c.is_active || c.code === p.category_code)).map((c) => (
              <option key={c.code} value={c.code}>{c.name}（{c.code}）</option>
            ))}
          </select>
        </label>
        <label>アイテム種別
          <select name="item_type_code" defaultValue={p.item_type_code} disabled={ro}>
            {types.filter((t) => t.is_active || t.code === p.item_type_code).map((t) => (
              <option key={t.code} value={t.code}>{t.name}</option>
            ))}
          </select>
        </label>
        <label>素材<input name="material" defaultValue={p.material ?? ""} maxLength={200} disabled={ro} /></label>
        <label className="wide">説明<textarea name="description" defaultValue={p.description ?? ""} rows={3} maxLength={2000} disabled={ro} /></label>
        {!ro ? <button type="submit" className="btn">保存する</button> : null}
      </form>

      {/* ---------------- F-702 SKU の一括生成 ---------------- */}
      <h2 className="h2">SKU（色 × サイズ）</h2>
      <p className="note">いま {d.skus.length} 件。{d.skus.map((s) => s.sku_code).join("　")}</p>
      {!ro ? (
        <form action={bulkSkuAction} className="skuform">
          <input {...hidden} />
          <fieldset><legend>色</legend>
            {colors.filter((c) => c.is_active).map((c) => (
              <label key={c.code}><input type="checkbox" name="colors" value={c.code} /> {c.name}</label>
            ))}
          </fieldset>
          <fieldset><legend>サイズ</legend>
            {sizes.filter((s) => s.is_active).map((s) => (
              <label key={s.code}><input type="checkbox" name="sizes" value={s.code} /> {s.name}</label>
            ))}
          </fieldset>
          <fieldset><legend>作ったSKUに入れる在庫数（拠点ごと。0 なら行を作らない）</legend>
            {shownLocs.map((l) => (
              <label key={l.location_code}>
                <input type="hidden" name="stock_location" value={l.location_code} />
                {l.location_code} <input type="number" name="stock_qty" min={0} defaultValue={0} style={{ width: 70 }} />
              </label>
            ))}
          </fieldset>
          <button type="submit" className="btn sub">選んだ組み合わせを作る（すでにあるものは作りません）</button>
        </form>
      ) : null}

      {d.skus.length > 0 ? (
        <form action={putStocksAction}>
          <input {...hidden} />
          <div className="scrollx">
            <table className="orders">
              <thead>
                <tr><th>SKU</th>{shownLocs.map((l) => <th key={l.location_code}>{l.location_code}</th>)}</tr>
              </thead>
              <tbody>
                {d.skus.map((s) => (
                  <tr key={s.sku_code}>
                    <td><code>{s.sku_code}</code><br /><small>{s.color_name} / {s.size_name}</small></td>
                    {shownLocs.map((l) => {
                      const st = stockOf(s.sku_code, l.location_code);
                      const k = `${s.sku_code}__${l.location_code}`;
                      return (
                        <td key={l.location_code} className="num">
                          <input type="hidden" name={`o__${k}`} value={st ? st.qty : ""} />
                          <input name={`q__${k}`} type="number" min={0} defaultValue={st ? st.qty : ""}
                                 placeholder="—" style={{ width: 64 }} disabled={ro} />
                          {st && st.reserved_qty > 0 ? <><br /><small>引当 {st.reserved_qty}</small></> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!ro ? <button type="submit" className="btn sub">在庫数を保存する（バックヤード）</button> : null}
        </form>
      ) : null}

      {/* ---------------- F-806 EC販売（拠点ごと）。R-30 ---------------- */}
      {excl !== null ? (
        <>
          <h2 className="h2">EC販売（拠点ごと）</h2>
          <p className="note">
            ★この商品を、その拠点の在庫からECで売るか。<strong>不可にする＝除外の行を足す／可に戻す＝行を消す</strong>（3.2.2 ②）。
            倉庫は不可にできません。拠点そのものの「EC販売可」は <Link href="/admin/locations">拠点管理</Link>。
          </p>
          <table className="orders">
            <thead><tr><th>拠点</th><th>拠点のEC販売</th><th>この商品</th><th></th></tr></thead>
            <tbody>
              {locs.map((l) => {
                const ex = excl!.some((e) => e.location_code === l.location_code);
                const wh = l.kind === 1;
                return (
                  <tr key={l.location_code}>
                    <td><code>{l.location_code}</code> {l.name}</td>
                    <td>{l.ec_saleable ? "可" : "不可"}{l.suspended ? "（一時停止中）" : ""}</td>
                    <td><span className={`badge ${ex ? "out" : "in"}`}>{ex ? "除外（ECで売らない）" : "売る"}</span></td>
                    <td>
                      {wh ? <small className="note">倉庫は固定</small> : (
                        <form action={exclusionAction} className="inline">
                          <input type="hidden" name="product_code" value={p.product_code} />
                          <input type="hidden" name="location_code" value={l.location_code} />
                          <input type="hidden" name="to" value={ex ? "include" : "exclude"} />
                          <button type="submit" className="mini">{ex ? "可に戻す" : "不可にする"}</button>
                        </form>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      ) : null}

      {/* ---------------- F-703 画像 ---------------- */}
      <h2 className="h2">画像（色ごと）</h2>
      <p className="note">JPEG・PNG、1枚5MBまで、1商品50枚まで（N-36。★拡張子ではなく中身で判定します）</p>
      {!ro ? (
        <form action={uploadImageAction} className="rowform">
          <input {...hidden} />
          <select name="color_code">
            {(skuColors.length ? colors.filter((c) => skuColors.includes(c.code)) : colors.filter((c) => c.is_active)).map((c) => (
              <option key={c.code} value={c.code}>{c.name}</option>
            ))}
          </select>
          <input type="file" name="file" accept="image/jpeg,image/png" required />
          <button type="submit" className="mini">取り込む</button>
        </form>
      ) : null}
      <div className="imggrid">
        {[...new Set(d.images.map((i) => i.color_code))].map((c) => (
          <div key={c} className="imgcol">
            <strong>{colors.find((x) => x.code === c)?.name ?? c}</strong>
            {d.images.filter((i) => i.color_code === c).map((i, idx, arr) => (
              <figure key={i.sort_no}>
                <img src={`${IMAGE_BASE}/${i.url}`} alt={`${c} ${i.sort_no}`} />
                <figcaption>
                  #{i.sort_no}
                  {!ro ? (
                    <>
                      {idx > 0 ? (
                        <form action={moveImageAction} className="inline">
                          <input {...hidden} /><input type="hidden" name="color_code" value={c} />
                          <input type="hidden" name="sort_no" value={i.sort_no} /><input type="hidden" name="direction" value="up" />
                          <button className="mini" type="submit">↑</button>
                        </form>
                      ) : null}
                      {idx < arr.length - 1 ? (
                        <form action={moveImageAction} className="inline">
                          <input {...hidden} /><input type="hidden" name="color_code" value={c} />
                          <input type="hidden" name="sort_no" value={i.sort_no} /><input type="hidden" name="direction" value="down" />
                          <button className="mini" type="submit">↓</button>
                        </form>
                      ) : null}
                      <form action={deleteImageAction} className="inline">
                        <input {...hidden} /><input type="hidden" name="color_code" value={c} />
                        <input type="hidden" name="sort_no" value={i.sort_no} />
                        <button className="mini" type="submit">削除</button>
                      </form>
                    </>
                  ) : null}
                </figcaption>
              </figure>
            ))}
          </div>
        ))}
      </div>
    </main>
  );
}
