-- ============================================================
-- 注文・出荷・決済・返品・運用
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

-- T-20 注文
--   届け先は複写して持つ（住所帳への外部キーにしない。BR-17 / 3.2.2 ③）
--   ship_pref_code は BR-05 の「近い順」の判定に使う
CREATE TABLE orders (
  order_no          VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  member_id         VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT 'ゲスト注文では NULL',
  -- 7.2.2a。AP-301a はゲストでも叩けるので、注文番号だけでは足りない。
  --   session への外部キーは張らない（セッションは消えるが注文は消さない。要るのは一致の比較だけ）
  origin_session_id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL
                    COMMENT 'この注文を作ったセッション（7.2.2a）。AP-301a はこれと一致する呼び出しだけを受ける。決済後は使わない',
  orderer_name      VARCHAR(50)  NOT NULL COMMENT '注文者。退会しても消さない',
  orderer_email     VARCHAR(254) NOT NULL,
  ordered_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  status            TINYINT      NOT NULL COMMENT '5.4 の注文状態',
  receive_method    TINYINT      NOT NULL COMMENT '1=配送 2=店舗受取',
  pickup_location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '店舗受取のときだけ',
  ship_name         VARCHAR(50)  NOT NULL,
  ship_zip          CHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  ship_pref_code    CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  ship_address      VARCHAR(100) NOT NULL,
  ship_tel          VARCHAR(11) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  item_total        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '商品合計・税込',
  discount_amount   INT UNSIGNED NOT NULL DEFAULT 0,
  shipping_fee      INT UNSIGNED NOT NULL DEFAULT 0,
  tax_amount        INT UNSIGNED NOT NULL DEFAULT 0,
  total_amount      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '支払総額',
  coupon_code       VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  cart_key          VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '注文を作ったカート（6.2.6）。成立してカートから消したら NULL に戻す',
  partial_returned  BOOLEAN      NOT NULL DEFAULT FALSE,
  created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (order_no),
  KEY idx_orders_status (status, ordered_at),
  KEY idx_orders_email (orderer_email) COMMENT 'F-313 ゲスト照会 / F-901 メアドで探す',
  KEY idx_orders_member (member_id),
  CONSTRAINT fk_orders_member  FOREIGN KEY (member_id)            REFERENCES member(member_id),
  CONSTRAINT fk_orders_pickup  FOREIGN KEY (pickup_location_code) REFERENCES location(location_code),
  CONSTRAINT fk_orders_pref    FOREIGN KEY (ship_pref_code)       REFERENCES prefecture(pref_code),
  CONSTRAINT fk_orders_coupon  FOREIGN KEY (coupon_code)          REFERENCES coupon(coupon_code)
) ENGINE=InnoDB;

-- T-21 注文明細
--   alloc_status と alloc_qty は、引当を二重に解放しないために持つ（3.2.4）
CREATE TABLE order_line (
  order_no            VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  line_no             SMALLINT     NOT NULL COMMENT 'BR-21 の端数を寄せる先の決定に使う',
  sku_code            VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  qty                 INT UNSIGNED NOT NULL,
  unit_price          INT UNSIGNED NOT NULL COMMENT '注文確定時の税込単価（BR-17）',
  tax_rate            DECIMAL(4,3) NOT NULL,
  allocated_discount  INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '割引の按分額。注文確定時に確定して保存する（BR-21・6.5.2）',
  alloc_location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NULL,
  alloc_status        TINYINT      NOT NULL DEFAULT 0 COMMENT '0=未引当 1=引当済 2=解放済',
  alloc_qty           INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '解放時にこの値を戻す',
  PRIMARY KEY (order_no, line_no),
  KEY idx_ol_sku (sku_code),
  CONSTRAINT fk_ol_order    FOREIGN KEY (order_no)            REFERENCES orders(order_no),
  CONSTRAINT fk_ol_sku      FOREIGN KEY (sku_code)            REFERENCES sku(sku_code),
  CONSTRAINT fk_ol_location FOREIGN KEY (alloc_location_code) REFERENCES location(location_code)
) ENGINE=InnoDB;

-- T-22 注文状態履歴
CREATE TABLE order_status_log (
  id           BIGINT AUTO_INCREMENT,
  order_no     VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  status_from  TINYINT      NULL,
  status_to    TINYINT      NOT NULL,
  changed_by   TINYINT      NOT NULL COMMENT '1=会員 2=運営者 3=システム',
  operator_id  VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  reason       VARCHAR(200) NULL,
  created_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_osl_order (order_no, created_at),
  CONSTRAINT fk_osl_order FOREIGN KEY (order_no) REFERENCES orders(order_no)
) ENGINE=InnoDB;

-- T-24 出荷
--   届け先は客の住所でも受取店でも同じ列に複写する（拠点の住所を後で編集しても過去は変わらない）
CREATE TABLE shipment (
  id              BIGINT AUTO_INCREMENT,
  order_no        VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  from_location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dest_kind       TINYINT      NOT NULL COMMENT '1=客の住所 2=受取店（BR-08b）',
  dest_name       VARCHAR(50)  NOT NULL,
  dest_zip        CHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dest_pref_code  CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  dest_address    VARCHAR(100) NOT NULL,
  dest_tel        VARCHAR(11) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  status          TINYINT      NOT NULL COMMENT '1=指示済 2=出荷済 3=到着済 4=店舗到着 5=引渡済 6=欠品 7=キャンセル',
  planned_ship_date DATE       NOT NULL COMMENT 'BR-23。作成時に確定し、以後再計算しない',
  carrier         VARCHAR(30)  NULL,
  tracking_no     VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '客の住所宛は必須、取り置きは空',
  staff_name      VARCHAR(50)  NULL COMMENT '発送を記録した担当者名（共有アカウントのため手入力）',
  shipped_at      DATETIME(3)  NULL,
  arrived_at      DATETIME(3)  NULL,
  handed_at       DATETIME(3)  NULL,
  short_actual_qty INT UNSIGNED NULL COMMENT '欠品時の報告実在庫数',
  short_reporter  VARCHAR(50)  NULL,
  short_at        DATETIME(3)  NULL,
  created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_ship_order (order_no),
  KEY idx_ship_from (from_location_code, status),
  CONSTRAINT fk_ship_order FOREIGN KEY (order_no)           REFERENCES orders(order_no),
  CONSTRAINT fk_ship_from  FOREIGN KEY (from_location_code) REFERENCES location(location_code),
  CONSTRAINT fk_ship_pref  FOREIGN KEY (dest_pref_code)     REFERENCES prefecture(pref_code)
) ENGINE=InnoDB;

-- T-25 出荷明細
CREATE TABLE shipment_line (
  shipment_id BIGINT       NOT NULL,
  order_no    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  line_no     SMALLINT     NOT NULL,
  qty         INT UNSIGNED NOT NULL,
  PRIMARY KEY (shipment_id, order_no, line_no),
  CONSTRAINT fk_sl_shipment FOREIGN KEY (shipment_id)      REFERENCES shipment(id),
  CONSTRAINT fk_sl_line     FOREIGN KEY (order_no,line_no) REFERENCES order_line(order_no,line_no)
) ENGINE=InnoDB;

-- T-26 返品申請 / T-26a 返品明細
CREATE TABLE return_req (
  return_no     VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  order_no      VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  status        TINYINT      NOT NULL COMMENT '1=申請中 2=却下 3=返送待ち 4=受領 5=検品済 6=返金済',
  applied_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  reject_reason VARCHAR(200) NULL,
  decided_at    DATETIME(3)  NULL COMMENT '承認・却下の日時（F-503a）',
  decided_by    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '承認・却下した運営者',
  return_deadline DATE      NULL COMMENT '返送期限（MSG-12）。承認のときに決めて保存する',
  received_at   DATETIME(3)  NULL,
  receiver      VARCHAR(50)  NULL,
  return_fee_bearer TINYINT  NOT NULL DEFAULT 1 COMMENT '1=客 2=当社（BR-20）',
  shipping_refund INT UNSIGNED NOT NULL DEFAULT 0,
  refund_total  INT UNSIGNED NOT NULL DEFAULT 0,
  refunded_at   DATETIME(3)  NULL COMMENT '返金を実行した日時（F-503d）',
  PRIMARY KEY (return_no),
  KEY idx_rr_status (status, applied_at),
  CONSTRAINT fk_rr_order FOREIGN KEY (order_no) REFERENCES orders(order_no)
) ENGINE=InnoDB;

CREATE TABLE return_line (
  return_no      VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  order_no       VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  line_no        SMALLINT     NOT NULL,
  qty            INT UNSIGNED NOT NULL,
  reason_kind    TINYINT      NOT NULL COMMENT '1=サイズ 2=イメージ違い 3=不良 4=誤出荷 5=その他',
  reason_text    VARCHAR(200) NULL COMMENT 'その他のときは必須（6.3）',
  inspect_result TINYINT      NULL COMMENT '1=合格 2=不合格',
  inspected_at   DATETIME(3)  NULL,
  inspector      VARCHAR(50)  NULL,
  inspect_note   VARCHAR(200) NULL COMMENT '検品の理由（F-503c）',
  disposal       TINYINT      NULL COMMENT '不合格時 1=返送 2=廃棄（F-503e）',
  refund_amount  INT UNSIGNED NOT NULL DEFAULT 0,
  restocked_at   DATETIME(3)  NULL COMMENT '倉庫の在庫に戻した日時（F-504）。★二重に戻さない',
  restocker      VARCHAR(50)  NULL COMMENT '戻した担当者（共有アカウントのため手入力）',
  PRIMARY KEY (return_no, order_no, line_no),
  CONSTRAINT fk_rl_return FOREIGN KEY (return_no)        REFERENCES return_req(return_no),
  CONSTRAINT fk_rl_line   FOREIGN KEY (order_no,line_no) REFERENCES order_line(order_no,line_no)
) ENGINE=InnoDB;

-- T-23 決済取引
--   冪等キーは与信の試行ごとに新しく発行する（BR-17b）
--   shipment_id と return_req_id は「最大でも一方」。与信・認証はどちらも NULL
CREATE TABLE payment_tx (
  id              BIGINT AUTO_INCREMENT,
  order_no        VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  shipment_id     BIGINT NULL COMMENT '売上確定 / 欠品の返金・取消',
  return_req_id   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '返品の返金',
  tx_kind         TINYINT      NOT NULL COMMENT '1=認証 2=与信 3=売上確定 4=返金 5=取消 6=照会 7=与信不要',
  provider_tx_id  VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  idempotency_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '与信はサーバ発行のキー。それ以外は INSERT 時に採番した UUID（7.2.1）',
  amount          INT UNSIGNED NOT NULL,
  status          TINYINT      NOT NULL COMMENT '1=成功 2=失敗 3=処理中 4=要実行 5=実行中 6=取消不要',
  started_at      DATETIME(3)  NULL COMMENT '実行開始日時。10分過ぎたら B-09・B-10 が拾い直す（7.2.5）',
  attempt_count   TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '3回で打ち切り／通知',
  response_code   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  executed_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_ptx_idem (idempotency_key),
  KEY idx_ptx_order (order_no, tx_kind),
  -- 外部キーの索引を明示する。MySQL は書かなければ自動で作るが、
  -- 自動で作られたぶんは「あとから ALTER で足した索引」より前に並ぶ。
  -- ここを書いておかないと migrations 経路と索引の並び順がずれる（R-05）
  KEY fk_ptx_shipment (shipment_id),
  KEY fk_ptx_return (return_req_id),
  KEY idx_ptx_pending (status, started_at),   -- B-09・B-10 が拾う条件（7.2.5・6.6.2）。無いと全表走査
  CONSTRAINT fk_ptx_order    FOREIGN KEY (order_no)      REFERENCES orders(order_no),
  CONSTRAINT fk_ptx_shipment FOREIGN KEY (shipment_id)   REFERENCES shipment(id),
  CONSTRAINT fk_ptx_return   FOREIGN KEY (return_req_id) REFERENCES return_req(return_no),
  CONSTRAINT ck_ptx_link CHECK (shipment_id IS NULL OR return_req_id IS NULL)
) ENGINE=InnoDB;

-- T-29 クーポン利用履歴
CREATE TABLE coupon_use (
  id          BIGINT AUTO_INCREMENT,
  coupon_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  member_id   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  order_no    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  discount    INT UNSIGNED NOT NULL,
  used_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_cu_member (coupon_code, member_id) COMMENT '会員あたりの上限判定（BR-16a）',
  CONSTRAINT fk_cu_coupon FOREIGN KEY (coupon_code) REFERENCES coupon(coupon_code),
  CONSTRAINT fk_cu_order  FOREIGN KEY (order_no)    REFERENCES orders(order_no)
) ENGINE=InnoDB;

-- T-37 注文メモ / T-36 操作ログ / T-39 認証イベント / T-00 送信メール / T-38 実行ロック / T-30 販売設定
CREATE TABLE order_memo (
  id          BIGINT AUTO_INCREMENT,
  order_no    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  operator_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  body        VARCHAR(500) NOT NULL,
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_memo_order (order_no),
  CONSTRAINT fk_memo_order FOREIGN KEY (order_no) REFERENCES orders(order_no)
) ENGINE=InnoDB;

CREATE TABLE operation_log (
  id          BIGINT AUTO_INCREMENT,
  operator_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  target      VARCHAR(100) NOT NULL,
  action      VARCHAR(100) NOT NULL,
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_oplog_at (created_at) COMMENT '1年保持（N-05）'
) ENGINE=InnoDB;

CREATE TABLE auth_event (
  id          BIGINT AUTO_INCREMENT,
  event_kind  TINYINT      NOT NULL COMMENT '1=ログイン成功 2=失敗 3=ロック 4=パスワード再設定',
  member_id   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  operator_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  src_ip      VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NULL,
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_authev_at (created_at) COMMENT '1年保持（N-05）。パスワードは記録しない'
) ENGINE=InnoDB;

CREATE TABLE sent_mail (
  id         BIGINT AUTO_INCREMENT,
  msg_kind   VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'MSG-01〜MSG-13',
  to_email   VARCHAR(254) NOT NULL,
  subject    VARCHAR(200) NOT NULL,
  body       TEXT         NOT NULL,
  status        TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0=未送信 1=送信済 2=送信失敗（7.3）',
  attempt_count TINYINT UNSIGNED NOT NULL DEFAULT 0,
  next_retry_at DATETIME(3) NULL COMMENT '1分間隔で3回まで。B-11 が拾う',
  result     TINYINT      NULL COMMENT '1=成功 2=失敗。未送信のあいだは NULL',
  sent_at    DATETIME(3)  NULL COMMENT '実際に送った時刻。未送信のあいだは NULL',
  PRIMARY KEY (id),
  KEY idx_mail_sent (sent_at),
  KEY idx_mail_pending (status, next_retry_at)
) ENGINE=InnoDB;

CREATE TABLE batch_lock (
  batch_id   VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'B-01〜B-12',
  holder     VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  acquired_at DATETIME(3) NULL,
  expires_at  DATETIME(3) NULL COMMENT '取得時に NOW()+最大実行時間。過ぎたら次回が奪う（6.6.1）',
  status     TINYINT      NOT NULL DEFAULT 0 COMMENT '0=空き 1=実行中',
  PRIMARY KEY (batch_id)
) ENGINE=InnoDB;

CREATE TABLE sales_config (
  effective_from        DATE         NOT NULL,
  tax_rate              DECIMAL(4,3) NOT NULL DEFAULT 0.100,
  shipping_fee          INT UNSIGNED NOT NULL DEFAULT 550,
  free_shipping_line    INT UNSIGNED NOT NULL DEFAULT 5000,
  session_idle_min      INT UNSIGNED NOT NULL DEFAULT 60,
  reset_url_valid_min   INT UNSIGNED NOT NULL DEFAULT 60,
  auth_timeout_min      INT UNSIGNED NOT NULL DEFAULT 30,
  unpaid_cancel_hour    INT UNSIGNED NOT NULL DEFAULT 24,
  return_limit_days     INT UNSIGNED NOT NULL DEFAULT 17,
  return_ship_back_days INT UNSIGNED NOT NULL DEFAULT 7 COMMENT '返送期限（承認から何日。MSG-12）。★過ぎても判定しない（目安）',
  arrival_assume_days   INT UNSIGNED NOT NULL DEFAULT 3,
  stagnant_days         INT UNSIGNED NOT NULL DEFAULT 60,
  login_lock_min        INT UNSIGNED NOT NULL DEFAULT 30,
  login_fail_limit      INT UNSIGNED NOT NULL DEFAULT 10,
  cart_keep_days        INT UNSIGNED NOT NULL DEFAULT 30,
  error_digest_min      INT UNSIGNED NOT NULL DEFAULT 10,
  pickup_limit_days     INT UNSIGNED NOT NULL DEFAULT 7,
  shortage_judge_hour   INT UNSIGNED NOT NULL DEFAULT 24,
  -- ここから下は 9/1 の追加分。migrations/001 が ALTER で末尾に足すため、列順を合わせてある
  confirm_url_valid_min INT UNSIGNED NOT NULL DEFAULT 60 COMMENT '会員登録の確認URLの有効期限（8.3.1）',
  notice_text           VARCHAR(200) NULL COMMENT '計画停止のお知らせ（N-02）',
  notice_from           DATETIME(3)  NULL,
  notice_to             DATETIME(3)  NULL,
  PRIMARY KEY (effective_from)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 設計 v0.1（2026-09-01）で足したテーブル
--   migrations/001_catch_up_to_design_v01.sql と同じ形
-- ------------------------------------------------------------

-- E-41 会員登録の確認  8.3.1
CREATE TABLE member_confirm (
  token          CHAR(43) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  email          VARCHAR(254) NOT NULL,
  password_hash  VARCHAR(255) NOT NULL COMMENT '会員と同じ形でハッシュ化して持つ',
  expires_at     DATETIME(3)  NOT NULL,
  used           BOOLEAN      NOT NULL DEFAULT FALSE,
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (token),
  KEY idx_mc_expires (expires_at)
) ENGINE=InnoDB;

-- E-40 通知抑止  8.4
CREATE TABLE notify_throttle (
  notify_kind    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  last_sent_at   DATETIME(3)  NULL,
  suppressed_cnt INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (notify_kind)
) ENGINE=InnoDB;

-- E-42 一時停止の到達記録  10.2.1（FT-07）
CREATE TABLE pause_hit (
  point_name  VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  hit_at      DATETIME(3) NULL,
  released_at DATETIME(3) NULL,
  PRIMARY KEY (point_name)
) ENGINE=InnoDB;

-- E-43 決済代行からの非同期通知（設計 7.2.4）
--   ★重複対策は「受けた通知IDを覚えている」ことでしか成立しない。
--     7.2.4 が「通知IDを保存する」と決めているのに、表が 3.2 に無かった（R-18）。
CREATE TABLE payment_notification (
  notification_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
                  COMMENT '決済代行が振る通知の識別子。★これで重複を弾く（7.2.4 ②）',
  received_at     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  provider_tx_id  VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  idempotency_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
  body            TEXT NOT NULL COMMENT '受けた本文そのもの。あとで突き合わせるため',
  PRIMARY KEY (notification_id),
  KEY idx_pn_received (received_at) COMMENT '1年保持（N-05）'
) ENGINE=InnoDB;

-- E-44 パスワード再設定のトークン（N-25・AP-503）
--   ★member_confirm（E-41）と同じ形にそろえてある。読む人が迷わないように。
--   ★トークンはURLのパス部分に置く。クエリ文字列に置かない（8.6）
CREATE TABLE password_reset (
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

-- E-45 IP単位のログイン失敗（N-23 の後半）
--   ★アカウントの鍵にしない。未登録のアドレスを何百通り試す攻撃は、
--     アカウント単位のロックでは1回も止まらない。
--   ★プロセスの中に持たない（App Service は複数インスタンス。6.6 と同じ理由）
CREATE TABLE login_attempt (
  src_ip       VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  window_start DATETIME(3)  NOT NULL COMMENT 'この時刻から数えている',
  failed_count INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (src_ip),
  KEY idx_la_window (window_start)
) ENGINE=InnoDB;

-- ★F-313 ゲスト照会の連続失敗（N-27。BR-26 と同じ形で、失敗だけを数える。R-29・migrations/008）
CREATE TABLE lookup_attempt (
  src_ip       VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  window_start DATETIME(3)  NOT NULL COMMENT 'この時刻から数えている',
  failed_count INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (src_ip),
  KEY idx_lk_window (window_start)
) ENGINE=InnoDB;
