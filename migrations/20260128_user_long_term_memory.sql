-- =====================================================
-- ユーザー長期記憶テーブル
-- 人生軸・価値観・長期WHYなどを保存
-- =====================================================

-- テーブル作成
-- v10.40.8: usersテーブルに合わせてuser_idをintegerに変更
CREATE TABLE IF NOT EXISTS user_long_term_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id INTEGER NOT NULL,

    -- 記憶タイプ
    -- life_why: 人生のWHY・存在意義
    -- values: 価値観・判断基準
    -- identity: アイデンティティ・自己認識
    -- principles: 行動原則・信条
    -- long_term_goal: 長期目標（5年以上）
    memory_type VARCHAR(50) NOT NULL,

    -- 記憶内容
    content TEXT NOT NULL,

    -- メタデータ（抽出されたキーワード、タグなど）
    metadata JSONB DEFAULT '{}',

    -- タイムスタンプ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- 外部キー制約
    CONSTRAINT fk_user_long_term_memory_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_long_term_memory_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_user_long_term_memory_org_user
    ON user_long_term_memory(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_long_term_memory_type
    ON user_long_term_memory(user_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_user_long_term_memory_created
    ON user_long_term_memory(user_id, created_at DESC);

-- コメント
COMMENT ON TABLE user_long_term_memory IS 'ユーザーの長期記憶（人生軸、価値観、長期WHYなど）';
COMMENT ON COLUMN user_long_term_memory.memory_type IS '記憶タイプ: life_why, values, identity, principles, long_term_goal';
COMMENT ON COLUMN user_long_term_memory.content IS '記憶内容（ユーザーの言葉をそのまま保存）';
COMMENT ON COLUMN user_long_term_memory.metadata IS 'メタデータ（抽出キーワード、タグ、関連目標IDなど）';
