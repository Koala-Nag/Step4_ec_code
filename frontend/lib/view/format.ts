// 表示の整形（設計 4.1.7・F-104a）。
//
// ★フロントで金額を計算しない（N-35）。ここにあるのは「整形」だけ。
//   計算する関数がこのファイルに現れたら、それは N-35 に反している合図。

/** 金額の表示。★3桁区切り。値そのものは触らない。 */
export function yen(amount: number): string {
  return `¥${Math.trunc(amount).toLocaleString("en-US")}`;
}

/**
 * 該当件数の表示（F-104a・設計 9.2.1d）。
 *
 * ★101件目以降は数えていない。数えると同時20人で 10.6 秒かかることを実測した（R-16）。
 *   打ち切ったときは「100件以上」と出して、正確な数でないことを分かるようにする。
 * ★0件のときも出す。絞り込みが効いていることが分かるように。
 */
export function countLabel(total: number, capped: boolean): string {
  const n = Math.max(0, Math.trunc(total)).toLocaleString("en-US");
  return capped ? `${n}件以上` : `${n}件`;
}

/** サイズの3状態（F-203・設計 4.1.7）。 */
export type SizeState = "ok" | "sold" | "none";

/**
 * ★「もともと取り扱っていない」と「いま売り切れ」を同じ見た目にしない。
 *   同じにすると、客は入荷を待ってしまう。
 *
 *   SKUの行があって在庫あり → ok    ふつう
 *   SKUの行があって0点      → sold  品切れ（薄い灰色）
 *   SKUの行が無い            → none  取り扱いなし（濃い灰色）
 */
export function sizeState(variant: { selectable: boolean } | undefined | null): SizeState {
  if (!variant) return "none";
  return variant.selectable ? "ok" : "sold";
}

/**
 * カードのサイズ展開「S〜XXL」（画面の型 1.3 ⑤）。
 * ★並びはサーバが返した順（サイズの並び順）。ここでは並べ替えない。
 */
export function sizeLabel(sizes: string[]): string {
  if (sizes.length <= 1) return sizes.join("");
  return `${sizes[0]}〜${sizes[sizes.length - 1]}`;
}
