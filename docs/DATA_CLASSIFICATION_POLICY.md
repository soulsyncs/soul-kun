# データ分類ポリシー

**作成日:** 2026-02-08
**目的:** 全テーブルのデータ機密レベルを定義し、RLS/監査ログ/削除ポリシーの基準とする

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | データ分類の基準と全テーブルの分類一覧 |
| **書くこと** | 4段階分類の定義、各テーブルの分類、保護要件 |
| **書かないこと** | RLS実装詳細（→RLS_POLICY_DESIGN.md）、監査ログ実装（→コード） |
| **SoT（この文書が正）** | テーブルごとのデータ分類レベル |
| **Owner** | Tech Lead |
| **更新トリガー** | 新テーブル追加時、分類変更時 |

---

## 1. 分類レベル定義

| レベル | 名称 | 説明 | アクセス権限 | 例 |
|--------|------|------|-------------|-----|
| **L4** | PII/機微 | 個人を特定できる情報、感情・健康データ | Level 5-6のみ | 氏名、メール、感情スコア |
| **L3** | 社内機密 | 経営判断、評価、CEO指示 | Level 4以上 | CEO教え、目標評価、Guardian判定 |
| **L2** | 社内一般 | 業務データ、タスク、ドキュメント | Level 2以上（組織内） | タスク、議事録、ナレッジ |
| **L1** | 公開/マスター | 全組織共通の設定データ | 認証済みユーザー全員 | AIモデル定義、目標設定パターン |

---

## 2. 保護要件マトリクス

| 要件 | L4 PII/機微 | L3 社内機密 | L2 社内一般 | L1 公開 |
|------|------------|------------|------------|---------|
| **RLS必須** | 必須 | 必須 | 必須 | 不要 |
| **監査ログ** | 全アクセス記録 | 書き込み記録 | なし | なし |
| **暗号化（at rest）** | 必須 | 推奨 | 標準 | 標準 |
| **PII除去** | ログ出力時必須 | ログ出力時必須 | 不要 | 不要 |
| **キャッシュTTL** | キャッシュ禁止 | 1分 | 5分（鉄則#6） | 24時間 |
| **保持期間** | 最小限（90日） | 1年 | 無期限 | 無期限 |
| **削除方法** | 物理削除 | 論理→物理 | 論理削除 | 削除なし |

---

## 3. テーブル分類一覧

### L4: PII/機微（8テーブル）

| テーブル | org_id型 | RLS | 含まれるPII |
|---------|---------|-----|------------|
| users | UUID | 計画中 | 氏名、メール、account_id |
| chatwork_users | UUID | なし | 氏名、account_id |
| emotion_scores | UUID | なし | 個人感情スコア（-1.0〜+1.0） |
| emotion_alerts | UUID | なし | 感情変化アラート |
| persons | なし（要追加） | なし | 氏名、属性 |
| person_attributes | なし（要追加） | なし | 個人属性情報 |
| person_events | なし（要追加） | なし | 個人イベント履歴 |
| user_preferences | UUID | なし | 個人嗜好・スタイル |

### L3: 社内機密（14テーブル）

| テーブル | org_id型 | RLS |
|---------|---------|-----|
| ceo_teachings | UUID | コメントアウト |
| ceo_teaching_conflicts | UUID | なし |
| guardian_alerts | UUID | なし |
| teaching_usage_logs | UUID | なし |
| goals | UUID | なし |
| goal_progress | UUID | なし |
| brain_ability_scores | VARCHAR | なし |
| brain_limitations | VARCHAR | なし |
| brain_improvement_logs | VARCHAR | なし |
| brain_self_diagnoses | VARCHAR | なし |
| brain_confidence_logs | VARCHAR | なし |
| brain_decision_logs | UUID | あり |
| personalization_risks | UUID | なし |
| feedback_deliveries | UUID | なし |

### L2: 社内一般（59テーブル）

| テーブル | org_id型 | RLS |
|---------|---------|-----|
| documents | UUID | あり(Phase 3) |
| document_chunks | UUID | あり(Phase 3) |
| document_versions | UUID | あり(Phase 3) |
| chatwork_tasks | VARCHAR | なし |
| conversation_summaries | UUID | なし |
| conversation_index | UUID | なし |
| organization_auto_knowledge | UUID | なし |
| scheduled_announcements | VARCHAR | なし |
| announcement_logs | VARCHAR | なし |
| announcement_patterns | VARCHAR | なし |
| question_patterns | UUID | なし |
| response_logs | UUID | なし |
| bottleneck_alerts | UUID | なし |
| notification_logs | UUID | なし |
| goal_reminders | UUID | なし |
| goal_setting_sessions | UUID | なし |
| goal_setting_logs | UUID | なし |
| goal_setting_user_patterns | UUID | なし |
| knowledge_search_logs | UUID | なし |
| knowledge_feedback | UUID | なし |
| proactive_action_logs | UUID | なし |
| proactive_cooldowns | UUID | なし |
| proactive_settings | UUID | なし |
| execution_plans | UUID | なし |
| execution_subtasks | UUID | なし |
| execution_escalations | UUID | なし |
| execution_quality_reports | UUID | なし |
| feedback_settings | UUID | なし |
| feedback_alert_cooldowns | UUID | なし |
| bot_persona_memory | UUID | なし |
| user_long_term_memory | UUID | なし |
| brain_learnings | UUID | あり |
| brain_learning_logs | UUID | あり |
| brain_episodes | UUID | あり |
| brain_episode_entities | UUID | あり |
| brain_knowledge_nodes | UUID | あり |
| brain_knowledge_edges | UUID | あり |
| brain_temporal_events | UUID | あり |
| brain_temporal_comparisons | UUID | あり |
| brain_memory_consolidations | UUID | あり |
| brain_outcome_events | UUID | なし |
| brain_outcome_patterns | UUID | なし |
| brain_conversation_states | UUID | あり |
| brain_state_history | UUID | あり |
| brain_dialogue_logs | UUID | なし |
| soulkun_insights | UUID | なし |
| soulkun_weekly_reports | UUID | なし |
| google_drive_sync_logs | UUID | なし |
| google_drive_sync_state | UUID | なし |
| ai_usage_logs | UUID | なし |
| ai_monthly_cost_summary | UUID | なし |
| ai_organization_settings | UUID | なし |
| audit_logs | VARCHAR | なし |
| organization_admin_configs | UUID | なし |
| organizations | N/A(root) | なし |
| departments | UUID | あり(Phase 3.5) |
| user_departments | UUID | あり(Phase 3.5) |
| roles | UUID/TEXT | あり |
| deep_understanding_logs | UUID | あり |

### L1: 公開/マスター（2テーブル）

| テーブル | org_id | RLS | 備考 |
|---------|--------|-----|------|
| ai_model_registry | なし | 不要 | 全組織共通のモデル定義 |
| goal_setting_patterns | なし | 不要 | 全組織共通の目標設定パターン |

---

## 4. 保持・削除ポリシー

| 分類 | データ種別 | 保持期間 | 削除方法 |
|------|-----------|---------|---------|
| L4 | 感情スコア | 90日 | 物理削除（バッチ） |
| L4 | ユーザー情報 | アカウント存続中 | 退会時物理削除 |
| L3 | CEO教え | 無期限 | 手動削除のみ |
| L3 | 目標・評価 | 年度末+1年 | 論理→物理削除 |
| L2 | タスク | 完了後1年 | 論理削除 |
| L2 | 監査ログ | 1年 | 物理削除 |
| L2 | AI利用ログ | 6ヶ月 | 集計後物理削除 |
| L1 | マスターデータ | 無期限 | 削除なし |

---

## 5. 関連ドキュメント

| ドキュメント | 参照内容 |
|-------------|---------|
| RLS_POLICY_DESIGN.md | RLS実装詳細 |
| CLAUDE.md セクション8-9 | 権限レベル、記憶ルール |
| COMPREHENSIVE_RISK_REMEDIATION_PLAN.md | リスク是正計画 |

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-02-08 | 初版作成（83テーブル分類完了） |
