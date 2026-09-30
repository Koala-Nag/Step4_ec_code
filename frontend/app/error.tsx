"use client";
// 想定外のエラー（R-28 (d)）。★白い画面にしない。★例外の中身は出さない（SEC-611）。
//
// ★文言は 8.2 の ERR-1401 と同じ1種類。原因の違いを客に見せない（8.2 の 14xx）。
import Link from "next/link";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="wrap narrow">
      <div className="result warn">
        <h1 style={{ margin: "0 0 8px", fontSize: 20 }}>エラーが発生しました</h1>
        <p style={{ margin: 0 }}>時間をおいてお試しください。</p>
      </div>
      <p style={{ marginTop: 18, display: "flex", gap: 10 }}>
        <button className="btn" type="button" onClick={() => reset()}>もう一度読み込む</button>
        <Link className="btn sub" href="/">トップへ</Link>
      </p>
    </main>
  );
}
