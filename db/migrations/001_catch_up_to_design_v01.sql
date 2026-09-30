-- ============================================================
-- 001  DDL を設計仕様書 v0.1（2026-09-01 版）に追いつかせる
--
--   起票  HANDOFF.md R-04
--   対象  8/31〜9/1 の設計変更で足りなくなったテーブル3つと列7つ
--   注意  ddl/ は「いま何があるか」の正、migrations/ は「前の版からどう動かすか」
--         このファイルを流したあと、ddl/ 側も同じ形になっている
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

-- ------------------------------------------------------------
-- 1. 新しいテーブル
-- ------------------------------------------------------------

-- E-41 会員登録の確認   設計 8.3.1 / 3.2.2a
--   N-26 は「応答をそろえる」だけでは守れない。会員はURLを開いた時点で作る。
--   そのため、登録要求の時点で受け取ったパスワードをここに預かる（平文では持たない）。
CREATE TABLE member_confirm (
  token          CHAR(43) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'URL に載せる乱数',
  email          VARCHAR(254) NOT NULL,
  password_hash  VARCHAR(255) NOT NULL COMMENT '会員と同じ形でハッシュ化して持つ',
  expires_at     DATETIME(3)  NOT NULL COMMENT '有効期限。sales_config.confirm_url_valid_min',
  used           BOOLEAN      NOT NULL DEFAULT FALSE,
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (token),
  KEY idx_mc_expires (expires_at)
) ENGINE=InnoDB;

-- E-40 通知抑止   設計 8.4
--   N-13 の「同一種別は10分に1通」を、複数インスタンスでも成立させる。
--   プロセスの中に持つと再起動とデプロイで消えるため、必ずここに置く。
--   ★DB接続の失敗（N-13 ④）だけは、この表が読めないので対象外にする。
CREATE TABLE notify_throttle (
  notify_kind    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'N-13 の4条件＋設計で足した5種',
  last_sent_at   DATETIME(3)  NULL,
  suppressed_cnt INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'まとめた件数。本文に出す',
  PRIMARY KEY (notify_kind)
) ENGINE=InnoDB;

-- E-42 一時停止の到達記録   設計 10.2.1
--   FT-07 の試験で「止める地点に着いた」ことを試験側から観測するため。
--   秒数を手で数える試験は再現しない。
--   検証環境でしか書かれないが、テーブルは本番にも作る（環境でスキーマを変えない）。
CREATE TABLE pause_hit (
  point_name  VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'before_stock_update など',
  hit_at      DATETIME(3) NULL COMMENT '地点に到達した時刻',
  released_at DATETIME(3) NULL,
  PRIMARY KEY (point_name)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2. 既存テーブルへの列の追加
-- ------------------------------------------------------------

-- 設計 6.6.1  落ちたプロセスのロックを次回が奪えるようにする。
--   期限が無いと、その定期処理は再起動しても永久に動かない。
ALTER TABLE batch_lock
  ADD COLUMN expires_at DATETIME(3) NULL COMMENT '取得時に NOW()+最大実行時間。過ぎたら次回が奪う' AFTER acquired_at,
  MODIFY COLUMN batch_id VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'B-01〜B-12';

-- 設計 7.2.5 / 6.6.2  「実行中」のまま落ちた行を B-09・B-10 が10分後に拾う。
--   3回失敗を数える場所も無かった。
--   冪等キーは与信だけでなく、売上確定・取消・返金にも添える（値は決済取引の行ID）。
ALTER TABLE payment_tx
  ADD COLUMN started_at    DATETIME(3)  NULL COMMENT '実行開始日時。10分過ぎたら拾い直す' AFTER status,
  ADD COLUMN attempt_count TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '3回で打ち切り／通知' AFTER started_at,
  MODIFY COLUMN idempotency_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL
    COMMENT '与信はサーバ発行のキー。それ以外は決済取引の行ID（7.2.1）',
  MODIFY COLUMN status TINYINT NOT NULL
    COMMENT '1=成功 2=失敗 3=処理中 4=要実行 5=実行中 6=取消不要';

-- 設計 7.3  メールはリクエストの中で送らない。行を先に作り、B-11 が拾う。
--   1通＝1行にすると「状態が2回変われば2通」と「失敗を3回試す」が混ざらない。
ALTER TABLE sent_mail
  ADD COLUMN status        TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0=未送信 1=送信済 2=送信失敗' AFTER body,
  ADD COLUMN attempt_count TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER status,
  ADD COLUMN next_retry_at DATETIME(3) NULL COMMENT '1分間隔で3回まで' AFTER attempt_count,
  MODIFY COLUMN result  TINYINT NULL COMMENT '1=成功 2=失敗。未送信のあいだは NULL',
  MODIFY COLUMN sent_at DATETIME(3) NULL COMMENT '実際に送った時刻。未送信のあいだは NULL',
  ADD KEY idx_mail_pending (status, next_retry_at);

-- 設計 8.3.1（会員登録の確認URL）／ N-02（計画停止のお知らせ）
--   時間に関する値と、掲出の文言は、すべて管理画面から変える（FT-01）。
ALTER TABLE sales_config
  ADD COLUMN confirm_url_valid_min INT UNSIGNED NOT NULL DEFAULT 60 COMMENT '会員登録の確認URLの有効期限',
  ADD COLUMN notice_text  VARCHAR(200) NULL COMMENT '計画停止のお知らせ（N-02）。全画面の最上部',
  ADD COLUMN notice_from  DATETIME(3)  NULL,
  ADD COLUMN notice_to    DATETIME(3)  NULL;

-- 設計 6.5.2  ★これが無いと、返品のたびに按分を計算することになり、
--   端数が申請回数ぶん多重に引かれる（3明細1000円・割引100円を2回に分けると1円ずれる）。
--   注文確定のときに1回だけ計算して、ここに保存する。
ALTER TABLE order_line
  ADD COLUMN allocated_discount INT UNSIGNED NOT NULL DEFAULT 0
    COMMENT '注文の割引額を明細金額の比で按分した額。端数は注文全体で行番号が最大の明細に寄せる（BR-21）'
    AFTER tax_rate;

-- ------------------------------------------------------------
-- 3. 確認
-- ------------------------------------------------------------
-- SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ec';
--   → 46 になること（43 + 3）
