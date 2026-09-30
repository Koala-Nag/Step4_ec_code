"use server";
// 販売設定の保存（AP-B33・F-308）。R-33。★判定は API（過去の適用開始日・範囲）。
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api/client";
import { putSalesConfig } from "@/lib/api/backoffice";

export async function saveSalesConfigAction(f: FormData): Promise<void> {
  const body: Record<string, string> = {};
  for (const [k, v] of f.entries()) if (typeof v === "string") body[k] = v.trim();
  let q = "";
  try {
    const r = (await putSalesConfig(body)).data;
    q = `ok=${encodeURIComponent(r.effective_from)}&now=${r.effective_now ? 1 : 0}&changed=${encodeURIComponent(r.changed.join(","))}`;
  } catch (e) {
    const code = e instanceof ApiError ? e.code : "ERR-1401";
    const field = e instanceof ApiError && e.detail && typeof e.detail.field === "string" ? e.detail.field : "";
    q = `err=${encodeURIComponent(code)}&field=${encodeURIComponent(field)}`;
  }
  revalidatePath("/admin/settings");
  redirect(`/admin/settings?${q}`);
}
