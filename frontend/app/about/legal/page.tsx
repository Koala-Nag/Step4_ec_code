// SCR-12 静的ページ｜特定商取引法に基づく表記（F-1101。R-28）。
// ★Could なので中身は最低限。★検証用のサイトなので、実在の事業者の情報は書かない。
import Link from "next/link";

export const metadata = { title: "特定商取引法に基づく表記" };

export default function Page() {
  return (
    <main className="wrap narrow doc">
      <p className="crumb"><Link href="/">トップ</Link> ／ 特定商取引法に基づく表記</p>
      <h1 className="h1">特定商取引法に基づく表記</h1>
      <p className="note">このサイトは検証用です。実在の店舗・事業者ではないため、事業者の情報は記載していません。</p>
      <table className="sum policy">
        <tbody>
          <tr><th>販売価格</th><td>各商品のページに税込価格で表示しています。</td></tr>
          <tr><th>商品代金以外の費用</th><td>送料（一定額以上のお買い上げで無料。金額はカートで表示します）。</td></tr>
          <tr><th>お支払い方法</th><td>クレジットカード（3Dセキュア）。</td></tr>
          <tr><th>お支払いの時期</th><td>ご注文時に与信を行い、商品の発送時に確定します。</td></tr>
          <tr><th>商品の引き渡し時期</th><td>在庫を確保したあと、準備ができ次第発送します。発送のご案内をメールでお送りします。</td></tr>
          <tr><th>返品・交換</th><td><Link href="/about/returns">返品について</Link>をご覧ください。</td></tr>
        </tbody>
      </table>
    </main>
  );
}
