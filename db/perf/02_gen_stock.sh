#!/bin/bash
set -u
M="docker compose exec -T db mysql -uroot -plocalonly ec_koala"
locs=$($M -N -B -e "SELECT location_code FROM location ORDER BY location_code;" 2>/dev/null)
i=0
for loc in $locs; do
  i=$((i+1))
  $M -e "
    SET SESSION foreign_key_checks=0; SET SESSION unique_checks=0;
    INSERT IGNORE INTO stock (sku_code, location_code, section, qty, reserved_qty)
    SELECT sk.sku_code, '$loc', 1,
           CRC32(CONCAT(sk.sku_code,'$loc','q')) % 21,
           CRC32(CONCAT(sk.sku_code,'$loc','r')) % 21
      FROM sku sk
     WHERE sk.sku_code LIKE 'X%'
       AND CRC32(CONCAT(sk.sku_code,'$loc')) % 100 < 60;
    INSERT IGNORE INTO stock (sku_code, location_code, section, qty, reserved_qty)
    SELECT sk.sku_code, '$loc', 2,
           CRC32(CONCAT(sk.sku_code,'$loc','q2')) % 11, 0
      FROM sku sk
     WHERE sk.sku_code LIKE 'X%'
       AND CRC32(CONCAT(sk.sku_code,'$loc','s2')) % 100 < 10;
  " 2>/dev/null
  printf "\r  %2d/51 拠点 %s まで投入" "$i" "$loc"
done
echo ""
