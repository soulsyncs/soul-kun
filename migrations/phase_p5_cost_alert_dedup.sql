-- P5: AIコスト月次アラート 重複防止カラム追加
-- 目的: 同じ月に同じ閾値（80%/100%）のアラートを何度も送らないようにする
-- 仕組み: 送信済みタイムスタンプを記録し、NULLなら未送信とみなす
--        翌月は新しいレコードが作られるので自動的にリセットされる
--
-- ロールバック:
--   ALTER TABLE ai_monthly_cost_summary
--       DROP COLUMN IF EXISTS alert_80pct_sent_at,
--       DROP COLUMN IF EXISTS alert_100pct_sent_at;

ALTER TABLE ai_monthly_cost_summary
    ADD COLUMN IF NOT EXISTS alert_80pct_sent_at  TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS alert_100pct_sent_at TIMESTAMPTZ DEFAULT NULL;

COMMENT ON COLUMN ai_monthly_cost_summary.alert_80pct_sent_at  IS '予算80%超過アラートを送信した日時（NULLなら未送信）';
COMMENT ON COLUMN ai_monthly_cost_summary.alert_100pct_sent_at IS '予算100%超過アラートを送信した日時（NULLなら未送信）';
