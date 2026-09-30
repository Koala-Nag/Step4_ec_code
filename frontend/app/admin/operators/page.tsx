// SCR-B13 運営者管理（AP-B34・F-1302・AT-202）。
//
// ★運用管理者だけ（2.4）。ほかの役割は API が 403 を返す——画面の出し分けは権限ではない（4.1.2）。
// ★倉庫・店舗は所属拠点が必須。作った店舗スタッフは、ログインすると自店の分しか見えない
//   （拠点を「確かめる」のではなく、在庫・出荷の API が拠点を引数で受け取らない。N-28a）。
import { redirect } from "next/navigation";

import { ApiError, adminMe } from "@/lib/api/client";
import { listLocations, listOperators } from "@/lib/api/catalog";
import {
  createOperatorAction,
  toggleOperatorAction,
  updateOperatorAction,
} from "@/lib/actions/catalog";
import { ROLE_LABEL, errText, one } from "@/lib/view/admin-labels";

export const dynamic = "force-dynamic";

export default async function OperatorsPage({
  searchParams,
}: {
  searchParams: Promise<{ [k: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  let me, ops, locs;
  try {
    me = (await adminMe()).data;
    ops = (await listOperators()).data.operators;
    locs = (await listLocations()).data.locations;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/admin/login");
    if (e instanceof ApiError && e.status === 403) {
      return (
        <main className="wrap">
          <h1 className="h1">運営者管理</h1>
          <p className="err">この操作は行えません（ERR-1102）。運営者の管理は運用管理者だけです。</p>
        </main>
      );
    }
    throw e;
  }

  const LocSelect = ({ name, value }: { name: string; value?: string | null }) => (
    <select name={name} defaultValue={value ?? ""}>
      <option value="">（拠点なし）</option>
      {locs.map((l) => (
        <option key={l.location_code} value={l.location_code}>
          {l.location_code} {l.name}（{l.kind === 1 ? "倉庫" : "店舗"}）
        </option>
      ))}
    </select>
  );
  const RoleSelect = ({ name, value }: { name: string; value?: number }) => (
    <select name={name} defaultValue={String(value ?? 4)}>
      {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>
  );

  return (
    <main className="wrap">
      <h1 className="h1">運営者管理</h1>
      <p className="note">{me.name}（{ROLE_LABEL[me.role]}）</p>
      {one(sp.ok) ? <p className="ok">{one(sp.ok)}</p> : null}
      {errText(one(sp.err)) ? <p className="err">{errText(one(sp.err))}</p> : null}

      <h2 className="h2">運営者を登録する</h2>
      <form action={createOperatorAction} className="gridform">
        <label>ID<input name="operator_id" required placeholder="T003B" /></label>
        <label>名前<input name="name" required placeholder="新宿店（遅番）" /></label>
        <label>メールアドレス<input name="email" type="email" required /></label>
        <label>初期パスワード（8〜128文字）<input name="password" type="password" required minLength={8} /></label>
        <label>役割<RoleSelect name="role" /></label>
        <label>所属拠点（倉庫・店舗は必須）<LocSelect name="location_code" /></label>
        <button type="submit" className="btn">登録する</button>
      </form>

      <h2 className="h2">運営者の一覧</h2>
      <table className="orders">
        <thead>
          <tr><th>ID</th><th>名前・役割・拠点</th><th>メール</th><th>状態</th><th></th></tr>
        </thead>
        <tbody>
          {ops.map((o) => (
            <tr key={o.operator_id} className={o.is_active ? "" : "inactive"}>
              <td><code>{o.operator_id}</code></td>
              <td>
                <form action={updateOperatorAction} className="rowform">
                  <input type="hidden" name="operator_id" value={o.operator_id} />
                  <input name="name" defaultValue={o.name} required />
                  <RoleSelect name="role" value={o.role} />
                  <LocSelect name="location_code" value={o.location_code} />
                  <button type="submit" className="mini">保存</button>
                </form>
              </td>
              <td><small>{o.email}</small></td>
              <td>{o.is_active ? "有効" : <strong>無効</strong>}</td>
              <td>
                {o.operator_id === me.operator_id ? (
                  <span className="can">（自分）</span>
                ) : (
                  <form action={toggleOperatorAction}>
                    <input type="hidden" name="operator_id" value={o.operator_id} />
                    <input type="hidden" name="to" value={o.is_active ? "0" : "1"} />
                    <button type="submit" className="mini">{o.is_active ? "無効にする" : "有効にする"}</button>
                  </form>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
