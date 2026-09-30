// ★登録済みでも未登録でも、必ずこの画面に着く（N-26・8.3.1 ②）。
//   確認の一段をはさんでいるので、「後続の画面が分かれる」経路そのものが無い。
export default function RegisterSentPage() {
  return (
    <main className="wrap narrow">
      <h1>確認メールをお送りしました</h1>
      <p>メール内のURLを開くと、会員登録が完了します。</p>
      <p className="note">URLの有効期限は60分です。</p>
    </main>
  );
}
