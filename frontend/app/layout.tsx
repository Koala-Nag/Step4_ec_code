import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

import { AccountNav } from "./account-nav";
import { ShopOnly } from "./shop-only";

// ★店名は架空（実在の会社の名前・ロゴ・配色を使わない。画面の型 0 章）
export const metadata: Metadata = { title: { default: "DAILY WEAR", template: "%s ｜ DAILY WEAR" } };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <ShopOnly>
          <header className="site">
            <div className="wrap">
              <Link href="/" className="brand">DAILY WEAR</Link>
              <nav className="gnav" aria-label="カテゴリ">
                <Link href="/products?category=TSHIRT">Tシャツ</Link>
                <Link href="/products?category=SHIRT">シャツ</Link>
                <Link href="/products?category=PANTS">パンツ</Link>
                <Link href="/products?category=SKIRT">スカート</Link>
                <Link href="/products?category=BLOUSON">ブルゾン</Link>
              </nav>
              {/* ★ログインしているかどうかは、毎回サーバで確かめる（4.1.2 ③） */}
              <AccountNav />
            </div>
          </header>
        </ShopOnly>
        {children}
        <ShopOnly>
          <footer className="site">
            <div className="wrap">
              <nav aria-label="ご案内">
                <Link href="/orders/lookup">ご注文の照会</Link>
                <Link href="/about/returns">返品について</Link>
                <Link href="/about/legal">特定商取引法に基づく表記</Link>
                <Link href="/about/terms">利用規約</Link>
                <Link href="/about/privacy">プライバシーポリシー</Link>
              </nav>
              <p className="copy">DAILY WEAR（検証用のサイトです。実在の店舗ではありません）</p>
            </div>
          </footer>
        </ShopOnly>
      </body>
    </html>
  );
}
