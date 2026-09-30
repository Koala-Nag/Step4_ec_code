-- マスタと拠点  6.4 の初期データ（機能確認用の最小セット）
SET NAMES utf8mb4;
USE ec_koala;

INSERT INTO color (color_code,name,sort_no) VALUES
 ('BK','ブラック',1),('WH','ホワイト',2),('NV','ネイビー',3),('BE','ベージュ',4);

INSERT INTO size (size_code,name,sort_no) VALUES
 ('S','S',1),('M','M',2),('L','L',3),('XL','XL',4),('XXL','XXL',5),
 ('W28','W28',11),('W30','W30',12),('W32','W32',13);

INSERT INTO common_size (common_size_code,name,sort_no) VALUES
 ('CS1','SS相当',1),('CS2','S相当',2),('CS3','M相当',3),('CS4','L相当',4),('CS5','LL相当',5);

-- 表記サイズ→共通サイズ（F-103 はこの対応がないと成立しない）
INSERT INTO size_map (size_code,common_size_code) VALUES
 ('S','CS2'),('M','CS3'),('L','CS4'),('XL','CS5'),('XXL','CS5'),
 ('W28','CS2'),('W30','CS3'),('W32','CS4');

INSERT INTO category (category_code,name,parent_code,sort_no) VALUES
 ('TOPS','トップス',NULL,1),('BOTTOMS','ボトムス',NULL,2),('OUTER','アウター',NULL,3);
INSERT INTO category (category_code,name,parent_code,sort_no) VALUES
 ('TSHIRT','Tシャツ','TOPS',1),('SHIRT','シャツ','TOPS',2),
 ('PANTS','パンツ','BOTTOMS',1),('SKIRT','スカート','BOTTOMS',2),
 ('BLOUSON','ブルゾン','OUTER',1);

INSERT INTO item_type (item_type_code,name) VALUES
 ('TOPS_T','トップス'),('BOTTOMS_T','ボトムス'),('OUTER_T','アウター');

INSERT INTO measure_template (item_type_code,item_name,sort_no) VALUES
 ('TOPS_T','着丈',1),('TOPS_T','身幅',2),('TOPS_T','肩幅',3),
 ('BOTTOMS_T','ウエスト',1),('BOTTOMS_T','股下',2),('BOTTOMS_T','わたり',3);

-- 拠点11件（倉庫1・店舗10）
--   ・都道府県は4ブロック以上に散らす（BR-05 の検証用）
--   ・同一都道府県に2拠点ある組み合わせを作る（東京 T003 / T004）
--   ・締め時刻 15:00 と 12:00 を1件ずつ（BR-23 の検証用）
--   ・EC販売可は倉庫＋店舗3件だけ
INSERT INTO location (location_code,kind,name,pref_code,zip,address,tel,business_days,cutoff_time,ec_saleable) VALUES
 ('W001',1,'中央倉庫',        '12','2600001','千葉県千葉市中央区1-1-1','0432000001',127,'15:00:00',TRUE),
 ('T001',2,'札幌店',          '01','0600001','北海道札幌市中央区北1条1','0112000001',127,'15:00:00',TRUE),
 ('T002',2,'仙台店',          '04','9800001','宮城県仙台市青葉区中央1-1','0222000002',127,'12:00:00',FALSE),
 ('T003',2,'新宿店',          '13','1600022','東京都新宿区新宿3-1-1','0332000003',127,'15:00:00',TRUE),
 ('T004',2,'渋谷店',          '13','1500002','東京都渋谷区渋谷1-1-1','0332000004',127,'15:00:00',TRUE),
 ('T005',2,'横浜店',          '14','2200011','神奈川県横浜市西区高島1-1','0452000005',127,'15:00:00',FALSE),
 ('T006',2,'名古屋店',        '23','4500002','愛知県名古屋市中村区名駅1-1','0522000006',127,'15:00:00',FALSE),
 ('T007',2,'大阪店',          '27','5300001','大阪府大阪市北区梅田1-1-1','0662000007',127,'15:00:00',FALSE),
 ('T008',2,'広島店',          '34','7300011','広島県広島市中区基町1-1','0822000008',126,'15:00:00',FALSE),
 ('T009',2,'高松店',          '37','7600017','香川県高松市番町1-1-1','0872000009',127,'15:00:00',FALSE),
 ('T010',2,'福岡店',          '40','8100001','福岡県福岡市中央区天神1-1','0922000010',127,'15:00:00',FALSE);

-- 休業日（BR-23 の検証用。T008 は日曜休業＋指定休業日、T009 は2日連続）
INSERT INTO location_holiday (location_code,holiday) VALUES
 ('T008','2026-09-15'),('T009','2026-09-21'),('T009','2026-09-22');

INSERT INTO sales_config (effective_from) VALUES ('2026-01-01');

-- ★B-01〜B-12。行が無い定期処理はロックを取れないので、1つも欠かさない。
--   設計 6.6.1 と migrations/001 のコメントは B-01〜B-12。seed が B-07 までしか
--   入れていなかったため、B-08〜B-12 はロックを取れなかった（R-18 で見つけた）。
--   INSERT IGNORE にしてあるので、すでに流した環境でも足りないぶんだけ入る。
INSERT IGNORE INTO batch_lock (batch_id) VALUES
 ('B-01'),('B-02'),('B-03'),('B-04'),('B-05'),('B-06'),
 ('B-07'),('B-08'),('B-09'),('B-10'),('B-11'),('B-12'),
 ('B-13');   -- R-34 で足した。★定期処理を1本足したら、ここにも行を足す（6.6.1）

INSERT INTO operator (operator_id,name,email,password_hash,role,location_code) VALUES
 ('OP001','運用管理者A','admin1@example.com','$dummy$',1,NULL),
 ('OP002','運用管理者B','admin2@example.com','$dummy$',1,NULL),
 ('OP003','受注担当A','order1@example.com','$dummy$',2,NULL),
 ('OP004','受注担当B','order2@example.com','$dummy$',2,NULL),
 ('OP005','サポートA','support1@example.com','$dummy$',5,NULL),
 ('W001S','中央倉庫',  'w001@example.com','$dummy$',3,'W001'),
 ('T001S','札幌店',    't001@example.com','$dummy$',4,'T001'),
 ('T003S','新宿店',    't003@example.com','$dummy$',4,'T003'),
 ('T004S','渋谷店',    't004@example.com','$dummy$',4,'T004');
