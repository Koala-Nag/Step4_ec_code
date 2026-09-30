// 読み込み中（R-28 (d)）。★サーバから返るまでのあいだ、白い画面にしない。
export default function Loading() {
  return (
    <main className="wrap" aria-busy="true">
      <p className="loading">カートを読み込んでいます…</p>
      <div className="skline" /><div className="skline" /><div className="skline short" />
    </main>
  );
}
