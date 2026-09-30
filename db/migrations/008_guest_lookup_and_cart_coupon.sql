-- ============================================================
-- 008_guest_lookup_and_cart_coupon.sql
--   ゲスト注文の照会（F-313・AP-306・N-27）と、カートのクーポン（F-309・AP-204）。R-29
--
--   ★001〜007 は書き換えない。追記は次の番号で（設計 2.2）
--   ★列を足す ALTER には AFTER を書く（書かないと末尾に付いて ddl/ と並びが変わる）
--
--   なぜ要るか
--     ① session.guest_order_no
--        N-27「ゲストの照会権は、その注文番号1件ぶんだけセッションに持たせる」。
--        ★列を1つにしたのが決めごとの形。2件目を照会すると上書きされ、1件目は触れなくなる。
--     ② lookup_attempt
--        N-27「連続失敗にはレート制限をかける」。BR-26（login_attempt）と同じ形で、★失敗だけを数える。
--        ★login_attempt と表を分ける。ログインの失敗と照会の失敗を足し合わせると、
--          照会を数回まちがえた客がログインまで締め出される。
--     ③ cart_coupon
--        AP-204「クーポンの適用・解除」。★適用したコードをカートと同じキーで持つ。
--        画面が注文のときにコードを送り直す形にしない（金額と同じく、サーバが持っているものを使う）。
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/008_guest_lookup_and_cart_coupon.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

ALTER TABLE session
  ADD COLUMN guest_order_no VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT 'F-313 照会を通った注文番号。★1件ぶんだけ（N-27）'
    AFTER operator_id;

CREATE TABLE lookup_attempt (
  src_ip       VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  window_start DATETIME(3)  NOT NULL COMMENT 'この時刻から数えている',
  failed_count INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (src_ip),
  KEY idx_lk_window (window_start)
) ENGINE=InnoDB;

CREATE TABLE cart_coupon (
  cart_key    VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'cart と同じキー（会員は会員ID）',
  coupon_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  applied_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (cart_key),
  KEY fk_cc_coupon (coupon_code),
  CONSTRAINT fk_cc_coupon FOREIGN KEY (coupon_code) REFERENCES coupon(coupon_code)
) ENGINE=InnoDB;
