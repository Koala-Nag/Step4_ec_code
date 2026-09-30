-- ============================================================
-- 003_migration_ledger.sql
--   移行の台帳を作り、すでに当ててある番号を遡って記録する
--   （設計仕様書 2.2.1・3.2.2a）
--
--   ★001・002 はこの台帳ができる前に当たっているので、
--     applied_at は「遡って記録した時刻」になる。実際に当てた時刻ではない。
--     ここは割り切る。台帳の目的は「どこまで当てたか」であって、
--     「いつ当てたか」ではない。
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/003_migration_ledger.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

CREATE TABLE IF NOT EXISTS schema_migration (
  version    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
             COMMENT '移行ファイルの番号（001, 002, ...）',
  applied_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
             COMMENT '当てた日時。ddl から作った場合は作成日時',
  note       VARCHAR(200) NULL
             COMMENT 'どの経路で入ったか',
  PRIMARY KEY (version)
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_migration (version, note) VALUES
  ('001', 'migrations で適用（003 で遡って記録）'),
  ('002', 'migrations で適用（003 で遡って記録）'),
  ('003', 'migrations で適用');

-- ------------------------------------------------------------
-- 確認
-- ------------------------------------------------------------
-- SELECT * FROM schema_migration ORDER BY version;
--   → 001 / 002 / 003 の3行
-- SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ec';
--   → 47 になること（46 + 1）
