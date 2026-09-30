"use server";
// 会員の認証（R-21）。
//
// ★Cookie を張り替えるのはこの層（4.1.1）。バックエンドは値を返すだけ。
//
// ★ログインに成功したら、バックエンドが発行し直したセッションIDで Cookie を上書きする
//   （N-24・SEC-308。セッション固定攻撃）。
//   ★「新しい値を作る」のはバックエンド、「Cookie に載せる」のはここ、と分けてある。
//     フロントで作ると、DB に無い値が Cookie に載ることがある。
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import {
  ApiError,
  confirmMember,
  confirmPasswordReset,
  loginMember,
  logoutMember,
  registerMember,
  requestPasswordReset,
} from "@/lib/api/client";
import { CART_COOKIE, CART_COOKIE_MAX_AGE, SESSION_COOKIE, newSessionId } from "@/lib/session";

/** N-24・SEC-802。Cookie の属性はここ1か所で決める。 */
function cookieOptions() {
  return {
    httpOnly: true as const,          // JS から読ませない（盗まれる経路を1つ減らす）
    sameSite: "lax" as const,         // 他サイトからの POST に付いていかない
    path: "/",
    secure: process.env.NODE_ENV === "production",   // 本番は HTTPS 限定（N-20）
  };
}

function backWith(path: string, code: string): never {
  redirect(`${path}?err=${encodeURIComponent(code)}`);
}

export async function loginAction(formData: FormData): Promise<never> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  let sid: string;
  let memberId: string;
  try {
    const res = await loginMember(email, password);
    sid = res.data.session_id;
    memberId = res.data.member_id;
  } catch (e) {
    // ★未登録・パスワード誤り・ロック中は、すべて ERR-1104（8.3.1 ③）。
    //   ここで分岐しない。画面もコード1つぶんの文言しか持たない
    return backWith("/login", e instanceof ApiError ? e.code : "ERR-1401");
  }

  const jar = await cookies();
  // ★バックエンドが発行し直した値で上書きする（SEC-308）。
  //   ここで前の値を残すと、セッション固定攻撃が通る
  jar.set(SESSION_COOKIE, sid, cookieOptions());

  // ★カートキーを会員IDに切り替える（BR-24a・設計 3.2 T-19）。
  //   バックエンドはゲストの行を会員側へ寄せている。★ここを忘れると、
  //   DB では寄っているのに画面は空のまま——という食い違いになる（R-21 で踏んだ）。
  jar.set(CART_COOKIE, memberId, { ...cookieOptions(), maxAge: CART_COOKIE_MAX_AGE });
  redirect("/");
}

export async function logoutAction(): Promise<never> {
  try {
    await logoutMember();     // ★サーバ側で無効にする（SEC-307）
  } catch {
    // 失敗しても Cookie は落とす。★手元に残すほうが危ない
  }
  const jar = await cookies();
  // ★セッションもカートキーも、ゲストの新しい値に張り替える。
  //   ★カートキーを会員IDのまま残すと、次に同じ端末を使う人に
  //     その会員のカートが見える（共有端末を想定する。要件 2.4 と同じ考え方）。
  //   ★会員のカートは DB に残っている。消すのではなく、指す先を変えるだけ。
  jar.set(SESSION_COOKIE, newSessionId(), cookieOptions());
  jar.set(CART_COOKIE, newSessionId(), { ...cookieOptions(), maxAge: CART_COOKIE_MAX_AGE });
  redirect("/");
}

export async function registerAction(formData: FormData): Promise<never> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");
  try {
    await registerMember(email, password);
  } catch (e) {
    // ★ここに来るのはパスワードの形が悪いときだけ。
    //   「登録済みです」は返ってこない（N-26）
    return backWith("/register", e instanceof ApiError ? e.code : "ERR-1401");
  }
  // ★登録済みでも未登録でも、同じ画面に着く（8.3.1 ②）
  redirect("/register/sent");
}

export async function confirmAction(formData: FormData): Promise<never> {
  const token = String(formData.get("token") ?? "");
  try {
    await confirmMember(token);
  } catch (e) {
    return backWith("/login", e instanceof ApiError ? e.code : "ERR-1401");
  }
  redirect("/login?registered=1");
}

export async function passwordResetRequestAction(formData: FormData): Promise<never> {
  try {
    await requestPasswordReset(String(formData.get("email") ?? ""));
  } catch (e) {
    return backWith("/password-reset", e instanceof ApiError ? e.code : "ERR-1401");
  }
  redirect("/password-reset/sent");
}

export async function passwordResetConfirmAction(formData: FormData): Promise<never> {
  const token = String(formData.get("token") ?? "");
  try {
    await confirmPasswordReset(token, String(formData.get("password") ?? ""));
  } catch (e) {
    return backWith(`/password-reset/${encodeURIComponent(token)}`,
                    e instanceof ApiError ? e.code : "ERR-1401");
  }
  redirect("/login?reset=1");
}
