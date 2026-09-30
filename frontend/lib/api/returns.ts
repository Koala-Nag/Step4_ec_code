// 返品の API 呼び出し（AP-401・AP-402・AP-B24〜B30。R-31）。
//
// ★client.ts と同じ call() を通す（X-Internal-Auth はブラウザに出ない。4.1.1）。
// ★返金額・期限・送料の負担の判定は画面で決めない。サーバが判定して返す（4.5 ⑦）。
import "server-only";

import { adminCall as call } from "./client";

const j = (b: unknown) => ({ body: JSON.stringify(b) });
const enc = encodeURIComponent;

// ---------------- 客（会員は自分の注文、ゲストは照会を通った1件。N-27）----------------
export type Returnable = {
  limit_days: number;
  can_apply: boolean;
  lines: { line_no: number; shipped_qty: number; applied_qty: number; returnable_qty: number;
           deadline: string | null; within_deadline: boolean; product_name: string;
           color_name: string; size_name: string; sku_code: string }[];
};
export type ReturnSummary = { return_no: string; status: number; status_label: string; applied_at: string;
                              qty: number; refund_total: number | null };
export type MyReturn = {
  return_no: string; order_no: string; status: number; status_label: string; applied_at: string;
  reject_reason: string | null; return_deadline: string | null; return_fee_bearer: string | null;
  refund_total: number | null; shipping_refund: number | null;
  lines: { line_no: number; sku_code: string; product_name: string; color_name: string; size_name: string;
           qty: number; reason: string; reason_text: string | null; inspect_result: string | null;
           inspect_note: string | null; refund_amount: number | null }[];
};

export const applyReturn = (b: { order_no: string; lines: { line_no: number; qty: number }[];
                                 reason_code: string; reason_text: string | null }) =>
  call<{ data: { return_no: string; status: string } }>("/returns", { method: "POST", ...j(b) });
export const getMyReturn = (no: string) => call<{ data: MyReturn }>(`/returns/${enc(no)}`);

// ---------------- 運営 ----------------
export type AdminReturnRow = { return_no: string; order_no: string; status: number; status_label: string;
                               applied_at: string; refund_total: number; orderer_name: string; qty: number;
                               restock_pending: number };
export type AdminReturn = {
  return_no: string; order_no: string; status: number; status_label: string; applied_at: string;
  orderer_name: string; orderer_email: string | null; reject_reason: string | null; decided_at: string | null;
  return_deadline: string | null; return_fee_bearer: number; return_fee_bearer_label: string;
  received_at: string | null; receiver: string | null; refund_total: number; shipping_refund: number;
  refunded_at: string | null; warehouse: { location_code: string; name: string };
  lines: { line_no: number; sku_code: string; product_name: string; color_name: string; size_name: string;
           qty: number; line_qty: number; unit_price: number; reason: string; reason_text: string | null;
           inspect_result: number | null; inspect_note: string | null; inspected_at: string | null;
           inspector: string | null; disposal: number | null; disposal_label: string | null;
           refund_amount: number; restocked_at: string | null; restocker: string | null }[];
  refund_preview: { lines: Record<string, number>; items: number; shipping_refund: number; refund_total: number;
                    already_refunded: number; capped: boolean } | null;
  can: { approve: boolean; reject: boolean; receive: boolean; inspect: boolean; restock: boolean;
         disposal: boolean; refund: boolean };
};

export const adminListReturns = (q: Record<string, string | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v) p.set(k, v);
  const qs = p.toString();
  return call<{ data: { scope: string; counts: { status: number; label: string; count: number }[];
                        returns: AdminReturnRow[] } }>(`/admin/returns${qs ? `?${qs}` : ""}`);
};
export const adminGetReturn = (no: string) => call<{ data: AdminReturn }>(`/admin/returns/${enc(no)}`);
export const approveReturn = (no: string, fee_bearer: string) =>
  call(`/admin/returns/${enc(no)}/approve`, { method: "POST", ...j({ fee_bearer }) });
export const rejectReturn = (no: string, reason: string) =>
  call(`/admin/returns/${enc(no)}/reject`, { method: "POST", ...j({ reason }) });
export const receiveReturn = (no: string, staff_name: string) =>
  call(`/admin/returns/${enc(no)}/receive`, { method: "POST", ...j({ staff_name }) });
export const inspectReturn = (no: string, staff_name: string,
                              lines: { line_no: number; result: string; note: string | null }[]) =>
  call(`/admin/returns/${enc(no)}/inspect`, { method: "POST", ...j({ staff_name, lines }) });
export const restockReturn = (no: string, staff_name: string) =>
  call(`/admin/returns/${enc(no)}/restock`, { method: "POST", ...j({ staff_name }) });
export const disposalReturn = (no: string, lines: { line_no: number; disposal: string }[]) =>
  call(`/admin/returns/${enc(no)}/disposal`, { method: "POST", ...j({ lines }) });
export const refundReturn = (no: string) =>
  call<{ data: { refund_total: number } }>(`/admin/returns/${enc(no)}/refund`, { method: "POST" });
