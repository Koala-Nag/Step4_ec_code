// 読み込み中（R-28 (d)）。★サーバから返るまでのあいだ、白い画面にしない。
export default function Loading() {
  return (
    <main className="wrap" aria-busy="true">
      <p className="loading">商品を読み込んでいます…</p>
      <div className="grid">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="card skel"><div className="skimg" /><div className="skline" /><div className="skline short" /></div>
        ))}
      </div>
    </main>
  );
}
