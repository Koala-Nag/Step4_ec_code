"use client";
// レイアウトそのものが落ちたとき（R-28 (d)）。★ここだけは html と body を自分で持つ。
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="ja">
      <body style={{ fontFamily: "system-ui, sans-serif", padding: 40 }}>
        <h1 style={{ fontSize: 20 }}>エラーが発生しました</h1>
        <p>時間をおいてお試しください。</p>
        <button type="button" onClick={() => reset()}>もう一度読み込む</button>{" "}
        <a href="/">トップへ</a>
      </body>
    </html>
  );
}
