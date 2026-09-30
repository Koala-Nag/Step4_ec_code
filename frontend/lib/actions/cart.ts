"use server";
// カートの操作。
//
// ★Server Action なので、ブラウザは Next.js だけを叩く（4.1.1・N-29）。
//   バックエンドへの呼び出しはサーバ側で起き、X-Internal-Auth はブラウザに出ない。
//
// ★失敗したときは 8.2 のエラーコードを URL に載せて戻す。
//   画面はコードで分岐する。文言では分岐しない（4.1.4）。
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, addToCart, applyCoupon, changeCartQty, removeCoupon, removeFromCart } from "@/lib/api/client";

function backTo(formData: FormData, fallback: string): string {
  const to = String(formData.get("redirect_to") ?? "").trim();
  // ★外部へ飛ばさない。自サイト内の絶対パスだけを受ける
  return to.startsWith("/") && !to.startsWith("//") ? to : fallback;
}

async function run(fn: () => Promise<unknown>, back: string, okTo: string): Promise<never> {
  let code: string | null = null;
  try {
    await fn();
  } catch (e) {
    code = e instanceof ApiError ? e.code : "ERR-1401";
  }
  revalidatePath("/cart");
  if (code) {
    const sep = back.includes("?") ? "&" : "?";
    redirect(`${back}${sep}err=${encodeURIComponent(code)}`);
  }
  redirect(okTo);
}

export async function addAction(formData: FormData): Promise<void> {
  const sku = String(formData.get("sku_code") ?? "");
  const qty = Number(formData.get("qty") ?? 1);
  const back = backTo(formData, "/products");
  await run(() => addToCart(sku, qty), back, "/cart");
}

export async function changeQtyAction(formData: FormData): Promise<void> {
  const sku = String(formData.get("sku_code") ?? "");
  const qty = Number(formData.get("qty") ?? 1);
  const back = backTo(formData, "/cart");
  await run(() => changeCartQty(sku, qty), back, back);
}

export async function removeAction(formData: FormData): Promise<void> {
  const sku = String(formData.get("sku_code") ?? "");
  const back = backTo(formData, "/cart");
  await run(() => removeFromCart(sku), back, back);
}

// AP-204 クーポンの適用・解除（F-309。R-29）。
// ★割引額は送らない。コードだけ。額も「使えるか」もサーバが決める（N-35・BR-16）
export async function applyCouponAction(formData: FormData): Promise<void> {
  const code = String(formData.get("coupon_code") ?? "").trim();
  let q = "coupon=applied";
  try {
    await applyCoupon(code);
  } catch (e) {
    const err = e instanceof ApiError ? e.code : "ERR-1401";
    const shortfall = e instanceof ApiError && typeof e.detail?.shortfall === "number" ? `&shortfall=${e.detail.shortfall}` : "";
    q = `err=${encodeURIComponent(err)}${shortfall}`;
  }
  revalidatePath("/cart");
  redirect(`/cart?${q}`);
}

export async function removeCouponAction(): Promise<void> {
  try {
    await removeCoupon();
  } catch {
    // 外すのに失敗しても、カートを開き直せば状態が分かる
  }
  revalidatePath("/cart");
  redirect("/cart?coupon=removed");
}
