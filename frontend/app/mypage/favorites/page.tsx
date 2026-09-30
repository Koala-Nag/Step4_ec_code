// SCR-10 お気に入り（AP-107・F-108）。R-32。
//
// ★会員だけ。ゲストはログインへ（API も ERR-1101 を返す。入口を隠すだけにしない）。
// ★ログインし直しても残る（サーバの favorite 表に持つ。AT-G03）。
import Link from "next/link";
import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { listFavorites } from "@/lib/api/mypage";
import { toggleFavoriteAction } from "@/lib/actions/mypage";
import { yen } from "@/lib/view/format";

export const dynamic = "force-dynamic";

export default async function FavoritesPage() {
  let favs;
  try {
    favs = (await listFavorites()).data.favorites;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/login");
    throw e;
  }

  return (
    <main className="wrap">
      <p className="crumb"><Link href="/products">商品一覧</Link> ／ お気に入り</p>
      <h1 className="h1">お気に入り</h1>
      {favs.length === 0 ? (
        <p className="empty">お気に入りはまだありません。商品の画面の「お気に入りに追加」から登録できます。<Link href="/products">商品を探す</Link></p>
      ) : (
        <table className="orders">
          <thead><tr><th></th><th>商品</th><th>価格</th><th></th></tr></thead>
          <tbody>
            {favs.map((f) => (
              <tr key={f.product_code}>
                <td style={{ width: 72 }}>{f.image_url ? <img src={f.image_url} alt="" style={{ width: 60 }} /> : null}</td>
                <td>
                  {f.is_published ? <Link href={`/products/${f.product_code}`}>{f.name}</Link> : <>{f.name}<br /><small className="note">公開を終えました</small></>}
                </td>
                <td className="num">{yen(f.price)}</td>
                <td>
                  <form action={toggleFavoriteAction}>
                    <input type="hidden" name="product_code" value={f.product_code} />
                    <input type="hidden" name="on" value="0" />
                    <input type="hidden" name="back" value="/mypage/favorites" />
                    <button type="submit" className="mini">お気に入りから外す</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
