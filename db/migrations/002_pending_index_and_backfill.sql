-- ============================================================
-- 002_pending_index_and_backfill.sql
--   設計仕様書 v0.1（2026-09-03 改訂）へ追いつかせる2件目
--
--   ★001 は書き換えない。一度どこかで流したマイグレーションを直すと、
--     「もう流した環境」と「これから流す環境」で結果が変わり、
--     ddl/ 経路との差分もまた開く（設計仕様書 2.2）。追記は次の番号で行う。
--
--   1. payment_tx に、B-09・B-10 が拾うための索引を足す
--   2. 001 で足した列の、既存行の値を詰め替える
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/002_pending_index_and_backfill.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

-- ------------------------------------------------------------
-- 1. 索引
-- ------------------------------------------------------------
-- 設計 7.2.5・6.6.2
--   sent_mail には idx_mail_pending があるのに、同じ形で拾う payment_tx には無かった。
--   EXPLAIN で全表走査になることを実機で確認（R-04）。
--   payment_tx は注文1件につき複数行増えるので、運用が続くほど B-09・B-10 が重くなる。
ALTER TABLE payment_tx
  ADD KEY idx_ptx_pending (status, started_at);

-- ------------------------------------------------------------
-- 2. 既存行の詰め替え  ★列を足すだけでは足りない
-- ------------------------------------------------------------
--   新しい列に入る DEFAULT は「まだ何も起きていない」を意味する値なので、
--   すでに何かが起きている行に入ると実態と食い違う。
--   検証環境はまっさらなので実害は出ない。本番相当のデータで初めて効く。

-- sent_mail.status は DEFAULT 0（未送信）。
--   このままだと送信済みの行まで「未送信」になり、B-11 が過去のメールを全部送り直す。
UPDATE sent_mail
   SET status = CASE WHEN result = 1 THEN 1
                     WHEN result = 2 THEN 2
                     ELSE 0 END
 WHERE sent_at IS NOT NULL;

-- batch_lock.expires_at が NULL のままだと、実行中のロックに期限が付かない。
--   6.6.1 が狙った「期限切れのロックを次回が奪う」がその行にだけ効かず、
--   落ちたプロセスのロックが永久に残る（まさに列を足して防ごうとした状態）。
UPDATE batch_lock
   SET expires_at = acquired_at + INTERVAL 30 MINUTE
 WHERE status = 1 AND acquired_at IS NOT NULL AND expires_at IS NULL;

-- ------------------------------------------------------------
-- 3. 確認
-- ------------------------------------------------------------
-- SHOW INDEX FROM payment_tx WHERE Key_name = 'idx_ptx_pending';
--   → 2行（status, started_at）
-- SELECT COUNT(*) FROM sent_mail  WHERE sent_at IS NOT NULL AND status = 0;   → 0
-- SELECT COUNT(*) FROM batch_lock WHERE status = 1 AND expires_at IS NULL;    → 0
-- EXPLAIN SELECT id FROM payment_tx
--   WHERE status IN (4,5) AND started_at < NOW(3) - INTERVAL 10 MINUTE;
--   → key: idx_ptx_pending になること（NULL でないこと）
