// SCR-04 カート（AP-201・203・205）
//
// ★金額はサーバが計算した値をそのまま出す。画面では足し算しない（N-35）。
// ★受取方法を切り替えると送料が変わる（BR-14・IT-108）。切り替えは AP-205 を引き直す。
import Link from "next/link";

import { applyCouponAction, changeQtyAction, removeAction, removeCouponAction } from "@/lib/actions/cart";
import { getMe } from "@/lib/api/client";
import { getCart } from "@/lib/api/client";
import { yen } from "@/lib/view/format";

export const dynamic = "force-dynamic";


// ★画面はコードで分岐する。文言では分岐しない（4.1.4）
const ERR_MESSAGE: Record<string, string> = {
  "ERR-1003": "入力できる範囲を超えています。",
  "ERR-1002": "形式が正しくありません。",
  "ERR-1202": "これ以上追加できません。",
  // ★同じコードでも画面によって言い方を変える（設計 8.2）。
  //   ここはゲストのカートなので「ログインしてください」ではない
  "ERR-1101": "カートを読み込めませんでした。開き直してください。",
  "ERR-1215": "その商品は見つかりませんでした。",
  "ERR-1401": "エラーが発生しました。しばらくしてからお試しください。",
  // クーポン（8.2・要件 9.5）。★ERR-1212 の「あと◯円」は不足額をサーバから受け取って組み立てる
  "ERR-1001": "クーポンコードを入力してください。",
  "ERR-1203": "このクーポンは使えません。",
  "ERR-1211": "このクーポンは期限が切れています。",
  "ERR-1213": "このクーポンは配布数の上限に達しました。",
  "ERR-1214": "このクーポンはすでにご利用済みです。",
};

function couponMessage(code: string, shortfall: number | null | undefined): string {
  if (code === "ERR-1212") {
    return shortfall != null ? `あと ${yen(shortfall)} のお買い上げで使えます。` : "最低購入金額に届いていません。";
  }
  return ERR_MESSAGE[code] ?? "このクーポンは使えません。";
}

export default async function CartPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const raw = Array.isArray(sp.delivery) ? sp.delivery[0] : sp.delivery;
  const delivery: "ship" | "pickup" = raw === "pickup" ? "pickup" : "ship";

  const { data } = await getCart(delivery);
  const s = data.summary;
  const err = Array.isArray(sp.err) ? sp.err[0] : sp.err;
  const shortfall = Number(Array.isArray(sp.shortfall) ? sp.shortfall[0] : sp.shortfall);
  // ★クーポンは会員だけ（要件 4.3）。入力欄を出すかどうかも、ログインしているかをサーバに聞いて決める
  let member = false;
  try { await getMe(); member = true; } catch { member = false; }
  const coupon = s.coupon;

  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/products">商品一覧</Link> ／ カート
      </p>

      {err && !["ERR-1001", "ERR-1203", "ERR-1211", "ERR-1212", "ERR-1213", "ERR-1214"].includes(err) ? (
        <p className="freeship">{ERR_MESSAGE[err] ?? "操作できませんでした。"}</p>
      ) : null}

      {data.items.length === 0 ? (
        <p className="empty">
          カートは空です。<Link href="/products">商品一覧へ</Link>
        </p>
      ) : (
        <>
          <div>
            {data.items.map((it) => (
              <div className="cartrow" key={it.sku_code}>
                {it.image_url ? <img src={it.image_url} alt={it.product_name} /> : <div />}
                <div>
                  <Link href={`/products/${it.product_code}`}>
                    <strong>{it.product_name}</strong>
                  </Link>
                  <p className="meta" style={{ margin: "4px 0 0" }}>
                    {it.color_name} ／ {it.size_name}
                    <br />
                    単価 {yen(it.unit_price)}
                    {it.saleable_qty < it.qty ? (
                      <>
                        <br />
                        <span style={{ color: "#8a5a00" }}>
                          在庫が {it.saleable_qty} 点に減っています
                        </span>
                      </>
                    ) : null}
                  </p>

                  <form action={changeQtyAction} style={{ marginTop: 10, display: "inline-flex", gap: 8 }}>
                    <input type="hidden" name="sku_code" value={it.sku_code} />
                    <input type="hidden" name="redirect_to" value={`/cart?delivery=${delivery}`} />
                    <select name="qty" defaultValue={String(it.qty)}>
                      {/* ★上限は「99」と「販売可能数」の小さい方（F-301）。サーバが返した値を使う */}
                      {Array.from({ length: Math.max(it.max_qty, 1) }, (_, i) => i + 1).map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                    <button className="btn sub" type="submit">
                      数量を変える
                    </button>
                  </form>

                  <form action={removeAction} style={{ display: "inline", marginLeft: 8 }}>
                    <input type="hidden" name="sku_code" value={it.sku_code} />
                    <input type="hidden" name="redirect_to" value={`/cart?delivery=${delivery}`} />
                    <button className="btn sub" type="submit">
                      削除
                    </button>
                  </form>
                </div>
                <div style={{ textAlign: "right", fontWeight: 600 }}>{yen(it.line_amount)}</div>
              </div>
            ))}
          </div>

          {/* ★受け取り方法の切り替えも外した（R-23）。理由は checkout と同じ。
              ★delivery の受け取り自体は残してある（BR-14 の分岐と UT-107 が見ている）。
                いま来るのは "ship" だけ。 */}

          <table className="sumtable">
            <tbody>
              <tr>
                <td>商品合計</td>
                <td>{yen(s.item_total)}</td>
              </tr>
              {s.discount > 0 ? (
                <tr>
                  <td>割引{coupon ? `（${coupon.name}）` : ""}</td>
                  <td>-{yen(s.discount)}</td>
                </tr>
              ) : null}
              <tr>
                <td>送料</td>
                <td>{s.shipping_fee === 0 ? "無料" : yen(s.shipping_fee)}</td>
              </tr>
              <tr className="total">
                <td>支払総額</td>
                <td>{yen(s.total_amount)}</td>
              </tr>
              <tr>
                <td className="meta">（うち消費税）</td>
                <td className="meta">{yen(s.tax_amount)}</td>
              </tr>
            </tbody>
          </table>

          {s.free_shipping_remain > 0 ? (
            <p className="freeship">
              あと <strong>{yen(s.free_shipping_remain)}</strong> のお買い上げで送料が無料になります
            </p>
          ) : (
            <p className="freeship" style={{ background: "#e8f2e8", color: "#1e5c2e" }}>
              送料は無料です
            </p>
          )}

          {/* ★クーポン（F-309・F-310。R-29）。会員だけ。1注文に1枚（BR-16） */}
          <div className="couponbox">
            <strong>クーポン</strong>
            {!member ? (
              <p className="note" style={{ margin: "6px 0 0" }}>
                クーポンは会員の方がお使いいただけます。<Link href="/login">ログイン</Link>
              </p>
            ) : coupon ? (
              <div style={{ marginTop: 6 }}>
                <p style={{ margin: 0 }}>
                  適用中：<strong>{coupon.name}</strong>（{coupon.coupon_code}）
                  {coupon.usable ? <>　<strong>-{yen(coupon.discount)}</strong></> : null}
                </p>
                {/* ★適用したあとで商品を減らすと使えなくなることがある。外さずに理由を出す */}
                {!coupon.usable && coupon.error_code ? (
                  <p className="err" style={{ margin: "6px 0" }}>{couponMessage(coupon.error_code, coupon.shortfall)}</p>
                ) : null}
                <form action={removeCouponAction} style={{ marginTop: 6 }}>
                  <button type="submit" className="btn sub">クーポンを外す</button>
                </form>
              </div>
            ) : (
              <form action={applyCouponAction} className="rowform" style={{ marginTop: 6 }}>
                <input name="coupon_code" placeholder="クーポンコード" aria-label="クーポンコード" autoComplete="off" />
                <button type="submit" className="btn sub">適用する</button>
              </form>
            )}
            {err && ["ERR-1001", "ERR-1203", "ERR-1211", "ERR-1212", "ERR-1213", "ERR-1214"].includes(err) ? (
              <p className="err" style={{ margin: "6px 0 0" }}>{couponMessage(err, Number.isFinite(shortfall) ? shortfall : null)}</p>
            ) : null}
          </div>

          {/* ★カートから注文手続きへ進む入口（R-28 で見つけた）。
              ★これまで /checkout を直接開かないと注文できなかった——一周すると必ずここで止まる */}
          <p style={{ marginTop: 20, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link className="btn" href="/checkout">ご注文手続きへ進む</Link>
            <Link className="btn sub" href="/products">買い物を続ける</Link>
          </p>

        </>
      )}
    </main>
  );
}
