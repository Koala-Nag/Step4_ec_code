// 一覧のURLの組み立て（設計 4.1.7）。
//
// ★画面の部品から切り出してある。判断が1行でも入っているものは、
//   ページの中に置いたままだと単体テストで触れない（単体テスト仕様書 0.4）。
//
// ★ページングは `after`。`offset` は使わない。
//   OFFSET は深いページで 1,408ms かかることを実測した（R-08）。

export type Search = { [k: string]: string | string[] | undefined };

/** クエリ文字列は同じ名前が2回来ることがある。先頭だけ見る。 */
export function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

/** 一覧で持ち回す条件。★`after` はここに入れない（下の href が落とすため）。 */
const CONDITIONS = ["sort", "category", "keyword", "in_stock", "size"] as const;

/**
 * 条件を組み替えたリンクを作る。
 *
 * ★`after` は patch で明示しない限り必ず落ちる。
 *   絞り込みや並び替えを変えたのに前ページの続きから引くと、
 *   「2ページ目の途中から始まる1ページ目」ができあがる（IT-109）。
 */
export function href(base: Search, patch: Record<string, string | undefined>): string {
  const q = new URLSearchParams();
  const merged: Record<string, string | undefined> = {};
  for (const k of CONDITIONS) merged[k] = one(base[k]);
  Object.assign(merged, patch);
  for (const [k, v] of Object.entries(merged)) if (v) q.set(k, v);
  const s = q.toString();
  return `/products${s ? `?${s}` : ""}`;
}
