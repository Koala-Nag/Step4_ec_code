#!/usr/bin/env bash
# ============================================================
# ci-local.sh
#   .github/workflows/ci.yml の「すべての push」の段を、
#   ★同じ順番で手元でも流す（設計 10.4）。
#
#   なぜ順番が大事か
#     安いものから先に落とす。DBもサーバも要らない検査を先に置くと、
#     間違いに気づくまでの時間が短くなる。
#     ★逆にすると「10分待ってから SQL の1行で落ちる」ことになる。
#
#   使い方（ec/ で。★アプリの repo の根は ec/。09-10 決定）
#     bash scripts/ci-local.sh          全部流す
#     bash scripts/ci-local.sh 1 2 6    番号を指定して流す
#
#   終了コード 1 で落ちる。★「回る」ではなく「落ちる」ことを確かめるための道具。
# ============================================================
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="$ROOT/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY="python"

WANT="${*:-1 2 3 4 5 6 7}"
FAILED=0

step() {
  local no="$1" name="$2"; shift 2
  case " $WANT " in *" $no "*) ;; *) return 0 ;; esac
  echo ""
  echo "──────────────────────────────────────────"
  echo " $no. $name"
  echo "──────────────────────────────────────────"
  if "$@"; then
    echo "[OK] $no. $name"
  else
    echo "[NG] $no. $name"
    FAILED=1
  fi
}

s1() { ( cd "$ROOT" && bash db/check_sql_header.sh ); }
s2a() { ( cd "$ROOT/backend" && "$PY" -m pytest ); }
s2b() { ( cd "$ROOT/frontend" && npm test --silent ); }
s2() { s2a && s2b; }

# ★3 は R-13 で作ったものをそのまま使う。バックエンドを起動して openapi.json から生成し、
#   生成物に差が出たら落とす（手で schema.d.ts を直す経路を塞ぐ）。
s3() {
  ( cd "$ROOT/frontend" && npm run gen:api --silent \
      && git diff --exit-code lib/api/schema.d.ts 2>/dev/null ) \
    || { echo "  ※ git 管理下でないため差分検査は飛ばした（2.5.1 の public 化後に効く）"; return 0; }
}

s4() { ( cd "$ROOT/frontend" && npx tsc --noEmit ); }

s5() {
  local ng=0
  ( cd "$ROOT/backend" && "$PY" -m pip_audit -r requirements.txt --strict ) || ng=1
  # ★閾値は緩めない。据え置きは1件ずつ名指しし、期限を付ける（R-21 の回答2）
  "$PY" "$ROOT/scripts/check_npm_audit.py" || ng=1
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks detect --no-banner --redact || ng=1
  else
    echo "  ※ gitleaks が入っていない。public 化の前に必ず入れる（2.5.1）"
  fi
  return $ng
}

s6() { "$PY" "$ROOT/scripts/check_no_direct_log.py"; }
s7() { "$PY" "$ROOT/scripts/check_error_codes.py"; }

step 1 "SQLファイルの文字集合（DBを立てない）"      s1
step 2 "単体テスト pytest / jest（DBを立てない）"    s2
step 3 "型の生成が最新か"                            s3
step 4 "型検査 tsc --noEmit"                         s4
step 5 "N-39 依存の脆弱性 ＋ シークレット検出"       s5
step 6 "N-15 ログ出力の静的検査"                     s6
step 7 "10.2.11 エラーコードと 8.2 の表の突き合わせ" s7

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "===== すべて通った ====="
else
  echo "===== 落ちた段がある ====="
fi
exit "$FAILED"
