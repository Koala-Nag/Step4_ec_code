// クーポンの入力欄（F-1001）。作成と編集で同じ欄を使う（R-32）。
// ★対象（全商品／カテゴリ／商品）を限定すると、割引は対象商品の明細金額の合計に掛かる（BR-12）。
import type { AdminCoupon } from "@/lib/api/promo";

export function CouponFields({ c, categories }: {
  c: AdminCoupon | null;
  categories: { code: string; name: string; parent_code: string | null }[];
}) {
  return (
    <>
      <label>名前<input name="name" defaultValue={c?.name ?? ""} maxLength={50} required /></label>
      <label>割引の方式
        <select name="discount_type" defaultValue={c?.discount_type ?? "amount"}>
          <option value="amount">金額引き（円）</option>
          <option value="rate">割合引き（%）</option>
        </select>
      </label>
      <label>割引の値<input type="number" name="discount_value" min={1} defaultValue={c?.discount_value ?? ""} required /></label>
      <label>最低購入金額（割引前の商品合計。BR-16）<input type="number" name="min_amount" min={0} defaultValue={c?.min_amount ?? 0} /></label>
      <label>開始<input type="datetime-local" name="start_at" defaultValue={c?.start_at ?? ""} required /></label>
      <label>終了<input type="datetime-local" name="end_at" defaultValue={c?.end_at ?? ""} required /></label>
      <label>全体の利用回数の上限（空＝上限なし）<input type="number" name="total_limit" min={1} defaultValue={c?.total_limit ?? ""} /></label>
      <label>会員あたりの上限（空＝上限なし）<input type="number" name="per_member_limit" min={1} defaultValue={c?.per_member_limit ?? ""} /></label>
      <fieldset className="wide">
        <legend>対象（BR-12）</legend>
        <label><input type="radio" name="target_kind" value="all" defaultChecked={!c || c.target_kind === "all"} /> 全商品</label>{" "}
        <label><input type="radio" name="target_kind" value="category" defaultChecked={c?.target_kind === "category"} /> カテゴリ：</label>
        {categories.map((k) => (
          <label key={k.code} style={{ marginRight: 8 }}>
            <input type="checkbox" name="target_category" value={k.code}
                   defaultChecked={c?.target_kind === "category" && c.target_ids.includes(k.code)} />
            {k.parent_code ? "" : "【"}{k.name}{k.parent_code ? "" : "】"}
          </label>
        ))}
        <br />
        <label><input type="radio" name="target_kind" value="product" defaultChecked={c?.target_kind === "product"} /> 商品：</label>
        <input name="target_products" placeholder="P0051, P0052" aria-label="対象の商品コード"
               defaultValue={c?.target_kind === "product" ? c.target_ids.join(", ") : ""} />
        <br /><small className="note">★カテゴリは親（【トップス】など）を選ぶと、その下のカテゴリの商品も対象になります。</small>
      </fieldset>
    </>
  );
}

export const COUPON_FIELD: Record<string, string> = {
  coupon_code: "コード（半角英数大文字20文字まで）", name: "名前", discount_type: "割引の方式",
  discount_value: "割引の値（割合は1〜100）", start_at: "開始", end_at: "終了（開始より後）", min_amount: "最低購入金額",
  total_limit: "全体の上限（1以上。使われた回数より小さくできません）", per_member_limit: "会員あたりの上限",
  target_kind: "対象", target_ids: "対象（1つ以上・存在するもの）",
};

export function couponLabel(c: AdminCoupon): string {
  return c.discount_type === "rate" ? `${c.discount_value}%引き` : `${c.discount_value.toLocaleString()}円引き`;
}
