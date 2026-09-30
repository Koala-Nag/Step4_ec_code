#!/bin/bash
# R-08 計測ハーネス。各クエリを N 回流し、接続のオーバーヘッドを差し引いた実測を出す。
set -u
M="docker compose exec -T db mysql -uroot -plocalonly ec_koala -N -B"
N=${N:-5}

# 接続＋docker exec のオーバーヘッドを測る
ov_total=0
for i in $(seq 1 5); do
  s=$(date +%s%N)
  $M -e "SELECT 1;" >/dev/null 2>&1
  e=$(date +%s%N)
  ov_total=$(( ov_total + (e-s)/1000000 ))
done
OVERHEAD=$(( ov_total / 5 ))
echo "  接続オーバーヘッドの中央値: ${OVERHEAD} ms（以下の数字はこれを引いてある）"
echo ""

run_q() {
  local label="$1" sql="$2"
  local times=()
  for i in $(seq 1 $N); do
    s=$(date +%s%N)
    $M -e "$sql" >/dev/null 2>&1
    e=$(date +%s%N)
    local ms=$(( (e-s)/1000000 - OVERHEAD ))
    [ $ms -lt 0 ] && ms=0
    times+=($ms)
  done
  local sorted=($(printf '%s\n' "${times[@]}" | sort -n))
  echo "  $label"
  echo "    実測(ms): ${times[*]}"
  echo "    最小 ${sorted[0]} / 中央 ${sorted[$((N/2))]} / 最大 ${sorted[$((N-1))]}"
}

Q1A="SELECT p.product_code, p.name, p.price
  FROM product p
 WHERE p.is_published = TRUE
   AND EXISTS (SELECT 1 FROM sku sk
          JOIN stock s ON s.sku_code = sk.sku_code AND s.section = 1
          JOIN location l ON l.location_code = s.location_code
         WHERE sk.product_code = p.product_code
           AND l.ec_saleable = TRUE AND l.suspended = FALSE
           AND s.qty > s.reserved_qty
           AND NOT EXISTS (SELECT 1 FROM ec_exclusion e
                WHERE e.product_code = p.product_code AND e.location_code = l.location_code))
 ORDER BY p.product_code LIMIT 20;"

Q1B="SELECT p.product_code, p.name, p.price,
       SUM(GREATEST(CAST(s.qty AS SIGNED) - CAST(s.reserved_qty AS SIGNED),0)) AS saleable
  FROM product p
  JOIN sku sk ON sk.product_code = p.product_code
  JOIN stock s ON s.sku_code = sk.sku_code AND s.section = 1
  JOIN location l ON l.location_code = s.location_code
 WHERE p.is_published = TRUE AND l.ec_saleable = TRUE AND l.suspended = FALSE
   AND NOT EXISTS (SELECT 1 FROM ec_exclusion e
        WHERE e.product_code = p.product_code AND e.location_code = l.location_code)
 GROUP BY p.product_code, p.name, p.price HAVING saleable > 0
 ORDER BY p.product_code LIMIT 20;"

Q1C="SELECT p.product_code, p.name,
       SUM(GREATEST(CAST(s.qty AS SIGNED) - CAST(s.reserved_qty AS SIGNED),0)) AS saleable
  FROM product p
  JOIN sku sk ON sk.product_code = p.product_code
  JOIN stock s ON s.sku_code = sk.sku_code AND s.section = 1
  JOIN location l ON l.location_code = s.location_code
 WHERE p.is_published = TRUE AND l.ec_saleable = TRUE AND l.suspended = FALSE
   AND NOT EXISTS (SELECT 1 FROM ec_exclusion e
        WHERE e.product_code = p.product_code AND e.location_code = l.location_code)
 GROUP BY p.product_code, p.name HAVING saleable > 0
 ORDER BY saleable DESC LIMIT 20;"

Q1D="SELECT p.product_code, p.name
  FROM product p
 WHERE p.is_published = TRUE
   AND EXISTS (SELECT 1 FROM sku sk
          JOIN stock s ON s.sku_code = sk.sku_code AND s.section = 1
          JOIN location l ON l.location_code = s.location_code
         WHERE sk.product_code = p.product_code
           AND l.ec_saleable = TRUE AND l.suspended = FALSE
           AND s.qty > s.reserved_qty
           AND NOT EXISTS (SELECT 1 FROM ec_exclusion e
                WHERE e.product_code = p.product_code AND e.location_code = l.location_code))
 ORDER BY p.product_code LIMIT 20 OFFSET 5000;"

case "${1:-all}" in
  a) run_q "Q1a EXISTS・商品コード順・LIMIT 20" "$Q1A" ;;
  b) run_q "Q1b 集計・商品コード順・LIMIT 20" "$Q1B" ;;
  c) run_q "Q1c 集計・販売可能数の多い順・LIMIT 20" "$Q1C" ;;
  d) run_q "Q1d EXISTS・OFFSET 5000" "$Q1D" ;;
  *) run_q "Q1a EXISTS・商品コード順・LIMIT 20" "$Q1A"
     run_q "Q1b 集計・商品コード順・LIMIT 20" "$Q1B"
     run_q "Q1c 集計・販売可能数の多い順・LIMIT 20" "$Q1C"
     run_q "Q1d EXISTS・OFFSET 5000" "$Q1D" ;;
esac
