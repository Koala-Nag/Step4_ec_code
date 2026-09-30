-- ============================================================
-- 009_returns.sql
--   返品と返金（F-502・F-503a〜e・F-504・F-507。設計 6.5）。R-31
--
--   ★001〜008 は書き換えない。追記は次の番号で（設計 2.2）
--   ★列を足す ALTER には AFTER を書く（書かないと末尾に付いて ddl/ と並びが変わる）
--
--   なぜ要るか（T-26・T-26a は 3.2 にあるが、流れを通すと足りない列があった）
--     ① return_req.decided_at・decided_by
--        承認・却下（F-503a）を、誰がいつしたか。受領（received_at・receiver）には列があるのに、承認には無かった
--     ② return_req.return_deadline
--        MSG-12 に「返送期限」を載せる（要件 4.4）。★載せた日付を後から変えないため、承認のときに保存する
--     ③ return_req.refunded_at
--        返金（F-503d）を実行した日時
--     ④ return_line.inspect_note
--        F-503c「明細ごとに合格・不合格と理由を記録する」の理由
--     ⑤ return_line.restocked_at・restocker
--        在庫戻入（F-504）は検品と別の操作（AP-B30）。★二重に戻さないために「戻したか」を持つ
--
--   実行方法（ec/ で）
--     docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/009_returns.sql
-- ============================================================
SET NAMES utf8mb4;
USE ec_koala;

ALTER TABLE return_req
  ADD COLUMN decided_at DATETIME(3) NULL COMMENT '承認・却下の日時（F-503a）' AFTER reject_reason,
  ADD COLUMN decided_by VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '承認・却下した運営者' AFTER decided_at,
  ADD COLUMN return_deadline DATE NULL COMMENT '返送期限（MSG-12）。承認のときに決めて保存する' AFTER decided_by,
  ADD COLUMN refunded_at DATETIME(3) NULL COMMENT '返金を実行した日時（F-503d）' AFTER refund_total;

ALTER TABLE return_line
  ADD COLUMN inspect_note VARCHAR(200) NULL COMMENT '検品の理由（F-503c）' AFTER inspector,
  ADD COLUMN restocked_at DATETIME(3) NULL COMMENT '倉庫の在庫に戻した日時（F-504）。★二重に戻さない' AFTER refund_amount,
  ADD COLUMN restocker VARCHAR(50) NULL COMMENT '戻した担当者（共有アカウントのため手入力）' AFTER restocked_at;
