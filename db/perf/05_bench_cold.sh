#!/bin/bash
# 各クエリについて「コンテナ再起動 → 1回だけ実行」でキャッシュ非搭載を測る
set -u
SP="$(dirname "$0")"
M="docker compose exec -T db mysql -uroot -plocalonly ec_koala -N -B"

# bench.sh を使わず直接測る
direct() {
  local label="$1" sql="$2"
  $M -e "SET GLOBAL innodb_buffer_pool_dump_at_shutdown=OFF;" >/dev/null 2>&1
  docker compose restart db >/dev/null 2>&1
  for i in $(seq 1 60); do
    docker compose exec -T db mysqladmin ping -h 127.0.0.1 -uroot -plocalonly >/dev/null 2>&1 && break
    sleep 1
  done
  sleep 2
  local s0=$(date +%s%N); $M -e "SELECT 1;" >/dev/null 2>&1; local e0=$(date +%s%N)
  local ov=$(( (e0-s0)/1000000 ))
  local s=$(date +%s%N)
  $M -e "$sql" >/dev/null 2>&1
  local e=$(date +%s%N)
  echo "  $label : $(( (e-s)/1000000 - ov )) ms  （接続 ${ov}ms を差し引き）"
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

direct "Q1a EXISTS・商品コード順" "$Q1A"
direct "Q1b 集計・商品コード順  " "$Q1B"
direct "Q1c 集計・販売可能数順  " "$Q1C"
direct "Q1d EXISTS・OFFSET 5000 " "$Q1D"
