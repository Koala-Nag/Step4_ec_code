-- 画面を成立させるためのデモ在庫（R-13）
--   ★P0001・P0002 には1行も触れない。
--     この2商品と、その拠点（W001/T001〜T004）は引当の検証（検証1〜13）が使っている。
--     触ると verify.sql・verify_split_alloc.sh の期待値がずれる。
--
--   なぜ要るか
--     04_product.sql は在庫を入れない（引当の検証を壊さないため）。
--     そのままだと P0003〜P0050 が全部「品切れ」になり、
--     一覧の2値（IT-106）も、詳細の3値（IT-107）も、片側しか確かめられない。
--
--   入れ方
--     倉庫（W001）のバックヤードにだけ置く。店舗には置かない。
--     CRC32 で散らすので、何度流しても同じ結果になる。
SET NAMES utf8mb4;
USE ec_koala;

-- 商品まるごと品切れにするもの（5商品に1つ）。一覧に「品切れ」を出すため
INSERT IGNORE INTO stock (sku_code, location_code, section, qty, reserved_qty)
SELECT sk.sku_code, 'W001', 1, 0, 0
  FROM sku sk
 WHERE sk.product_code NOT IN ('P0001','P0002','P0051','P0052')
   AND CRC32(sk.product_code) % 5 = 0;

-- 残り。SKUごとに散らす
--   1割     0点        → 品切れ。そのサイズは選べない（F-203）
--   2割     1〜3点     → 残りわずか（BR-25）
--   それ以外 5〜24点   → 在庫あり
INSERT IGNORE INTO stock (sku_code, location_code, section, qty, reserved_qty)
SELECT sk.sku_code, 'W001', 1,
       CASE
         WHEN CRC32(sk.sku_code) % 10 = 0      THEN 0
         WHEN CRC32(sk.sku_code) % 10 IN (1,2) THEN 1 + (CRC32(sk.sku_code) % 3)
         ELSE 5 + (CRC32(sk.sku_code) % 20)
       END,
       0
  FROM sku sk
 WHERE sk.product_code NOT IN ('P0001','P0002','P0051','P0052');

-- 確認
--   SELECT COUNT(*) FROM stock WHERE location_code='W001' AND section=1;
--   P0001・P0002 の在庫が9行のままであること：
--   SELECT COUNT(*) FROM stock WHERE sku_code LIKE 'P0001%' OR sku_code LIKE 'P0002%';   → 9

-- ★R-26 ①。境目の価格の2商品は、散らさずに必ず在庫を置く（AT-401・402 を画面で確かめるため）。
--   ★CRC32 で散らすと「品切れ」を引く可能性がある。境目を作る商品が売れないと、また作れなくなる。
--   ★店舗 T003（EC販売可）にも少し置く。倉庫の出荷で欠品を報告したとき、
--     再引当（F-912・AT-303）で「他の拠点に引き当て直せる」ことを画面で確かめるため。
INSERT IGNORE INTO stock (sku_code, location_code, section, qty, reserved_qty)
SELECT sk.sku_code, 'W001', 1, 20, 0 FROM sku sk WHERE sk.product_code IN ('P0051','P0052');
INSERT IGNORE INTO stock (sku_code, location_code, section, qty, reserved_qty)
SELECT sk.sku_code, 'T003', 1, 3, 0 FROM sku sk WHERE sk.product_code IN ('P0051','P0052');

-- ★R-30｜滞留在庫（F-807）の境界を画面で見られるようにする（要件 6.4「58日／60日／62日 × 在庫2点／3点」）。
--   ★最終販売日は、それまで誰も書いていなかった（発送の記録で書くようにした）。seed は日付を今日から数える。
--
--   T005 横浜店（EC販売不可）の P0050 スイングトップ
--     BK-M 在庫5・62日前   → 抽出される
--     BK-L 在庫3・60日前   → 抽出される（★境界。60日ちょうど・3点ちょうどは含む）
--     BK-S 在庫3・58日前   → 出ない（日数が足りない）
--     BK-XL 在庫2・62日前  → 出ない（在庫が足りない）
--   T003 新宿店（EC販売可）の P0049 キルティングジャケット NV-M 在庫4・70日前 ＋ ★商品×拠点の除外
--     → 抽出され、「この商品の除外を外す」で EC に出せる
INSERT IGNORE INTO stock (sku_code, location_code, section, qty, reserved_qty, last_sold_at) VALUES
  ('P0050-BK-M',  'T005', 1, 5, 0, CURDATE() - INTERVAL 62 DAY),
  ('P0050-BK-L',  'T005', 1, 3, 0, CURDATE() - INTERVAL 60 DAY),
  ('P0050-BK-S',  'T005', 1, 3, 0, CURDATE() - INTERVAL 58 DAY),
  ('P0050-BK-XL', 'T005', 1, 2, 0, CURDATE() - INTERVAL 62 DAY),
  ('P0049-NV-M',  'T003', 1, 4, 0, CURDATE() - INTERVAL 70 DAY);
INSERT IGNORE INTO ec_exclusion (product_code, location_code) VALUES ('P0049', 'T003');
