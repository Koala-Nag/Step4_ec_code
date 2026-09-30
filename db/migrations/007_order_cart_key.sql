-- ============================================================
-- 007_order_cart_key.sql
--   注文に「どのカートから作ったか」を控える（設計 6.2.6。R-27）
--
--   ★001〜006 は書き換えない。追記は次の番号で（設計 2.2）
--   ★列を足す ALTER には AFTER を書く（書かないと末尾に付いて ddl/ と並びが変わる）
--
--   なぜ要るか
--     6.2.6「注文が客の注文として成立した時点で、その注文になった明細だけをカートから消す」。
--     成立するのは AP-301a（引当済・支払い待ち）だけでなく、
--     ★B-07（認証中のまま30分 → 支払い待ち）でも起きる。B-07 はリクエストを持たないので、
--       カートキー（X-Cart-Key）を注文の側に控えておかないと消せない。
--
--     ★消したら NULL に戻す。「NULL でないときだけ消す」を条件付きUPDATEにすると、
--       再決済（支払い待ち → 引当済）でもう一度成立したときに、二重に減らさない。
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/007_order_cart_key.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

ALTER TABLE orders
  ADD COLUMN cart_key VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL
    COMMENT '注文を作ったカート（6.2.6）。成立してカートから消したら NULL に戻す'
    AFTER coupon_code;
