-- ============================================================
-- 004_image_url_and_origin_session.sql
--   R-12。判断が決まった2件を入れる
--
--   1. product_image.url の説明を「相対パス」に直す（R-10 ③・設計 3.2 T-11）
--   2. orders に origin_session_id を足す（設計 7.2.2a）
--
--   ★001〜003 は書き換えない。追記は次の番号で行う（設計 2.2）
--
--   ★型について
--     設計 7.2.2a / T-20 は CHAR(43)（secrets.token_urlsafe(32) の長さ）と書いてあるが、
--     session.session_id は 01_schema.sql の時点から CHAR(64) である。
--     依頼の「食い違うなら session に合わせてほしい」に従い CHAR(64) にした。
--     （HANDOFF の報告に、設計側で直す箇所として書いてある）
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/004_image_url_and_origin_session.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

-- ------------------------------------------------------------
-- 1. 画像のURLは相対パスで持つ
-- ------------------------------------------------------------
--   ベースURLは環境ごとに変わる（手元／検証／本番）。DBに絶対URLを持つと、
--   ストレージが変わるたびに product_image を200行ぶん書き換えることになる。
--   相対で持てば、変えるのは IMAGE_BASE_URL の1か所だけで済む。
--   ★列の型は変えない。説明だけを直す。
ALTER TABLE product_image
  MODIFY COLUMN url VARCHAR(500) NOT NULL
    COMMENT '画像の相対パス（products/P0001_BK_1.jpg）。表示時に IMAGE_BASE_URL を前置する';

-- ------------------------------------------------------------
-- 2. 注文に「作ったセッション」を控える
-- ------------------------------------------------------------
--   設計 7.2.2a。AP-301a（与信）はゲストでも叩けるように認証を要らなくしてある。
--   そのため注文番号さえ分かれば誰でも呼べる。
--   「その認証結果がこの注文のものか」を確かめる手が無かった。
--
--   AP-301  注文を作るとき、呼び出し元のセッションIDをここに入れる
--   AP-301a 同じセッションからの呼び出しだけを受ける。違えば 404 / ERR-1215
--   AP-302  再決済のとき、そのときのセッションIDで上書きする
--
--   ★session への外部キーは張らない。
--     セッションは期限切れで消える（N-05・sales_config.session_idle_min）が、
--     注文は消さない。外部キーを張ると、セッションの掃除が注文に引っかかるか、
--     掃除のたびに注文側が書き換わることになる。
--     ここで要るのは「一致するか」の比較だけで、参照整合性ではない。
ALTER TABLE orders
  ADD COLUMN origin_session_id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL
    COMMENT 'この注文を作ったセッション（7.2.2a）。AP-301a はこれと一致する呼び出しだけを受ける。決済後は使わない'
    AFTER member_id;

-- ------------------------------------------------------------
-- 3. 台帳に記録する
-- ------------------------------------------------------------
INSERT IGNORE INTO schema_migration (version, note) VALUES
  ('004', 'migrations で適用');

-- ------------------------------------------------------------
-- 4. 確認
-- ------------------------------------------------------------
-- SELECT column_comment FROM information_schema.columns
--  WHERE table_schema='ec' AND table_name='product_image' AND column_name='url';
--   → 「画像の相対パス…」になっていること
-- SHOW COLUMNS FROM orders LIKE 'origin_session_id';
--   → char(64) / YES（NULL可）
-- SELECT * FROM schema_migration ORDER BY version;
--   → 001 / 002 / 003 / 004 の4行
