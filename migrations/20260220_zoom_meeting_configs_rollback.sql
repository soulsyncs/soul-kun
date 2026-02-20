-- Rollback: zoom_meeting_configs テーブル削除
-- Phase Z1 ②: 管理ダッシュボードZoom連携設定ロールバック

BEGIN;

DROP TABLE IF EXISTS zoom_meeting_configs CASCADE;

COMMIT;
