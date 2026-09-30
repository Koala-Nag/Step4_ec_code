#!/usr/bin/env bash
# ============================================================
# check_sql_header.sh
#   すべての .sql が SET NAMES utf8mb4; と USE ec_koala; で始まっているかを検査する
#   （設計仕様書 2.2・10.4。R-07 で実際に踏んだ）
#
#   ★「先頭2行」ではなく「最初に現れる実行文2つ」を見る。
#     どのファイルも -- ==== のコメント枠で始まるため、
#     文字どおり先頭2行を見ると全ファイルが落ちる。
#
#   なぜ要るか
#     SET NAMES が無いと、この接続の既定（latin1）で日本語が格納される。
#     書き込みも読み出しも同じ間違った文字集合を通るので、
#     往復すると正しく見える。目視では絶対に気づけない。
#     → だから人ではなく機械が見る。
#
#   使い方（ec/ で）
#     bash db/check_sql_header.sh
#   終了コード 1 で CI を落とす。
# ============================================================
set -uo pipefail

SQL_DIR=${SQL_DIR:-db}
EXPECT1='SET NAMES utf8mb4;'
EXPECT2='USE ec_koala;'

rc=0
count=0

while IFS= read -r f; do
  count=$((count+1))
  # コメント行（-- で始まる）と空行を飛ばして、最初の実行文を2つ取る
  mapfile -t stmts < <(
    sed -e 's/[[:space:]]*$//' "$f" \
      | grep -v '^[[:space:]]*--' \
      | grep -v '^[[:space:]]*$' \
      | head -2
  )
  s1="${stmts[0]:-}"
  s2="${stmts[1]:-}"

  if [ "$s1" != "$EXPECT1" ] || [ "$s2" != "$EXPECT2" ]; then
    echo "[NG] $f"
    echo "     1つ目の文: ${s1:-（無し）}   期待: $EXPECT1"
    echo "     2つ目の文: ${s2:-（無し）}   期待: $EXPECT2"
    rc=1
  fi
done < <(find "$SQL_DIR" -name '*.sql' | sort)

if [ $rc -eq 0 ]; then
  echo "[OK] $count 本の .sql すべてが SET NAMES utf8mb4; / USE ec_koala; で始まっている"
else
  echo ""
  echo "→ 直し方：ファイルの先頭コメントのあとに、この2行を置く"
  echo "     SET NAMES utf8mb4;"
  echo "     USE ec_koala;"
  echo "→ 無いと日本語が二重エンコードで格納され、往復すると正しく見えるので目視では気づけない"
fi
exit $rc
