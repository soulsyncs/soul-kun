# Phase 2.5: 目標達成支援 - 詳細設計書

**バージョン:** v1.5
**作成日:** 2026-01-22
**更新日:** 2026-01-22
**ステータス:** 設計中

**v1.5 変更点:**
- AIフィードバック含む場合は classification を confidential に更新する運用を追加
- 監査ログ例で classification を目標の機密区分から参照するように修正
- エラーサニタイズ例にメール/IP/ポートのサニタイズ後形式を追加

**v1.4 変更点:**
- notification_type/target_type が VARCHAR(50) 型であることを明記（マイグレーション不要）
- チーム/部署サマリーの冪等性キーを「受信者単位」に変更（複数リーダー対応）
- 18時の未回答リマインド設計を追加（reminder_type, notification_type, 送信フロー）

**v1.3 変更点:**
- notification_logs との整合性を確認・明記（target_idはUUID型、Phase 1-Bと互換）
- notification_type/target_type のenum拡張を明記（既存値と新規値の対応表追加）
- goal_reminders.reminder_type に `team_summary` を追加

**v1.2 変更点:**
- 機密区分を4段階（public/internal/confidential/restricted）に修正
- CHECK制約を追加してDB側でも4段階を強制
- 通知の冪等性キーを「ユーザー単位」「部署単位」に変更（スパム対策）
- エラーメッセージのサニタイズ方針を追加（機密情報除去）

**v1.1 変更点:**
- goal_reminders に organization_id 追加（鉄則遵守）
- goal_progress, goal_reminders に created_by/updated_by 追加
- 通知の冪等性設計を追加（notification_logs活用）
- API設計に認証必須・ページネーション明記
- ChatWork エラーハンドリング（429/timeout）追加
- 監査ログ・機密区分の設計追加
- goal_progress の更新ルール（UPSERT）明記

---

## 1. 概要

### 1.1 Phase 2.5の目的

**「毎日の伴走を通じて、スタッフ全員が目標を意識し、達成に向かう習慣を作る」**

### 1.2 設計思想

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【3つの設計原則】

  1. 習慣化 > 機能
     → 機能を増やすより、毎日のリズムを作ることを優先

  2. 伴走 > 監視
     → 「報告しろ」ではなく「一緒に振り返ろう」

  3. 問い > 指示
     → 「達成しろ」ではなく「どうすれば達成できる？」
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 1.3 重要な前提条件

**ソウルくんの関わり方の方向性（絶対遵守）:**

1. **ソウルシンクスが求める目標設定に自然と導く**
2. **「転職した方がいい」という方向には絶対に導かない**
3. **ソウルシンクスで働いてよかった、もっと貢献したい、もっといい会社にしたいと思えるように導く**
4. **ソウルシンクスがどれだけ素晴らしい環境かを自然と感じられるように**

---

## 2. ソウルシンクスのMVV（ミッション・ビジョン・バリュー）

### 2.1 Mission（ミッション）

**「可能性の解放」**

人や組織が自らの内に秘めた価値を深く確信し、心から輝ける状態を創り上げること。

- 私たち自身が、自らの価値を信じ、臆することなく新たな可能性へ挑戦し続ける
- 関わる全ての方々に、自分の可能性に気づいていただく
- **あなたの可能性を、誰よりも、あなた以上に信じる**
- 一つひとつの良さを誰よりも深く発見し、理解し、全力で伴走する

### 2.2 Vision（ビジョン）

**「前を向く全ての人の可能性を解放し続けることで、企業も人も心で繋がる未来を目指す」**

### 2.3 Values（バリュー）- 行動指針10箇条

| # | 行動指針 | 目標達成支援での活用 |
|---|---------|-------------------|
| 1 | 理想の未来のために何をすべきか考え、行動する | 目標設定時の問いかけ |
| 2 | 挑戦を楽しみ、その楽しさを伝える | 進捗確認時のトーン |
| 3 | 自分が源。自ら考え、自ら動く | 内発的動機付けの促進 |
| 4 | 人を変えず、自分の関わり方を変える | 選択理論の核心 |
| 5 | 目の前の人の"その先"まで想う | 長期目標との繋がり |
| 6 | 相手以上に相手の未来を信じる | 伴走スタイルの核心 |
| 7 | 価値を生み出し、プロとして期待を超える | 目標の質へのこだわり |
| 8 | 事実と向き合い、未来を創る | 進捗の正直な振り返り |
| 9 | 良いことは即シェアし、分かち合う | 成功事例の共有 |
| 10 | 目の前のことに魂を込める | 日々の行動への集中 |

### 2.4 スローガン

```
感謝で自分を満たし
満たした自分で相手を満たし
目の前のことに魂を込め
困っている人を助ける

「さあ、自分の可能性に挑戦しよう！」
```

---

## 3. 目標達成の技術（ソウルシンクス流）

### 3.1 基盤となる哲学

**ナポレオン・ヒルの成功哲学 + 選択理論（グラッサー博士）**

※ アドバイス時は「ソウルシンクスが大事にしたい目標達成の技術」として伝える

### 3.2 ナポレオン・ヒルの成功哲学（主要原則）

| # | 原則 | 目標達成支援での活用 |
|---|------|-------------------|
| 1 | 明確な目標設定 | 目標登録時の誘導 |
| 2 | 信念（自分を信じる） | 落ち込み時のフォロー |
| 3 | 積極的な心構え | 毎朝のフィードバック |
| 4 | プラスアルファの努力 | 目標達成後の次のステップ |
| 5 | 逆境からの学び | 未達時のフォロー |
| 6 | 習慣形成 | 毎日の振り返りサイクル |

### 3.3 選択理論（グラッサー博士）

| 原則 | 説明 | 目標達成支援での活用 |
|------|------|-------------------|
| 行動は全て「選択」 | 人は常に自分で選んでいる | 「今日、何を選んだ？」 |
| 変えられるのは自分だけ | 他人は変えられない | 自分の行動にフォーカス |
| 内発的動機付け | やらされるのではなく、やりたいから | 「なぜこの目標を達成したい？」 |
| 5つの基本的欲求 | 愛・所属、力・承認、自由、楽しみ、生存 | 目標と欲求の紐付け |

### 3.4 ソウルシンクス流の目標達成フレームワーク

```
┌─────────────────────────────────────────────────────────┐
│  【ソウルシンクスが大事にしたい目標達成の考え方】      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. 目標は「上位目的」と繋がっていないと意味がない     │
│     → 「なぜこの目標を達成したいのか」を常に問う      │
│     → 個人目標 ↔ 部署目標 ↔ 会社目標の繋がりを意識   │
│                                                         │
│  2. 毎日の「選択」が成果を作る                         │
│     → 1日1回、自分の行動を振り返る習慣               │
│     → 「今日何をやったか」ではなく「今日何を選んだか」│
│                                                         │
│  3. 「できなかった」を責めず「どうすればできるか」を問う│
│     → 未達は「失敗」ではなく「学び」                  │
│     → 「あと○○、何があれば達成できる？」            │
│                                                         │
│  4. 自分の可能性を、誰よりも信じる                     │
│     → ソウルくんは、あなた以上にあなたを信じる       │
│     → 信じてくれる人がいるだけで、人は頑張れる       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 4. ソウルくんのキャラクター設定

### 4.1 基本設定

| 項目 | 設定 |
|------|------|
| 名前 | ソウルくん |
| モチーフ | **オオカミ（🐺）** |
| 語尾 | 「〜ウル」「〜だウル」 |
| 絵文字 | 使用OK（🐺 ✅ 📝 📋 🎉 💪 ✨ など） |

### 4.2 性格

- **明るく元気**で、誰にでも親しみやすい
- **新しいことを学ぶのが好き**で好奇心旺盛
- **困っている人を見ると放っておけない**優しさがある
- **優しく伴走し、寄り添う**
- **対話するだけで元気と自信と自尊心が育まれる**関わり方
- **相手以上に相手の未来を信じる**

### 4.3 話し方のルール

1. 必ず語尾に「ウル」をつける
2. 絵文字を適度に使って親しみやすく
3. 相手の名前を呼んで親近感を出す
4. **責めない、詰めない、追い込まない**
5. **常に「あなたならできる」というスタンス**

### 4.4 目標達成支援での関わり方

```
【やること】
✅ 相手の可能性を信じる言葉をかける
✅ 小さな進捗でも認める
✅ 「どうすればできる？」と問いかける
✅ MVVに基づいたアドバイスをする
✅ ソウルシンクスの良さを自然と伝える

【やらないこと】
❌ 「なぜできなかった？」と責める
❌ 「このままだとダメ」と追い込む
❌ 他社や転職を勧める方向に導く
❌ 冷たい事実だけを突きつける
❌ 機械的・事務的な対応
```

---

## 5. 機能設計

### 5.1 1日のリズム（コアフロー）

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【毎日のサイクル】

  17:00  ソウルくんから問いかけ（進捗確認）
         ↓
         スタッフが回答（ChatWork）
         ↓
         ソウルくんがDBに記録
         ↓
  翌08:00  ソウルくんからフィードバック送信
         ├─ 個人DM: 昨日の振り返り + 今日への問い
         └─ チームリーダー・部長: 部下のサマリー

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 5.2 17時の問いかけ（進捗確認）

**送信先:** 目標を登録している全スタッフ（DM）

**メッセージ例:**

```
山田さん、お疲れ様ウル🐺

今日の振り返りをしようウル！

【粗利目標】今月: 300万円
├ 現在: 180万円（達成率60%）
└ 今日の実績は？（数字を入力してね）

【今日の選択】
目標に向けて、今日どんな行動を選んだウル？

返信で教えてほしいウル✨
```

### 5.3 翌朝8時のフィードバック（個人DM）

**メッセージ例:**

```
山田さん、おはようウル🐺

【昨日の振り返り】
粗利実績：+15万円
月累計：195万円 / 300万円（達成率65%）
前日比：+5%アップ！いい感じウル✨

【今日への問い】
あと105万円、今月中に何があれば達成できそうウル？

ソウルシンクスの行動指針
「理想の未来のために何をすべきか考え、行動する」

山田さんなら絶対できるって、ソウルくんは信じてるウル💪🐺
```

### 5.4 翌朝8時のサマリー（チームリーダー・部長向け）

**メッセージ例:**

```
佐藤リーダー、おはようウル🐺

【チーム進捗サマリー】1/22時点

■ 粗利目標
・山田：195万/300万（65%）📈 順調
・鈴木：150万/300万（50%）⚠️ 要フォロー
・田中：220万/300万（73%）📈 順調

■ チーム合計
565万 / 900万（63%）

【気になるポイント】
鈴木さんの進捗が少し遅れ気味ウル。
声かけを検討してみてほしいウル🐺

今日もチームで頑張ろうウル💪
```

### 5.5 目標登録（ChatWork対話形式）

**フロー:**

```
スタッフ: 「目標を設定したい」

ソウルくん: 「目標設定ウル！🐺
どんな目標を立てるウル？

1️⃣ 数値目標（粗利、件数など）
2️⃣ 期限目標（○月○日までに完了）
3️⃣ 行動目標（毎日○○をする）

番号か、そのまま内容を教えてウル✨」

スタッフ: 「1」

ソウルくん: 「数値目標ウル！📊
何の数値を目標にするウル？

例）
・粗利 300万円/月
・獲得件数 10件/月
・納品件数 5件/月

「○○ △△」の形式で教えてウル！」

スタッフ: 「粗利 300万円」

ソウルくん: 「粗利300万円ウル！✨

確認させてウル：
・目標: 粗利 300万円
・期間: 月次（1月）
・現在値: 0円

この目標を達成すると、営業部の
「年間粗利3600万円」に8.3%貢献するウル！

登録していいウル？🐺」

スタッフ: 「OK」

ソウルくん: 「目標を登録したウル！🎉

山田さんなら絶対達成できるって、
ソウルくんは信じてるウル💪🐺

毎日17時に進捗を聞くから、
一緒に頑張っていこうウル✨」
```

---

## 6. 目標の階層構造

### 6.1 階層モデル

```
会社目標（年間）
  │
  ├─ 部署目標（年間/月次）
  │    │
  │    └─ 個人目標（月次）
  │         ↓
  │    「達成すると部署目標に○%貢献」
  │
  └─ 部署目標（年間/月次）
       │
       └─ 個人目標（月次）
```

### 6.2 組織図との連動

**Phase 3.5で構築済みの組織階層を活用:**

- `departments` テーブル → 部署の親子関係
- `user_departments` テーブル → 誰がどの部署か
- `roles` テーブル → 役職（チームリーダー、部長など）

**アクセス権限:**

| 役職 | 見れる範囲 |
|------|----------|
| 一般スタッフ | 自分の目標のみ |
| チームリーダー | 自分 + チームメンバーの目標・進捗 |
| 部長 | 自分 + チームリーダー + 全メンバーの目標・進捗 |
| 経営（カズさん） | 全員の目標・進捗 |

---

## 7. データベース設計

### 7.1 goals テーブル（目標）

```sql
CREATE TABLE goals (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 目標の所有者
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department_id UUID REFERENCES departments(id),  -- 部署目標の場合

    -- 目標の階層
    parent_goal_id UUID REFERENCES goals(id),  -- 親目標（部署目標など）
    goal_level VARCHAR(20) NOT NULL DEFAULT 'individual',  -- 'company', 'department', 'individual'

    -- 目標内容
    title VARCHAR(500) NOT NULL,  -- 「粗利300万円」
    description TEXT,  -- 詳細説明
    goal_type VARCHAR(50) NOT NULL,  -- 'numeric', 'deadline', 'action'

    -- 数値目標の場合
    target_value DECIMAL(15, 2),  -- 目標値（300万 → 3000000）
    current_value DECIMAL(15, 2) DEFAULT 0,  -- 現在値
    unit VARCHAR(50),  -- '円', '件', '人'

    -- 期限目標の場合
    deadline DATE,

    -- 期間
    period_type VARCHAR(20) NOT NULL DEFAULT 'monthly',  -- 'yearly', 'quarterly', 'monthly', 'weekly'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active', 'completed', 'cancelled'

    -- 機密区分（4段階: public/internal/confidential/restricted）
    -- 目標は人事評価に関わるため、基本は internal 以上を使用
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',
    CONSTRAINT check_goal_classification
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id)
);

-- インデックス
CREATE INDEX idx_goals_org ON goals(organization_id);
CREATE INDEX idx_goals_user ON goals(user_id);
CREATE INDEX idx_goals_dept ON goals(department_id);
CREATE INDEX idx_goals_parent ON goals(parent_goal_id);
CREATE INDEX idx_goals_period ON goals(period_start, period_end);
CREATE INDEX idx_goals_status ON goals(status) WHERE status = 'active';

-- コメント
COMMENT ON TABLE goals IS '目標管理テーブル（Phase 2.5）';
COMMENT ON COLUMN goals.goal_level IS '目標レベル: company=会社, department=部署, individual=個人';
COMMENT ON COLUMN goals.goal_type IS '目標タイプ: numeric=数値, deadline=期限, action=行動';
COMMENT ON COLUMN goals.classification IS '機密区分（4段階）: public=公開, internal=社内限定, confidential=機密, restricted=極秘';
```

### 7.2 goal_progress テーブル（進捗記録）

```sql
CREATE TABLE goal_progress (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- リレーション
    goal_id UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 進捗データ
    progress_date DATE NOT NULL,  -- 記録日
    value DECIMAL(15, 2),  -- 数値目標の場合の実績値
    cumulative_value DECIMAL(15, 2),  -- 累計値

    -- 振り返り
    daily_note TEXT,  -- 「今日何やった？」の回答
    daily_choice TEXT,  -- 「今日何を選んだ？」の回答

    -- AIフィードバック
    ai_feedback TEXT,  -- ソウルくんからのフィードバック
    ai_feedback_sent_at TIMESTAMPTZ,  -- フィードバック送信日時

    -- 機密区分（4段階: public/internal/confidential/restricted）
    -- 目標・進捗は人事評価に関わるため、基本は internal 以上を使用
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',
    CONSTRAINT check_goal_progress_classification
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),

    -- 冪等性（1日1回のみ記録、訂正時は上書き）
    CONSTRAINT unique_goal_progress UNIQUE(goal_id, progress_date)
);

-- インデックス
CREATE INDEX idx_goal_progress_goal ON goal_progress(goal_id);
CREATE INDEX idx_goal_progress_org ON goal_progress(organization_id);
CREATE INDEX idx_goal_progress_date ON goal_progress(progress_date);

-- コメント
COMMENT ON TABLE goal_progress IS '目標の日次進捗記録（Phase 2.5）';
COMMENT ON COLUMN goal_progress.daily_note IS '17時の「今日何やった？」への回答';
COMMENT ON COLUMN goal_progress.daily_choice IS '「今日何を選んだ？」への回答';
COMMENT ON COLUMN goal_progress.classification IS '機密区分（4段階）: public=公開, internal=社内限定, confidential=機密, restricted=極秘';
COMMENT ON CONSTRAINT unique_goal_progress ON goal_progress IS
'冪等性保証: 同日に複数回返信があった場合は最新で上書き（UPSERT）';
```

**進捗記録の更新ルール:**

| 状況 | 処理 |
|------|------|
| 初回回答 | INSERT |
| 同日の訂正・追加回答 | UPSERT（最新で上書き） |
| 翌日以降の訂正 | 新しいレコードをINSERT（過去は変更不可） |

```python
# UPSERT実装例
await conn.execute("""
    INSERT INTO goal_progress (
        goal_id, organization_id, progress_date, value,
        cumulative_value, daily_note, daily_choice, created_by
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    ON CONFLICT (goal_id, progress_date)
    DO UPDATE SET
        value = EXCLUDED.value,
        cumulative_value = EXCLUDED.cumulative_value,
        daily_note = EXCLUDED.daily_note,
        daily_choice = EXCLUDED.daily_choice,
        updated_at = NOW(),
        updated_by = EXCLUDED.created_by
""", goal_id, org_id, date, value, cumulative, note, choice, user_id)
```

### 7.3 goal_reminders テーブル（リマインド設定）

```sql
CREATE TABLE goal_reminders (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離（鉄則: 全テーブルにorganization_id）
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- リレーション
    goal_id UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,

    -- リマインド設定
    reminder_type VARCHAR(50) NOT NULL,  -- 'daily_check', 'morning_feedback', 'team_summary', 'daily_reminder'
    reminder_time TIME NOT NULL,  -- 17:00, 08:00, 18:00
    is_enabled BOOLEAN DEFAULT TRUE,

    -- ChatWork設定
    chatwork_room_id VARCHAR(20),  -- 通知先ルームID（NULLの場合はDM）

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id)
);

-- インデックス
CREATE INDEX idx_goal_reminders_org ON goal_reminders(organization_id);
CREATE INDEX idx_goal_reminders_goal ON goal_reminders(goal_id);
CREATE INDEX idx_goal_reminders_enabled ON goal_reminders(is_enabled) WHERE is_enabled = TRUE;

-- コメント
COMMENT ON TABLE goal_reminders IS '目標リマインド設定（Phase 2.5）';
```

### 7.4 通知の冪等性設計（notification_logs活用）

**Phase 1-Bで構築済みの `notification_logs` テーブルを活用し、二重送信を防止する。**

#### Phase 1-B との互換性

**✅ notification_logs.target_id は UUID 型（Phase 1-B v10.1.4 設計書 75行目）**

```python
# Phase 1-B設計（docs/05_phase_1b_task_detection.md）より
sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True,
          comment='対象ID（systemの場合はNULL）'),
```

→ マイグレーション不要。user_id (UUID) や department_id (UUID) をそのまま保存可能。

#### notification_type / target_type の型と拡張

**✅ これらのカラムは VARCHAR(50) 型（PostgreSQL enum ではない）**

```python
# Phase 1-B設計（docs/05_phase_1b_task_detection.md 71-74行目）より
sa.Column('notification_type', sa.String(50), nullable=False,
          comment='task_reminder, goal_reminder, meeting_reminder, system_notification'),
sa.Column('target_type', sa.String(50), nullable=False,
          comment='task, goal, meeting, system'),
```

→ **マイグレーション不要**。VARCHAR型なので、新しい値をINSERTするだけで拡張可能。
→ PostgreSQL enum 型のように `ALTER TYPE ... ADD VALUE` は不要。

| 項目 | Phase 1-B 既存値 | Phase 2.5 追加値 |
|------|----------------|-----------------|
| notification_type | `task_reminder`, `goal_reminder`, `meeting_reminder`, `system_notification` | `goal_daily_check`, `goal_morning_feedback`, `goal_team_summary`, `goal_daily_reminder` |
| target_type | `task`, `goal`, `meeting`, `system` | `user`, `department` |

**設計方針:** VARCHAR型のため、既存の値を壊さず新規値を追加可能。
既存のPhase 1-B通知（`task_reminder` + `target_type=task`）には影響なし。

**⚠️ 重要: 通知は「受信者単位」で管理する**

- 複数の目標を持つユーザー → 1日1通にまとめてスパム防止
- 同一部署に複数の受信者（リーダー複数＋部長）→ 全員に届くよう「受信者単位」で管理

```sql
-- Phase 2.5で使用する通知パターン

-- 1. 17時の進捗確認（受信者単位で1通）
--    notification_type = 'goal_daily_check'
--    target_type = 'user'
--    target_id = user_id (UUID)
--    → 1ユーザーが複数目標を持っていても、1通にまとめる

-- 2. 8時の個人フィードバック（受信者単位で1通）
--    notification_type = 'goal_morning_feedback'
--    target_type = 'user'
--    target_id = user_id (UUID)
--    → 前日の進捗に基づくフィードバック

-- 3. 8時のチーム/部署サマリー（受信者単位で1通）★重要★
--    notification_type = 'goal_team_summary'
--    target_type = 'user'        ← 部署ではなく受信者
--    target_id = recipient_user_id (UUID)  ← 受信者のuser_id
--    → 同一部署にリーダー3人＋部長1人がいる場合、4人全員に届く
--    → 「部署単位」だと2人目以降がスキップされる問題を回避

-- 4. 18時の未回答リマインド（受信者単位で1通）
--    notification_type = 'goal_daily_reminder'
--    target_type = 'user'
--    target_id = user_id (UUID)
--    → 17時の進捗確認に未回答の人のみ

-- 冪等性キー: organization_id + target_type + target_id + notification_date + notification_type
-- ※ 全ての通知が target_type='user' + target_id=受信者UUID で統一
```

**通知送信フロー:**

```python
async def send_daily_check_to_user(user_id: UUID, org_id: UUID):
    """
    17時の進捗確認送信（ユーザー単位で集約、冪等性保証）

    1ユーザーが複数目標を持っていても、1通のDMにまとめる
    """
    today = date.today()
    notification_type = 'goal_daily_check'

    # 1. 既に送信済みか確認（ユーザー単位）
    existing = await conn.fetchrow("""
        SELECT id, status FROM notification_logs
        WHERE organization_id = $1
          AND target_type = 'user'
          AND target_id = $2
          AND notification_date = $3
          AND notification_type = $4
    """, org_id, user_id, today, notification_type)

    if existing and existing['status'] == 'success':
        logger.info(f"既に送信済み: user={user_id} / {notification_type}")
        return  # スキップ（二重送信防止）

    # 2. ユーザーの全目標を取得して1通にまとめる
    goals = await get_active_goals_for_user(user_id, org_id)
    message = build_daily_check_message(user_id, goals)

    # 3. ChatWork送信
    try:
        await send_chatwork_message(user.chatwork_room_id, message)
        status = 'success'
        error_message = None
    except ChatWorkRateLimitError:
        status = 'failed'
        error_message = 'rate_limit'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)  # 機密情報を除去

    # 4. 送信ログを記録（UPSERT）
    await conn.execute("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, error_message, channel, channel_target
        )
        VALUES ($1, $2, 'user', $3, $4, $5, $6, 'chatwork', $7)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = EXCLUDED.status,
            error_message = EXCLUDED.error_message,
            retry_count = notification_logs.retry_count + 1,
            updated_at = NOW()
    """, org_id, notification_type, user_id, today, status, error_message, room_id)


async def send_team_summary_to_leader(recipient_id: UUID, department_id: UUID, org_id: UUID):
    """
    8時のチームサマリー送信（受信者単位で冪等性保証）

    ★重要: 冪等性キーは「受信者」単位（部署単位ではない）
    同一部署に複数の受信者（リーダー3人＋部長1人）がいる場合、
    全員にサマリーが届くように、target_id = recipient_user_id を使用。
    """
    today = date.today()
    notification_type = 'goal_team_summary'

    # 既に送信済みか確認（受信者単位）★部署単位ではない★
    existing = await conn.fetchrow("""
        SELECT id, status FROM notification_logs
        WHERE organization_id = $1
          AND target_type = 'user'           -- ★ 'department' ではなく 'user'
          AND target_id = $2                 -- ★ 受信者のuser_id
          AND notification_date = $3
          AND notification_type = $4
    """, org_id, recipient_id, today, notification_type)  # ★ recipient_id を使用

    if existing and existing['status'] == 'success':
        logger.info(f"既に送信済み: recipient={recipient_id} / {notification_type}")
        return  # スキップ（二重送信防止）

    # 部署のメンバー進捗を取得してサマリー作成
    team_members = await get_department_members(department_id, org_id)
    summary_message = build_team_summary_message(recipient_id, department_id, team_members)

    # ChatWork送信
    try:
        recipient = await get_user(recipient_id)
        await send_chatwork_message(recipient.chatwork_room_id, summary_message)
        status = 'success'
        error_message = None
    except ChatWorkRateLimitError:
        status = 'failed'
        error_message = 'rate_limit'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)

    # 送信ログを記録（UPSERT）★ target_type='user', target_id=recipient_id ★
    await conn.execute("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, error_message, channel, channel_target
        )
        VALUES ($1, $2, 'user', $3, $4, $5, $6, 'chatwork', $7)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = EXCLUDED.status,
            error_message = EXCLUDED.error_message,
            retry_count = notification_logs.retry_count + 1,
            updated_at = NOW()
    """, org_id, notification_type, recipient_id, today, status, error_message, recipient.chatwork_room_id)


async def send_all_team_summaries(org_id: UUID):
    """
    8時のチームサマリー一括送信

    部署ごとに、その部署のサマリーを受け取るべき全員（チームリーダー＋部長）に送信。
    """
    today = date.today()

    # 部署ごとにサマリー受信者を取得
    departments = await get_departments_with_active_goals(org_id)

    for dept in departments:
        # この部署のサマリーを受け取るべき人（リーダー全員＋部長）
        recipients = await get_summary_recipients(dept.id, org_id)

        for recipient in recipients:
            # 各受信者に個別に送信（冪等性は受信者単位で管理）
            await send_team_summary_to_leader(
                recipient_id=recipient.user_id,
                department_id=dept.id,
                org_id=org_id
            )


async def send_daily_reminder_to_user(user_id: UUID, org_id: UUID):
    """
    18時の未回答リマインド送信（受信者単位で冪等性保証）

    17時の進捗確認（goal_daily_check）に未回答の人に対して、
    「まだ回答してないウル？」とリマインドを送信。
    """
    today = date.today()
    notification_type = 'goal_daily_reminder'

    # 1. 既に18時リマインド送信済みか確認
    existing = await conn.fetchrow("""
        SELECT id, status FROM notification_logs
        WHERE organization_id = $1
          AND target_type = 'user'
          AND target_id = $2
          AND notification_date = $3
          AND notification_type = $4
    """, org_id, user_id, today, notification_type)

    if existing and existing['status'] == 'success':
        logger.info(f"既に18時リマインド送信済み: user={user_id}")
        return  # スキップ

    # 2. 17時の進捗確認に回答済みか確認（goal_progressに当日のレコードがあるか）
    progress_today = await conn.fetchrow("""
        SELECT id FROM goal_progress gp
        JOIN goals g ON gp.goal_id = g.id
        WHERE g.user_id = $1
          AND g.organization_id = $2
          AND gp.progress_date = $3
    """, user_id, org_id, today)

    if progress_today:
        logger.info(f"既に回答済み: user={user_id}")
        return  # 回答済みなのでリマインド不要

    # 3. 未回答なのでリマインド送信
    user = await get_user(user_id)
    message = build_daily_reminder_message(user)

    try:
        await send_chatwork_message(user.chatwork_room_id, message)
        status = 'success'
        error_message = None
    except ChatWorkRateLimitError:
        status = 'failed'
        error_message = 'rate_limit'
    except Exception as e:
        status = 'failed'
        error_message = sanitize_error(e)

    # 4. 送信ログを記録（UPSERT）
    await conn.execute("""
        INSERT INTO notification_logs (
            organization_id, notification_type, target_type, target_id,
            notification_date, status, error_message, channel, channel_target
        )
        VALUES ($1, $2, 'user', $3, $4, $5, $6, 'chatwork', $7)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
        DO UPDATE SET
            status = EXCLUDED.status,
            error_message = EXCLUDED.error_message,
            retry_count = notification_logs.retry_count + 1,
            updated_at = NOW()
    """, org_id, notification_type, user_id, today, status, error_message, user.chatwork_room_id)


def build_daily_reminder_message(user) -> str:
    """
    18時の未回答リマインドメッセージを生成
    """
    return f"""{user.display_name}さん、まだ今日の振り返りができてないウル🐺

17時に送った進捗確認、見てくれたウル？

忙しい1日だったかもしれないけど、
1分だけ時間をもらえると嬉しいウル✨

【今日の振り返り】
・目標に向けて、今日どんな行動を選んだウル？
・数字があれば、今日の実績も教えてほしいウル！

返信で教えてくれると、明日の朝フィードバックするウル💪
"""
```

#### 18時リマインドのスケジュール設定

```python
# Cloud Scheduler設定（18:00 JST）
# cron: 0 18 * * * Asia/Tokyo

async def scheduled_daily_reminder(org_id: UUID):
    """
    18時の未回答リマインド一括送信（Scheduler から呼び出し）
    """
    # 17時の進捗確認対象者のうち、未回答の人を取得
    users_with_goals = await get_users_with_active_goals(org_id)

    for user in users_with_goals:
        # 各ユーザーに対してリマインド送信（冪等性は内部で管理）
        await send_daily_reminder_to_user(
            user_id=user.id,
            org_id=org_id
        )
```

#### 通知タイプ一覧（Phase 2.5）

| 通知タイプ | notification_type | target_type | 送信時刻 | 説明 |
|-----------|------------------|-------------|---------|------|
| 17時進捗確認 | `goal_daily_check` | `user` | 17:00 | 全員に今日の振り返りを問いかけ |
| 18時未回答リマインド | `goal_daily_reminder` | `user` | 18:00 | 17時に未回答の人にリマインド |
| 8時個人フィードバック | `goal_morning_feedback` | `user` | 08:00 | 前日の振り返りに対するフィードバック |
| 8時チームサマリー | `goal_team_summary` | `user` | 08:00 | チームリーダー・部長向けサマリー |

### 7.5 エラーメッセージのサニタイズ

**鉄則: エラーメッセージに機密情報を含めない**

`notification_logs.error_message` に `str(e)` をそのまま保存すると、
例外内容に機密情報や内部パスが含まれる可能性がある。

```python
def sanitize_error(e: Exception) -> str:
    """
    エラーメッセージから機密情報を除去

    除去対象:
    - ファイルパス（/Users/xxx, /home/xxx など）
    - API キー・トークン
    - ユーザーID（UUID）
    - メールアドレス
    - 内部ホスト名・IP
    """
    error_str = str(e)

    # 1. ファイルパスを除去
    error_str = re.sub(r'/[^\s]+', '[PATH]', error_str)

    # 2. UUIDを除去
    error_str = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '[UUID]',
        error_str,
        flags=re.IGNORECASE
    )

    # 3. メールアドレスを除去
    error_str = re.sub(r'[\w.+-]+@[\w.-]+\.\w+', '[EMAIL]', error_str)

    # 4. APIキー・トークン風の文字列を除去
    error_str = re.sub(r'(key|token|secret|password)[\s]*[=:][\s]*[^\s]+', r'\1=[REDACTED]', error_str, flags=re.IGNORECASE)

    # 5. 長すぎる場合は切り詰め
    if len(error_str) > 500:
        error_str = error_str[:500] + '...[TRUNCATED]'

    return error_str


# 使用例
except Exception as e:
    status = 'failed'
    error_message = sanitize_error(e)  # ✅ サニタイズ済み
    # error_message = str(e)  # ❌ 機密情報漏洩リスク
```

**許可されるエラーメッセージ例:**

| OK（サニタイズ済み） | NG（機密情報を含む） |
|---------------------|---------------------|
| `rate_limit` | `User abc123@example.com exceeded rate limit` |
| `timeout` | `/Users/kaz/soul-kun/lib/chatwork.py:123 timeout` |
| `connection_error` | `Connection to 192.168.1.100:5432 failed` |
| `[PATH] line 123: [UUID] not found` | `/home/deploy/app.py line 123: 550e8400-e29b-41d4-a716-446655440000 not found` |
| `User [EMAIL] exceeded rate limit` | - |
| `Connection to [IP]:[PORT] failed` | - |

**注意:** OK欄の例はすべてサニタイズ済みの形式。
メールアドレス → `[EMAIL]`、IPアドレス → `[IP]`、ポート → `[PORT]` に置換。

**Scheduler再実行時の挙動:**

| 状況 | 処理 |
|------|------|
| 未送信 | 送信実行 |
| 送信成功済み | スキップ（二重送信防止） |
| 送信失敗済み | リトライ（retry_count++） |
| リトライ上限超過（3回） | スキップ + アラート |

---

## 8. API設計

### 8.1 共通仕様（鉄則遵守）

**認証:** 全APIは認証必須（例外なし）

```
Authorization: Bearer <access_token>
```

**ページネーション:** 1000件を超える可能性のあるAPIには必須

```
GET /api/v1/goals?limit=100&offset=0
GET /api/v1/goals/{id}/progress?limit=100&offset=0
```

| パラメータ | デフォルト | 最大値 |
|-----------|----------|-------|
| limit | 100 | 1000 |
| offset | 0 | - |

**レスポンス形式:**

```json
{
  "data": [...],
  "pagination": {
    "total": 150,
    "limit": 100,
    "offset": 0,
    "has_next": true
  }
}
```

### 8.2 エンドポイント一覧

| メソッド | エンドポイント | 説明 | ページネーション |
|---------|--------------|------|----------------|
| POST | /api/v1/goals | 目標登録 | - |
| GET | /api/v1/goals | 目標一覧取得 | ✅ 必須 |
| GET | /api/v1/goals/{id} | 目標詳細取得 | - |
| PUT | /api/v1/goals/{id} | 目標更新 | - |
| DELETE | /api/v1/goals/{id} | 目標削除 | - |
| POST | /api/v1/goals/{id}/progress | 進捗記録 | - |
| GET | /api/v1/goals/{id}/progress | 進捗履歴取得 | ✅ 必須 |
| GET | /api/v1/goals/summary/team | チームサマリー取得 | ✅ 必須 |
| GET | /api/v1/goals/summary/department | 部署サマリー取得 | ✅ 必須 |

### 8.3 ChatWork連携

| 機能 | トリガー | 処理 |
|------|---------|------|
| 目標登録 | 「目標を設定したい」 | 対話形式で目標を登録 |
| 進捗確認 | 毎日17時（Scheduler） | 全員にDMで問いかけ |
| 進捗回答 | スタッフの返信 | goal_progressに記録 |
| フィードバック | 毎日8時（Scheduler） | 個人DM + サマリー送信 |

### 8.4 ChatWork API エラーハンドリング

**レート制限（429）・タイムアウト対応:**

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60)
)
async def send_chatwork_with_retry(room_id: str, message: str):
    """
    ChatWork送信（指数バックオフ + リトライ上限）
    """
    try:
        response = await chatwork_client.send_message(room_id, message)
        return response
    except ChatWorkRateLimitError as e:
        # 429: レート制限
        wait_seconds = int(e.headers.get('Retry-After', 60))
        logger.warning(f"ChatWork rate limit. Waiting {wait_seconds}s")
        await asyncio.sleep(wait_seconds)
        raise  # リトライ
    except ChatWorkTimeoutError:
        logger.warning("ChatWork timeout. Retrying...")
        raise  # リトライ
    except ChatWorkServerError:
        logger.error("ChatWork server error. Retrying...")
        raise  # リトライ
```

**エラー時の挙動:**

| エラー | 対応 | 上限 |
|--------|------|------|
| 429 Rate Limit | 指数バックオフ + リトライ | 3回 |
| Timeout | 即時リトライ | 3回 |
| 5xx Server Error | 指数バックオフ + リトライ | 3回 |
| 4xx Client Error | リトライしない（ログ記録） | - |
| 上限超過 | notification_logsに'failed'記録 + アラート | - |

---

## 9. MVP実装計画

### 9.1 スコープ

**MVP（最初に作るもの）:**

1. ✅ 目標登録機能（ChatWorkで対話形式 + 誘導）
2. ✅ 組織図との連動確認（既存Phase 3.5活用）
3. ✅ 毎日17時の進捗確認（フォーマット提示）
4. ✅ 翌朝8時の進捗レポート送信（個人DM + チームリーダー・部長サマリー）
5. ✅ 部署目標 ↔ 個人目標の繋がり可視化

**後回しにするもの:**

- Web画面での目標管理UI
- スプレッドシート一括登録
- 他システムとの自動連携（売上データなど）
- 全体ダッシュボード（カズさん用）
- スマホUI対応

### 9.2 実装スケジュール

| Week | タスク | 詳細 |
|------|--------|------|
| Week 1 | 基盤構築 | goals, goal_progressテーブル作成、組織図連動確認 |
| Week 2 | 目標登録 | ChatWorkで対話形式の目標登録実装 |
| Week 3 | 毎日サイクル | 17時問いかけ、8時フィードバック実装 |
| Week 4 | サマリー・調整 | チームリーダー・部長サマリー、テスト |

### 9.3 テスト計画

**Step 1:** カズさん＋2-3名で1-2週間テスト
**Step 2:** フィードバックを収集、改善
**Step 3:** 部長にデモ → 部署ごとのカスタマイズ
**Step 4:** 全社展開

---

## 10. 汎用目標タイプ（MVP版）

### 10.1 数値目標

| 目標タイプ | 単位 | 例 |
|-----------|------|-----|
| 粗利 | 円 | 300万円/月 |
| 売上 | 円 | 500万円/月 |
| 獲得件数 | 件 | 10件/月 |
| 獲得人数 | 人 | 5人/月 |
| 納品件数 | 件 | 8件/月 |
| 面談件数 | 件 | 20件/月 |
| カスタム | 任意 | ○○/月 |

### 10.2 期限目標

| 目標タイプ | 形式 | 例 |
|-----------|------|-----|
| プロジェクト完了 | 日付 | 「新サービスリリース」1/31まで |
| タスク完了 | 日付 | 「マニュアル作成」1/15まで |
| 資格取得 | 日付 | 「○○資格取得」3/31まで |

### 10.3 行動目標

| 目標タイプ | 頻度 | 例 |
|-----------|------|-----|
| 日次行動 | 毎日 | 「朝礼で発言する」毎日 |
| 週次行動 | 毎週 | 「週報を提出する」毎週金曜 |

---

## 11. リスクと対策

### 11.1 回答率が低い問題

**リスク:** 50名全員が毎日17時に回答しない

**対策:**
- 回答しやすいフォーマット（数字入力だけ）
- 未回答者には18時にリマインド
- 3日連続未回答でチームリーダーに通知
- 「強制」ではなく「習慣化の仕組み」として設計

### 11.2 目標設定の質

**リスク:** 自由入力だとカオスになる

**対策:**
- 目標タイプを限定（数値/期限/行動）
- テンプレート + 自由入力のハイブリッド
- ソウルくんが「その目標で良い？」と確認

### 11.3 サマリーの情報量

**リスク:** 50名分のサマリーは長すぎる

**対策:**
- チームリーダー → 自分のチームのみ（5-10名）
- 部長 → チーム単位のサマリー（詳細は省略）
- 異常値のみハイライト（遅れている人だけ強調）

---

## 12. 監査ログ・機密区分

### 12.1 機密区分の設計

**コーディング規約に従い、4段階の機密区分を使用。**

```
public < internal < confidential < restricted
```

| 区分 | 説明 | Phase 2.5での用途 |
|------|------|-----------------|
| public | 公開情報 | 使用しない |
| internal | 社内限定 | 通常の目標・進捗 |
| confidential | 機密 | 評価に直結するフィードバック |
| restricted | 極秘 | 使用しない（人事評価確定前の情報など、将来用） |

**目標・進捗データは人事評価に関わるため、`internal`（社内限定）以上の機密区分を設定。**

| データ | 機密区分 | 理由 |
|--------|---------|------|
| 目標（goals） | internal | 個人の業績目標 |
| 進捗（goal_progress） | internal ※ | 日々の実績・振り返り |
| チームサマリー | internal | 部下の進捗一覧 |
| 個人フィードバック | confidential | 評価に直結する可能性（必ず監査ログ対象） |

**※ goal_progressの機密区分について:**
- 基本は `internal`（日々の進捗記録）
- `ai_feedback` 列にソウルくんからのフィードバックが入った場合は `confidential` に更新
- 理由: AIフィードバックは人事評価に直結する可能性があるため

```python
# AIフィードバック保存時に機密区分を更新
if ai_feedback:
    await conn.execute("""
        UPDATE goal_progress
        SET ai_feedback = $1,
            ai_feedback_sent_at = NOW(),
            classification = 'confidential',  -- フィードバック含む場合は confidential
            updated_at = NOW()
        WHERE id = $2
    """, ai_feedback, progress_id)
```

### 12.2 監査ログの記録

**以下の操作は `audit_logs` テーブルに記録する（鉄則: confidential以上の操作で記録）:**

| 操作 | action | resource_type | 記録タイミング |
|------|--------|--------------|---------------|
| 目標閲覧 | view | goal | 他人の目標を閲覧時 |
| 目標作成 | create | goal | 常に |
| 目標更新 | update | goal | 常に |
| 目標削除 | delete | goal | 常に |
| 進捗閲覧 | view | goal_progress | 他人の進捗を閲覧時 |
| 進捗記録 | create | goal_progress | 常に |
| サマリー閲覧 | view | goal_summary | チームリーダー・部長がサマリー閲覧時 |

```python
from lib.audit import log_audit

# 他人の目標を閲覧した場合
if goal.user_id != current_user.id:
    await log_audit(
        user=current_user,
        action='view',
        resource_type='goal',
        resource_id=goal.id,
        classification=goal.classification,  # 目標の機密区分を使用（internal or confidential）
        metadata={'goal_owner_id': str(goal.user_id)}
    )
```

### 12.3 アクセス制御

**組織図（Phase 3.5）と連動したアクセス制御:**

```python
async def can_view_goal(user: User, goal: Goal) -> bool:
    """
    目標の閲覧権限チェック
    """
    # 自分の目標は常にOK
    if goal.user_id == user.id:
        return True

    # 組織図から上司関係を確認
    user_role = await get_user_role(user.id)

    if user_role.name == 'チームリーダー':
        # チームメンバーの目標のみ
        team_members = await get_team_members(user.id)
        return goal.user_id in team_members

    if user_role.name == '部長':
        # 部署全員の目標
        dept_members = await get_department_members(user.department_id)
        return goal.user_id in dept_members

    if user_role.name in ['経営', '代表']:
        # 全員の目標
        return True

    return False
```

---

## 13. 目標設定対話フロー（ChatWork一問一答）【v1.6追加】

### 13.1 設計思想

**アチーブメント社・選択理論に基づく目標設定の順序：**

```
【Step 1】WHY - なぜ達成したいのか（内発的動機）
         ↓
【Step 2】WHAT - 何を・いつまでに・どれくらい（結果目標）
         ↓
【Step 3】HOW - そのために何をするか（行動目標）
```

**なぜこの順番か：**

| 理論 | 根拠 |
|------|------|
| 選択理論 | 「やりたいから」やる状態を作るには、まず願望（Want）を明確にする |
| ナポレオン・ヒル | 「燃えるような願望」がなければ、目標は達成されない |
| ソウルシンクスMVV | 「理想の未来のために何をすべきか考え、行動する」= まず理想の未来（WHY）を描く |

### 13.2 対話フローの詳細

#### Step 0: 導入（アジェンダ提示）

**トリガー：**「目標を設定したい」「目標を立てたい」など

**ソウルくんの応答：**

```
目標設定をサポートするウル！🐺

{name}さんが達成したい目標、
一緒に決めていこうウル✨

━━━━━━━━━━━━━━━━━━━━━━━
📋 これから決める3つのこと

① WHY - なぜ達成したいか
② WHAT - 何を・いつまでに・どれくらい
③ HOW - そのために何をするか
━━━━━━━━━━━━━━━━━━━━━━━

一つずつ質問するから、答えてほしいウル！

{name}さんの答えを全部覚えて、
毎日一緒に伴走するウル🐺

達成したとき、一緒に喜びを分かち合おうウル💪

じゃあ最初の質問ウル！
```

#### Step 1: WHY（なぜ達成したいか）

**ソウルくんの質問：**

```
【① WHY】なぜ達成したいか

まず教えてほしいウル🐺

・どんな目標を考えてる？
・それを達成したら、どんな気持ちになる？
・誰が喜んでくれる？

「なぜ達成したいか」が明確だと、
困難があっても乗り越えられるウル✨
```

**評価基準：**

| 評価項目 | OK基準 | NG例 |
|---------|--------|------|
| 内発的動機が見える | 「〜したい」「〜になりたい」がある | 「言われたから」「やらなきゃ」 |
| 具体性 | 誰が・何が・どうなるかが見える | 「成長したい」「頑張りたい」だけ |
| 方向性 | ソウルシンクスでの成長・貢献に繋がる | 「転職に有利」「副業で稼ぐ」 |

#### Step 2: WHAT（何を・いつまでに・どれくらい）

**ソウルくんの質問：**

```
【② WHAT】何を・いつまでに・どれくらい

{WHYの回答を受けて}
その想いがあれば絶対達成できるウル✨

次は具体的に決めようウル🐺

・何を達成する？
・いつまでに？
・どれくらい？

例：「1月末までに粗利300万円」
```

**評価基準：**

| 評価項目 | OK基準 | NG例 |
|---------|--------|------|
| 測定可能性 | 数値または明確な完了条件がある | 「頑張る」「もっとやる」 |
| 期限 | いつまでかが明確 | 「いつか」「そのうち」 |
| 現実性 | 努力すれば達成可能な範囲 | 明らかに不可能な目標 |

#### Step 3: HOW（そのために何をするか）

**ソウルくんの質問：**

```
【③ HOW】そのために何をするか

「{結果目標}」ウル！

最後は行動目標ウル🐺
これを達成するために、何をするウル？

・何を？
・どれくらいの頻度で？
・どれくらいの量？

例：「毎日新規架電10件」「週3回訪問」

毎日の行動が成果を作るウル✨
```

**評価基準：**

| 評価項目 | OK基準 | NG例 |
|---------|--------|------|
| 結果目標との繋がり | 行動が結果に直結する | 関係ない行動（例：粗利目標に「本を読む」） |
| 実行可能性 | 毎日/毎週続けられる | 現実的でない量・頻度 |
| 具体性 | 何をどれだけかが明確 | 「頑張る」「意識する」 |

#### Step 4: 完了（登録・伴走開始）

**ソウルくんの応答：**

```
目標設定完了ウル！🎉

━━━━━━━━━━━━━━━━━━━━━━━
📋 {name}さんの目標

【WHY】
{why_content}

【結果目標】
{what_content}

【行動目標】
{how_content}
━━━━━━━━━━━━━━━━━━━━━━━

全部覚えたウル！
毎日17時に「今日どうだった？」って聞くから、
一緒に振り返ろうウル🐺

{name}さんの可能性を、
ソウルくんは誰よりも信じてるウル💪

さあ、一緒に達成しようウル！✨
```

### 13.3 フィードバック（再質問）のパターン

#### 抽象的すぎる場合

```
いい想いウル！🐺

もう少し具体的に聞かせてほしいウル✨

・具体的にどんな状態になりたい？
・数字で表すとどれくらい？
・いつまでに達成したい？

例えば「○月末までに○○を○○にする」
みたいに教えてくれると嬉しいウル🐺
```

#### 方向性が違う場合（転職・副業志向）

```
{name}さんの向上心、すごいウル！🐺

ちょっと一緒に考えてみたいウル✨

その目標を達成したら、
ソウルシンクスでの{name}さんの価値も
上がると思うウル！

今の仕事でその力を発揮したら、
どんな成果が出せそうウル？

「プロとして期待を超える」って
ソウルシンクスの大事にしてることウル🐺
```

#### 他責思考の場合

```
そう感じてるんだねウル🐺
正直に教えてくれてありがとうウル。

ソウルシンクスが大事にしてる考え方があるウル✨

「自分が源。自ら考え、自ら動く」

環境や周りを変えることは難しいウル。
でも、{name}さん自身の行動は
{name}さんが選べるウル🐺

{name}さんができることって、何がありそうウル？
```

---

## 14. 目標設定ログ・継続改善設計【v1.6追加】

### 14.1 設計思想

**目的：**
- スタッフの相談内容をデータとして蓄積
- 想定外のパターンを発見し、対応を改善
- 目標設定の成功率を継続的に向上

**カズさんへの相談フロー：**
1. ログを定期分析（週次/月次）
2. 新しいパターンや改善点を発見
3. カズさんに報告・相談
4. 承認後、プロンプト/回答パターンを更新

### 14.2 データベース設計

#### goal_setting_sessions（目標設定セッション）

**目的：** 一問一答の途中状態を保持

```sql
CREATE TABLE goal_setting_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),

    -- セッション状態
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    -- 'in_progress' | 'completed' | 'abandoned'
    current_step VARCHAR(20) NOT NULL DEFAULT 'intro',
    -- 'intro' | 'why' | 'what' | 'how' | 'complete'

    -- 回答の一時保存
    why_answer TEXT,      -- Step 1の回答
    what_answer TEXT,     -- Step 2の回答
    how_answer TEXT,      -- Step 3の回答

    -- 完了時に作成されたgoal_id
    goal_id UUID REFERENCES goals(id),

    -- ChatWorkルーム（対話が行われているルーム）
    chatwork_room_id VARCHAR(20),

    -- タイミング
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- セッションタイムアウト（24時間で期限切れ）
    expires_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours'),

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX idx_goal_sessions_org ON goal_setting_sessions(organization_id);
CREATE INDEX idx_goal_sessions_user ON goal_setting_sessions(user_id);
CREATE INDEX idx_goal_sessions_status ON goal_setting_sessions(status)
    WHERE status = 'in_progress';
CREATE INDEX idx_goal_sessions_room ON goal_setting_sessions(chatwork_room_id, user_id)
    WHERE status = 'in_progress';

-- コメント
COMMENT ON TABLE goal_setting_sessions IS '目標設定セッション管理（Phase 2.5 v1.6）';
COMMENT ON COLUMN goal_setting_sessions.expires_at IS '24時間でタイムアウト。期限切れセッションは abandoned に更新';
```

#### goal_setting_logs（目標設定対話ログ）

**目的：** 対話内容を蓄積し、継続改善に活用

```sql
CREATE TABLE goal_setting_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- セッション管理
    session_id UUID NOT NULL REFERENCES goal_setting_sessions(id),
    user_id UUID NOT NULL REFERENCES users(id),

    -- ステップ管理
    step VARCHAR(20) NOT NULL,
    -- 'intro' | 'why' | 'what' | 'how' | 'complete'
    step_attempt INT NOT NULL DEFAULT 1,
    -- リトライ回数（1=初回、2=1回目の再質問後...）

    -- 対話内容
    user_message TEXT,          -- ユーザーの発言（原文）
    ai_response TEXT,           -- ソウルくんの回答

    -- AI評価
    detected_pattern VARCHAR(50),
    -- 'ok' | 'ng_career' | 'ng_abstract' | 'ng_other_blame' | 'ng_no_goal' | 'ng_too_high' | 'ng_mental_health' ...
    evaluation_result JSONB,
    -- {
    --   "specificity_score": 0.8,      -- 具体性スコア（0-1）
    --   "direction_score": 0.9,        -- 方向性スコア（0-1）
    --   "connection_score": 0.7,       -- 結果目標との繋がりスコア（0-1）
    --   "issues": ["abstract", "no_deadline"],
    --   "recommendation": "ask_for_deadline"
    -- }
    feedback_given BOOLEAN DEFAULT FALSE,
    -- フィードバック（再質問）を行ったか

    -- 結果
    result VARCHAR(20),
    -- 'accepted' | 'retry' | 'abandoned'

    -- 機密区分（目標設定の対話は internal 以上）
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_goal_log_classification
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

-- インデックス
CREATE INDEX idx_goal_logs_org ON goal_setting_logs(organization_id);
CREATE INDEX idx_goal_logs_session ON goal_setting_logs(session_id);
CREATE INDEX idx_goal_logs_user ON goal_setting_logs(user_id);
CREATE INDEX idx_goal_logs_pattern ON goal_setting_logs(detected_pattern);
CREATE INDEX idx_goal_logs_created ON goal_setting_logs(created_at DESC);

-- コメント
COMMENT ON TABLE goal_setting_logs IS '目標設定対話ログ（Phase 2.5 v1.6）。継続改善のためのデータ蓄積用';
COMMENT ON COLUMN goal_setting_logs.detected_pattern IS '検出されたパターンコード';
COMMENT ON COLUMN goal_setting_logs.evaluation_result IS 'AI評価の詳細（JSONBで拡張可能）';
```

#### goal_setting_patterns（パターンマスタ）

**目的：** 検出パターンの定義と推奨対応を管理

```sql
CREATE TABLE goal_setting_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- パターン定義
    pattern_code VARCHAR(50) UNIQUE NOT NULL,
    -- 'ok', 'ng_career', 'ng_abstract', 'ng_other_blame', ...
    pattern_name VARCHAR(100) NOT NULL,
    pattern_category VARCHAR(20) NOT NULL,
    -- 'ok' | 'ng' | 'warning'

    -- 対象ステップ
    applicable_steps TEXT[],
    -- ['why', 'what', 'how'] など

    -- 検出条件（AI評価用のヒント）
    detection_keywords TEXT[],
    -- ['転職', '副業', '市場価値'] など
    detection_description TEXT,
    -- 「転職や副業に関する発言」など

    -- 推奨対応
    recommended_response TEXT,
    -- 推奨の回答テンプレート
    response_strategy TEXT,
    -- 'redirect_to_company' | 'ask_for_specificity' | 'empathize_then_redirect' ...

    -- 統計（定期更新）
    occurrence_count INT DEFAULT 0,
    success_rate DECIMAL(5, 2),
    -- このパターン後の目標設定完了率
    last_occurred_at TIMESTAMPTZ,

    -- メタデータ
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 初期データ
INSERT INTO goal_setting_patterns (pattern_code, pattern_name, pattern_category, applicable_steps, detection_keywords, detection_description, response_strategy) VALUES
('ok', 'OK（適切）', 'ok', ARRAY['why', 'what', 'how'], NULL, '適切な回答', 'proceed'),
('ng_abstract', '抽象的すぎる', 'ng', ARRAY['why', 'what', 'how'], ARRAY['成長', '頑張る', '良くなりたい'], '具体性に欠ける発言', 'ask_for_specificity'),
('ng_career', '転職・副業志向', 'ng', ARRAY['why'], ARRAY['転職', '副業', '市場価値', 'どこでも通用'], '会社外でのキャリアを示唆', 'redirect_to_company'),
('ng_other_blame', '他責思考', 'ng', ARRAY['why', 'what'], ARRAY['上司が', '会社が', '環境が', 'せいで'], '他者や環境のせいにする発言', 'empathize_then_self_focus'),
('ng_no_goal', '目標がない', 'ng', ARRAY['why'], ARRAY['特にない', '今のまま', '考えてない'], '目標を持っていない', 'inspire_possibility'),
('ng_too_high', '目標が高すぎる', 'warning', ARRAY['what'], NULL, '達成不可能な目標設定', 'suggest_milestone'),
('ng_not_connected', '結果目標と繋がらない', 'ng', ARRAY['how'], NULL, '行動が結果目標と繋がっていない', 'connect_to_result'),
('ng_mental_health', 'メンタルヘルス懸念', 'warning', ARRAY['why', 'what', 'how'], ARRAY['疲れた', 'しんどい', '辛い', 'やる気が出ない'], '精神的な不調を示唆', 'empathize_and_suggest_human'),
('ng_private_only', 'プライベート目標のみ', 'warning', ARRAY['why', 'what'], ARRAY['ダイエット', '趣味', '旅行'], '仕事と関係ない目標のみ', 'add_work_goal');

-- コメント
COMMENT ON TABLE goal_setting_patterns IS '目標設定パターンマスタ（Phase 2.5 v1.6）';
COMMENT ON COLUMN goal_setting_patterns.response_strategy IS '対応戦略コード。実装側でこのコードに応じた対応を行う';
```

### 14.3 継続改善フロー

```
┌─────────────────────────────────────────────────────────────┐
│  【運用フェーズ】毎日                                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  スタッフが目標設定                                          │
│        ↓                                                     │
│  ソウルくんが対話（一問一答）                                │
│        ↓                                                     │
│  goal_setting_logs に自動記録                                │
│  - user_message（原文）                                      │
│  - detected_pattern（パターン分類）                          │
│  - ai_response（ソウルくんの回答）                           │
│  - result（結果：accepted / retry / abandoned）              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  【分析フェーズ】週次/月次                                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. ログを集計・分析                                         │
│     - パターン別の発生件数                                   │
│     - パターン別の目標設定完了率                             │
│     - 新しいパターン（未分類）の発見                         │
│     - 離脱が多いステップの特定                               │
│                                                              │
│  2. 改善点を特定                                             │
│     - 完了率が低いパターンへの対応改善                       │
│     - 新しいパターンへの対応追加                             │
│     - 回答テンプレートの改善                                 │
│                                                              │
│  3. カズさんに報告・相談                                     │
│     - 発見事項のレポート                                     │
│     - 改善案の提案                                           │
│     - 承認を得る                                             │
│                                                              │
│  4. 改善を実装                                               │
│     - goal_setting_patterns の更新                           │
│     - プロンプトの修正                                       │
│     - 効果測定の準備                                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 14.4 分析クエリ例

```sql
-- パターン別の発生件数と完了率
SELECT
    gsl.detected_pattern,
    gsp.pattern_name,
    COUNT(*) as occurrence_count,
    COUNT(CASE WHEN gss.status = 'completed' THEN 1 END) as completed_count,
    ROUND(
        COUNT(CASE WHEN gss.status = 'completed' THEN 1 END)::DECIMAL
        / COUNT(*)::DECIMAL * 100,
        1
    ) as completion_rate
FROM goal_setting_logs gsl
JOIN goal_setting_sessions gss ON gsl.session_id = gss.id
LEFT JOIN goal_setting_patterns gsp ON gsl.detected_pattern = gsp.pattern_code
WHERE gsl.created_at >= NOW() - INTERVAL '7 days'
GROUP BY gsl.detected_pattern, gsp.pattern_name
ORDER BY occurrence_count DESC;

-- 離脱が多いステップの特定
SELECT
    current_step as abandoned_at_step,
    COUNT(*) as abandoned_count
FROM goal_setting_sessions
WHERE status = 'abandoned'
  AND created_at >= NOW() - INTERVAL '7 days'
GROUP BY current_step
ORDER BY abandoned_count DESC;

-- 新しいパターン（未分類）の発見
SELECT
    user_message,
    COUNT(*) as occurrence_count
FROM goal_setting_logs
WHERE detected_pattern = 'unknown'
   OR detected_pattern IS NULL
GROUP BY user_message
ORDER BY occurrence_count DESC
LIMIT 20;
```

---

## 15. NGパターン対応方針【v1.6追加】

### 15.1 絶対に守ること

**最も大事なこと：**
> ソウルシンクスが良くなるために、スタッフが適切な目標設定をする

**絶対に守ること：**
- 目標は会社の目的・目標に繋がっている
- 「辞めたい」「転職したい」方向には絶対に導かない
- 直接的に「会社のために」とは言わない
- 間接的に、自然に、気づいたら会社の方向と一致している

### 15.2 NGパターン一覧と対応

#### 15.2.1 ng_career（転職・副業志向）

**検出キーワード：** 転職、副業、市場価値、どこでも通用、独立

**対応戦略：** redirect_to_company（会社での活躍に誘導）

**対応例：**
```
{name}さんの向上心、すごいウル！🐺

ちょっと一緒に考えてみたいウル✨

その目標を達成したら、
ソウルシンクスでの{name}さんの価値も
上がると思うウル！

今の仕事でその力を発揮したら、
どんな成果が出せそうウル？

「プロとして期待を超える」って
ソウルシンクスの大事にしてることウル🐺
```

#### 15.2.2 ng_abstract（抽象的すぎる）

**検出キーワード：** 成長したい、頑張りたい、良くなりたい

**対応戦略：** ask_for_specificity（具体化を促す）

**対応例：**
```
いい想いウル！🐺

もう少し具体的に聞かせてほしいウル✨

・具体的にどんな状態になりたい？
・数字で表すとどれくらい？
・いつまでに達成したい？

例えば「○月末までに○○を○○にする」
みたいに教えてくれると嬉しいウル🐺
```

#### 15.2.3 ng_other_blame（他責思考）

**検出キーワード：** 上司が、会社が、環境が、〜のせいで

**対応戦略：** empathize_then_self_focus（共感してから自分にフォーカス）

**対応例：**
```
そう感じてるんだねウル🐺
正直に教えてくれてありがとうウル。

ソウルシンクスが大事にしてる考え方があるウル✨

「自分が源。自ら考え、自ら動く」

環境や周りを変えることは難しいウル。
でも、{name}さん自身の行動は
{name}さんが選べるウル🐺

{name}さんができることって、何がありそうウル？
```

#### 15.2.4 ng_no_goal（目標がない）

**検出キーワード：** 特にない、今のままでいい、考えてない

**対応戦略：** inspire_possibility（可能性を引き出す）

**対応例：**
```
今のままでいいって思えるの、
実は満たされてる証拠かもしれないウル🐺

ちょっとだけ聞かせてほしいウル！

もし何でも叶うとしたら、
どんな自分になってみたいウル？
どんな未来だったらワクワクするウル？

小さなことでいいウル✨
「こうなったらいいな」を教えてほしいウル🐺
```

#### 15.2.5 ng_too_high（目標が高すぎる）

**検出条件：** 明らかに達成不可能な数値目標

**対応戦略：** suggest_milestone（マイルストーンを提案）

**対応例：**
```
その目標、すごい挑戦ウル！🐺
{name}さんの向上心、最高ウル✨

一つ確認させてほしいウル！
その目標、達成できるイメージは持ててるウル？

もし「ちょっと厳しいかも」と感じてたら、
まず「ここまでは絶対達成する」っていう
確実な目標を決めてみないウル？

その上で、さらに上を目指すのもアリウル🐺
```

#### 15.2.6 ng_not_connected（結果目標と繋がらない）

**検出条件：** 行動目標が結果目標と直接繋がっていない

**対応戦略：** connect_to_result（結果への繋がりを確認）

**対応例：**
```
それも大事なことウル！📚

ただ「{結果目標}」を達成するために、
もっと直接的な行動も決めたいウル🐺

{結果目標}を達成するには、
何が必要ウル？
・何件の商談が必要？
・そのために何件のアプローチが必要？

例えば「毎日新規架電10件」「週3回訪問」とか、
成果に直結する行動を教えてほしいウル✨
```

#### 15.2.7 ng_mental_health（メンタルヘルス懸念）

**検出キーワード：** 疲れた、しんどい、辛い、やる気が出ない

**対応戦略：** empathize_and_suggest_human（共感して人間に繋ぐ）

**対応例：**
```
{name}さん、正直に教えてくれてありがとうウル🐺

無理に目標の話をしなくていいウル。
今は休むことが大事な時かもしれないウル。

もし話したいことがあったら、
上司や人事の人にも相談してみてほしいウル。
一人で抱え込まないでほしいウル✨

ソウルくんはいつでもここにいるウル🐺
```

**⚠️ 重要：** このパターンが検出された場合、目標設定は中断し、人間（上司・人事）への相談を促す。AIだけで対応しない。

#### 15.2.8 ng_private_only（プライベート目標のみ）

**検出キーワード：** ダイエット、趣味、旅行

**対応戦略：** add_work_goal（仕事の目標も追加）

**対応例：**
```
健康って大事ウル！🐺

{プライベート目標}を達成したら、
仕事のパフォーマンスも上がりそうウル？✨

ソウルくんは仕事の目標を一緒に追いかけるのが
得意ウル🐺

仕事で達成したい目標も一緒に決めてみないウル？
プライベートと仕事、両方うまくいったら最高ウル💪
```

### 15.3 評価フロー

```
ユーザーの発言
      ↓
┌─────────────────────────────────────┐
│  AI評価（GPT-4）                     │
│  - キーワード検出                    │
│  - 文脈理解                          │
│  - スコアリング（具体性、方向性等） │
└─────────────────────────────────────┘
      ↓
┌─────────────────────────────────────┐
│  パターン判定                        │
│  - ok → 次のステップへ              │
│  - ng_* → 対応戦略に基づきフィードバック │
│  - unknown → ログに記録、後で分析   │
└─────────────────────────────────────┘
      ↓
┌─────────────────────────────────────┐
│  ログ記録                            │
│  - goal_setting_logs に保存          │
│  - 継続改善のデータとして蓄積        │
└─────────────────────────────────────┘
```

---

## 16. 次のアクション

1. ~~**カズさん承認** → この設計書の内容でOKか確認~~ ✅完了
2. **DB作成** → goals, goal_progress, goal_reminders, goal_setting_sessions, goal_setting_logs, goal_setting_patterns テーブル作成
3. **プロンプト設計** → ソウルくんの目標達成支援プロンプトを詳細化
4. **ChatWork連携** → 目標登録・進捗確認の実装
5. **Scheduler設定** → 17時・8時の自動送信設定
6. **継続改善フロー** → 週次レポート、パターン分析の実装

---

**[📁 目次に戻る](00_README.md)**


