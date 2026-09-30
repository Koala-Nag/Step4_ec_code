-- 引当を試すための最小データ
--   商品1件・SKU 1件に対して、在庫を「近い順」の検証ができるように配置する
SET NAMES utf8mb4;
USE ec_koala;

INSERT INTO product (product_code,name,category_code,item_type_code,material,price,is_published) VALUES
 ('P0001','ベーシックTシャツ','TSHIRT','TOPS_T','綿100%',1990,TRUE),
 ('P0002','テーパードパンツ','PANTS','BOTTOMS_T','ポリエステル65% 綿35%',3990,TRUE);

INSERT INTO sku (sku_code,product_code,color_code,size_code,common_size_code) VALUES
 ('P0001-BK-M','P0001','BK','M','CS3'),
 ('P0001-BK-L','P0001','BK','L','CS4'),
 ('P0001-WH-M','P0001','WH','M','CS3'),
 ('P0002-NV-W30','P0002','NV','W30','CS3');

-- 在庫。section 1=バックヤード 2=店頭
--   届け先が東京（13）のとき、BR-05 の期待順は
--     T003 新宿（同一都道府県・店舗）→ T004 渋谷（同一都道府県・店舗）
--     …ではなく、まず W001 中央倉庫（千葉＝同一ブロック・倉庫）より
--     同一都道府県の T003/T004 が先。同段では倉庫が先だが、段が違えば段が優先する。
INSERT INTO stock (sku_code,location_code,section,qty,reserved_qty) VALUES
 ('P0001-BK-M','W001',1, 10, 0),   -- 倉庫（千葉＝関東ブロック）
 ('P0001-BK-M','T003',1,  3, 0),   -- 新宿（東京＝届け先と同一都道府県）
 ('P0001-BK-M','T004',1,  5, 0),   -- 渋谷（東京＝同一都道府県）
 ('P0001-BK-M','T001',1,  8, 0),   -- 札幌（別ブロック）
 ('P0001-BK-M','T003',2,  4, 0),   -- 新宿の店頭。ECでは売らない（BR-02）
 ('P0001-BK-M','T002',1,  9, 0),   -- 仙台。ec_saleable=FALSE なので候補外
 ('P0001-BK-L','W001',1,  1, 0),   -- 残り1点。同時実行の検証に使う
 ('P0001-WH-M','T004',1,  2, 0),
 ('P0002-NV-W30','W001',1, 6, 0);

-- 商品×拠点の除外（行があれば EC販売しない）
INSERT INTO ec_exclusion (product_code,location_code) VALUES
 ('P0002','T003');   -- 新宿ではP0002をECに出さない

INSERT INTO member (member_id,email,password_hash,name,tel) VALUES
 ('M0001','taro@example.com','$dummy$','山田太郎','09000000001');

INSERT INTO address (member_id,name,zip,pref_code,address,tel,is_default) VALUES
 ('M0001','山田太郎','1600022','13','東京都新宿区新宿1-2-3','09000000001',TRUE);

-- ------------------------------------------------------------
-- クーポン（BR-16・BR-16a）。R-23 で足した
--   ★IT-413 が使うのは C-LIMIT1。全体上限が1枚のもの。
--     2人が同時に使って「片方だけ通る」を確かめるため。
-- ------------------------------------------------------------
INSERT IGNORE INTO coupon
  (coupon_code, name, discount_type, discount_value, start_at, end_at,
   min_amount, total_limit, used_count, per_member_limit) VALUES
 ('C500',    '500円引き',      2,  500, '2020-01-01 00:00:00', '2099-12-31 23:59:59',
  3000, NULL, 0, NULL),
 ('C10P',    '10%引き',        1,   10, '2020-01-01 00:00:00', '2099-12-31 23:59:59',
     0, NULL, 0, NULL),
 ('C-LIMIT1','先着1名（試験用）', 2, 300, '2020-01-01 00:00:00', '2099-12-31 23:59:59',
     0,    1, 0, NULL),
 ('C-ENDED', '期間外（試験用）',  2, 300, '2020-01-01 00:00:00', '2020-12-31 23:59:59',
     0, NULL, 0, NULL);
