"use server";
// 運営の操作（R-22）。
//
// ★客側と同じ Cookie（ec_sid）を使い回す。セッションは1つ。
//   ★どちらの種類かはサーバが `session.user_kind` で判断する（R-21）。
//   客のセッションで運営APIは通らないし、その逆も通らない（SEC-706）。
//
// ★画面がボタンを隠すことを権限の代わりにしない（4.1.2）。
//   ここで出し分けても、APIは必ず自分で判定する。
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import {
  ApiError,
  adminCreateShippingInstructions,
  adminLogin,
  adminAddMemo,
  adminCancelOrder,
  adminLogout,
  adminPartialCancel,
  adminReallocate,
  adminReportShortage,
  adminShip,
} from "@/lib/api/client";
import { SESSION_COOKIE, newSessionId } from "@/lib/session";

function cookieOptions() {
  return {
    httpOnly: true as const,
    sameSite: "lax" as const,
    path: "/",
    secure: process.env.NODE_ENV === "production",
  };
}

export async function adminLoginAction(formData: FormData): Promise<never> {
  let sid: string;
  try {
    const res = await adminLogin(String(formData.get("email") ?? ""),
                                String(formData.get("password") ?? ""));
    sid = res.data.session_id;
  } catch (e) {
    // ★未登録・パスワード誤り・ロック中は全部 ERR-1104（8.3.1）
    return redirect(`/admin/login?err=${e instanceof ApiError ? e.code : "ERR-1401"}`);
  }
  const jar = await cookies();
  jar.set(SESSION_COOKIE, sid, cookieOptions());   // ★再発行された値で上書き（SEC-308）
  redirect("/admin/shipments");
}

export async function adminLogoutAction(): Promise<never> {
  try {
    await adminLogout();
  } catch {
    // 失敗しても Cookie は張り替える
  }
  const jar = await cookies();
  jar.set(SESSION_COOKIE, newSessionId(), cookieOptions());
  redirect("/admin/login");
}

export async function instructAction(formData: FormData): Promise<void> {
  const orderNo = String(formData.get("order_no") ?? "");
  try {
    await adminCreateShippingInstructions(orderNo);
  } catch (e) {
    revalidatePath("/admin/orders");
    redirect(`/admin/orders?err=${e instanceof ApiError ? e.code : "ERR-1401"}`);
  }
  revalidatePath("/admin/orders");
  // ★作った出荷を見せる（一覧は件数で切るので、そのままだと出ないことがある。R-32）
  redirect(`/admin/shipments?instructed=1&order_no=${encodeURIComponent(orderNo)}`);
}

export async function shipAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("shipment_id"));
  try {
    await adminShip(id, {
      carrier: String(formData.get("carrier") ?? "") || null,
      tracking_no: String(formData.get("tracking_no") ?? "") || null,
      // ★拠点のアカウントは共有なので、誰がやったかを手入力させる（2.4・8.6）
      staff_name: String(formData.get("staff_name") ?? ""),
    });
  } catch (e) {
    revalidatePath("/admin/shipments");
    redirect(`/admin/shipments?err=${e instanceof ApiError ? e.code : "ERR-1401"}`);
  }
  revalidatePath("/admin/shipments");
  redirect("/admin/shipments?shipped=1");
}

// ------------------------------------------------------------
// R-26  欠品の報告（AP-B21）・再引当（B15）・部分キャンセル（B16）・キャンセル（B14）
// ★金額も「取消か返金か」も画面から送らない。サーバが決める（N-35・BR-17d）
// ------------------------------------------------------------
function errCode(e: unknown): string {
  return encodeURIComponent(e instanceof ApiError ? e.code : "ERR-1401");
}

export async function shortageAction(formData: FormData): Promise<void> {
  const id = Number(formData.get("shipment_id"));
  const lines = formData.getAll("line_no").map((v) => {
    const n = Number(v);
    return { line_no: n, actual_qty: Number(formData.get(`actual_${n}`) ?? 0) };
  });
  try {
    await adminReportShortage(id, {
      lines,
      staff_name: String(formData.get("staff_name") ?? ""),
      reason: String(formData.get("reason") ?? ""),
    });
  } catch (e) {
    revalidatePath("/admin/shipments");
    redirect(`/admin/shipments?err=${errCode(e)}`);
  }
  revalidatePath("/admin/shipments");
  redirect("/admin/shipments?short=1");
}

export async function reallocateAction(formData: FormData): Promise<void> {
  const no = String(formData.get("order_no") ?? "");
  const path = `/admin/orders/${encodeURIComponent(no)}`;
  let q = "";
  try {
    const r = (await adminReallocate(no)).data;
    q = r.reallocated ? "realloc=1" : `realloc_ng=${encodeURIComponent(r.reason ?? "")}`;
  } catch (e) {
    revalidatePath(path);
    redirect(`${path}?err=${errCode(e)}`);
  }
  revalidatePath(path);
  redirect(`${path}?${q}`);
}

export async function partialCancelAction(formData: FormData): Promise<void> {
  const no = String(formData.get("order_no") ?? "");
  const path = `/admin/orders/${encodeURIComponent(no)}`;
  let back = 0;
  try {
    back = (await adminPartialCancel(no)).data.refund_total;
  } catch (e) {
    revalidatePath(path);
    redirect(`${path}?err=${errCode(e)}`);
  }
  revalidatePath(path);
  redirect(`${path}?partial=${back}`);
}

export async function adminCancelAction(formData: FormData): Promise<void> {
  const no = String(formData.get("order_no") ?? "");
  const path = `/admin/orders/${encodeURIComponent(no)}`;
  try {
    await adminCancelOrder(no);
  } catch (e) {
    revalidatePath(path);
    redirect(`${path}?err=${errCode(e)}`);
  }
  revalidatePath(path);
  redirect(`${path}?cancelled=1`);
}

// AP-B18 対応メモ（F-908。R-29）。★追記だけ。直さない・消さない
export async function addMemoAction(formData: FormData): Promise<void> {
  const no = String(formData.get("order_no") ?? "");
  const path = `/admin/orders/${encodeURIComponent(no)}`;
  let q = "memo=1";
  try {
    await adminAddMemo(no, String(formData.get("body") ?? ""));
  } catch (e) {
    q = `err=${errCode(e)}`;
  }
  revalidatePath(path);
  redirect(`${path}?${q}`);
}
