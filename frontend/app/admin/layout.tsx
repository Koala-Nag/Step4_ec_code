// 運営の画面の枠（R-22）。★客の画面とヘッダを分ける。
//
// ★見た目を分けるのは、どちらの立場で操作しているかを取り違えないため。
//   権限そのものはサーバが持つ（4.1.2）。ここは見た目だけ。
import Link from "next/link";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="admin">
      <header className="adminbar">
        <div className="wrap">
          <strong>運営画面</strong>
          <Link href="/admin/orders">注文</Link>
          <Link href="/admin/shipments">出荷</Link>
          <Link href="/admin/returns">返品</Link>
          <Link href="/admin/stocks">在庫</Link>
          <Link href="/admin/stocks/stagnant">滞留在庫</Link>
          <Link href="/admin/stocks/move-to-floor">店頭へ払い出し</Link>
          <Link href="/admin/products">商品</Link>
          <Link href="/admin/locations">拠点</Link>
          <Link href="/admin/coupons">クーポン</Link>
          <Link href="/admin/members">会員</Link>
          <Link href="/admin/settings">販売設定</Link>
          <Link href="/admin/masters/colors">マスタ</Link>
          <Link href="/admin/operators">運営者</Link>
        </div>
      </header>
      {children}
    </div>
  );
}
