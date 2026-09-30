"use server";
// お気に入り・レビュー・会員情報の操作（R-32）。★Server Action。ブラウザは Next.js だけを叩く（4.1.1）。
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api/client";
import * as api from "@/lib/api/mypage";

const s = (f: FormData, k: string) => String(f.get(k) ?? "").trim();
const code = (e: unknown) => (e instanceof ApiError ? e.code : "ERR-1401");

// ★戻り先は自分のサイトの中だけ（外へ飛ばさない）
const back = (f: FormData, fallback: string) => {
  const b = s(f, "back");
  return b.startsWith("/") && !b.startsWith("//") ? b : fallback;
};
const withQ = (path: string, q: string) => `${path}${path.includes("?") ? "&" : "?"}${q}`;

// ---------------- AP-107 お気に入り ----------------
export async function toggleFavoriteAction(f: FormData): Promise<void> {
  const p = s(f, "product_code");
  const to = back(f, `/products/${encodeURIComponent(p)}`);
  let q = s(f, "on") === "1" ? "fav=added" : "fav=removed";
  try {
    if (s(f, "on") === "1") await api.addFavorite(p);
    else await api.removeFavorite(p);
  } catch (e) {
    // ★ゲスト（ERR-1101）はログインへ。戻り先は商品に
    if (code(e) === "ERR-1101") redirect("/login");
    q = `err=${encodeURIComponent(code(e))}`;
  }
  revalidatePath("/mypage/favorites");
  redirect(withQ(to, q));
}

// ---------------- AP-105 レビュー ----------------
export async function postReviewAction(f: FormData): Promise<void> {
  const p = s(f, "product_code");
  const to = `/products/${encodeURIComponent(p)}`;
  let q = "review=posted#reviews";
  try {
    await api.postReview(p, Number(s(f, "rating") || 0), String(f.get("body") ?? ""));
  } catch (e) {
    q = `review_err=${encodeURIComponent(code(e))}#reviews`;
  }
  revalidatePath(to);
  redirect(`${to}?${q}`);
}

// ---------------- AP-504 会員情報 ----------------
export async function updateProfileAction(f: FormData): Promise<void> {
  let q = "ok=1";
  try {
    await api.patchProfile({ name: s(f, "name"), tel: s(f, "tel") });
  } catch (e) {
    q = `err=${encodeURIComponent(code(e))}`;
  }
  revalidatePath("/", "layout");          // ★ヘッダの「◯◯ 様」も変わる
  redirect(`/mypage/profile?${q}`);
}
