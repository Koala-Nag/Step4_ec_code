#!/bin/bash
# 20並列で同じクエリを投げ、95パーセンタイルを出す（N-06：同時20人で2秒）
set -u
PAR=${PAR:-20}
OUT=/tmp/conc_out
rm -rf $OUT; mkdir -p $OUT

# コンテナ内で完結させる（docker exec のオーバーヘッドを20回ぶん載せないため）
run_parallel() {
  local label="$1" sql="$2"
  rm -f $OUT/*.txt
  # 1本の docker exec の中で、mysql を PAR 本同時に起動する
  docker compose exec -T db bash -c "
    rm -f /tmp/t_*.txt
    for i in \$(seq 1 $PAR); do
      ( s=\$(date +%s%N)
        mysql -uroot -plocalonly ec_koala -N -B -e \"$sql\" >/dev/null 2>&1
        e=\$(date +%s%N)
        echo \$(( (e-s)/1000000 )) > /tmp/t_\$i.txt ) &
    done
    wait
    cat /tmp/t_*.txt
  " 2>/dev/null > $OUT/times.txt

  local times=($(sort -n $OUT/times.txt))
  local n=${#times[@]}
  [ $n -eq 0 ] && { echo "  $label : 計測できず"; return; }
  local p50=${times[$((n*50/100))]}
  local p95i=$((n*95/100)); [ $p95i -ge $n ] && p95i=$((n-1))
  local p95=${times[$p95i]}
  echo "  $label"
  echo "    $n 本同時 / 最小 ${times[0]} ms / 中央 ${p50} ms / p95 ${p95} ms / 最大 ${times[$((n-1))]} ms"
  echo "    ※この数字には mysql クライアントの起動時間（数十ms）が含まれる"
}

Q1A="SELECT p.product_code, p.name, p.price FROM product p WHERE p.is_published = TRUE AND EXISTS (SELECT 1 FROM sku sk JOIN stock s ON s.sku_code = sk.sku_code AND s.section = 1 JOIN location l ON l.location_code = s.location_code WHERE sk.product_code = p.product_code AND l.ec_saleable = TRUE AND l.suspended = FALSE AND s.qty > s.reserved_qty AND NOT EXISTS (SELECT 1 FROM ec_exclusion e WHERE e.product_code = p.product_code AND e.location_code = l.location_code)) ORDER BY p.product_code LIMIT 20;"

Q1B="SELECT p.product_code, p.name, p.price, SUM(GREATEST(CAST(s.qty AS SIGNED) - CAST(s.reserved_qty AS SIGNED),0)) AS saleable FROM product p JOIN sku sk ON sk.product_code = p.product_code JOIN stock s ON s.sku_code = sk.sku_code AND s.section = 1 JOIN location l ON l.location_code = s.location_code WHERE p.is_published = TRUE AND l.ec_saleable = TRUE AND l.suspended = FALSE AND NOT EXISTS (SELECT 1 FROM ec_exclusion e WHERE e.product_code = p.product_code AND e.location_code = l.location_code) GROUP BY p.product_code, p.name, p.price HAVING saleable > 0 ORDER BY p.product_code LIMIT 20;"

Q1D="SELECT p.product_code, p.name FROM product p WHERE p.is_published = TRUE AND EXISTS (SELECT 1 FROM sku sk JOIN stock s ON s.sku_code = sk.sku_code AND s.section = 1 JOIN location l ON l.location_code = s.location_code WHERE sk.product_code = p.product_code AND l.ec_saleable = TRUE AND l.suspended = FALSE AND s.qty > s.reserved_qty AND NOT EXISTS (SELECT 1 FROM ec_exclusion e WHERE e.product_code = p.product_code AND e.location_code = l.location_code)) ORDER BY p.product_code LIMIT 20 OFFSET 5000;"

case "${1:-all}" in
  a) run_parallel "Q1a EXISTS・商品コード順" "$Q1A" ;;
  b) run_parallel "Q1b 集計・商品コード順"   "$Q1B" ;;
  d) run_parallel "Q1d EXISTS・OFFSET 5000"  "$Q1D" ;;
  agg) run_parallel "Q2 集計表を引く"        "$2" ;;
  *) run_parallel "Q1a EXISTS・商品コード順" "$Q1A"
     run_parallel "Q1b 集計・商品コード順"   "$Q1B"
     run_parallel "Q1d EXISTS・OFFSET 5000"  "$Q1D" ;;
esac
