// 運営が入力する画面の API 呼び出し（AP-B02・B03・B04・B08・B34。R-27）。
//
// ★client.ts と同じ call() を通す（X-Internal-Auth はブラウザに出ない。4.1.1）。
// ★金額も「作ってよいか」も画面で決めない。サーバが判定して ERR を返す（4.1.2）。
import "server-only";

import { adminCall } from "./client";

export type Location = { location_code: string; name: string; kind: number;
                         ec_saleable: number | boolean; suspended: number | boolean };
export type Operator = { operator_id: string; name: string; email: string; role: number;
                         location_code: string | null; is_active: number | boolean };
export type MasterItem = { code: string; name: string; is_active: number | boolean;
                           sort_no?: number; parent_code?: string | null; used: boolean };
export type AdminProductRow = { product_code: string; name: string; price: number;
                                category_code: string; is_published: number | boolean;
                                sku_count: number; image_count: number; updated_at: string };
export type AdminProductDetail = {
  product: { product_code: string; name: string; category_code: string; item_type_code: string;
             material: string | null; description: string | null; price: number;
             is_published: number | boolean };
  skus: { sku_code: string; color_code: string; size_code: string; color_name: string;
          size_name: string }[];
  stocks: { sku_code: string; location_code: string; section: number; qty: number;
            reserved_qty: number }[];
  images: { color_code: string; sort_no: number; url: string }[];
  can_edit: boolean;
};

const j = (b: unknown) => ({ body: JSON.stringify(b) });
const enc = encodeURIComponent;

export const listLocations = () =>
  adminCall<{ data: { locations: (Location & { pref_code: string; cutoff_time: string; business_days: number })[];
                      prefectures: { pref_code: string; name: string }[]; can_edit: boolean } }>("/admin/locations");

// ---- 運営者（F-1302）----
export const listOperators = () =>
  adminCall<{ data: { operators: Operator[] } }>("/admin/operators");
export const createOperator = (b: { operator_id: string; name: string; email: string;
                                    password: string; role: number; location_code: string | null }) =>
  adminCall("/admin/operators", { method: "POST", ...j(b) });
export const patchOperator = (id: string, b: Record<string, unknown>) =>
  adminCall(`/admin/operators/${enc(id)}`, { method: "PATCH", ...j(b) });

// ---- マスタ（F-709）----
export const listMaster = (kind: string) =>
  adminCall<{ data: { kind: string; items: MasterItem[] } }>(`/admin/masters/${enc(kind)}`);
export const createMaster = (kind: string, b: Record<string, unknown>) =>
  adminCall(`/admin/masters/${enc(kind)}`, { method: "POST", ...j(b) });
export const patchMaster = (kind: string, code: string, b: Record<string, unknown>) =>
  adminCall(`/admin/masters/${enc(kind)}/${enc(code)}`, { method: "PATCH", ...j(b) });
export const deleteMaster = (kind: string, code: string) =>
  adminCall(`/admin/masters/${enc(kind)}/${enc(code)}`, { method: "DELETE" });
export const listSizeMap = () =>
  adminCall<{ data: { size_map: { size_code: string; common_size_code: string }[] } }>(
    "/admin/masters/size-map");
export const addSizeMap = (b: { size_code: string; common_size_code: string }) =>
  adminCall("/admin/masters/size-map", { method: "POST", ...j(b) });

// ---- 商品（F-701〜705）----
export const listAdminProducts = (keyword?: string) =>
  adminCall<{ data: { products: AdminProductRow[] } }>(
    `/admin/products${keyword ? `?keyword=${enc(keyword)}` : ""}`);
export const getAdminProduct = (code: string) =>
  adminCall<{ data: AdminProductDetail }>(`/admin/products/${enc(code)}`);
export const createProduct = (b: Record<string, unknown>) =>
  adminCall("/admin/products", { method: "POST", ...j(b) });
export const patchProduct = (code: string, b: Record<string, unknown>) =>
  adminCall(`/admin/products/${enc(code)}`, { method: "PATCH", ...j(b) });
export const bulkSkus = (code: string, b: { colors: string[]; sizes: string[];
                                            stocks: { location_code: string; qty: number }[] }) =>
  adminCall<{ data: { created: string[]; skipped: string[] } }>(
    `/admin/products/${enc(code)}/skus`, { method: "POST", ...j(b) });
export const putStocks = (code: string, items: { sku_code: string; location_code: string; qty: number }[]) =>
  adminCall(`/admin/products/${enc(code)}/stocks`, { method: "PUT", ...j({ items }) });
export const uploadImage = (code: string, color_code: string, content_base64: string) =>
  adminCall(`/admin/products/${enc(code)}/images`, { method: "POST", ...j({ color_code, content_base64 }) });
export const deleteImage = (code: string, color: string, sort: number) =>
  adminCall(`/admin/products/${enc(code)}/images/${enc(color)}/${sort}`, { method: "DELETE" });
export const moveImage = (code: string, color: string, sort: number, direction: "up" | "down") =>
  adminCall(`/admin/products/${enc(code)}/images/${enc(color)}/${sort}/move`,
            { method: "POST", ...j({ direction }) });

// ---- 店頭への払い出し（F-808）----
export const floorPage = () =>
  adminCall<{ data: { scope: string; can_move: boolean;
                      history: { sku_code: string; location_code: string; qty_before: number;
                                 qty_after: number; staff_name: string | null; created_at: string }[] } }>(
    "/admin/stocks/move-to-floor");
export const moveToFloor = (b: { sku_code: string; qty: number; staff_name: string }) =>
  adminCall<{ data: { backyard_before: number; backyard_after: number; floor_after: number } }>(
    "/admin/stocks/move-to-floor", { method: "POST", ...j(b) });

// ---- 拠点のEC販売可（F-809）・商品×拠点の除外（F-806）・滞留在庫（F-807）。R-30 ----
export type Exclusion = { product_code: string; location_code: string; product_name: string; location_name: string };
export type StagnantRow = {
  location_code: string; location_name: string; kind: number; ec_saleable: boolean; suspended: boolean;
  sku_code: string; product_code: string; product_name: string; color_name: string; size_name: string;
  qty: number; reserved_qty: number; last_sold_at: string; days: number; excluded: boolean; sellable_on_ec: boolean;
};

export const patchLocation = (code: string, b: { ec_saleable?: boolean; suspended?: boolean }) =>
  adminCall(`/admin/locations/${enc(code)}`, { method: "PATCH", ...j(b) });
export const listExclusions = (productCode?: string) =>
  adminCall<{ data: { exclusions: Exclusion[] } }>(
    `/admin/ec-exclusions${productCode ? `?product_code=${enc(productCode)}` : ""}`);
export const putExclusion = (product_code: string, location_code: string) =>
  adminCall("/admin/ec-exclusions", { method: "PUT", ...j({ product_code, location_code }) });
export const deleteExclusion = (product_code: string, location_code: string) =>
  adminCall("/admin/ec-exclusions", { method: "DELETE", ...j({ product_code, location_code }) });
export const getStagnant = () =>
  adminCall<{ data: { days: number; min_qty: number; can_switch_location: boolean;
                      can_switch_exclusion: boolean; rows: StagnantRow[] } }>("/admin/stocks/stagnant");
