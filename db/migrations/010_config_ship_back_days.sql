-- ============================================================
-- 010_config_ship_back_days.sql
--   返送期限の日数を販売設定に置く（FT-01。R-32）
--
--   ★001〜009 は書き換えない。追記は次の番号で（設計 2.2）
--   ★列を足す ALTER には AFTER を書く（書かないと末尾に付いて ddl/ と並びが変わる）
--
--   なぜ要るか
--     R-31 で返送期限（MSG-12）を「承認から7日」とコードの定数で書いた。
--     ★FT-01 は期限値をコードに直接書かないと決めている。定数のままだと、試験も運用も値を変えられない。
--     ★承認のときに日付を保存するので、日数を変えても送ったメールと画面は食い違わない（R-31 の回答1）。
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/010_config_ship_back_days.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

ALTER TABLE sales_config
  ADD COLUMN return_ship_back_days INT UNSIGNED NOT NULL DEFAULT 7 COMMENT '返送期限（承認から何日。MSG-12）。★過ぎても判定しない（目安）' AFTER return_limit_days;
