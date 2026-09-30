-- ============================================================
-- 006_auth.sql
--   会員・運営者の認証に要るもの（設計 8.3.1・要件 N-22〜N-26・N-28a）
--
--   ★001〜005 は書き換えない。追記は次の番号で（設計 2.2）
--   ★列を足す ALTER には AFTER を書く（2.2。書かないと末尾に付いて ddl/ と並びが変わる）
--
--   なぜ要るか
--     N-23「同一アカウントへのログイン失敗10回で30分ロック」を守るには、
--     「何回失敗したか」と「いつまでロックか」を持つ場所が要る。
--     member.status に 2=ロック はあるが、★これは戻し方が無い。
--     30分で自然に解ける必要があるので、期限を持つ列を足す。
--
--     N-25「再設定URLの有効期限60分・一度使ったら無効」も、保存先が 3.2 に無かった。
--     member_confirm（E-41）と同じ形の表を作る。
--
--     N-23 の後半「あわせてIP単位のレート制限を設ける」も保存先が無かった。
--     ★プロセスの中に持ってはいけない（App Service は複数インスタンス。6.6 と同じ理由）。
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/006_auth.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

-- ------------------------------------------------------------
-- ① 会員・運営者に「失敗回数」と「ロック期限」を足す（N-23）
--    ★AFTER を書く。書かないと末尾に付いて ddl/ と並びがずれる（R-04 で踏んだ）
-- ------------------------------------------------------------
ALTER TABLE member
  ADD COLUMN failed_count TINYINT UNSIGNED NOT NULL DEFAULT 0
      COMMENT 'N-23 連続ログイン失敗回数。成功で0に戻す' AFTER status,
  ADD COLUMN locked_until DATETIME(3) NULL
      COMMENT 'N-23 ここまでロック。★status=2 と違い、時間で自然に解ける' AFTER failed_count;

ALTER TABLE operator
  ADD COLUMN failed_count TINYINT UNSIGNED NOT NULL DEFAULT 0
      COMMENT 'N-23。会員と同じ制限をかける（F-1301）' AFTER is_active,
  ADD COLUMN locked_until DATETIME(3) NULL
      COMMENT 'N-23' AFTER failed_count;

-- ------------------------------------------------------------
-- ② パスワード再設定のトークン（N-25・AP-503）
--    ★member_confirm（E-41）と同じ形にそろえる。読む人が迷わないように
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS password_reset (
  token      CHAR(43) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
             COMMENT '★URLのパス部分に置く。クエリ文字列に置かない（8.6）',
  member_id  VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  expires_at DATETIME(3)  NOT NULL COMMENT 'N-25 発行から60分',
  used       BOOLEAN      NOT NULL DEFAULT FALSE COMMENT 'N-25 一度使ったら無効',
  created_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (token),
  KEY idx_pr_expires (expires_at),
  KEY idx_pr_member (member_id),
  CONSTRAINT fk_pr_member FOREIGN KEY (member_id) REFERENCES member(member_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- ③ IP単位のレート制限（N-23 の後半）
--    ★アカウントの鍵にしない。未登録のアドレスを何百通り試す攻撃は、
--      アカウント単位のロックでは1回も止まらない
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS login_attempt (
  src_ip       VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  window_start DATETIME(3)  NOT NULL COMMENT 'この時刻から数えている',
  failed_count INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (src_ip),
  KEY idx_la_window (window_start)
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_migration (version, note) VALUES
  ('006', 'migrations で適用');

-- ------------------------------------------------------------
-- 確認
-- ------------------------------------------------------------
-- SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ec';  → 50
-- SELECT * FROM schema_migration ORDER BY version;                          → 006 まで
-- SHOW COLUMNS FROM member LIKE 'locked_until';                             → status の後ろ
