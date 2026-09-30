-- ============================================================
-- 07_dev_accounts.sql
--   ★検証環境だけのアカウント（R-21）。本番では絶対に流さない。
--
--   なぜ別ファイルか
--     02_master.sql / 03_demo.sql には password_hash に '$dummy$' が入っている。
--     ★あれは「照合が必ず失敗する値」で、それ自体は正しい（ログインできない）。
--     試験にはログインできるアカウントが要るので、そのぶんだけここで上書きする。
--
--   ★パスワードは検証用と分かる名前にする（設計 2.5.1）
--     全アカウント共通： DevPassw0rd!
--     ★これは秘密ではない。検証環境にしか無いアカウントの、公開された合言葉。
--       本番のアカウントはこのファイルを流さないので影響しない。
--
--   ★ハッシュは1行ずつ違う。同じパスワードでも塩が違うため（N-22・SEC-804）。
--     ここが同じ値で並んでいたら、塩が効いていない合図。
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/seed/07_dev_accounts.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

-- 運営者（2.4 の5役割。倉庫・店舗は拠点で共有するアカウント）
UPDATE operator SET password_hash = '$2b$12$MIksT/ae5vgPH4QiDLvCue.0RkPCs7JYAIT8fw6G5FlREZeuA5hQK' WHERE operator_id = 'OP001';   -- 運用管理者A / admin1@example.com
UPDATE operator SET password_hash = '$2b$12$uYCAXwn9Zi6jrvqN/G967OKdu/dMF.hF/HZyih7kCBhcv0bKuQI0.' WHERE operator_id = 'OP002';   -- 運用管理者B / admin2@example.com
UPDATE operator SET password_hash = '$2b$12$408wNzhqhy408Xs/9nN3fuQmz9TLvpIBAzIvb7o8B22ank37wlsmy' WHERE operator_id = 'OP003';   -- 受注担当A / order1@example.com
UPDATE operator SET password_hash = '$2b$12$3OdooIKi1XVijfZWX78QM.NWHsMqMiSoUyME/2JKo8lpl.qIi1ik6' WHERE operator_id = 'OP004';   -- 受注担当B / order2@example.com
UPDATE operator SET password_hash = '$2b$12$A3Z1A4Ez6K9Irqsk56q/a.U8TjZU.6aof0taHK65/grkRjYLHfTNq' WHERE operator_id = 'OP005';   -- サポートA / support1@example.com
UPDATE operator SET password_hash = '$2b$12$SzTrdz9HRI5yn6ynsP46x.xe4YMwi5zO6u2YrI/SA03o0XQr6thO6' WHERE operator_id = 'W001S';   -- 中央倉庫 / w001@example.com
UPDATE operator SET password_hash = '$2b$12$wIiCwbo6.RdntLouMN48SOSlqeypdhrUF0badRHs6Ht3.7R8l1/O2' WHERE operator_id = 'T001S';   -- 札幌店 / t001@example.com
UPDATE operator SET password_hash = '$2b$12$y72cNwgNXoZbqfaCrH9xX.E0a/YMoWLYpSod6InX4fw5IVjcJjgrS' WHERE operator_id = 'T003S';   -- 新宿店 / t003@example.com
UPDATE operator SET password_hash = '$2b$12$R40.uEbKjut952.Tf2Jy9O23glpTZKmizV7FNcX4x4m0cY7WiLLGu' WHERE operator_id = 'T004S';   -- 渋谷店 / t004@example.com

-- 会員
INSERT IGNORE INTO member (member_id,email,password_hash,name,tel,status) VALUES
 ('M0001','taro@example.com','$2b$12$JTWN0dAfev.vrSIuUnXMaOWg3JDrPrAjS4CwFI2L/ChihR/vpEHS2','山田太郎','09000000001',1),
 ('M0002','hanako@example.com','$2b$12$LVFEfwYpN1dfed0qSUwZZ.BK81kZwOEuill4xw9p.2chCX01m.D1O','鈴木花子','09000000001',1),
 ('M0090','lock-test@example.com','$2b$12$xF90YAkJq0eRSxyjdIY5ceothZVGLeiBqR84NW7ArffeCCl8vr1PC','ロック試験専用','09000000001',1);

-- ★すでに居る会員は UPDATE で上書きする（03_demo.sql の $dummy$ を置き換える）
UPDATE member SET password_hash = '$2b$12$RxgQaVlwbAOri4JyyiNg/eabeQhHp1nU647.qHhTg7E3yFujV2uA6', failed_count = 0, locked_until = NULL WHERE member_id = 'M0001';   -- 山田太郎
UPDATE member SET password_hash = '$2b$12$19veTuiUQ7L6UvlefNJV3.kjGe9NxJJRZtC9Nyjq2tK/OlMMZiN6q', failed_count = 0, locked_until = NULL WHERE member_id = 'M0002';   -- 鈴木花子
UPDATE member SET password_hash = '$2b$12$UD3yaVuFtvBrCXfpy0ZuRukOHNFX385uR.vxcs82x18mUYVks/YJy', failed_count = 0, locked_until = NULL WHERE member_id = 'M0090';   -- ロック試験専用

-- ------------------------------------------------------------
-- 確認
-- ------------------------------------------------------------
--   SELECT member_id, LEFT(password_hash,7) FROM member;   → 全部 $2b$12$
--   SELECT COUNT(DISTINCT password_hash) FROM member;      → 行数と同じ（塩が効いている）
