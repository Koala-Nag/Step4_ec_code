// SCR-05 注文手続き（AP-201 で金額、AP-301 で確定）
//
// ★「支払い方法を選ぶ」と「注文を確定する」を同じ操作にしない（09-05 決定）。
//   確認の段を挟む。押し間違いが取り返せないため。
//   step=input → step=confirm → 送信
import Link from "next/link";

import { SubmitButton } from "@/app/submit-button";
import { randomUUID } from "node:crypto";

import { placeOrderAction } from "@/lib/actions/order";
import { getCart } from "@/lib/api/client";
import { yen } from "@/lib/view/format";

export const dynamic = "force-dynamic";


const ERR_MESSAGE: Record<string, string> = {
  "ERR-1003": "入力できる範囲を超えています。",
  "ERR-1207": "カートの内容が変わりました。ご確認ください。",
  "ERR-1101": "カートを読み込めませんでした。開き直してください。",
  "ERR-1401": "エラーが発生しました。しばらくしてからお試しください。",
};

type SP = { [k: string]: string | string[] | undefined };
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default async function CheckoutPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const err = one(sp.err);
  const step = one(sp.step) === "confirm" ? "confirm" : "input";
  const delivery = one(sp.delivery) === "pickup" ? "pickup" : "ship";

  const { data } = await getCart(delivery);
  const s = data.summary;

  const f = {
    orderer_name: one(sp.orderer_name) ?? "",
    orderer_email: one(sp.orderer_email) ?? "",
    name: one(sp.name) ?? "",
    zip: one(sp.zip) ?? "",
    pref_code: one(sp.pref_code) ?? "13",
    address: one(sp.address) ?? "",
    tel: one(sp.tel) ?? "",
  };

  if (data.items.length === 0) {
    return (
      <main className="wrap">
        <p className="crumb">
          <Link href="/products">商品一覧</Link> ／ 注文手続き
        </p>
        <p className="empty">
          カートが空です。<Link href="/products">商品一覧へ</Link>
        </p>
      </main>
    );
  }

  return (
    <main className="wrap">
      <p className="crumb">
        <Link href="/products">商品一覧</Link> ／ <Link href="/cart">カート</Link> ／ 注文手続き
      </p>

      <ol className="steps">
        <li className={step === "input" ? "on" : "done"}>1. お届け先の入力</li>
        <li className={step === "confirm" ? "on" : ""}>2. 内容の確認</li>
        <li>3. お支払い</li>
      </ol>

      {err ? (
        <p className="freeship">
          {ERR_MESSAGE[err] ?? "処理できませんでした。"}（{err}）
        </p>
      ) : null}

      {step === "input" ? (
        // ★ここは「確認へ進む」だけ。まだ注文しない
        <form className="cartbox" method="get" action="/checkout">
          <input type="hidden" name="step" value="confirm" />
          {/* ★店舗受取（F-405・F-406）は 09-01 の凍結で落とした9件に入っている。
              受取店を選ぶ画面（AP-307）が無いので、選べても「どの店に届くか」が決まらない。
              ★構造は残して入口だけ閉じる（R-23）。
                BR-14 の送料の判定・BR-05 の段1・BR-08b・receive_method は消さない。
              ★AP-307 と F-406 はセットで開ける。片方だけ開けると、
                店に荷物だけ届いて誰に渡したか分からない状態になる（FR-406）。 */}
          <input type="hidden" name="delivery" value="ship" />

          <h3 style={{ fontSize: 15 }}>ご注文者</h3>
          <div className="fields">
            <label>
              お名前
              <input name="orderer_name" defaultValue={f.orderer_name} required />
            </label>
            <label>
              メールアドレス
              <input name="orderer_email" type="email" defaultValue={f.orderer_email} required />
            </label>
          </div>

          <h3 style={{ fontSize: 15 }}>お届け先</h3>
          <div className="fields">
            <label>
              お名前
              <input name="name" defaultValue={f.name} required />
            </label>
            <label>
              郵便番号（7桁）
              <input name="zip" defaultValue={f.zip} pattern="[0-9]{7}" required />
            </label>
            <label>
              都道府県コード
              <input name="pref_code" defaultValue={f.pref_code} pattern="[0-9]{2}" required />
            </label>
            <label>
              住所
              <input name="address" defaultValue={f.address} required />
            </label>
            <label>
              電話番号
              <input name="tel" defaultValue={f.tel} pattern="[0-9]{10,11}" required />
            </label>
          </div>

          <button className="btn" type="submit" style={{ marginTop: 14 }}>
            確認へ進む
          </button>
        </form>
      ) : (
        <>
          <div className="cartbox">
            <h3 style={{ marginTop: 0, fontSize: 15 }}>ご注文の内容</h3>
            {data.items.map((it) => (
              <p key={it.sku_code} className="meta" style={{ margin: "6px 0" }}>
                {it.product_name}（{it.color_name} / {it.size_name}）× {it.qty}　{yen(it.line_amount)}
              </p>
            ))}
            <h3 style={{ fontSize: 15 }}>お届け先</h3>
            <p className="meta" style={{ margin: 0 }}>
              {f.name}／〒{f.zip}／{f.address}／{f.tel}
              <br />
              受け取り方法：{delivery === "pickup" ? "店舗受取" : "配送"}
            </p>
          </div>

          <table className="sumtable">
            <tbody>
              <tr>
                <td>商品合計</td>
                <td>{yen(s.item_total)}</td>
              </tr>
              {s.discount > 0 ? (
                <tr>
                  <td>割引{s.coupon ? `（${s.coupon.name}）` : ""}</td>
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

          <p className="meta" style={{ marginTop: 16 }}>
            ※「お支払いへ進む」を押すと注文が作られ、決済代行の画面へ移ります。
          </p>

          <form action={placeOrderAction} style={{ marginTop: 8, display: "flex", gap: 10 }}>
            {Object.entries({ ...f, delivery }).map(([k, v]) => (
              <input key={k} type="hidden" name={k} value={String(v)} />
            ))}
            {/* ★冪等キー。二重送信・再読み込みで注文が2つできないようにする（N-40） */}
            <input type="hidden" name="idem" value={randomUUID()} />
            <SubmitButton pending="注文を作っています…">お支払いへ進む</SubmitButton>
            <Link
              className="btn sub"
              href={`/checkout?${new URLSearchParams({ ...f, delivery }).toString()}`}
            >
              入力に戻る
            </Link>
          </form>
        </>
      )}
    </main>
  );
}
