// 読み込み中（R-28 (d)）。★サーバから返るまでのあいだ、白い画面にしない。
export default function Loading() {
  return (
    <main className="wrap" aria-busy="true">
      <p className="loading">お支払いと在庫を確認しています。画面を閉じずにお待ちください…</p>

    </main>
  );
}
