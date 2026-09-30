// react-dom の型のうち、この画面で使う1つだけ（R-28）。
// ★@types/react-dom を依存に足さずに済ませる（package.json と監査の対象を増やさない）。
//   足すことにしたら、このファイルは消す。
declare module "react-dom" {
  export function useFormStatus(): { pending: boolean };
}
