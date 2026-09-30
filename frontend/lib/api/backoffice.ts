// 販売設定（AP-B33・F-308）と会員の照会（AP-B31・F-609）。R-33。
import "server-only";

import { adminCall as call } from "./client";

const enc = encodeURIComponent;

export type ConfigRow = Record<string, string | number | null> & { effective_from: string };
export type ConfigField = { name: string; label: string; kind: "rate" | "yen" | "int"; min: number; max: number; unit: string; used: boolean };

export const getSalesConfig = () =>
  call<{ data: { today: string; current: ConfigRow; scheduled: ConfigRow[]; history: ConfigRow[];
                 fields: ConfigField[]; can_edit: boolean } }>("/admin/sales-config");
export const putSalesConfig = (b: Record<string, string>) =>
  call<{ data: { effective_from: string; added: boolean; effective_now: boolean; changed: string[] } }>(
    "/admin/sales-config", { method: "PUT", body: JSON.stringify(b) });

export type MemberRow = { member_id: string; email: string | null; name: string | null; status: number;
                          status_label: string; created_at: string; order_count: number };
export type MemberDetail = {
  member_id: string; email: string | null; name: string | null; tel: string | null; shop_member_id: string | null;
  status: number; status_label: string; locked_until: string | null; created_at: string; updated_at: string;
  addresses: { name: string; zip: string; pref_code: string; address: string; tel: string }[];
  orders: { order_no: string; ordered_at: string; status: number; total_amount: number; receive_method: number }[];
  can_open_order: boolean;
};

export const searchMembers = (q: { email?: string; name?: string; member_id?: string }) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v) p.set(k, v);
  return call<{ data: { searched: boolean; members: MemberRow[] } }>(`/admin/members?${p.toString()}`);
};
export const getMember = (id: string) => call<{ data: MemberDetail }>(`/admin/members/${enc(id)}`);
