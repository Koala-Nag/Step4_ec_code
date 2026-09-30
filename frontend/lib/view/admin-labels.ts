// 運営画面の表示名（要件 2.4・8.2）。★判定はしない。表示だけ。

export const ROLE_LABEL: Record<number, string> = {
  1: "運用管理者", 2: "受注担当", 3: "倉庫スタッフ", 4: "店舗スタッフ", 5: "サポート",
};

/** 8.2 の文言（運営画面で出すぶん）。★コードは API が決める。 */
export const ADMIN_ERR: Record<string, string> = {
  "ERR-1001": "入力してください",
  "ERR-1002": "形式が正しくありません",
  "ERR-1003": "入力できる範囲を超えています",
  "ERR-1004": "選択し直してください",
  "ERR-1101": "ログインしてください",
  "ERR-1102": "この操作は行えません（権限がありません）",
  "ERR-1106": "この拠点の情報は表示できません",
  "ERR-1205": "この申請は現在の状態では操作できません（ほかの人が先に進めた可能性があります）",
  "ERR-1208": "引当済の数量を下回る値は設定できません",
  "ERR-1209": "決済の処理中です。しばらくしてからお試しください",
  "ERR-1215": "見つかりません",
  "ERR-1216": "すでに登録されています",
  "ERR-1217": "使われているため削除できません。無効にしてください",
};

export function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

export function errText(code: string | undefined): string | null {
  if (!code) return null;
  return `${ADMIN_ERR[code] ?? "この操作は行えませんでした"}（${code}）`;
}
