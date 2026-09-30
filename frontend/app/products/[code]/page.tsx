// SCR-03 商品詳細（AP-102）
//
// ★ここだけ BR-25 の3値（在庫あり／残りわずか／品切れ）。1商品ぶんなので軽い（9.2.1b）。
// ★色を切り替えると画像が変わる（product_image を色コードで引く）。
//
// ★R-15｜サイズを3つの状態で見せる（4.1.7）。
//   ふつう      … 在庫がある（選べる）
//   薄い灰色    … その色にはあるが売り切れ（選べない）
//   濃い灰色    … そもそもその色では作っていない（選べない）
//   ★データは足していない。sku（T-02）に行があるかどうかで見分けている。
import Link from "next/link";
import { notFound } from "next/navigation";

import { addAction } from "@/lib/actions/cart";
import { postReviewAction, toggleFavoriteAction } from "@/lib/actions/mypage";
import { ApiError, getProduct } from "@/lib/api/client";
import { getReviews, listFavorites } from "@/lib/api/mypage";
import { sizeState, yen } from "@/lib/view/format";

export const dynamic = "force-dynamic";

const ERR_MESSAGE: Record<string, string> = {
  "ERR-1003": "入力できる範囲を超えています。",
  "ERR-1002": "形式が正しくありません。",
  "ERR-1202": "これ以上追加できません。",
  "ERR-1215": "その商品は見つかりませんでした。",
  "ERR-1401": "エラーが発生しました。しばらくしてからお試しください。",
};

const LABEL: Record<string, { text: string; cls: string }> = {
  in_stock: { text: "在庫あり", cls: "in" },
  low: { text: "残りわずか", cls: "low" },
  out: { text: "品切れ", cls: "out" },
};

export default async function ProductDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const { code } = await params;
  const sp = await searchParams;

  let res;
  try {
    res = await getProduct(code);
  } catch (e) {
    // ERR-1215（404）。存在しないのか見せてよい相手でないのかを区別しない（8.2）
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const p = res.data;
  // ★お気に入り（F-108）とレビュー（F-206）。R-32。
  //   ★会員かどうかはサーバに聞く（ゲストは ERR-1101 → お気に入りのボタンはログインへ）
  const favs = await listFavorites().then((r) => r.data.favorites).catch(() => null);
  const isFav = favs?.some((f) => f.product_code === p.product_code) ?? false;
  const rv = await getReviews(p.product_code).then((r) => r.data).catch(() => null);
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
  const reviewErr = one(sp.review_err);

  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;
  const picked = (Array.isArray(sp.color) ? sp.color[0] : sp.color) ?? p.colors[0]?.color_code;
  const color = p.colors.find((c) => c.color_code === picked) ?? p.colors[0];

  const rows = p.sizes.map((s) => {
    const v = p.variants.find(
      (x) => x.color_code === color?.color_code && x.size_code === s.size_code,
    );
    // 行が無い＝この色では作っていない／行があって0点＝売り切れ（lib/view/format.ts）
    const state = sizeState(v);
    return { size: s, variant: v, state };
  });

  const buyable = rows.filter((r) => r.state === "ok");

  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/products">商品一覧</Link> ／ {p.name}
      </p>

      <div className="detail">
        <div>
          {color?.image_url ? (
            <img className="hero" src={color.image_url} alt={`${p.name} ${color.name}`} />
          ) : null}

          {/* 色を切り替えると画像が変わる（IT-602） */}
          <div className="swatches">
            {p.colors.map((c) => (
              <Link
                key={c.color_code}
                className={`swatch ${c.color_code === color?.color_code ? "on" : ""}`}
                href={`/products/${p.product_code}?color=${c.color_code}`}
                title={c.name}
              >
                {c.image_url ? <img src={c.image_url} alt={c.name} /> : null}
              </Link>
            ))}
          </div>
        </div>

        <div>
          <h2 style={{ margin: "0 0 4px", fontSize: 22 }}>{p.name}</h2>
          <p className="price">{yen(p.price)}</p>
          {rv && rv.count > 0 ? (
            <p className="meta"><a href="#reviews">★ {rv.average} （レビュー {rv.count}件）</a></p>
          ) : null}
          {/* ★お気に入り（F-108）。ゲストが押すとログインへ（会員だけの機能。要件 4.3） */}
          <form action={toggleFavoriteAction} style={{ margin: "4px 0" }}>
            <input type="hidden" name="product_code" value={p.product_code} />
            <input type="hidden" name="on" value={isFav ? "0" : "1"} />
            <input type="hidden" name="back" value={`/products/${p.product_code}?color=${color?.color_code ?? ""}`} />
            <button type="submit" className="btn sub">{isFav ? "★ お気に入りから外す" : "☆ お気に入りに追加"}</button>
            {one(sp.fav) === "added" ? <span className="note"> お気に入りに追加しました。<Link href="/mypage/favorites">お気に入りを見る</Link></span> : null}
            {one(sp.fav) === "removed" ? <span className="note"> お気に入りから外しました。</span> : null}
            {favs === null ? <small className="note"> （ログインが必要です）</small> : null}
          </form>
          <p className="meta">
            色：{color?.name}
            <br />
            素材：{p.material ?? "—"}
            <br />
            商品コード：{p.product_code}
          </p>

          <h3 style={{ fontSize: 15, margin: "24px 0 8px" }}>サイズと在庫</h3>
          <table className="sizes">
            <thead>
              <tr>
                <th>サイズ</th>
                <th>在庫</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ size, variant, state }) => (
                <tr key={size.size_code}>
                  <td className={state === "ok" ? "" : state === "sold" ? "sold" : "none"}>
                    {state === "ok" ? (
                      <strong>{size.name}</strong>
                    ) : (
                      <span
                        title={
                          state === "sold"
                            ? "このサイズは売り切れです"
                            : "この色では作っていないサイズです"
                        }
                      >
                        {size.name}
                      </span>
                    )}
                  </td>
                  <td>
                    {state === "none" ? (
                      <span className="badge out">取り扱いなし</span>
                    ) : (
                      <span className={`badge ${LABEL[variant!.stock_label].cls}`}>
                        {LABEL[variant!.stock_label].text}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* カートに入れる（AP-202）。★単価は送らない。サーバがマスタから引く（N-35） */}
          <div className="cartbox">
            {err ? (
              <p className="freeship" style={{ marginTop: 0 }}>
                {ERR_MESSAGE[err] ?? "操作できませんでした。"}（{err}）
              </p>
            ) : null}
            {buyable.length === 0 ? (
              <p className="meta" style={{ margin: 0 }}>
                この色は現在お選びいただけません。ほかの色をお試しください。
              </p>
            ) : (
              <form action={addAction} style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  type="hidden"
                  name="redirect_to"
                  value={`/products/${p.product_code}?color=${color?.color_code ?? ""}`}
                />
                <select name="sku_code" aria-label="サイズ">
                  {buyable.map((r) => (
                    <option key={r.variant!.sku_code} value={r.variant!.sku_code}>
                      {r.size.name}
                    </option>
                  ))}
                </select>
                <select name="qty" aria-label="数量" defaultValue="1">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
                <button className="btn" type="submit">
                  カートに入れる
                </button>
                <Link className="btn sub" href="/cart">
                  カートを見る
                </Link>
              </form>
            )}
          </div>

          {/* ---------------- F-206 レビュー（AP-104・AP-105）。R-32 ---------------- */}
          <h3 id="reviews" style={{ fontSize: 15, margin: "24px 0 8px" }}>レビュー{rv ? `（${rv.count}件${rv.average !== null ? `・平均 ★${rv.average}` : ""}）` : ""}</h3>
          {one(sp.review) === "posted" ? <p className="ok">レビューを投稿しました。</p> : null}
          {reviewErr ? (
            <p className="err">{({ "ERR-1001": "本文を入力してください", "ERR-1003": "評価は1〜5、本文は1000文字以内です",
                                    "ERR-1102": "ご購入いただいた商品だけレビューを書けます", "ERR-1216": "この商品のレビューは投稿済みです" } as Record<string, string>)[reviewErr] ?? `投稿できませんでした（${reviewErr}）`}</p>
          ) : null}
          {rv && rv.reviews.length > 0 ? (
            <ul className="reviews" style={{ listStyle: "none", padding: 0 }}>
              {rv.reviews.map((r, i) => (
                <li key={i} style={{ borderTop: "1px solid #eee", padding: "8px 0" }}>
                  <strong>{"★".repeat(r.rating)}{"☆".repeat(5 - r.rating)}</strong> <small className="note">{r.posted_at}{r.mine ? "（あなたのレビュー）" : ""}</small>
                  <br />{r.body}
                </li>
              ))}
            </ul>
          ) : <p className="meta">まだレビューはありません。</p>}
          {rv?.my_status === "can_post" ? (
            <form action={postReviewAction} className="cartbox">
              <input type="hidden" name="product_code" value={p.product_code} />
              <label>評価{" "}
                <select name="rating" defaultValue="5" aria-label="評価">
                  {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{"★".repeat(n)}</option>)}
                </select>
              </label>
              <label style={{ display: "block", marginTop: 8 }}>本文（1000文字まで）
                <textarea name="body" rows={3} maxLength={1000} style={{ width: "100%" }} />
              </label>
              <button type="submit" className="btn">レビューを投稿する</button>
            </form>
          ) : rv?.my_status === "guest" ? (
            <p className="meta">ご購入いただいた会員の方は、<Link href="/login">ログイン</Link>するとレビューを書けます。</p>
          ) : rv?.my_status === "not_purchased" ? (
            <p className="meta">レビューは、この商品をご購入いただいた方（発送済み）が書けます。</p>
          ) : null}

          {/* ★返品の条件は買う前に見られる（F-501・AT-125） */}
          <p className="meta" style={{ marginTop: 16 }}>
            返品は出荷日から17日以内・未使用タグ付きのものに限ります。<Link href="/about/returns">返品について</Link>
          </p>

        </div>
      </div>
    </main>
  );
}
