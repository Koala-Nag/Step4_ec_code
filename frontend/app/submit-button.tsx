"use client";
// 押したあと、結果が返るまで「処理中…」にして押せなくするボタン（R-28 (d)）。
// ★注文の確定は外部（決済代行）を待つので、押したのに何も起きないように見える時間がある。
// ★二重送信そのものは冪等キーで防いでいる（N-40）。これは見た目の手当て。
import { useFormStatus } from "react-dom";

export function SubmitButton({ children, pending, className = "btn" }:
  { children: React.ReactNode; pending: string; className?: string }) {
  const { pending: busy } = useFormStatus();
  return (
    <button className={className} type="submit" disabled={busy} aria-busy={busy}>
      {busy ? pending : children}
    </button>
  );
}
