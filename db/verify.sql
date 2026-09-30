-- ============================================================
-- 設計の検証  引当まわりが本当に成立するかを確かめる
--   docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/verify.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

SELECT '===== 検証1  引当済数が在庫数を上回った状態を作れるか =====' AS `　`;
-- BR-04a の結果として恒常的に起きる状態（在庫数2・引当済数7）
UPDATE stock SET qty=10, reserved_qty=10 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
UPDATE stock SET reserved_qty = reserved_qty - 3 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1 AND reserved_qty >= 3;
UPDATE stock SET qty = 2 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
SELECT sku_code,location_code,qty,reserved_qty,
       '↑ 引当済数7 > 在庫数2。これが通常運用で残る状態' AS note
  FROM stock WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;

SELECT '===== 検証2  引き算をすると落ちるか（落ちるのが正しい） =====' AS `　`;
-- 次の1行はエラー 1690 で落ちる。落ちることが「引き算を使ってはいけない」証拠になる
--   コメントを外して1回だけ実行し、エラーを確認したら戻すこと
-- SELECT qty - reserved_qty FROM stock WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;
SELECT '上の行はコメントアウトしてある。手で外して1回実行し、ERROR 1690 が出ることを確認する' AS note;

SELECT '===== 検証3  引き算をしない読み方なら0が返るか =====' AS `　`;
SELECT sku_code, location_code,
       GREATEST(CAST(qty AS SIGNED) - CAST(reserved_qty AS SIGNED), 0) AS saleable_qty
  FROM stock WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;

-- 元に戻す
UPDATE stock SET qty=3, reserved_qty=0 WHERE sku_code='P0001-BK-M' AND location_code='T003' AND section=1;

SELECT '===== 検証4  BR-05 の並び順  届け先が東京(13)のとき =====' AS `　`;
SELECT s.location_code, l.name, l.kind AS `1=倉庫2=店舗`, l.pref_code, p.region,
       CASE WHEN l.pref_code = '13' THEN 2
            WHEN p.region = (SELECT region FROM prefecture WHERE pref_code='13') THEN 3
            ELSE 4 END AS priority_step,
       GREATEST(CAST(s.qty AS SIGNED) - CAST(s.reserved_qty AS SIGNED),0) AS saleable
  FROM stock s
  JOIN location   l ON l.location_code = s.location_code
  JOIN prefecture p ON p.pref_code = l.pref_code
  JOIN sku       sk ON sk.sku_code = s.sku_code
 WHERE s.sku_code = 'P0001-BK-M'
   -- ↓ ここから 3.2.2 ⑥（a）候補拠点の条件。検証5と一字一句そろえる
   AND s.section = 1                       -- バックヤードのみ（BR-02）
   AND l.ec_saleable = TRUE
   AND l.suspended = FALSE
   AND NOT EXISTS (SELECT 1 FROM ec_exclusion e
                    WHERE e.product_code = sk.product_code AND e.location_code = l.location_code)
   -- ↑ ここまで（a）。数量の条件（b）は付けない（明細ごとに違うため。3.2.2 ⑥）
 ORDER BY priority_step, l.kind, l.location_code;
SELECT '期待：T003(東京) → T004(東京) → W001(千葉=関東) → T001(北海道)。T002は ec_saleable=FALSE で出ない' AS note;
SELECT '※ 段1（受取店）は配送の注文には現れない。欠番ではない（3.2.2 ⑥）。店舗受取は未実装のため検証しない' AS note;

SELECT '===== 検証5  除外テーブルが効くか（P0002 は新宿に出ないこと） =====' AS `　`;
SELECT s.location_code, l.name
  FROM stock s
  JOIN sku      sk ON sk.sku_code = s.sku_code
  JOIN location l  ON l.location_code = s.location_code
 WHERE sk.product_code = 'P0002'
   -- ↓ ここから 3.2.2 ⑥（a）候補拠点の条件。検証4と一字一句そろえる
   AND s.section = 1                       -- バックヤードのみ（BR-02）
   AND l.ec_saleable = TRUE
   AND l.suspended = FALSE
   AND NOT EXISTS (SELECT 1 FROM ec_exclusion e
                    WHERE e.product_code = sk.product_code AND e.location_code = l.location_code)
   -- ↑ ここまで（a）。数量の条件（b）は付けない（明細ごとに違うため。3.2.2 ⑥）
 ORDER BY l.kind, l.location_code;
SELECT '期待：W001 のみ（T003 は ec_exclusion にあるので出ない）' AS note;

SELECT '===== 検証6  解放を二重にしても落ちないか（3手で確かめる） =====' AS `　`;
-- 前提をそろえる。P0001-BK-L / W001 を 在庫1・引当0 に戻す
UPDATE stock SET qty=1, reserved_qty=0 WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1;

SELECT '--- 手順1  引当する（reserved_qty を 1 にする）。期待：更新件数 1 ---' AS `　`;
UPDATE stock SET reserved_qty = reserved_qty + 1
 WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1
   AND qty >= reserved_qty + 1;
SELECT ROW_COUNT() AS `手順1の更新件数（期待 1）`;

SELECT '--- 手順2  解放する。期待：更新件数 1 ---' AS `　`;
UPDATE stock SET reserved_qty = reserved_qty - 1
 WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1
   AND reserved_qty >= 1;
SELECT ROW_COUNT() AS `手順2の更新件数（期待 1）`;

SELECT '--- 手順3  もう一度おなじ解放。期待：更新件数 0、かつエラーにならない ---' AS `　`;
UPDATE stock SET reserved_qty = reserved_qty - 1
 WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1
   AND reserved_qty >= 1;
SELECT ROW_COUNT() AS `手順3の更新件数（期待 0。ここが0で、かつ例外にならないことが要件。3.2.4）`;

SELECT sku_code, location_code, qty, reserved_qty,
       '↑ 引当済数は0で止まる。負にもならず、例外にもならない' AS note
  FROM stock WHERE sku_code='P0001-BK-L' AND location_code='W001' AND section=1;
