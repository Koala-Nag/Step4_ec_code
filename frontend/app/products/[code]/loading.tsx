// 読み込み中（R-28 (d)）。★サーバから返るまでのあいだ、白い画面にしない。
export default function Loading() {
  return (
    <main className="wrap" aria-busy="true">
      <p className="loading">商品の詳細を読み込んでいます…</p>
      <div className="detail">
        <div className="skimg tall" />
        <div><div className="skline" /><div className="skline short" /><div className="skline" /></div>
      </div>
    </main>
  );
}
