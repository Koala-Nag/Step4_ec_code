// 拠点の登録・編集（AP-B04・F-809）とクーポン管理（AP-B32・F-1001）。R-32。
import "server-only";

import { adminCall as call } from "./client";

const j = (b: unknown) => ({ body: JSON.stringify(b) });
const enc = encodeURIComponent;

// ---------------- 拠点 ----------------
export type LocationDetail = {
  location_code: string; kind: number; name: string; pref_code: string; zip: string; address: string; tel: string;
  business_days: number; weekdays: number[]; cutoff_time: string; suspended: boolean; ec_saleable: boolean;
  holidays: string[]; prefectures: { pref_code: string; name: string }[]; can_edit: boolean;
};
export type LocationInput = {
  location_code?: string; kind?: number; name: string; pref_code: string; zip: string; address: string; tel: string;
  business_days: number[]; cutoff_time: string; ec_saleable?: boolean;
};

export const getLocation = (code: string) => call<{ data: LocationDetail }>(`/admin/locations/${enc(code)}`);
export const createLocation = (b: LocationInput) => call("/admin/locations", { method: "POST", ...j(b) });
export const editLocation = (code: string, b: Partial<LocationInput>) =>
  call(`/admin/locations/${enc(code)}`, { method: "PATCH", ...j(b) });
export const addHoliday = (code: string, holiday: string) =>
  call(`/admin/locations/${enc(code)}/holidays`, { method: "POST", ...j({ holiday }) });
export const removeHoliday = (code: string, day: string) =>
  call(`/admin/locations/${enc(code)}/holidays/${enc(day)}`, { method: "DELETE" });

// ---------------- クーポン ----------------
export type AdminCoupon = {
  coupon_code: string; name: string; discount_type: "rate" | "amount"; discount_value: number;
  start_at: string; end_at: string; min_amount: number; total_limit: number | null; used_count: number;
  per_member_limit: number | null; target_kind: "all" | "category" | "product"; target_ids: string[];
};
export type CouponInput = {
  coupon_code?: string; name: string; discount_type: string; discount_value: number; start_at: string; end_at: string;
  min_amount: number; total_limit: number | null; per_member_limit: number | null;
  clear_total_limit?: boolean; clear_per_member_limit?: boolean; target_kind: string; target_ids: string[];
};

export const listCoupons = () =>
  call<{ data: { coupons: AdminCoupon[]; categories: { code: string; name: string; parent_code: string | null }[] } }>(
    "/admin/coupons");
export const createCoupon = (b: CouponInput) => call("/admin/coupons", { method: "POST", ...j(b) });
export const editCoupon = (code: string, b: CouponInput) =>
  call(`/admin/coupons/${enc(code)}`, { method: "PATCH", ...j(b) });
