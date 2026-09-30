-- ============================================================
-- 自社ECサイト  テーブル定義
-- 設計仕様書 ECDD-01 v0.1 / 3章 データ設計 に対応する
-- このファイルがテーブル定義の正である
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

-- 共通の約束
--   * 文字コードは utf8mb4、照合順序は utf8mb4_0900_ai_ci（全角半角・大小文字を同一視）
--   * コード列だけは ascii_bin。昇順の比較に使うため（9.4 のデッドロック回避）
--   * 金額は INT（円単位）。小数は使わない
--   * 日時は DATETIME(3)。日本時間で入れる
--   * 論理削除は使わない。マスタは is_active で無効化する

-- ------------------------------------------------------------
-- マスタ
-- ------------------------------------------------------------

-- T-11a 都道府県  BR-05a
CREATE TABLE prefecture (
  pref_code   CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name        VARCHAR(8)  NOT NULL,
  region      TINYINT     NOT NULL COMMENT '1=北海道 2=東北 3=関東 4=中部 5=近畿 6=中国 7=四国 8=九州沖縄',
  PRIMARY KEY (pref_code)
) ENGINE=InnoDB;

-- T-03 色
CREATE TABLE color (
  color_code  VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name        VARCHAR(30) NOT NULL,
  sort_no     SMALLINT    NOT NULL DEFAULT 0,
  is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
  PRIMARY KEY (color_code)
) ENGINE=InnoDB;

-- T-04 サイズ
CREATE TABLE size (
  size_code   VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name        VARCHAR(30) NOT NULL,
  sort_no     SMALLINT    NOT NULL DEFAULT 0,
  is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
  PRIMARY KEY (size_code)
) ENGINE=InnoDB;

-- T-05 共通サイズ  F-109
CREATE TABLE common_size (
  common_size_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name        VARCHAR(30) NOT NULL,
  sort_no     SMALLINT    NOT NULL DEFAULT 0,
  is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
  PRIMARY KEY (common_size_code)
) ENGINE=InnoDB;

-- T-06 サイズ対応  表記サイズ→共通サイズ
CREATE TABLE size_map (
  size_code        VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  common_size_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (size_code, common_size_code),
  CONSTRAINT fk_sizemap_size   FOREIGN KEY (size_code)        REFERENCES size(size_code),
  CONSTRAINT fk_sizemap_common FOREIGN KEY (common_size_code) REFERENCES common_size(common_size_code)
) ENGINE=InnoDB;

-- T-07 カテゴリ  2階層（親が NULL なら大分類）
CREATE TABLE category (
  category_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name          VARCHAR(50) NOT NULL,
  parent_code   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  sort_no       SMALLINT    NOT NULL DEFAULT 0,
  is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
  PRIMARY KEY (category_code),
  CONSTRAINT fk_category_parent FOREIGN KEY (parent_code) REFERENCES category(category_code)
) ENGINE=InnoDB;

-- T-08 アイテム種別
CREATE TABLE item_type (
  item_type_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name           VARCHAR(50) NOT NULL,
  is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
  PRIMARY KEY (item_type_code)
) ENGINE=InnoDB;

-- T-09 採寸項目テンプレート  F-707
CREATE TABLE measure_template (
  item_type_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  item_name      VARCHAR(30) NOT NULL,
  sort_no        SMALLINT    NOT NULL DEFAULT 0,
  PRIMARY KEY (item_type_code, item_name),
  CONSTRAINT fk_measure_itemtype FOREIGN KEY (item_type_code) REFERENCES item_type(item_type_code)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 商品
-- ------------------------------------------------------------

-- T-01 商品
CREATE TABLE product (
  product_code   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name           VARCHAR(100) NOT NULL,
  category_code  VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  item_type_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  material       VARCHAR(200) NULL,
  description    VARCHAR(2000) NULL,
  price          INT UNSIGNED NOT NULL COMMENT '通常価格・税込（BR-09）',
  is_published   BOOLEAN     NOT NULL DEFAULT FALSE,
  publish_at     DATETIME(3) NULL COMMENT 'F-708 公開予約',
  created_at     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (product_code),
  KEY idx_product_cat (category_code, is_published),
  CONSTRAINT fk_product_category FOREIGN KEY (category_code)  REFERENCES category(category_code),
  CONSTRAINT fk_product_itemtype FOREIGN KEY (item_type_code) REFERENCES item_type(item_type_code)
) ENGINE=InnoDB;

-- T-02 SKU
CREATE TABLE sku (
  sku_code         VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  product_code     VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  color_code       VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  size_code        VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  common_size_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (sku_code),
  UNIQUE KEY uq_sku_combo (product_code, color_code, size_code),
  KEY idx_sku_common (common_size_code),
  CONSTRAINT fk_sku_product FOREIGN KEY (product_code)     REFERENCES product(product_code),
  CONSTRAINT fk_sku_color   FOREIGN KEY (color_code)       REFERENCES color(color_code),
  CONSTRAINT fk_sku_size    FOREIGN KEY (size_code)        REFERENCES size(size_code),
  CONSTRAINT fk_sku_common  FOREIGN KEY (common_size_code) REFERENCES common_size(common_size_code)
) ENGINE=InnoDB;

-- T-10 寸法
CREATE TABLE dimension (
  product_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  size_code    VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  item_name    VARCHAR(30)  NOT NULL,
  value        VARCHAR(20)  NOT NULL,
  PRIMARY KEY (product_code, size_code, item_name),
  CONSTRAINT fk_dim_product FOREIGN KEY (product_code) REFERENCES product(product_code)
) ENGINE=InnoDB;

-- T-11 商品画像
CREATE TABLE product_image (
  product_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  color_code   VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  sort_no      SMALLINT     NOT NULL,
  url          VARCHAR(500) NOT NULL COMMENT '画像の相対パス（products/P0001_BK_1.jpg）。表示時に IMAGE_BASE_URL を前置する',
  PRIMARY KEY (product_code, color_code, sort_no),
  CONSTRAINT fk_img_product FOREIGN KEY (product_code) REFERENCES product(product_code),
  CONSTRAINT fk_img_color   FOREIGN KEY (color_code)   REFERENCES color(color_code)
) ENGINE=InnoDB;

-- T-15 セール価格
CREATE TABLE sale_price (
  product_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  start_at     DATETIME(3)  NOT NULL,
  end_at       DATETIME(3)  NOT NULL,
  price        INT UNSIGNED NOT NULL COMMENT 'セール価格・税込',
  PRIMARY KEY (product_code, start_at),
  CONSTRAINT fk_sale_product FOREIGN KEY (product_code) REFERENCES product(product_code)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 拠点と在庫  ここが引当の中心
-- ------------------------------------------------------------

-- T-12 拠点
CREATE TABLE location (
  location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  kind          TINYINT      NOT NULL COMMENT '1=倉庫 2=店舗。BR-05 の並び順にそのまま使う',
  name          VARCHAR(50)  NOT NULL,
  pref_code     CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  zip           CHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  address       VARCHAR(100) NOT NULL,
  tel           VARCHAR(11) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  business_days TINYINT UNSIGNED NOT NULL DEFAULT 127 COMMENT '営業曜日。日=bit0 〜 土=bit6',
  cutoff_time   TIME         NOT NULL DEFAULT '15:00:00' COMMENT 'BR-23 出荷の締め時刻',
  suspended     BOOLEAN      NOT NULL DEFAULT FALSE COMMENT 'BR-24 一時停止',
  ec_saleable   BOOLEAN      NOT NULL DEFAULT FALSE COMMENT 'BR-02 の1段目。倉庫は TRUE 固定',
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (location_code),
  CONSTRAINT fk_location_pref FOREIGN KEY (pref_code) REFERENCES prefecture(pref_code)
) ENGINE=InnoDB;

-- T-12a 拠点の休業日  可変長なので分離
CREATE TABLE location_holiday (
  location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  holiday       DATE NOT NULL,
  PRIMARY KEY (location_code, holiday),
  CONSTRAINT fk_holiday_location FOREIGN KEY (location_code) REFERENCES location(location_code)
) ENGINE=InnoDB;

-- T-14 EC販売の除外  行の存在＝EC販売しない。可否の列は持たない（3.2.2 ②）
CREATE TABLE ec_exclusion (
  product_code  VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (product_code, location_code),
  CONSTRAINT fk_exc_product  FOREIGN KEY (product_code)  REFERENCES product(product_code),
  CONSTRAINT fk_exc_location FOREIGN KEY (location_code) REFERENCES location(location_code)
) ENGINE=InnoDB;

-- T-13 在庫  主キーの列順は (sku, location, section)。F-104 が SKU 先頭で引くため
--   qty と reserved_qty は INT UNSIGNED。
--   引当済数 <= 在庫数 のチェック制約は付けない（BR-04a の後に恒常的に破れるため）。
--   そのかわり SQL で引き算をしない（3.2.2 ①）。
CREATE TABLE stock (
  sku_code      VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  section       TINYINT      NOT NULL COMMENT '1=バックヤード 2=店頭。BR-01',
  qty           INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '在庫数＝実物の数',
  reserved_qty  INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '引当済数',
  last_sold_at  DATE         NULL COMMENT 'F-807 滞留在庫の判定',
  updated_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (sku_code, location_code, section),
  KEY idx_stock_location (location_code),
  CONSTRAINT fk_stock_sku      FOREIGN KEY (sku_code)      REFERENCES sku(sku_code),
  CONSTRAINT fk_stock_location FOREIGN KEY (location_code) REFERENCES location(location_code)
) ENGINE=InnoDB;

-- T-13a 在庫を動かした記録  要件定義に対応する実体はない。設計で追加
CREATE TABLE stock_change_log (
  id            BIGINT AUTO_INCREMENT,
  sku_code      VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  section       TINYINT      NOT NULL,
  reason        TINYINT      NOT NULL COMMENT '1=手修正 F-802  2=欠品報告 F-805  3=店頭払い出し F-808  4=在庫戻入 F-504',
  qty_before    INT UNSIGNED NOT NULL,
  qty_after     INT UNSIGNED NOT NULL,
  note          VARCHAR(200) NULL,
  operator_id   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  staff_name    VARCHAR(50)  NULL COMMENT '共有アカウントのため手入力させる担当者名',
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_scl_target (sku_code, location_code, created_at)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 会員・セッション・カート
-- ------------------------------------------------------------

-- T-16 会員
CREATE TABLE member (
  member_id      VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  email          VARCHAR(254) NULL COMMENT '退会時に NULL にする',
  password_hash  VARCHAR(255) NULL,
  name           VARCHAR(50)  NULL,
  tel            VARCHAR(11) CHARACTER SET ascii COLLATE ascii_bin NULL,
  shop_member_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT 'F-606 照合はしない',
  status         TINYINT      NOT NULL DEFAULT 1 COMMENT '1=有効 2=ロック 3=退会済',
  failed_count   TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'N-23 連続ログイン失敗回数。成功で0に戻す',
  locked_until   DATETIME(3)  NULL COMMENT 'N-23 ここまでロック。★status=2 と違い、時間で自然に解ける',
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (member_id),
  UNIQUE KEY uq_member_email (email)
) ENGINE=InnoDB;

-- T-17 住所帳
CREATE TABLE address (
  id         BIGINT AUTO_INCREMENT,
  member_id  VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name       VARCHAR(50)  NOT NULL,
  zip        CHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  pref_code  CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  address    VARCHAR(100) NOT NULL,
  tel        VARCHAR(11) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  is_default BOOLEAN      NOT NULL DEFAULT FALSE,
  PRIMARY KEY (id),
  KEY idx_address_member (member_id),
  CONSTRAINT fk_address_member FOREIGN KEY (member_id) REFERENCES member(member_id),
  CONSTRAINT fk_address_pref   FOREIGN KEY (pref_code) REFERENCES prefecture(pref_code)
) ENGINE=InnoDB;

-- T-35 運営者  拠点の共有アカウントもここ
CREATE TABLE operator (
  operator_id   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name          VARCHAR(50)  NOT NULL,
  email         VARCHAR(254) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role          TINYINT      NOT NULL COMMENT '1=運用管理者 2=受注担当 3=倉庫 4=店舗 5=サポート',
  location_code VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '倉庫・店舗のみ',
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  failed_count  TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'N-23。会員と同じ制限をかける（F-1301）',
  locked_until  DATETIME(3)  NULL COMMENT 'N-23',
  PRIMARY KEY (operator_id),
  UNIQUE KEY uq_operator_email (email),
  CONSTRAINT fk_operator_location FOREIGN KEY (location_code) REFERENCES location(location_code)
) ENGINE=InnoDB;

-- T-18 セッション  複数インスタンスで共有するため DB に置く
CREATE TABLE session (
  session_id    CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_kind     TINYINT     NOT NULL COMMENT '1=ゲスト 2=会員 3=運営者',
  member_id     VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  operator_id   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  guest_order_no VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT 'F-313 照会を通った注文番号。★1件ぶんだけ（N-27）',
  issued_at     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  last_access_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (session_id),
  KEY idx_session_last (last_access_at),
  CONSTRAINT fk_session_member   FOREIGN KEY (member_id)   REFERENCES member(member_id),
  CONSTRAINT fk_session_operator FOREIGN KEY (operator_id) REFERENCES operator(operator_id)
) ENGINE=InnoDB;

-- T-19 カート  会員にもゲストにも紐づく（BR-24a）
CREATE TABLE cart (
  cart_key   VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '会員は会員ID、ゲストは発行した識別子',
  sku_code   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_kind  TINYINT      NOT NULL COMMENT '1=ゲスト 2=会員',
  qty        INT UNSIGNED NOT NULL,
  added_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (cart_key, sku_code),
  KEY idx_cart_added (added_at),
  CONSTRAINT fk_cart_sku FOREIGN KEY (sku_code) REFERENCES sku(sku_code)
) ENGINE=InnoDB;

-- T-32 お気に入り / T-31 レビュー / T-33 再入荷通知
CREATE TABLE favorite (
  member_id    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  product_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (member_id, product_code),
  CONSTRAINT fk_fav_member  FOREIGN KEY (member_id)    REFERENCES member(member_id),
  CONSTRAINT fk_fav_product FOREIGN KEY (product_code) REFERENCES product(product_code)
) ENGINE=InnoDB;

CREATE TABLE review (
  product_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  member_id    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  rating       TINYINT       NOT NULL COMMENT '1〜5の整数（6.3）',
  body         VARCHAR(1000) NOT NULL,
  is_anonymous BOOLEAN       NOT NULL DEFAULT FALSE COMMENT '退会時に TRUE',
  posted_at    DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (product_code, member_id),
  CONSTRAINT fk_review_product FOREIGN KEY (product_code) REFERENCES product(product_code),
  CONSTRAINT fk_review_member  FOREIGN KEY (member_id)    REFERENCES member(member_id)
) ENGINE=InnoDB;

CREATE TABLE restock_notice (
  sku_code   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  email      VARCHAR(254) NOT NULL,
  created_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  notified   BOOLEAN      NOT NULL DEFAULT FALSE,
  PRIMARY KEY (sku_code, email),
  CONSTRAINT fk_restock_sku FOREIGN KEY (sku_code) REFERENCES sku(sku_code)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 販促
-- ------------------------------------------------------------

CREATE TABLE coupon (
  coupon_code    VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name           VARCHAR(50)  NOT NULL,
  discount_type  TINYINT      NOT NULL COMMENT '1=割合 2=金額',
  discount_value INT UNSIGNED NOT NULL,
  start_at       DATETIME(3)  NOT NULL,
  end_at         DATETIME(3)  NOT NULL,
  min_amount     INT UNSIGNED NOT NULL DEFAULT 0,
  total_limit    INT UNSIGNED NULL COMMENT 'NULL は上限なし',
  used_count     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '条件付きUPDATEで先勝ち判定する（BR-16a）',
  per_member_limit INT UNSIGNED NULL,
  PRIMARY KEY (coupon_code)
) ENGINE=InnoDB;

CREATE TABLE coupon_target (
  id          BIGINT AUTO_INCREMENT,
  coupon_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  target_kind TINYINT      NOT NULL COMMENT '1=全商品 2=カテゴリ 3=商品',
  target_id   VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL,
  PRIMARY KEY (id),
  KEY idx_ct_coupon (coupon_code),
  CONSTRAINT fk_ct_coupon FOREIGN KEY (coupon_code) REFERENCES coupon(coupon_code)
) ENGINE=InnoDB;

-- ★AP-204 カートに適用したクーポン（R-29。migrations/008）
CREATE TABLE cart_coupon (
  cart_key    VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'cart と同じキー（会員は会員ID）',
  coupon_code VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  applied_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (cart_key),
  KEY fk_cc_coupon (coupon_code),
  CONSTRAINT fk_cc_coupon FOREIGN KEY (coupon_code) REFERENCES coupon(coupon_code)
) ENGINE=InnoDB;
