// 注文状態の表示名（要件定義書 5.4 の「客が見る表示」）。
//
// ★内部の呼び名（出荷指示済）をそのまま客に出さない。5.4 が別の言葉を決めている。
//   「出荷指示済」は運営の言葉、「発送準備中」が客の言葉。
//
// ★キャンセルできるかはここで決めない。サーバが返す `cancellable` に従う（BR-17f）。
//   画面が独自に条件を持つと、AP-303 が受ける条件とずれる（IT-101・102）。

export const ORDER_STATUS_LABEL: Record<number, string> = {
  1: "受付",
  2: "お支払いの手続き中です",
  3: "お支払いの確認が必要です",
  4: "準備中",
  5: "準備中",
  6: "発送準備中",
  7: "確認中",
  8: "一部発送済み",
  9: "発送済み",
  10: "お届け済み",
  11: "キャンセル済み",
};

export function orderStatusLabel(status: number): string {
  return ORDER_STATUS_LABEL[status] ?? "確認中";
}

/** 出荷の状態（E-24）。★客に見せるぶんだけ。 */
export const SHIPMENT_STATUS_LABEL: Record<number, string> = {
  1: "発送準備中",
  2: "発送済み",
  3: "お届け済み",
  4: "店舗に到着",
  5: "お渡し済み",
  6: "確認中",
  7: "キャンセル",
};

export function shipmentStatusLabel(status: number): string {
  return SHIPMENT_STATUS_LABEL[status] ?? "確認中";
}
