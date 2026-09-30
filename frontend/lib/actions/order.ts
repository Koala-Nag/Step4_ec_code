"use server";
// 注文の操作。★Server Action。ブラウザは Next.js だけを叩く（4.1.1・N-29）。
import { redirect } from "next/navigation";

import { revalidatePath } from "next/cache";

import { ApiError, cancelMyOrder, createOrder, lookupOrder, repayOrder, type ShipTo } from "@/lib/api/client";

export async function placeOrderAction(formData: FormData): Promise<void> {
  const ship: ShipTo = {
    name: String(formData.get("name") ?? ""),
    zip: String(formData.get("zip") ?? ""),
    pref_code: String(formData.get("pref_code") ?? ""),
    address: String(formData.get("address") ?? ""),
    tel: String(formData.get("tel") ?? ""),
  };
  const delivery = String(formData.get("delivery") ?? "ship") === "pickup" ? "pickup" : "ship";
  // ★冪等キーは画面が持ち回る（4.1.6・N-40）。
  //   二重送信・再読み込みで注文が2つできないようにするため。
  const idem = String(formData.get("idem") ?? crypto.randomUUID());

  let to = "";
  try {
    const res = await createOrder(
      {
        orderer_name: String(formData.get("orderer_name") ?? ""),
        orderer_email: String(formData.get("orderer_email") ?? ""),
        delivery_type: delivery,
        ship_to: ship,
        // ★金額は送らない。サーバがカートから計算し直す（N-35・SEC-401）
      },
      idem,
    );
    // ブラウザは決済代行の画面へ。★当社を通らない（N-21・CON-08）
    to = res.data.three_ds_url;
  } catch (e) {
    const code = e instanceof ApiError ? e.code : "ERR-1401";
    redirect(`/checkout?err=${encodeURIComponent(code)}`);
  }
  redirect(to);
}

// AP-303 客によるキャンセル（F-909・BR-17f）。
// ★本文は空で送る。「キャンセルできる状態か」はサーバが注文の状態で決める。
//   ボタンを出したあとで出荷指示が入っていれば、ERR-1205 が返る（IT-102）
export async function cancelMyOrderAction(formData: FormData): Promise<void> {
  const no = String(formData.get("order_no") ?? "");
  const path = `/orders/${encodeURIComponent(no)}/detail`;
  try {
    await cancelMyOrder(no);
  } catch (e) {
    const code = e instanceof ApiError ? e.code : "ERR-1401";
    revalidatePath(path);
    redirect(`${path}?err=${encodeURIComponent(code)}`);
  }
  revalidatePath("/orders");
  revalidatePath(path);
  redirect(`${path}?cancelled=1`);
}

// AP-302 再決済（F-314。R-28）。★新しい API ではない。購入履歴の注文詳細から押せる入口を置いた。
// ★金額は送らない（注文の支払総額をサーバが使う。N-35）。冪等キーは押すたびに作る（N-40）。
export async function repayAction(formData: FormData): Promise<void> {
  const no = String(formData.get("order_no") ?? "");
  let to = "";
  try {
    const res = await repayOrder(no, crypto.randomUUID());
    to = res.data.three_ds_url;          // ★決済代行の画面へ。当社を通らない（N-21）
  } catch (e) {
    const code = e instanceof ApiError ? e.code : "ERR-1401";
    to = `/orders/${encodeURIComponent(no)}/detail?err=${encodeURIComponent(code)}`;
  }
  redirect(to);
}

// AP-306 ゲスト注文の照会（F-313・N-27。R-29）。
// ★通ったら、セッションにその注文1件ぶんの照会権が付く。注文詳細は AP-305 を開き直す。
// ★一致しないときは、注文があるかどうかも言わない（ERR-1107。8.2）。
// ★メールアドレスは URL に載せない（入力し直してもらう）。注文番号だけ戻す
export async function lookupAction(formData: FormData): Promise<void> {
  const no = String(formData.get("order_no") ?? "").trim();
  const email = String(formData.get("email") ?? "").trim();
  let to = "";
  try {
    const r = await lookupOrder(no, email);
    to = `/orders/${encodeURIComponent(r.data.order_no)}/detail`;
  } catch (e) {
    const code = e instanceof ApiError ? e.code : "ERR-1401";
    to = `/orders/lookup?order_no=${encodeURIComponent(no)}&err=${encodeURIComponent(code)}`;
  }
  redirect(to);
}
