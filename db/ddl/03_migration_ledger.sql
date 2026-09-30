-- ============================================================
-- 03_migration_ledger.sql
--   移行の台帳（設計仕様書 2.2.1・3.2.2a）
--
--   ★このファイルは ddl/ の最後に流れる。
--     ddl/ から作った新品は「自分が何番相当か」を、この表で名乗る。
--     これが無いと、新品に migrations/002 を流して ERROR 1061 で落ち、
--     しかも落ちた位置より後ろの詰め替えだけが漏れる（R-05 で実際に踏んだ）。
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

CREATE TABLE schema_migration (
  version    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
             COMMENT '移行ファイルの番号（001, 002, ...）',
  applied_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
             COMMENT '当てた日時。ddl から作った場合は作成日時',
  note       VARCHAR(200) NULL
             COMMENT 'どの経路で入ったか',
  PRIMARY KEY (version)
) ENGINE=InnoDB;

-- ddl/ には 002 までの内容が含まれている。
--   ★migrations/ を1本足したら、必ずここにも1行足す。
--     足し忘れると、新品に対してその番号がもう一度流れる。
INSERT IGNORE INTO schema_migration (version, note) VALUES
  ('001', 'ddl から作成（内容は 01/02_schema に含まれている）'),
  ('002', 'ddl から作成（内容は 01/02_schema に含まれている）'),
  ('003', 'ddl から作成（この台帳そのもの）'),
  ('004', 'ddl から作成（内容は 01/02_schema に含まれている）'),
  ('005', 'ddl から作成（内容は 02_schema_order に含まれている）'),
  ('006', 'ddl から作成（内容は 01_schema の列と 02_schema_order の表に含まれている）'),
  ('007', 'ddl から作成（内容は 02_schema_order の orders.cart_key に含まれている）'),
  ('008', 'ddl から作成（内容は 01_schema の session.guest_order_no・cart_coupon と 02_schema_order の lookup_attempt に含まれている）'),
  ('009', 'ddl から作成（内容は 02_schema_order の return_req・return_line の列に含まれている）'),
  ('010', 'ddl から作成（内容は 02_schema_order の sales_config.return_ship_back_days に含まれている）'),
  ('011', 'ddl から作成（内容は seed/02_master.sql の batch_lock B-13 の行に含まれている）');
