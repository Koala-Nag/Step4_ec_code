#!/bin/bash
# ============================================================
# 検証8〜10  引当の割り付け（BR-06・BR-07）  設計仕様書 6.2
#   bash db/verify_split_alloc.sh
#
#   6.2.1 の手順1〜6 をそのまま実装して、実機で成立するか確かめる。
#     手順1〜5 はメモリの中の計算で、DBを1行も更新しない
#     DBに触れるのは手順6の1回だけ
#   ★手順3で「手元の残数」を減らすこと、
#   ★手順6で同じ拠点×SKUへの更新を1本にまとめること、
#   ★更新件数が0でもやり直さないこと（6.2.2）を、コードとして書いてある。
# ============================================================
set -u
M="docker compose exec -T db mysql -uroot -plocalonly ec_koala -N -B"
SHIP_PREF='13'   # 届け先＝東京
PASS=0
FAIL=0

# ------------------------------------------------------------
# 手順1・2  候補になる在庫の行を1回で読み、BR-05 の3キーで並べる
#   3.2.2 ⑥（a）の条件だけ。数量の条件（b）は付けない
# ------------------------------------------------------------
fetch_candidates() {
  $M -e "
    SELECT s.sku_code, s.location_code, l.kind,
           CASE WHEN l.pref_code = '$SHIP_PREF' THEN 2
                WHEN p.region = (SELECT region FROM prefecture WHERE pref_code='$SHIP_PREF') THEN 3
                ELSE 4 END AS step,
           s.qty, s.reserved_qty
      FROM stock s
      JOIN location   l  ON l.location_code = s.location_code
      JOIN prefecture p  ON p.pref_code = l.pref_code
      JOIN sku        sk ON sk.sku_code = s.sku_code
     WHERE s.sku_code IN ($1)
       AND s.section = 1
       AND l.ec_saleable = TRUE
       AND l.suspended = FALSE
       AND NOT EXISTS (SELECT 1 FROM ec_exclusion e
                        WHERE e.product_code = sk.product_code
                          AND e.location_code = l.location_code)
     ORDER BY step, l.kind, l.location_code;" 2>/dev/null
}

# ------------------------------------------------------------
# 手順3〜5  貪欲に割り付け、3拠点以上なら倉庫だけで組み直す
# ------------------------------------------------------------
allocate() {
  awk -F'\t' '
    FNR==NR {
      n++; c_sku[n]=$1; c_loc[n]=$2; c_kind[n]=$3; c_qty[n]=$5; c_rsv[n]=$6
      avail[$1 SUBSEP $2] = $5 - $6
      next
    }
    { m++; l_no[m]=$1; l_sku[m]=$2; l_qty[m]=$3 }

    function try_alloc(warehouse_only,   i, j, found, key) {
      for (key in work) delete work[key]
      for (key in avail) work[key] = avail[key]
      for (j = 1; j <= m; j++) {
        found = 0
        for (i = 1; i <= n; i++) {
          if (c_sku[i] != l_sku[j]) continue
          if (warehouse_only && c_kind[i] != 1) continue
          key = c_sku[i] SUBSEP c_loc[i]
          if (work[key] >= l_qty[j]) {
            a_loc[j] = c_loc[i]
            work[key] -= l_qty[j]
            found = 1
            break
          }
        }
        if (!found) return 0
      }
      return 1
    }

    END {
      if (!try_alloc(0)) {
        print "NG\t手順3で割り付けられない明細がある（BR-06：1明細を複数拠点に分割しない）"
        exit
      }
      nloc = 0
      for (key in ucount) delete ucount[key]
      for (j = 1; j <= m; j++) if (!(a_loc[j] in ucount)) { ucount[a_loc[j]] = 1; nloc++ }
      if (nloc >= 3) {
        print "INFO\t手順4：使った拠点が " nloc " か所 → BR-07 により倉庫だけで組み直す（手順5）"
        if (!try_alloc(1)) {
          print "NG\t手順5で倉庫だけでは全明細を割れない → 引当失敗（9.2）"
          exit
        }
        print "INFO\t手順5：倉庫だけで組み直せた"
      } else {
        print "INFO\t手順4：使った拠点が " nloc " か所 → 組み直さない（手順6へ）"
      }
      for (j = 1; j <= m; j++) printf "OK\t%s\t%s\t%s\t%s\n", l_no[j], l_sku[j], a_loc[j], l_qty[j]
    }
  ' "$1" "$2"
}

# ------------------------------------------------------------
# 手順6  location_code, sku_code の昇順に並べ替えて条件つきUPDATE
# ------------------------------------------------------------
apply() {
  local merged sql rows zero cnt loc sku qty r
  merged=$(awk -F'\t' '$1=="OK"{ sum[$4 "\t" $3] += $5 } END { for (k in sum) print k "\t" sum[k] }' "$1" | sort)
  if [ -z "$merged" ]; then
    echo "  (更新対象なし)"
    return 1
  fi
  sql="START TRANSACTION;"
  cnt=0
  while IFS=$'\t' read -r loc sku qty; do
    [ -z "$loc" ] && continue
    cnt=$((cnt + 1))
    sql="$sql UPDATE stock SET reserved_qty = reserved_qty + $qty WHERE sku_code='$sku' AND location_code='$loc' AND section=1 AND qty >= reserved_qty + $qty; SELECT ROW_COUNT();"
    echo "  UPDATE $loc / $sku / +$qty"
  done <<< "$merged"
  sql="$sql COMMIT;"
  echo "$cnt" > /tmp/upd_count.txt
  rows=$($M -e "$sql" 2>/dev/null)
  zero=0
  while read -r r; do
    [ "$r" = "0" ] && zero=1
  done <<< "$rows"
  if [ "$zero" = "1" ]; then
    echo "  → 更新件数に0があった。すべて取り消して引当失敗（やり直さない。6.2.2）"
    return 1
  fi
  echo "  → 全 $cnt 本が更新件数1。引当済"
  return 0
}

judge() {
  if [ "$2" = "$3" ]; then
    echo "  [PASS] 期待=$2  実際=$3"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] 期待=$2  実際=$3"
    FAIL=$((FAIL + 1))
  fi
}

run_case() {
  local title="$1" setup="$2" skus="$3" lines="$4" expected="$5" exp_upd="${6:-}" actual
  echo "0" > /tmp/upd_count.txt
  echo ""
  echo "============================================================"
  echo " $title"
  echo "============================================================"
  $M -e "$setup" >/dev/null 2>&1
  echo "--- 在庫の配置 ---"
  $M -e "SELECT s.location_code, s.sku_code, s.qty, s.reserved_qty, l.kind
           FROM stock s JOIN location l ON l.location_code = s.location_code
          WHERE s.sku_code IN ($skus) AND s.section = 1 AND s.qty > 0
          ORDER BY s.sku_code, s.location_code;" 2>/dev/null \
    | awk -F'\t' '{ k = ($5 == 1 ? "倉庫" : "店舗"); printf "  %-6s %-14s 在庫%-3s 引当%-3s %s\n", $1, $2, $3, $4, k }'

  fetch_candidates "$skus" > /tmp/cand.tsv
  printf '%b' "$lines" > /tmp/lines.tsv
  echo "--- 注文明細 ---"
  awk -F'\t' '{ printf "  明細%s  %s  %s点\n", $1, $2, $3 }' /tmp/lines.tsv

  allocate /tmp/cand.tsv /tmp/lines.tsv > /tmp/plan.tsv
  echo "--- 手順3〜5 ---"
  grep -E '^(INFO|NG)' /tmp/plan.tsv | cut -f2- | sed 's/^/  /'

  if grep -q '^NG' /tmp/plan.tsv; then
    actual="引当失敗"
  else
    echo "--- 手順6  条件つきUPDATE（location_code, sku_code 昇順）---"
    if apply /tmp/plan.tsv; then actual="成功"; else actual="引当失敗"; fi
    echo "--- 割り付け結果 ---"
    awk -F'\t' '$1=="OK"{ printf "  明細%s  %s  → %s  %s点\n", $2, $3, $4, $5 }' /tmp/plan.tsv
  fi
  judge "$title" "$expected" "$actual"
  if [ -n "$exp_upd" ]; then
    echo "  --- 手順6が発行した UPDATE の本数（★同じ拠点×SKUは1本にまとめる）---"
    judge "$title / UPDATE本数" "$exp_upd" "$(cat /tmp/upd_count.txt)"
  fi
}

RESET="UPDATE stock SET qty=0, reserved_qty=0 WHERE sku_code IN ('P0001-BK-M','P0001-BK-L','P0001-WH-M');
 INSERT INTO stock (sku_code,location_code,section,qty,reserved_qty) VALUES
   ('P0001-BK-M','W001',1,0,0),('P0001-BK-L','W001',1,0,0),('P0001-WH-M','W001',1,0,0),
   ('P0001-BK-M','T003',1,0,0),('P0001-BK-L','T004',1,0,0),('P0001-WH-M','T001',1,0,0),
   ('P0001-BK-M','T004',1,0,0),('P0001-BK-M','T001',1,0,0)
   ON DUPLICATE KEY UPDATE qty=0, reserved_qty=0;"

echo "############################################################"
echo "# 検証8〜10  引当の割り付け（設計仕様書 6.2）  届け先＝東京(13)"
echo "############################################################"

run_case "検証8  1明細3点／どの拠点も1点ずつ → 引当失敗（BR-06）" \
"$RESET
 UPDATE stock SET qty=1 WHERE sku_code='P0001-BK-M' AND location_code IN ('T003','T004','T001') AND section=1;" \
"'P0001-BK-M'" \
"1\tP0001-BK-M\t3\n" \
"引当失敗"

run_case "検証9a  3明細が3拠点に散る／倉庫で足りる → 倉庫のみで成功（BR-07）" \
"$RESET
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-L' AND location_code='T004' AND section=1;
 UPDATE stock SET qty=5 WHERE sku_code='P0001-WH-M' AND location_code='T001' AND section=1;
 UPDATE stock SET qty=5 WHERE location_code='W001' AND section=1
   AND sku_code IN ('P0001-BK-M','P0001-BK-L','P0001-WH-M');" \
"'P0001-BK-M','P0001-BK-L','P0001-WH-M'" \
"1\tP0001-BK-M\t2\n2\tP0001-BK-L\t2\n3\tP0001-WH-M\t2\n" \
"成功"

run_case "検証9b  3明細が3拠点に散る／倉庫が1明細ぶん足りない → 引当失敗（BR-07）" \
"$RESET
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-L' AND location_code='T004' AND section=1;
 UPDATE stock SET qty=5 WHERE sku_code='P0001-WH-M' AND location_code='T001' AND section=1;
 UPDATE stock SET qty=5 WHERE location_code='W001' AND section=1
   AND sku_code IN ('P0001-BK-M','P0001-BK-L');
 UPDATE stock SET qty=1 WHERE location_code='W001' AND section=1
   AND sku_code='P0001-WH-M';" \
"'P0001-BK-M','P0001-BK-L','P0001-WH-M'" \
"1\tP0001-BK-M\t2\n2\tP0001-BK-L\t2\n3\tP0001-WH-M\t2\n" \
"引当失敗"

run_case "検証10  2明細が2拠点で収まる → 組み直さずに成功" \
"$RESET
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-L' AND location_code='T004' AND section=1;
 UPDATE stock SET qty=5 WHERE location_code='W001' AND section=1
   AND sku_code IN ('P0001-BK-M','P0001-BK-L');" \
"'P0001-BK-M','P0001-BK-L'" \
"1\tP0001-BK-M\t2\n2\tP0001-BK-L\t2\n" \
"成功"

# ------------------------------------------------------------
# ここから、6.2 の ★3点が入っていることを名指しで確かめる
#   （入っていなければ、在庫があるのに引当失敗する）
# ------------------------------------------------------------

# ★手順3「割るたびに手元の残数を減らす」が入っているか
#   同一SKUの明細2本（各3点）。T003 に5点、W001 に5点。
#     減らしている  → 明細1=T003（残2）、明細2は T003 では足りず W001 → 2拠点で成功
#     減らしていない → 両方 T003 に割り、まとめて +6 → 在庫5 なので手順6が0件 → 引当失敗
#   つまり「成功」すること自体が、手元の残数を減らしている証拠になる
run_case "検証11  同一SKUの明細2本／★手順3で手元の残数を減らしているか" \
"$RESET
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-M' AND location_code='W001' AND section=1;" \
"'P0001-BK-M'" \
"1\tP0001-BK-M\t3\n2\tP0001-BK-M\t3\n" \
"成功"

# ★手順6「同じ拠点×SKUへの更新は1本にまとめる」が入っているか
#   同一SKUの明細2本（各2点）。T003 に5点あるので両方 T003 に落ちる。
#   まとめていれば UPDATE は1本（+4）。まとめていなければ2本になる。
run_case "検証12  同一SKU・同一拠点の明細2本／★手順6で1本にまとめているか" \
"$RESET
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
 UPDATE stock SET qty=5 WHERE sku_code='P0001-BK-M' AND location_code='W001' AND section=1;" \
"'P0001-BK-M'" \
"1\tP0001-BK-M\t2\n2\tP0001-BK-M\t2\n" \
"成功" "1"

# 6.2.2  更新件数が0のとき、やり直さずその場で引当失敗になるか
#   手順1〜5 のあとで在庫を横から抜いて、手順6 を必ず外れさせる
echo ""
echo "============================================================"
echo " 検証13  手順6が0件だったとき、やり直さずに引当失敗になるか（6.2.2）"
echo "============================================================"
$M -e "$RESET
 UPDATE stock SET qty=3 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;" >/dev/null 2>&1
fetch_candidates "'P0001-BK-M'" > /tmp/cand.tsv
printf '1\tP0001-BK-M\t3\n' > /tmp/lines.tsv
allocate /tmp/cand.tsv /tmp/lines.tsv > /tmp/plan.tsv
echo "  手順1〜5 は T003 に3点を割り付けた（このときDBは1行も更新していない）"
echo "  --- ここで横から在庫を抜く（別の注文が先に取った状況を作る）---"
$M -e "UPDATE stock SET reserved_qty=1 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;" >/dev/null 2>&1
$M -e "SELECT CONCAT('  いまの T003 は 在庫',qty,' 引当',reserved_qty,'（販売可能 ',qty-reserved_qty,'点）')
         FROM stock WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;" 2>/dev/null
echo "--- 手順6 ---"
before=$($M -e "SELECT reserved_qty FROM stock WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;" 2>/dev/null)
if apply /tmp/plan.tsv; then r13="成功"; else r13="引当失敗"; fi
after=$($M -e "SELECT reserved_qty FROM stock WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;" 2>/dev/null)
judge "検証13 その場で引当失敗する" "引当失敗" "$r13"
judge "検証13 在庫は動いていない" "$before" "$after"

# ------------------------------------------------------------
# 後片付け  seed/03_demo.sql と同じ在庫の状態に戻す
#   （この検証は在庫を作り替えるので、戻さないと verify.sql の期待値がずれる）
# ------------------------------------------------------------
echo ""
echo "--- 後片付け：在庫を seed/03_demo.sql の状態に戻す ---"
$M -e "
 DELETE FROM stock WHERE sku_code IN ('P0001-BK-M','P0001-BK-L','P0001-WH-M');
 INSERT INTO stock (sku_code,location_code,section,qty,reserved_qty) VALUES
   ('P0001-BK-M','W001',1,10,0),
   ('P0001-BK-M','T003',1, 3,0),
   ('P0001-BK-M','T004',1, 5,0),
   ('P0001-BK-M','T001',1, 8,0),
   ('P0001-BK-M','T003',2, 4,0),
   ('P0001-BK-M','T002',1, 9,0),
   ('P0001-BK-L','W001',1, 1,0),
   ('P0001-WH-M','T004',1, 2,0);" >/dev/null 2>&1
$M -e "SELECT CONCAT('  ',sku_code,' / ',location_code,' / 区分',section,' 在庫',qty,' 引当',reserved_qty)
         FROM stock ORDER BY sku_code, location_code, section;" 2>/dev/null

echo ""
echo "############################################################"
echo "# 合計  PASS=$PASS  FAIL=$FAIL"
echo "############################################################"
[ "$FAIL" = "0" ]
