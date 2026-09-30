// SCR-12 静的ページ｜返品について（F-501・AT-125）。
//
// ★買う前に見られる。ログイン不要。文言は lib/view/returns.ts の1か所（注文詳細と同じもの）。
import Link from "next/link";

import { RETURN_POLICY as R } from "@/lib/view/returns";

export const metadata = { title: "返品について" };

export default function ReturnsPolicyPage() {
  return (
    <main className="wrap">
      <p className="crumb"><Link href="/products">商品一覧</Link> ／ 返品について</p>
      <h1 className="h1">返品について</h1>
      <table className="sum policy">
        <tbody>
          <tr><th>返品の期限</th><td>{R.deadline}<br /><small>{R.deadlineNote}</small></td></tr>
          <tr><th>返品できる条件</th><td>{R.condition}<br /><small>{R.conditionNote}</small></td></tr>
          <tr><th>返送先</th><td>{R.destination}</td></tr>
          <tr><th>返送送料</th><td>{R.shippingFee}</td></tr>
          <tr><th>返金</th><td>{R.refund}</td></tr>
        </tbody>
      </table>
    </main>
  );
}
