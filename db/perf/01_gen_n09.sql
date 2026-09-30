-- R-08 用の量データ生成（N-09 / 要件定義書 6.4）
--   商品1万・SKU5万・拠点51（倉庫1＋店舗50）
--   stock は SKU×拠点 2,550,000 通りのうち約6割に間引く
SET NAMES utf8mb4;
USE ec_koala;

SET SESSION cte_max_recursion_depth = 1000000;
SET SESSION foreign_key_checks = 0;
SET SESSION unique_checks = 0;

-- 連番表
DROP TABLE IF EXISTS nums;
CREATE TABLE nums (n INT PRIMARY KEY) ENGINE=InnoDB;
INSERT INTO nums (n)
WITH RECURSIVE seq(n) AS (
  SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n < 50000
)
SELECT n FROM seq;

-- 拠点を51まで増やす（既存 W001 + T001〜T010 に T011〜T050 を足す）
INSERT INTO location
  (location_code, kind, name, pref_code, zip, address, tel,
   business_days, cutoff_time, suspended, ec_saleable)
SELECT CONCAT('T', LPAD(n, 3, '0')),
       2,
       CONCAT('店舗', LPAD(n, 3, '0')),
       LPAD(((n - 1) % 47) + 1, 2, '0'),
       LPAD(((n * 7919) % 10000000), 7, '0'),
       CONCAT('住所', n),
       LPAD(((n * 104729) % 100000000000), 11, '0'),
       127, '15:00:00',
       (n % 25 = 0),          -- 50店中2店を一時停止
       (n % 50 < 40)          -- 50店中40店をEC販売可
  FROM nums WHERE n BETWEEN 11 AND 50;

-- 商品1万件
INSERT INTO product
  (product_code, name, category_code, item_type_code, material, price, is_published)
SELECT CONCAT('X', LPAD(n, 6, '0')),
       CONCAT('商品', n),
       'TSHIRT', 'TOPS_T', '綿100%',
       1000 + (n % 9000),
       TRUE
  FROM nums WHERE n <= 10000;

-- SKU 5万件（1商品5SKU。(product,color,size) は一意）
INSERT INTO sku (sku_code, product_code, color_code, size_code, common_size_code)
SELECT CONCAT('X', LPAD(p.n, 6, '0'), '-', c.color_code, '-', c.size_code),
       CONCAT('X', LPAD(p.n, 6, '0')),
       c.color_code, c.size_code, c.common_size_code
  FROM nums p
  JOIN (
        SELECT 'BK' color_code,'S' size_code,'CS2' common_size_code
  UNION SELECT 'BK','M','CS3'
  UNION SELECT 'BK','L','CS4'
  UNION SELECT 'WH','M','CS3'
  UNION SELECT 'NV','M','CS3'
  ) c
 WHERE p.n <= 10000;

SET SESSION foreign_key_checks = 1;
SET SESSION unique_checks = 1;
