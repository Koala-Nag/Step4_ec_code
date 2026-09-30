-- ============================================================
-- 005_payment_notification.sql
--   非同期通知の受け口（設計 7.2.4）に要る表
--
--   ★001〜004 は書き換えない。追記は次の番号で（設計 2.2）
--
--   なぜ要るか
--     7.2.4 は「② 通知IDを保存する。すでにあれば 200 を返して何もしない」と
--     決めているが、保存する先の表が 3.2 に無かった（R-18 で見つけた）。
--     重複対策は「受けた通知IDを覚えている」ことでしか成立しないので、
--     表が無いと ② が実装できない。
--
--   ★列を足す ALTER には AFTER を書く決め（2.2）だが、これは新しい表なので該当しない。
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/005_payment_notification.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

CREATE TABLE IF NOT EXISTS payment_notification (
  notification_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
                  COMMENT '決済代行が振る通知の識別子。★これで重複を弾く（7.2.4 ②）',
  received_at     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  provider_tx_id  VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  idempotency_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
  body            TEXT NOT NULL COMMENT '受けた本文そのもの。あとで突き合わせるため',
  PRIMARY KEY (notification_id),
  KEY idx_pn_received (received_at) COMMENT '1年保持（N-05）'
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_migration (version, note) VALUES
  ('005', 'migrations で適用');

-- ------------------------------------------------------------
-- 確認
-- ------------------------------------------------------------
-- SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ec';  → 48
-- SELECT * FROM schema_migration ORDER BY version;                          → 005 まで
