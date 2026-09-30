// SCR-02 商品一覧（AP-101）
//
// ★行ごとに別のAPIを呼ばない（N-06・9.2.2）。
//   在庫の有無も画像URLも、この1回の listProducts で全部返ってくる。
//
// ★ページングは `after`。`offset` は使わない（4.1.7）。「5ページ目へ飛ぶ」は作らない。
//
// ★R-15｜絞り込みと並び替えを見た目で分ける（4.1.7）。
//   絞り込み＝件数が減る（角ばった四角）／並び替え＝順番だけ変わる（丸い枠）。
//   「在庫ありのみ」は絞り込みなので、カテゴリと同じ列に置く。
import Link from "next/link";

import { listProducts, type ListParams } from "@/lib/api/client";
import { countLabel, sizeLabel, yen } from "@/lib/view/format";
import { href, one, type Search } from "@/lib/view/list-url";

export const dynamic = "force-dynamic";

const SORTS = [
  { key: "new", label: "新着" },
  { key: "price_asc", label: "価格が安い順" },
  { key: "price_desc", label: "価格が高い順" },
] as const;

// ★共通サイズ（BR-03）。表記が違う商品も、これで絞ると M 相当が出る（FR-103・AT-103）
const SIZES = ["S", "M", "L", "XL", "XXL"];

const CATEGORIES = [
  { key: "", label: "すべて" },
  { key: "TSHIRT", label: "Tシャツ" },
  { key: "SHIRT", label: "シャツ" },
  { key: "PANTS", label: "パンツ" },
  { key: "SKIRT", label: "スカート" },
  { key: "BLOUSON", label: "ブルゾン" },
];

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  const sp = await searchParams;
  const sort = (one(sp.sort) ?? "new") as ListParams["sort"];
  const category = one(sp.category);
  const keyword = one(sp.keyword);
  const inStock = one(sp.in_stock) === "true";
  const size = one(sp.size);
  const after = one(sp.after);

  let res;
  let invalid = false;
  try {
    res = await listProducts({ limit: 20, sort, category, keyword, size, inStock, after });
  } catch {
    // `after` や `sort` の形が違うとバックエンドが 400 を返す（SEC-504a）。
    // 画面は落とさず、条件が悪いことを伝える
    invalid = true;
    res = {
      data: [],
      page: { limit: 20, sort: sort ?? "new", next_after: null, total: 0, total_capped: false },
    };
  }

  // ★いま効いている条件を1行で見せる（R-15 の本命）。
  //   何が効いているか分からないまま「該当なし」を見せない。
  const activeFilters: string[] = [];
  if (category) activeFilters.push(CATEGORIES.find((c) => c.key === category)?.label ?? category);
  if (size) activeFilters.push(`サイズ ${size}`);
  if (inStock) activeFilters.push("在庫あり");
  if (keyword) activeFilters.push(`「${keyword}」を含む`);
  const sortLabel = SORTS.find((s) => s.key === sort)?.label ?? "新着";
  const hasFilter = activeFilters.length > 0;

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/">トップ</Link> ／ 商品一覧</p>

      <form className="filters" method="get" action="/products">
        <input type="search" name="keyword" placeholder="商品名で探す" defaultValue={keyword ?? ""} />
        {sort ? <input type="hidden" name="sort" value={sort} /> : null}
        {category ? <input type="hidden" name="category" value={category} /> : null}
        {inStock ? <input type="hidden" name="in_stock" value="true" /> : null}
        {size ? <input type="hidden" name="size" value={size} /> : null}
        <button className="chip" type="submit">検索</button>
      </form>

      {/* 絞り込み＝件数が減る。「在庫ありのみ」もここ（並び替えの列から移した） */}
      <div className="facet">
        <div className="lbl">絞り込み</div>
        <div className="opts">
          {CATEGORIES.map((c) => (
            <Link
              key={c.key || "all"}
              className={`f-filter ${(category ?? "") === c.key ? "on" : ""}`}
              href={href(sp, { category: c.key || undefined, after: undefined })}
            >
              {c.label}
            </Link>
          ))}
          <Link
            className={`f-filter ${inStock ? "on" : ""}`}
            href={href(sp, { in_stock: inStock ? undefined : "true", after: undefined })}
          >
            在庫ありのみ
          </Link>
        </div>
      </div>

      {/* ★サイズで絞る（FR-103・AT-103）。APIには前からあったが、画面に出していなかった。
          ★共通サイズで絞るので、表記が違う商品も M 相当が出る（BR-03） */}
      <div className="facet">
        <div className="lbl">サイズ</div>
        <div className="opts">
          {SIZES.map((z) => (
            <Link
              key={z}
              className={`f-filter ${size === z ? "on" : ""}`}
              href={href(sp, { size: size === z ? undefined : z, after: undefined })}
            >
              {z}
            </Link>
          ))}
        </div>
      </div>

      {/* 並び替え＝件数は変わらず順番だけ変わる */}
      <div className="facet">
        <div className="lbl">並び替え</div>
        <div className="opts">
          {SORTS.map((s) => (
            <Link
              key={s.key}
              className={`f-sort ${sort === s.key ? "on" : ""}`}
              href={href(sp, { sort: s.key, after: undefined })}
            >
              {s.label}
            </Link>
          ))}
        </div>
      </div>

      {/* いまの条件。まとめて外せる */}
      <div className="active-cond">
        <span className="k">いまの条件：</span>
        <span className="v">{hasFilter ? activeFilters.join("・") : "絞り込みなし"}</span>
        <span className="k">／</span>
        <span className="v">{sortLabel}</span>
        {hasFilter || sort !== "new" ? (
          <Link className="clear" href="/products">
            条件をクリア
          </Link>
        ) : null}
      </div>

      {/* ★件数は cap で打ち切って数えている（9.2.1d）。101 件目が見つかったら「100件以上」 */}
      {!invalid ? (
        <p className="count">
          {countLabel(res.page.total, res.page.total_capped)}
        </p>
      ) : null}

      {invalid ? (
        <p className="empty">条件が正しくありません。「条件をクリア」から選び直してください。</p>
      ) : null}

      {res.data.length === 0 && !invalid ? (
        <p className="empty">
          上の条件に当てはまる商品がありません。
          {hasFilter ? "絞り込みを外すと見つかるかもしれません。" : null}
        </p>
      ) : (
        <div className="grid">
          {res.data.map((p) => (
            <Link className="card" key={p.product_code} href={`/products/${p.product_code}`}>
              {p.image_url ? <img src={p.image_url} alt={p.name} loading="lazy" /> : <div className="noimg" />}
              {/* ★新着だけ採る（画面の型 1.3 ⑥）。判定はサーバ（登録から14日以内） */}
              {p.is_new ? <span className="badge new">新着</span> : null}
              <p className="nm">{p.name}</p>
              <p className="pr">{yen(p.price)}</p>
              {p.size_range.length > 0 ? (
                <p className="sizerange">{sizeLabel(p.size_range)}</p>
              ) : null}
              {/* ★2値だけ。「残りわずか」は商品詳細でしか出さない（9.2.1b） */}
              <span className={`badge ${p.in_stock ? "in" : "out"}`}>
                {p.in_stock ? "在庫あり" : "品切れ"}
              </span>
            </Link>
          ))}
        </div>
      )}

      {/* ★キーセット方式。ページ番号のリンクは作らない（4.1.7） */}
      <div className="pager">
        {res.page.next_after ? (
          <Link className="chip" href={href(sp, { after: res.page.next_after })}>
            次の20件へ →
          </Link>
        ) : (
          <span className="chip" style={{ color: "var(--muted)" }}>これで最後です</span>
        )}
        {after ? (
          <Link className="chip" href={href(sp, { after: undefined })}>
            ← 先頭へ
          </Link>
        ) : null}
      </div>
    </main>
  );
}
