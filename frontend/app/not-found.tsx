// 見つからない（ERR-1215 と同じ見せ方。R-28 (d)）。
// ★他人の注文も「無い」と同じにする（8.2。403 にすると在ることを教える）。
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="wrap narrow">
      <h1 className="h1">ページが見つかりません</h1>
      <p className="note">公開を終えた商品か、URL が変わった可能性があります。</p>
      <p style={{ display: "flex", gap: 10 }}>
        <Link className="btn" href="/products">商品一覧へ</Link>
        <Link className="btn sub" href="/">トップへ</Link>
      </p>
    </main>
  );
}
