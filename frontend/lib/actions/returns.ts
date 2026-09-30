"use server";
// 返品の操作（R-31）。★Server Action。ブラウザは Next.js だけを叩く（4.1.1）。
//
// ★画面がボタンを隠すことを権限の代わりにしない（4.1.2）。API が必ず判定する。
// ★結果はクエリ文字列の ok / err で戻す（既存の画面と同じ形）。
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api/client";
import * as api from "@/lib/api/returns";

const s = (f: FormData, k: string) => String(f.get(k) ?? "").trim();
const code = (e: unknown) => (e instanceof ApiError ? e.code : "ERR-1401");

// ---------------- 客：AP-401 返品申請（F-502）----------------
// ★送るのは「行番号と数・理由」だけ。返金額も期限の判定も送らない（4.5 ⑦）
export async function applyReturnAction(f: FormData): Promise<void> {
  const no = s(f, "order_no");
  const lines = [...f.keys()]
    .filter((k) => k.startsWith("qty_"))
    .map((k) => ({ line_no: Number(k.slice(4)), qty: Number(f.get(k) ?? 0) }))
    .filter((l) => l.qty > 0);
  const back = `/orders/${encodeURIComponent(no)}`;
  let to = "";
  try {
    const r = await api.applyReturn({ order_no: no, lines, reason_code: s(f, "reason_code"),
                                      reason_text: s(f, "reason_text") || null });
    to = `${back}/returns/${encodeURIComponent(r.data.return_no)}?applied=1`;
  } catch (e) {
    to = `${back}/return?err=${encodeURIComponent(code(e))}`;
  }
  revalidatePath(`${back}/detail`);
  redirect(to);
}

// ---------------- 運営：AP-B25〜B30 ----------------
async function run(no: string, fn: () => Promise<unknown>, ok: string, okPath?: string): Promise<void> {
  const path = `/admin/returns/${encodeURIComponent(no)}`;
  let to = `${okPath ?? path}?ok=${encodeURIComponent(ok)}`;
  try {
    await fn();
  } catch (e) {
    to = `${path}?err=${encodeURIComponent(code(e))}`;
  }
  revalidatePath(path);
  revalidatePath("/admin/returns");
  redirect(to);
}

export async function approveReturnAction(f: FormData): Promise<void> {
  const no = s(f, "return_no");
  await run(no, () => api.approveReturn(no, s(f, "fee_bearer")), "承認しました。お客様に返送のご案内（MSG-12）を送りました");
}

export async function rejectReturnAction(f: FormData): Promise<void> {
  const no = s(f, "return_no");
  await run(no, () => api.rejectReturn(no, s(f, "reason")), "却下しました。お客様に理由（MSG-13）を送りました");
}

export async function receiveReturnAction(f: FormData): Promise<void> {
  const no = s(f, "return_no");
  await run(no, () => api.receiveReturn(no, s(f, "staff_name")), "受領を記録しました");
}

export async function inspectReturnAction(f: FormData): Promise<void> {
  const no = s(f, "return_no");
  // ★結果を選んだ明細だけ送る（明細ごとに記録できる。F-503c）
  const lines = [...f.keys()]
    .filter((k) => k.startsWith("result_"))
    .map((k) => ({ line_no: Number(k.slice(7)), result: s(f, k), note: s(f, `note_${k.slice(7)}`) || null }))
    .filter((l) => l.result === "pass" || l.result === "fail");
  await run(no, () => api.inspectReturn(no, s(f, "staff_name"), lines), "検品の結果を記録しました");
}

export async function restockReturnAction(f: FormData): Promise<void> {
  const no = s(f, "return_no");
  // ★戻し終えると、その申請は倉庫の一覧から外れる（F-507「倉庫には返送待ちと受領だけ」）。
  //   詳細に戻すと倉庫には「見つかりません」になる（R-31 の1周で踏んだ）。★一覧に戻す
  await run(no, () => api.restockReturn(no, s(f, "staff_name")),
            `${no} の合格品を倉庫の在庫に戻しました`, "/admin/returns");
}

export async function disposalReturnAction(f: FormData): Promise<void> {
  const no = s(f, "return_no");
  const lines = [...f.keys()]
    .filter((k) => k.startsWith("disposal_"))
    .map((k) => ({ line_no: Number(k.slice(9)), disposal: s(f, k) }))
    .filter((l) => l.disposal === "return" || l.disposal === "discard");
  await run(no, () => api.disposalReturn(no, lines), "不合格品の扱いを記録しました");
}

export async function refundReturnAction(f: FormData): Promise<void> {
  const no = s(f, "return_no");
  await run(no, () => api.refundReturn(no), "返金を実行しました。お客様に返金完了（MSG-08）を送りました");
}
