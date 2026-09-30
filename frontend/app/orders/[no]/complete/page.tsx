// SCR-06 注文完了（結果の表示）
//
// ★画面は result とエラーコードで分岐する。文言では分岐しない（4.1.4）。
import Link from "next/link";

export const dynamic = "force-dynamic";

type SP = { [k: string]: string | string[] | undefined };
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

const VIEW: Record<string, { title: string; body: string; tone: string }> = {
  allocated: {
    title: "ご注文ありがとうございました",
    body: "在庫を確保しました。準備ができ次第、発送のご案内をお送りします。",
    tone: "ok",
  },
  declined: {
    title: "お支払いを確認できませんでした",
    body: "認証または与信が通りませんでした。注文詳細の「お支払い手続きへ進む」から、お支払い方法を変えてお手続きいただけます。会員でない方は、注文番号とメールアドレスで照会してから進めます。",
    tone: "warn",
  },
  payment_pending: {
    title: "お支払いの確認が必要です",
    body: "決済の応答を確認できませんでした。結果はメールでお知らせします。注文詳細（会員でない方は照会）から状況を確かめられます。",
    tone: "warn",
  },
  allocation_failed: {
    title: "在庫を確保できませんでした",
    body: "ご注文はキャンセルされました。決済は行われていません。",
    tone: "warn",
  },
  error: {
    title: "処理できませんでした",
    body: "しばらくしてからお試しください。",
    tone: "warn",
  },
};

export default async function Complete({
  params,
  searchParams,
}: {
  params: Promise<{ no: string }>;
  searchParams: Promise<SP>;
}) {
  const { no } = await params;
  const sp = await searchParams;
  const result = one(sp.result) ?? "error";
  const err = one(sp.err);
  const v = VIEW[result] ?? VIEW.error;
  const shipments = Number(one(sp.shipments) ?? 1);

  return (
    <main className="wrap">
      <p className="crumb">注文完了</p>
      <div className={`result ${v.tone}`}>
        <h2 style={{ margin: "0 0 8px", fontSize: 20 }}>{v.title}</h2>
        <p style={{ margin: 0 }}>{v.body}</p>
      </div>
      {/* ★2拠点に分かれたときは、ここで伝える（AT-131・FR-306）。
          ★確認メールにも同じ断りが入る。片方だけにしない */}
      {shipments >= 2 ? (
        <p className="note" style={{ marginTop: 14 }}>
          ※ 商品は{shipments}つに分けてお届けします。送料は1回ぶんのみです。
        </p>
      ) : null}
      <p className="meta" style={{ marginTop: 18 }}>
        注文番号：<strong>{no}</strong>
        {err ? (
          <>
            <br />
            エラーコード：{err}
          </>
        ) : null}
      </p>
      <p style={{ marginTop: 22, display: "flex", gap: 10, flexWrap: "wrap" }}>
        {result === "declined" || result === "payment_pending" || result === "allocated" ? (
          <>
            <Link className="btn" href={`/orders/${encodeURIComponent(no)}/detail`}>
              注文の詳細を見る（会員の方）
            </Link>
            {/* ★ゲストは照会から（F-313）。注文番号は入れておく。メールアドレスは入力してもらう */}
            <Link className="btn sub" href={`/orders/lookup?order_no=${encodeURIComponent(no)}`}>
              注文を照会する（会員でない方）
            </Link>
          </>
        ) : null}
        <Link className="btn sub" href="/products">
          買い物を続ける
        </Link>
      </p>
    </main>
  );
}
