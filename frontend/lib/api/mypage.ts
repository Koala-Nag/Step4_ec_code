// お気に入り（AP-107）・レビュー（AP-104・105）・会員情報の変更（AP-504 PATCH）。R-32。
//
// ★会員だけの機能は、サーバがセッションで判定する（ゲストは ERR-1101）。画面は入口を出し分けるだけ。
import "server-only";

import { adminCall as call } from "./client";

const j = (b: unknown) => ({ body: JSON.stringify(b) });
const enc = encodeURIComponent;

export type Favorite = { product_code: string; name: string; price: number; is_published: boolean;
                         image_url: string | null; added_at: string };
export type Reviews = { count: number; average: number | null;
                        my_status: "guest" | "not_purchased" | "can_post" | "posted";
                        reviews: { rating: number; body: string; posted_at: string; mine: boolean }[] };

export const listFavorites = () => call<{ data: { favorites: Favorite[] } }>("/favorites");
export const addFavorite = (product_code: string) => call("/favorites", { method: "POST", ...j({ product_code }) });
export const removeFavorite = (code: string) => call(`/favorites/${enc(code)}`, { method: "DELETE" });

export const getReviews = (code: string) => call<{ data: Reviews }>(`/products/${enc(code)}/reviews`);
export const postReview = (code: string, rating: number, body: string) =>
  call(`/products/${enc(code)}/reviews`, { method: "POST", ...j({ rating, body }) });

export const getProfile = () =>
  call<{ data: { member_id: string; email: string; name: string | null; tel: string | null } }>("/me");
export const patchProfile = (b: { name?: string; tel?: string }) => call("/me", { method: "PATCH", ...j(b) });
