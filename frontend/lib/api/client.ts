// バックエンド呼び出しの薄いラッパ（設計 2.2 frontend/lib/api）。
//
// ★ここはサーバ側でしか動かない。ブラウザは Next.js しか呼ばない（設計 4.1.1・N-29）。
//   だから CORS も要らないし、X-Internal-Auth がブラウザに出ることもない。
//
// ★型は openapi.json から生成したものを使う。手で書かない（付録A-0b）。
//   バックエンドが項目名を変えたら、ここのビルドが落ちる。それが狙い。
import "server-only";

import { cookies } from "next/headers";

import type { components } from "./schema";
import { CART_COOKIE, SESSION_COOKIE } from "../session";

export type ProductListItem = components["schemas"]["ProductListItem"];
export type ProductListResponse = components["schemas"]["ProductListResponse"];
export type ProductDetail = components["schemas"]["ProductDetail"];
export type ProductDetailResponse = components["schemas"]["ProductDetailResponse"];
export type ErrorResponse = components["schemas"]["ErrorResponse"];
export type CartData = components["schemas"]["CartData"];
export type CartResponse = components["schemas"]["CartResponse"];
export type CartSummary = components["schemas"]["CartSummary"];
export type CartSummaryResponse = components["schemas"]["CartSummaryResponse"];
export type OrderCreatedResponse = components["schemas"]["OrderCreatedResponse"];
export type OrderResultResponse = components["schemas"]["OrderResultResponse"];

const BASE = process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:8000";
const INTERNAL_AUTH = process.env.INTERNAL_AUTH_TOKEN ?? "dev-internal-token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    // ★8.2 の detail（例：ERR-1212 の shortfall＝不足額）。文言はコードで決め、数字だけここから取る
    readonly detail: Record<string, unknown> | null = null,
  ) {
    super(code);
  }
}

async function call<T>(path: string, init?: RequestInit, extra?: Record<string, string>): Promise<T> {
  const jar = await cookies();
  const sid = jar.get(SESSION_COOKIE)?.value ?? "";
  const cartKey = jar.get(CART_COOKIE)?.value ?? "";

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // 設計 4.1.2 ②。バックエンドへの全リクエストに2つとも付ける
      "X-Internal-Auth": INTERNAL_AUTH,
      "X-Session-Id": sid,
      // ★カートキーはセッションとは別（09-06 決定）
      "X-Cart-Key": cartKey,
      ...(extra ?? {}),
    },
    cache: "no-store",
  });

  if (!res.ok) {
    let code = "ERR-1401";
    let detail: Record<string, unknown> | null = null;
    try {
      const body = (await res.json()) as ErrorResponse & { error?: { detail?: Record<string, unknown> } };
      code = body?.error?.code ?? code;
      detail = body?.error?.detail ?? null;
    } catch {
      // 本文が読めないときはそのまま ERR-1401 として扱う
    }
    throw new ApiError(res.status, code, detail);
  }
  return (await res.json()) as T;
}

// ★R-27。運営の入力画面（lib/api/catalog.ts）から同じ call() を使うための出口。
//   ★call() を複製しない（X-Internal-Auth を付ける場所を2つにしない）
export function adminCall<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  return call<T>(path, init);
}

export type ListParams = {
  limit?: number;
  sort?: "new" | "price_asc" | "price_desc";
  category?: string;
  keyword?: string;
  size?: string;
  color?: string;
  inStock?: boolean;
  after?: string;
};

export function listProducts(p: ListParams = {}): Promise<ProductListResponse> {
  const q = new URLSearchParams();
  if (p.limit) q.set("limit", String(p.limit));
  if (p.sort) q.set("sort", p.sort);
  if (p.category) q.set("category", p.category);
  if (p.keyword) q.set("keyword", p.keyword);
  if (p.size) q.set("size", p.size);
  if (p.color) q.set("color", p.color);
  if (p.inStock) q.set("in_stock", "true");
  if (p.after) q.set("after", p.after);
  const qs = q.toString();
  return call<ProductListResponse>(`/products${qs ? `?${qs}` : ""}`);
}

export function getProduct(code: string): Promise<ProductDetailResponse> {
  return call<ProductDetailResponse>(`/products/${encodeURIComponent(code)}`);
}


// ------------------------------------------------------------
// カート（AP-201・202・203・205）
// ★数量も単価もサーバが決める。ここは渡すだけ（N-35）
// ------------------------------------------------------------
export function getCart(deliveryType: "ship" | "pickup" = "ship"): Promise<CartResponse> {
  return call<CartResponse>(`/cart?delivery_type=${deliveryType}`);
}

export function getCartSummary(
  deliveryType: "ship" | "pickup",
): Promise<CartSummaryResponse> {
  return call<CartSummaryResponse>(`/cart/summary?delivery_type=${deliveryType}`);
}

export function addToCart(skuCode: string, qty: number): Promise<CartResponse> {
  // ★unit_price は送らない。送っても無視されるが、そもそも送らない
  return call<CartResponse>("/cart/items", {
    method: "POST",
    body: JSON.stringify({ sku_code: skuCode, qty }),
  });
}

export function changeCartQty(skuCode: string, qty: number): Promise<CartResponse> {
  return call<CartResponse>(`/cart/items/${encodeURIComponent(skuCode)}`, {
    method: "PATCH",
    body: JSON.stringify({ qty }),
  });
}

export function removeFromCart(skuCode: string): Promise<CartResponse> {
  return call<CartResponse>(`/cart/items/${encodeURIComponent(skuCode)}`, {
    method: "DELETE",
  });
}


// ------------------------------------------------------------
// 注文（AP-301・301a・302）
// ★金額は送らない。サーバがカートから計算し直す（N-35・SEC-401）
// ------------------------------------------------------------
export type ShipTo = {
  name: string; zip: string; pref_code: string; address: string; tel: string;
};

export function createOrder(
  input: { orderer_name: string; orderer_email: string; delivery_type: "ship" | "pickup"; ship_to: ShipTo },
  idempotencyKey: string,
): Promise<OrderCreatedResponse> {
  return call<OrderCreatedResponse>("/orders", {
    method: "POST",
    body: JSON.stringify(input),
  }, { "Idempotency-Key": idempotencyKey });
}

export function authorizeOrder(
  orderNo: string,
  input: { auth_result?: string | null; auth_ref?: string | null },
): Promise<OrderResultResponse> {
  return call<OrderResultResponse>(`/orders/${encodeURIComponent(orderNo)}/authorize`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function repayOrder(orderNo: string, idempotencyKey: string): Promise<OrderCreatedResponse> {
  return call<OrderCreatedResponse>(`/orders/${encodeURIComponent(orderNo)}/repay`, {
    method: "POST",
  }, { "Idempotency-Key": idempotencyKey });
}


// ------------------------------------------------------------
// 認証（AP-501・501a・502・503・504。R-21）
// ★Cookie を張るのはフロント層。ここは値をやりとりするだけ（4.1.1 の層の分け）
// ------------------------------------------------------------
export type LoginData = {
  session_id: string; member_id: string; name: string | null; cart_merged: number;
};

export function registerMember(email: string, password: string): Promise<unknown> {
  return call("/members", { method: "POST", body: JSON.stringify({ email, password }) });
}

export function confirmMember(token: string): Promise<unknown> {
  return call("/members/confirm", { method: "POST", body: JSON.stringify({ token }) });
}

export function loginMember(email: string, password: string): Promise<{ data: LoginData }> {
  return call<{ data: LoginData }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logoutMember(): Promise<unknown> {
  return call("/auth/logout", { method: "POST" });
}

export function requestPasswordReset(email: string): Promise<unknown> {
  return call("/auth/password-reset", { method: "POST", body: JSON.stringify({ email }) });
}

export function confirmPasswordReset(token: string, password: string): Promise<unknown> {
  return call("/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
}

export function getMe(): Promise<{ data: { member_id: string; email: string; name: string | null } }> {
  return call("/me");
}


// ------------------------------------------------------------
// 購入履歴（AP-304・AP-305。串の⑩。R-22）
// ------------------------------------------------------------
export type MyOrder = {
  order_no: string; status: number; ordered_at: string;
  total_amount: number; receive_method: number; cancellable: boolean;
  repayable: boolean;       // ★支払い待ちなら再決済できる（F-314）。判定はサーバ
  viewer?: "member" | "guest";   // ★ゲストは照会（F-313）を通った1件（N-27）
};
export type MyOrderDetail = MyOrder & {
  item_total: number; discount_amount: number; shipping_fee: number; tax_amount: number;
  ship_to: { name: string; zip: string; pref_code: string; address: string; tel: string };
  lines: { line_no: number; sku_code: string; qty: number; unit_price: number;
           product_name: string }[];
  shipments: { id: number; status: number; planned_ship_date: string;
               carrier: string | null; tracking_no: string | null;
               shipped_at: string | null; dest_kind: number }[];
  // ★返品（R-31）。申請できる数と期限はサーバが決める（BR-18）
  returnable: import("./returns").Returnable;
  returns: import("./returns").ReturnSummary[];
};

export function listMyOrders(): Promise<{ data: { orders: MyOrder[] } }> {
  return call("/orders");
}

export function getMyOrder(orderNo: string): Promise<{ data: MyOrderDetail }> {
  return call(`/orders/${encodeURIComponent(orderNo)}/detail`);
}

// AP-303。★本文は空。「キャンセルできる状態か」を画面から送らない（設計 4.2 ③）
export function cancelMyOrder(orderNo: string): Promise<unknown> {
  return call(`/orders/${encodeURIComponent(orderNo)}/cancel`, { method: "POST" });
}


// ------------------------------------------------------------
// 運営（AP-B01・B10・B12・B19・B20。R-22）
// ★この層も同じ call() を通る。X-Internal-Auth はブラウザに出ない（4.1.1）
// ------------------------------------------------------------
export type AdminSession = {
  session_id: string; operator_id: string; name: string;
  role: number; location_code: string | null;
};
export type AdminStock = {
  location_code: string; sku_code: string; section: number;
  qty: number; reserved_qty: number; saleable_qty: number;
};

export function adminListStocks(skuCode?: string):
    Promise<{ data: { scope: string; stocks: AdminStock[] } }> {
  const q = skuCode ? `?sku_code=${encodeURIComponent(skuCode)}` : "";
  return call(`/admin/stocks${q}`);
}

export type AdminShipment = {
  id: number; order_no: string; from_location_code: string; dest_kind: number;
  dest_name: string; dest_zip: string; dest_pref_code: string; dest_address: string;
  status: number; planned_ship_date: string; carrier: string | null;
  tracking_no: string | null; shipped_at: string | null; staff_name: string | null;
  orderer_name: string;
  lines: { line_no: number; qty: number; sku_code: string; product_name: string }[];
};
export type AdminOrder = {
  order_no: string; status: number; total_amount: number; created_at: string;
};

export function adminLogin(email: string, password: string): Promise<{ data: AdminSession }> {
  return call("/admin/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
}

export function adminLogout(): Promise<unknown> {
  return call("/admin/auth/logout", { method: "POST" });
}

export function adminMe(): Promise<{ data: Omit<AdminSession, "session_id"> }> {
  return call("/admin/me");
}

export function adminListOrders(): Promise<{ data: { orders: AdminOrder[] } }> {
  return call("/admin/orders");
}

export function adminCreateShippingInstructions(orderNo: string): Promise<unknown> {
  return call(`/admin/orders/${encodeURIComponent(orderNo)}/shipping-instructions`,
              { method: "POST" });
}

export function adminListShipments(orderNo?: string): Promise<{ data: { scope: string;
                                                        shipments: AdminShipment[] } }> {
  // ★注文番号で絞れる（出荷指示を作った直後に、その注文の出荷を見せる。R-32）
  return call(`/admin/shipments${orderNo ? `?order_no=${encodeURIComponent(orderNo)}` : ""}`);
}

export function adminShip(
  id: number,
  input: { carrier?: string | null; tracking_no?: string | null; staff_name: string },
): Promise<unknown> {
  return call(`/admin/shipments/${id}/ship`, { method: "POST", body: JSON.stringify(input) });
}


// ------------------------------------------------------------
// 欠品・再引当・部分キャンセル・キャンセル（AP-B11・B14・B15・B16・B21。R-26）
// ------------------------------------------------------------
export type AdminOrderDetail = {
  order_no: string; status: number; ordered_at: string; member_id: string | null;
  orderer_name: string; orderer_email: string; receive_method: number;
  ship_to: { name: string; zip: string; pref_code: string; address: string; tel: string };
  item_total: number; discount_amount: number; shipping_fee: number; tax_amount: number;
  total_amount: number; coupon_code: string | null;
  lines: { line_no: number; sku_code: string; product_name: string; qty: number;
           unit_price: number; allocated_discount: number; alloc_status: number;
           alloc_location_code: string | null }[];
  shipments: { id: number; from_location_code: string; dest_kind: number; dest_name: string;
               status: number; planned_ship_date: string; carrier: string | null;
               tracking_no: string | null; staff_name: string | null;
               shipped_at: string | null; short_actual_qty: number | null;
               short_reporter: string | null; short_at: string | null;
               line_nos: number[] }[];
  actions: { cancel: boolean; reallocate: boolean; partial_cancel: boolean };
  memos: { id: number; body: string; at: string; operator_id: string; operator_name: string | null }[];
  can_add_memo: boolean;
  status_log: { from: number | null; to: number; by: number; reason: string | null;
                at: string }[];
  payments: { tx_kind: number; status: number; amount: number; response_code: string | null;
              shipment_id: number | null }[];
};

export function adminGetOrder(orderNo: string): Promise<{ data: AdminOrderDetail }> {
  return call(`/admin/orders/${encodeURIComponent(orderNo)}`);
}

export function adminReportShortage(
  id: number,
  input: { lines: { line_no: number; actual_qty: number }[]; staff_name: string; reason: string },
): Promise<unknown> {
  return call(`/admin/shipments/${id}/shortage`, { method: "POST", body: JSON.stringify(input) });
}

export type ReallocateResult = {
  reallocated: boolean; reason?: string; next?: string;
  shipments?: { from_location_code: string; planned_ship_date: string; lines: number[] }[];
};

export function adminReallocate(orderNo: string): Promise<{ data: ReallocateResult }> {
  return call(`/admin/orders/${encodeURIComponent(orderNo)}/reallocate`, { method: "POST" });
}

export function adminPartialCancel(orderNo: string):
    Promise<{ data: { refund_total: number;
                      cancelled: { shipment_id: number; amount: number; kind: string }[] } }> {
  return call(`/admin/orders/${encodeURIComponent(orderNo)}/partial-cancel`, { method: "POST" });
}

export function adminCancelOrder(orderNo: string): Promise<unknown> {
  return call(`/admin/orders/${encodeURIComponent(orderNo)}/cancel`, { method: "POST" });
}


// ------------------------------------------------------------
// R-29｜ゲスト照会（AP-306）・クーポン（AP-204）・対応メモ（AP-B18）
// ------------------------------------------------------------
export function lookupOrder(orderNo: string, email: string): Promise<{ data: { order_no: string } }> {
  return call("/orders/lookup", { method: "POST", body: JSON.stringify({ order_no: orderNo, email }) });
}

export function applyCoupon(code: string): Promise<CartResponse> {
  return call<CartResponse>("/cart/coupon", { method: "POST", body: JSON.stringify({ coupon_code: code }) });
}

export function removeCoupon(): Promise<CartResponse> {
  return call<CartResponse>("/cart/coupon", { method: "DELETE" });
}

export type AdminMemo = { id: number; body: string; at: string; operator_id: string; operator_name: string | null };

export function adminAddMemo(orderNo: string, body: string): Promise<unknown> {
  return call(`/admin/orders/${encodeURIComponent(orderNo)}/memos`, { method: "POST", body: JSON.stringify({ body }) });
}
