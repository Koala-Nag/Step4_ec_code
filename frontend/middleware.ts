// ゲストのセッションを発行して Cookie に載せるところまで（設計 4.1.4）。
// ★ログイン画面はまだ無い（R-13 ④）。会員機能はこの串では作らない。
import { NextRequest, NextResponse } from "next/server";
import { CART_COOKIE, CART_COOKIE_MAX_AGE, SESSION_COOKIE, newSessionId } from "./lib/session";

export function middleware(req: NextRequest) {
  const res = NextResponse.next();
  if (!req.cookies.get(SESSION_COOKIE)) {
    res.cookies.set(SESSION_COOKIE, newSessionId(), {
      httpOnly: true,   // JS から読ませない
      sameSite: "lax",
      path: "/",
      secure: process.env.NODE_ENV === "production",
    });
  }
  // ★カートキーは別に発行し、30日持たせる（F-301）
  if (!req.cookies.get(CART_COOKIE)) {
    res.cookies.set(CART_COOKIE, newSessionId(), {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: CART_COOKIE_MAX_AGE,
      secure: process.env.NODE_ENV === "production",
    });
  }
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
