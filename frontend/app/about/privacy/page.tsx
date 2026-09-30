// SCR-12 静的ページ｜プライバシーポリシー（F-1101。R-28）。
// ★Could なので中身は最低限。★検証用のサイトなので、実在の事業者の情報は書かない。
import Link from "next/link";

export const metadata = { title: "プライバシーポリシー" };

export default function Page() {
  return (
    <main className="wrap narrow doc">
      <p className="crumb"><Link href="/">トップ</Link> ／ プライバシーポリシー</p>
      <h1 className="h1">プライバシーポリシー</h1>
      <p className="note">このサイトは検証用です。以下は、実際のサービスで定めるべき項目の要旨です。</p>
      <h2 className="h2">取得する情報</h2>
      <p>氏名・メールアドレス・お届け先・電話番号・ご注文の内容。クレジットカードの番号は当サイトでは受け取りません（決済代行の画面で入力します）。</p>
      <h2 className="h2">利用の目的</h2>
      <p>ご注文の処理、商品の発送、ご連絡（注文確定・発送・返品などのメール）のために使います。</p>
      <h2 className="h2">第三者への提供</h2>
      <p>商品の配送に必要な範囲で配送会社に、決済に必要な範囲で決済代行会社に提供します。</p>

    </main>
  );
}
