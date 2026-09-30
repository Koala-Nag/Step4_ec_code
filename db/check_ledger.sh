#!/usr/bin/env bash
# ============================================================
# check_ledger.sh
#   ddl/03_migration_ledger.sql への番号の足し忘れを検出する
#   （設計仕様書 2.2.1・10.4）
#
#   ★「まっさらな新品」に対して流す検査である。
#     docker compose down -v のあと、ddl/ だけが流れた状態で使う。
#     移行経路のDBで走らせると、まだ当てていない番号を「足し忘れ」と誤検知する。
#
#   使い方（ec/ で）
#     bash db/check_ledger.sh
#   終了コード 1 で CI を落とす。
# ============================================================
set -uo pipefail

MYSQL_CMD=${MYSQL_CMD:-"docker compose exec -T db mysql -uroot -plocalonly ec_koala"}
MIG_DIR=${MIG_DIR:-db/migrations}

ledger=$($MYSQL_CMD -N -B -e "SELECT version FROM schema_migration ORDER BY version;" 2>/dev/null | sort)
if [ -z "$ledger" ]; then
  echo "[NG] 台帳が読めない。schema_migration が無いか、DBに繋がっていない"
  exit 1
fi

files=$(ls "$MIG_DIR" | sed -n 's/^\([0-9][0-9][0-9]\)_.*\.sql$/\1/p' | sort)

echo "  migrations/ のファイル : $(echo $files)"
echo "  台帳の行               : $(echo $ledger)"

missing=$(comm -23 <(echo "$files") <(echo "$ledger"))
extra=$(comm -13 <(echo "$files") <(echo "$ledger"))

rc=0
if [ -n "$missing" ]; then
  echo "[NG] ddl/03_migration_ledger.sql に足し忘れ: $(echo $missing)"
  echo "     → 新品にこの番号がもう一度流れる（ERROR 1060/1061 で落ち、後ろの詰め替えが漏れる）"
  rc=1
fi
if [ -n "$extra" ]; then
  echo "[NG] 台帳にあるが migrations/ に無い番号: $(echo $extra)"
  echo "     → 移行ファイルを消したか、番号を打ち間違えている"
  rc=1
fi
[ $rc -eq 0 ] && echo "[OK] 台帳と migrations/ は一致している"
exit $rc
