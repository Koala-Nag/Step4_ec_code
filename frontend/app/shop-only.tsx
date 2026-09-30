"use client";
// 客の画面だけに出すもの（ヘッダ・フッタ）。★運営の画面（/admin）では出さない（R-28）。
//
// ★見た目の出し分けだけ。権限はサーバが持つ（4.1.2）。
import { usePathname } from "next/navigation";

export function ShopOnly({ children }: { children: React.ReactNode }) {
  const path = usePathname() ?? "";
  if (path === "/admin" || path.startsWith("/admin/")) return null;
  return <>{children}</>;
}
