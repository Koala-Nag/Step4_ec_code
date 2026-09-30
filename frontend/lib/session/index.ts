// セッションIDの発行と読み出し。★中身は解釈しない（設計 4.1.4・2.2）。
//   フロント層は「Cookie の受け渡しのみ」。会員IDも役割もここでは持たない。

export const SESSION_COOKIE = "ec_sid";

// ★カートキーはセッションとは別に持つ（09-06 決定）。
//   セッションは60分で切れる（SEC-309）が、カートの保持は30日（F-301）。
//   同じ Cookie を使い回すと、1時間でカートが消えて要件を満たさない。
export const CART_COOKIE = "ec_cart";
export const CART_COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30日

// 設計 3.2 T-18。session_id は CHAR(64)。
//
// ★Math.random は使わない。Web Crypto の暗号用乱数から
//   32バイト＝16進64文字を作る（Python 側の secrets.token_hex(32) と同じ）。
//
// ★node:crypto ではなく Web Crypto を使う理由
//   middleware は Edge ランタイムで動くので node: のモジュールを読めない。
//   globalThis.crypto は Edge でも Node 18+ でも同じものが使え、強度も同じ。
export function newSessionId(): string {
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
