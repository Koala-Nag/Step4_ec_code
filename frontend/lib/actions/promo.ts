"use server";
// 拠点の登録・編集（F-809）とクーポン管理（F-1001）の操作。R-32。
// ★判定は API。画面はそろえて送るだけ（4.1.2）。結果はクエリ文字列の ok / err で戻す。
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api/client";
import * as api from "@/lib/api/promo";

const s = (f: FormData, k: string) => String(f.get(k) ?? "").trim();
const code = (e: unknown) => (e instanceof ApiError ? e.code : "ERR-1401");
const field = (e: unknown) => (e instanceof ApiError && e.detail && typeof e.detail.field === "string" ? e.detail.field : "");

function locationBody(f: FormData): api.LocationInput {
  return {
    name: s(f, "name"), pref_code: s(f, "pref_code"), zip: s(f, "zip"), address: s(f, "address"), tel: s(f, "tel"),
    business_days: f.getAll("weekday").map((v) => Number(v)), cutoff_time: s(f, "cutoff_time"),
  };
}

// ---------------- 拠点 ----------------
export async function createLocationAction(f: FormData): Promise<void> {
  const codeIn = s(f, "location_code").toUpperCase();
  let to = `/admin/locations/${encodeURIComponent(codeIn)}?ok=${encodeURIComponent("拠点を登録しました")}`;
  try {
    await api.createLocation({ ...locationBody(f), location_code: codeIn, kind: Number(s(f, "kind")),
                               ec_saleable: s(f, "ec_saleable") === "1" });
  } catch (e) {
    to = `/admin/locations/new?err=${encodeURIComponent(code(e))}&field=${encodeURIComponent(field(e))}`;
  }
  revalidatePath("/admin/locations");
  redirect(to);
}

export async function editLocationAction(f: FormData): Promise<void> {
  const c = s(f, "location_code");
  const path = `/admin/locations/${encodeURIComponent(c)}`;
  let q = `ok=${encodeURIComponent("保存しました。★これから作る出荷指示の発送予定日に効きます（作った出荷は変えません）")}`;
  try {
    await api.editLocation(c, locationBody(f));
  } catch (e) {
    q = `err=${encodeURIComponent(code(e))}&field=${encodeURIComponent(field(e))}`;
  }
  revalidatePath(path);
  revalidatePath("/admin/locations");
  redirect(`${path}?${q}`);
}

export async function holidayAction(f: FormData): Promise<void> {
  const c = s(f, "location_code");
  const path = `/admin/locations/${encodeURIComponent(c)}`;
  const del = s(f, "remove");
  let q = `ok=${encodeURIComponent(del ? `${del} を休業日から外しました` : "休業日を追加しました")}`;
  try {
    if (del) await api.removeHoliday(c, del);
    else await api.addHoliday(c, s(f, "holiday"));
  } catch (e) {
    q = `err=${encodeURIComponent(code(e))}&field=holiday`;
  }
  revalidatePath(path);
  redirect(`${path}?${q}`);
}

// ---------------- クーポン ----------------
function couponBody(f: FormData): api.CouponInput {
  const num = (k: string) => (s(f, k) === "" ? null : Number(s(f, k)));
  const kind = s(f, "target_kind") || "all";
  const ids = kind === "category" ? f.getAll("target_category").map(String)
    : kind === "product" ? s(f, "target_products").split(/[\s,、]+/).filter(Boolean) : [];
  return {
    name: s(f, "name"), discount_type: s(f, "discount_type"), discount_value: Number(s(f, "discount_value") || 0),
    start_at: s(f, "start_at"), end_at: s(f, "end_at"), min_amount: Number(s(f, "min_amount") || 0),
    total_limit: num("total_limit"), per_member_limit: num("per_member_limit"),
    clear_total_limit: s(f, "total_limit") === "", clear_per_member_limit: s(f, "per_member_limit") === "",
    target_kind: kind, target_ids: ids,
  };
}

export async function createCouponAction(f: FormData): Promise<void> {
  const c = s(f, "coupon_code").toUpperCase();
  let to = `/admin/coupons?ok=${encodeURIComponent(`クーポン ${c} を作りました`)}`;
  try {
    await api.createCoupon({ ...couponBody(f), coupon_code: c });
  } catch (e) {
    to = `/admin/coupons?err=${encodeURIComponent(code(e))}&field=${encodeURIComponent(field(e))}`;
  }
  revalidatePath("/admin/coupons");
  redirect(to);
}

export async function editCouponAction(f: FormData): Promise<void> {
  const c = s(f, "coupon_code");
  const path = `/admin/coupons/${encodeURIComponent(c)}`;
  let q = `ok=${encodeURIComponent("保存しました")}`;
  try {
    await api.editCoupon(c, couponBody(f));
  } catch (e) {
    q = `err=${encodeURIComponent(code(e))}&field=${encodeURIComponent(field(e))}`;
  }
  revalidatePath(path);
  revalidatePath("/admin/coupons");
  redirect(`${path}?${q}`);
}
