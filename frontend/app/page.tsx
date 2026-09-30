// SCR-01 トップ（R-28 (a)）。
//
// ★新しい API は作らない。新着は商品一覧（AP-101）の sort=new の先頭をそのまま使う。
// ★未実装の機能（セール・お気に入り・再入荷通知・店舗受取…）への入口は置かない。
import Link from "next/link";

import { listProducts } from "@/lib/api/client";
import { sizeLabel, yen } from "@/lib/view/format";

export const dynamic = "force-dynamic";

const CATEGORIES = [
  { key: "TSHIRT", label: "Tシャツ", note: "毎日の定番" },
  { key: "SHIRT", label: "シャツ", note: "きちんと見える" },
  { key: "PANTS", label: "パンツ", note: "はき心地で選ぶ" },
  { key: "SKIRT", label: "スカート", note: "季節を問わず" },
  { key: "BLOUSON", label: "ブルゾン", note: "羽織りを1枚" },
];

export default async function Home() {
  let fresh: Awaited<ReturnType<typeof listProducts>>["data"] = [];
  try {
    fresh = (await listProducts({ limit: 8, sort: "new" })).data;
  } catch {
    // ★新着が取れなくても、トップは開ける（入口だけは出す）
  }

  return (
    <main className="wrap">
      <section className="hero">
        <h1>毎日着る服を、サイズで迷わず。</h1>
        <p>色とサイズごとの在庫をその場で確かめて、そのまま注文できます。</p>
        <form action="/products" method="get" className="herosearch" role="search">
          <input type="search" name="keyword" placeholder="商品名・商品コードで探す" aria-label="商品を探す" />
          <button className="btn" type="submit">探す</button>
        </form>
      </section>

      <h2 className="h2">カテゴリから探す</h2>
      <div className="cats">
        {CATEGORIES.map((c) => (
          <Link key={c.key} href={`/products?category=${c.key}`} className="cat">
            <strong>{c.label}</strong>
            <span>{c.note}</span>
          </Link>
        ))}
      </div>

      <div className="sechead">
        <h2 className="h2">新着</h2>
        <Link href="/products?sort=new">もっと見る →</Link>
      </div>
      {fresh.length === 0 ? (
        <p className="empty">新着の商品を読み込めませんでした。<Link href="/products">商品一覧へ</Link></p>
      ) : (
        <div className="grid">
          {fresh.map((p) => (
            <Link className="card" key={p.product_code} href={`/products/${p.product_code}`}>
              {p.image_url ? <img src={p.image_url} alt={p.name} loading="lazy" /> : <div className="noimg" />}
              {p.is_new ? <span className="badge new">新着</span> : null}
              <p className="nm">{p.name}</p>
              <p className="pr">{yen(p.price)}</p>
              {p.size_range.length > 0 ? <p className="sizerange">{sizeLabel(p.size_range)}</p> : null}
            </Link>
          ))}
        </div>
      )}

      <section className="guide">
        <div>
          <strong>送料</strong>
          <p>一定額以上のお買い上げで送料無料。あといくらで無料になるかは、カートでお知らせします。</p>
        </div>
        <div>
          <strong>返品</strong>
          <p>出荷日から17日以内・未使用のものに限ります。<Link href="/about/returns">くわしく</Link></p>
        </div>
        <div>
          <strong>会員登録なしでも</strong>
          <p>ゲストのままご注文いただけます。会員は購入履歴から注文を確かめられます。</p>
        </div>
      </section>
    </main>
  );
}
