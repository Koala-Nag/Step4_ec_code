#!/bin/bash
# ============================================================
# 検証7  残り1点を2人が同時に買ったとき、1人だけ成功するか（9.4）
#   bash db/verify_concurrent.sh
# ============================================================
set -u
M="docker compose exec -T db mysql -uroot -plocalonly ec_koala -N -B"

echo "--- 準備：P0001-BK-L を W001 に 残り1点 で置く ---"
$M -e "UPDATE stock SET qty=1, reserved_qty=0 WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1;"

echo "--- 2本同時に引当を投げる ---"
SQL="START TRANSACTION;
     UPDATE stock SET reserved_qty = reserved_qty + 1
      WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1
        AND qty >= reserved_qty + 1;
     SELECT ROW_COUNT();
     SELECT SLEEP(2);
     COMMIT;"

$M -e "$SQL" > /tmp/a.txt 2>/dev/null &
$M -e "$SQL" > /tmp/b.txt 2>/dev/null &
wait

echo "A の更新件数: $(head -1 /tmp/a.txt)"
echo "B の更新件数: $(head -1 /tmp/b.txt)"
echo ""
echo "--- 結果 ---"
$M -e "SELECT qty, reserved_qty FROM stock WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1;"
echo ""
echo "期待：片方が 1、もう片方が 0。reserved_qty は 1 で止まる（2にならない）"
