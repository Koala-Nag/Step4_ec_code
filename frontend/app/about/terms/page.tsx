// SCR-12 静的ページ｜利用規約（F-1101。R-28）。
// ★Could なので中身は最低限。★検証用のサイトなので、実在の事業者の情報は書かない。
import Link from "next/link";

export const metadata = { title: "利用規約" };

export default function Page() {
  return (
    <main className="wrap narrow doc">
      <p className="crumb"><Link href="/">トップ</Link> ／ 利用規約</p>
      <h1 className="h1">利用規約</h1>
      <p className="note">このサイトは検証用です。以下は、実際のサービスで定めるべき項目の見出しと要旨です。</p>
      <h2 className="h2">第1条　適用</h2>
      <p>この規約は、当サイトで商品を購入するすべての方に適用されます。</p>
      <h2 className="h2">第2条　会員登録</h2>
      <p>会員登録はメールアドレスの確認をもって完了します。登録しなくてもご注文いただけます。</p>
      <h2 className="h2">第3条　注文と契約の成立</h2>
      <p>在庫を確保し、ご注文確定のメールをお送りした時点で契約が成立します。</p>
      <h2 className="h2">第4条　キャンセル・返品</h2>
      <p>発送の準備に入る前であれば、購入履歴からキャンセルできます。返品は<Link href="/about/returns">返品について</Link>に従います。</p>
      <h2 className="h2">第5条　禁止事項</h2>
      <p>不正な注文、他人の情報の利用、サイトの運営を妨げる行為を禁止します。</p>
    </main>
  );
}
