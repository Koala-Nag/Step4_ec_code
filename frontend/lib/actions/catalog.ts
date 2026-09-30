"use server";
// 運営が入力する画面の操作（R-27）。★Server Action。ブラウザは Next.js だけを叩く（4.1.1）。
//
// ★画面がボタンを隠すことを権限の代わりにしない（4.1.2）。APIが必ず判定する。
// ★結果はクエリ文字列の ok / err で戻す（既存の運営画面と同じ形）。
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api/client";
import * as api from "@/lib/api/catalog";

const s = (f: FormData, k: string) => String(f.get(k) ?? "").trim();
const n = (f: FormData, k: string) => Number(f.get(k) ?? 0);

function fail(e: unknown): string {
  if (e instanceof ApiError) return e.code;
  return "ERR-1401";
}

async function run(path: string, fn: () => Promise<unknown>, okParam: string): Promise<void> {
  let q = okParam;
  try {
    await fn();
  } catch (e) {
    q = `err=${encodeURIComponent(fail(e))}`;
  }
  revalidatePath(path);
  redirect(`${path}${path.includes("?") ? "&" : "?"}${q}`);
}

// ---------------- 運営者（F-1302）----------------
export async function createOperatorAction(f: FormData): Promise<void> {
  await run("/admin/operators", () => api.createOperator({
    operator_id: s(f, "operator_id"), name: s(f, "name"), email: s(f, "email"),
    password: String(f.get("password") ?? ""), role: n(f, "role"),
    location_code: s(f, "location_code") || null,
  }), `ok=${encodeURIComponent("運営者を登録しました")}`);
}

export async function updateOperatorAction(f: FormData): Promise<void> {
  const id = s(f, "operator_id");
  const loc = s(f, "location_code");
  await run("/admin/operators", () => api.patchOperator(id, {
    name: s(f, "name"), role: n(f, "role"),
    ...(loc ? { location_code: loc } : { clear_location: true }),
  }), `ok=${encodeURIComponent(`${id} を更新しました`)}`);
}

export async function toggleOperatorAction(f: FormData): Promise<void> {
  const id = s(f, "operator_id");
  const active = s(f, "to") === "1";
  await run("/admin/operators", () => api.patchOperator(id, { is_active: active }),
            `ok=${encodeURIComponent(`${id} を${active ? "有効" : "無効"}にしました`)}`);
}

// ---------------- マスタ（F-709）----------------
export async function createMasterAction(f: FormData): Promise<void> {
  const kind = s(f, "kind");
  await run(`/admin/masters/${kind}`, () => api.createMaster(kind, {
    code: s(f, "code"), name: s(f, "name"),
    sort_no: f.get("sort_no") ? n(f, "sort_no") : null,
    parent_code: s(f, "parent_code") || null,
  }), `ok=${encodeURIComponent("登録しました")}`);
}

export async function updateMasterAction(f: FormData): Promise<void> {
  const kind = s(f, "kind"); const code = s(f, "code");
  await run(`/admin/masters/${kind}`, () => api.patchMaster(kind, code, {
    name: s(f, "name"), ...(f.get("sort_no") !== null ? { sort_no: n(f, "sort_no") } : {}),
  }), `ok=${encodeURIComponent(`${code} を更新しました`)}`);
}

export async function toggleMasterAction(f: FormData): Promise<void> {
  const kind = s(f, "kind"); const code = s(f, "code"); const active = s(f, "to") === "1";
  await run(`/admin/masters/${kind}`, () => api.patchMaster(kind, code, { is_active: active }),
            `ok=${encodeURIComponent(`${code} を${active ? "有効" : "無効"}にしました`)}`);
}

export async function deleteMasterAction(f: FormData): Promise<void> {
  const kind = s(f, "kind"); const code = s(f, "code");
  await run(`/admin/masters/${kind}`, () => api.deleteMaster(kind, code),
            `ok=${encodeURIComponent(`${code} を削除しました`)}`);
}

export async function addSizeMapAction(f: FormData): Promise<void> {
  await run("/admin/masters/sizes", () => api.addSizeMap({
    size_code: s(f, "size_code"), common_size_code: s(f, "common_size_code"),
  }), `ok=${encodeURIComponent("サイズ対応を足しました")}`);
}

// ---------------- 商品（F-701〜705）----------------
export async function createProductAction(f: FormData): Promise<void> {
  const code = s(f, "product_code").toUpperCase();
  let to = `/admin/products/${encodeURIComponent(code)}?ok=${encodeURIComponent("商品を登録しました（非公開）")}`;
  try {
    await api.createProduct({
      product_code: code, name: s(f, "name"), category_code: s(f, "category_code"),
      item_type_code: s(f, "item_type_code"), material: s(f, "material") || null,
      description: s(f, "description") || null, price: n(f, "price"),
    });
  } catch (e) {
    to = `/admin/products?err=${encodeURIComponent(fail(e))}`;
  }
  revalidatePath("/admin/products");
  redirect(to);
}

const productPath = (f: FormData) => `/admin/products/${encodeURIComponent(s(f, "product_code"))}`;

export async function updateProductAction(f: FormData): Promise<void> {
  const code = s(f, "product_code");
  await run(productPath(f), () => api.patchProduct(code, {
    name: s(f, "name"), category_code: s(f, "category_code"), item_type_code: s(f, "item_type_code"),
    material: s(f, "material"), description: s(f, "description"), price: n(f, "price"),
  }), `ok=${encodeURIComponent("商品を更新しました")}`);
}

export async function publishAction(f: FormData): Promise<void> {
  const code = s(f, "product_code"); const on = s(f, "to") === "1";
  await run(productPath(f), () => api.patchProduct(code, { is_published: on }),
            `ok=${encodeURIComponent(on ? "公開しました" : "非公開にしました")}`);
}

export async function bulkSkuAction(f: FormData): Promise<void> {
  const code = s(f, "product_code");
  const stocks = f.getAll("stock_location").map((l, i) => ({
    location_code: String(l), qty: Number(f.getAll("stock_qty")[i] ?? 0),
  })).filter((x) => x.qty > 0);
  let q: string;
  try {
    const r = await api.bulkSkus(code, {
      colors: f.getAll("colors").map(String), sizes: f.getAll("sizes").map(String), stocks,
    });
    q = `ok=${encodeURIComponent(`SKUを${r.data.created.length}件作りました` +
      (r.data.skipped.length ? `（すでにある ${r.data.skipped.length}件は作っていません）` : ""))}`;
  } catch (e) {
    q = `err=${encodeURIComponent(fail(e))}`;
  }
  revalidatePath(productPath(f));
  redirect(`${productPath(f)}?${q}`);
}

export async function putStocksAction(f: FormData): Promise<void> {
  const code = s(f, "product_code");
  const items: { sku_code: string; location_code: string; qty: number }[] = [];
  for (const [k, v] of f.entries()) {
    if (!k.startsWith("q__")) continue;
    const [, sku, loc] = k.split("__");
    const orig = f.get(`o__${sku}__${loc}`);
    if (String(v) === String(orig ?? "")) continue;         // ★変えたマスだけ送る
    if (String(v) === "") continue;
    items.push({ sku_code: sku, location_code: loc, qty: Number(v) });
  }
  if (items.length === 0) redirect(`${productPath(f)}?ok=${encodeURIComponent("変更はありません")}`);
  await run(productPath(f), () => api.putStocks(code, items),
            `ok=${encodeURIComponent(`在庫数を${items.length}か所更新しました`)}`);
}

export async function uploadImageAction(f: FormData): Promise<void> {
  const code = s(f, "product_code");
  const file = f.get("file");
  if (!(file instanceof File) || file.size === 0) {
    redirect(`${productPath(f)}?err=ERR-1001`);
  }
  // ★形式の判定はサーバが中身で行う（N-36）。ここは中身をそのまま渡すだけ
  const b64 = Buffer.from(await (file as File).arrayBuffer()).toString("base64");
  await run(productPath(f), () => api.uploadImage(code, s(f, "color_code"), b64),
            `ok=${encodeURIComponent("画像を取り込みました")}`);
}

export async function deleteImageAction(f: FormData): Promise<void> {
  await run(productPath(f), () => api.deleteImage(s(f, "product_code"), s(f, "color_code"), n(f, "sort_no")),
            `ok=${encodeURIComponent("画像を削除しました")}`);
}

export async function moveImageAction(f: FormData): Promise<void> {
  const dir = s(f, "direction") === "up" ? "up" : "down";
  await run(productPath(f), () => api.moveImage(s(f, "product_code"), s(f, "color_code"), n(f, "sort_no"), dir),
            `ok=${encodeURIComponent("並び順を変えました")}`);
}

// ---------------- 店頭への払い出し（F-808）----------------
export async function moveToFloorAction(f: FormData): Promise<void> {
  const sku = s(f, "sku_code"); const qty = n(f, "qty");
  await run("/admin/stocks/move-to-floor", () => api.moveToFloor({
    sku_code: sku, qty, staff_name: s(f, "staff_name"),
  }), `ok=${encodeURIComponent(`${sku} を店頭へ ${qty}点 出しました`)}`);
}

// ---------------- 拠点のEC販売可・一時停止（F-809）／商品×拠点の除外（F-806）。R-30 ----------------
const safeBack = (f: FormData, fallback: string) => {
  const b = s(f, "back");
  return b.startsWith("/admin/") ? b : fallback;
};

export async function toggleLocationAction(f: FormData): Promise<void> {
  const code = s(f, "location_code"); const field = s(f, "field"); const on = s(f, "to") === "1";
  const body = field === "suspended" ? { suspended: on } : { ec_saleable: on };
  const label = field === "suspended" ? (on ? "一時停止にしました" : "一時停止を解除しました")
                                      : (on ? "EC販売可にしました" : "EC販売不可にしました");
  await run(safeBack(f, "/admin/locations"), () => api.patchLocation(code, body),
            `ok=${encodeURIComponent(`${code} を${label}`)}`);
}

export async function exclusionAction(f: FormData): Promise<void> {
  const p = s(f, "product_code"); const l = s(f, "location_code"); const exclude = s(f, "to") === "exclude";
  // ★不可にする＝行を追加（PUT）／可に戻す＝行を削除（DELETE）。非対称な操作（3.2.2 ②）
  await run(safeBack(f, `/admin/products/${encodeURIComponent(p)}`),
            () => (exclude ? api.putExclusion(p, l) : api.deleteExclusion(p, l)),
            `ok=${encodeURIComponent(`${p} × ${l} を${exclude ? "EC販売不可" : "EC販売可"}にしました`)}`);
}
