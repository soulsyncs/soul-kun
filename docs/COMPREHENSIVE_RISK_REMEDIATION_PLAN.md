# 包括的リスク是正計画

**作成日:** 2026-01-30
**目的:** 徹底的なリスク分析で発見された全問題の是正計画と対応状況を追跡

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | 全リスクの是正計画と進捗管理 |
| **書くこと** | リスク一覧、是正計画、対応状況、完了基準 |
| **書かないこと** | 是正の実装詳細（→各設計書・コード） |
| **SoT（この文書が正）** | リスク是正の全体計画と進捗 |
| **Owner** | Tech Lead（連絡先: #dev チャンネル） |
| **更新トリガー** | 是正完了時、新規リスク発見時 |

---

## 1. エグゼクティブサマリー

### 1.1 発見されたリスク総数

| 深刻度 | 件数 | 対応状況 |
|--------|------|---------|
| 🔴 致命的 | 5件 | 1件再評価済、4件は Phase 4前に対応予定 |
| 🟠 高優先度 | 6件 | ✅ 5件対応完了、1件は実装待ち |
| 🟡 中優先度 | 7件 | ✅ 5件対応完了、2件は継続対応 |
| **合計** | **18件** | **11件対応完了** |

### 1.2 対応方針

```
【原則】
1. セキュリティリスクは最優先で対応
2. 設計書の矛盾は実装前に解消
3. 運用手順の欠如は本番障害前に補完
4. テスト戦略は段階的に強化
```

---

## 2. 致命的リスク（🔴）の是正計画

### 2.1 SQLインジェクション脆弱性【再評価: リスク低】

| 項目 | 内容 |
|------|------|
| **発見場所** | api/app/api/v1/knowledge.py 行240, 246 |
| **当初評価** | 致命的 |
| **再評価結果** | **リスク低（リファクタリング推奨）** |

**再評価理由:**
```python
# 実際のコード分析
conditions.append("category = :category")  # パラメータプレースホルダー
params["category"] = category              # 値は辞書経由で渡される

# where_clauseは以下のような文字列になる
# "organization_id = :org_id AND category = :category"
# ユーザー入力は全て:param形式でパラメータ化されている
```

**結論:**
- 現在のコードはSQLインジェクションに対して**安全**
- ただしf-stringでSQL構築はベストプラクティスではない
- SQLAlchemy ORMへのリファクタリングを**推奨**（必須ではない）

**対応:**
- [ ] コードレビュー時にSQLパターンを確認するチェックリスト追加
- [ ] 将来的にSQLAlchemy ORMへ移行検討

---

### 2.2 organization_idフィルタ漏れ（114箇所）【2026-02-08 再監査で大幅拡大】

| 項目 | 内容 |
|------|------|
| **発見場所** | 全サービス、114クエリ |
| **影響** | **現時点でデータ漏洩リスク（Phase 4待ちではない）** |
| **対応期限** | **即時対応（Tier 1セキュリティ緊急）** |
| **ブロッカー** | personsテーブルにorganization_idカラムが**存在しない**（スキーマ変更が先決） |

**影響ファイル（再監査結果）:**
| ファイル | 箇所数 | テーブル |
|---------|--------|---------|
| lib/person_service.py (×2コピー) | 10 | persons, person_attributes, person_events |
| main.py（ルート） | 6 | persons |
| chatwork-webhook/main.py | 5 | chatwork_tasks |
| chatwork-webhook/handlers/task_handler.py | 4 | chatwork_tasks |
| api/app/api/v1/tasks.py | 3 | chatwork_tasks |
| remind-tasks/main.py | 13 | persons, chatwork_tasks |
| sync-chatwork-tasks/main.py | 21 | persons, chatwork_tasks |
| check-reply-messages/main.py | 7+ | persons, chatwork_tasks（サービス全体にorg_id参照ゼロ） |
| cleanup-old-data/main.py | 13+ | persons, chatwork_tasks（サービス全体にorg_id参照ゼロ） |
| lib/brain/memory_access.py | 3 | persons, person_attributes, chatwork_tasks |
| lib/detection/bottleneck_detector.py | 3 | bottleneck関連 |
| pattern-detection/lib/detection/emotion_detector.py | 2 | emotion関連（org_idをuser_idとして誤使用） |

**是正計画:**

| Phase | 内容 | 担当 | 期限 |
|-------|------|------|------|
| 1 | テーブルスキーマ変更（organization_idカラム追加） | DB担当 | Phase 4A-2週間前 |
| 2 | 既存データのorganization_id設定（デフォルト: org_soulsyncs） | DB担当 | Phase 4A-2週間前 |
| 3 | 23箇所のクエリ修正 | 開発担当 | Phase 4A-1週間前 |
| 4 | 組織分離テストケース追加・実行 | QA担当 | Phase 4A開始時 |

**修正パターン:**
```python
# Before
cursor.execute("SELECT value FROM system_config WHERE key = %s", (key,))

# After
cursor.execute("""
    SELECT value FROM system_config
    WHERE key = %s AND organization_id = %s
""", (key, ORGANIZATION_ID))
```

**詳細:** → `SECURITY_AUDIT_ORGANIZATION_ID.md`

---

### 2.3 API認証ミドルウェア未実装

| 項目 | 内容 |
|------|------|
| **発見場所** | api/app/api/v1/knowledge.py |
| **問題** | ヘッダーからユーザーID/テナントIDを直接取得（認証なし） |
| **影響** | ヘッダー偽造でなりすまし可能 |
| **対応期限** | Phase 4開始前（必須） |

**現状のコード:**
```python
# 問題: 認証なしでヘッダーを信頼
async def get_current_user(
    x_user_id: str = Header(...),
    x_tenant_id: str = Header(...),
) -> UserContext:
```

**是正計画:**

| Phase | 内容 | 担当 | 期限 |
|-------|------|------|------|
| 1 | JWT認証ミドルウェア設計 | セキュリティ担当 | 2週間以内 |
| 2 | 認証ミドルウェア実装 | 開発担当 | 4週間以内 |
| 3 | 全エンドポイントへの適用 | 開発担当 | Phase 4A前 |
| 4 | 認証バイパステスト | QA担当 | Phase 4A前 |

**設計要件:**
- JWTトークン検証
- テナントID検証（トークン内のclaim）
- リフレッシュトークン対応
- 認証失敗時の適切なエラーレスポンス（401/403）

---

### 2.4 RLS（Row Level Security）未実装【2026-02-08 再監査で大幅拡大】

| 項目 | 内容 |
|------|------|
| **発見場所** | 全テナントテーブル |
| **問題** | 83テーブル中31のみRLS有効、**52テーブルが無防備** |
| **対応期限** | **即時対応（Tier 1セキュリティ緊急）** |

**是正計画:** → ロードマップ計画 Tier 1-3 に詳細記載

**対象テーブル（52個、4グループ）:**
- Tier 1-A: コアデータ21テーブル（documents, goals, user_preferences等）
- Tier 1-B: 機能テーブル16テーブル（emotion_scores, proactive_action_logs等）
- Tier 1-C: ログ・分析8テーブル（ai_usage_logs, audit_logs等）
- Tier 1-D: persons関連3テーブル（スキーマ変更後）
- ceo_teachings関連4テーブル（Tier 3で対応）
- マスター2テーブルはRLS不要（ai_model_registry, goal_setting_patterns）

**実装手順:**
1. テスト環境でRLSポリシー検証
2. FORCE ROW LEVEL SECURITYを全テーブルに適用
3. 本番環境で段階的有効化（テーブルごと）
4. テナント分離テスト実行

---

### 2.5 LLM Brain層の設計vs実装乖離 ✅ **是正完了（2026-01-31）**

| 項目 | 内容 |
|------|------|
| **発見場所** | proactive-monitor/lib/brain/ |
| **当初問題** | 設計は「LLM常駐型」、実装は「キーワードマッチ+フォールバック」 |
| **当初実装度** | 15% |
| **現在実装度** | **100%（コア層）** |
| **対応状況** | ✅ **LLMBrain実装完了、USE_BRAIN_ARCHITECTURE=true で本番稼働中** |

**是正完了内容:**
- LLMBrainクラス: `lib/brain/llm_brain.py`（1,249行）✅
- Claude API連携（Function Calling形式）: `lib/brain/tool_converter.py` ✅
- Context Builder: `lib/brain/context_builder.py`（686行）✅
- Chain-of-Thought: System Promptで強制 ✅
- Guardian Layer: `lib/brain/guardian_layer.py`（522行）✅

**残課題（低優先度）:**
- Observability DB永続化: 60%（Cloud Loggingのみ、DB未実装）
- Tool Executor分離: 70%（BrainExecutionで代用中）

**詳細:** → `DESIGN_IMPLEMENTATION_GAP_REPORT.md`

---

## 3. 高優先度リスク（🟠）の是正計画

### 3.1 CLAUDE.mdと25章の権限定義矛盾 ✅ 対応完了

| 項目 | 内容 |
|------|------|
| **問題** | CLAUDE.md: 脳が「判断」/ 25章: 脳は「提案」、Guardianが「判断」 |
| **対応** | CLAUDE.mdにセクション2-3「3層判断アーキテクチャ」追加 |
| **対応状況** | ✅ **完了**（2026-01-30） |

### 3.2 Context Builder層未実装 ✅ **是正完了（2026-01-31）**

| 項目 | 内容 |
|------|------|
| **当初実装度** | 30% |
| **現在実装度** | **100%** |
| **対応状況** | ✅ **完了** - `lib/brain/context_builder.py`（686行）、LLMContext実装済み、Truth順位の厳密適用済み |

### 3.3 外部サービス障害対応の欠如 ✅ 対応完了

| サービス | 対応状況 | 対応内容 |
|---------|---------|---------|
| Google Drive API | ✅ 対応済 | OPERATIONS_RUNBOOK セクション12.1追加 |
| Pinecone | ✅ 対応済 | OPERATIONS_RUNBOOK セクション12.2追加 |
| DNS | ✅ 対応済 | OPERATIONS_RUNBOOK セクション12.3追加 |

### 3.4 マイグレーション失敗対応の欠如 ✅ 対応完了

| 項目 | 内容 |
|------|------|
| **問題** | DBスキーマ変更時のロールバック手順がない |
| **対応** | OPERATIONS_RUNBOOK セクション14追加 |
| **対応状況** | ✅ **完了**（2026-01-30） |

### 3.5 テストカバレッジ計測なし ✅ 対応完了

| 項目 | 内容 |
|------|------|
| **問題** | 80%基準が検証されていない |
| **対応** | `.github/workflows/test-coverage.yml` 追加 |
| **対応状況** | ✅ **完了**（2026-01-30）|

---

## 4. 中優先度リスク（🟡）の是正計画

| # | リスク | 対応内容 | 状況 |
|---|--------|---------|------|
| 1 | ~~DDoS攻撃対応なし~~ | OPERATIONS_RUNBOOK セクション15追加 | ✅ 完了 |
| 2 | ~~バックアップ復旧テストなし~~ | DISASTER_DRILL_PLAN DR-007追加 | ✅ 完了 |
| 3 | E2Eテストシナリオ不足 | テストケース追加 | ⏳ 継続対応 |
| 4 | パフォーマンステスト実装なし | テスト実装 | ⏳ 継続対応 |
| 5 | ~~コスト上限テスト未定義~~ | 09章 11.8（仕様）+ test-coverage.yml（基盤）追加 | ✅ 仕様定義完了（実装はPhase 4） |
| 6 | ~~Phase番号の混乱~~ | DESIGN_COVERAGE_MATRIXで整理済み | ✅ 完了 |
| 7 | ~~09章のSoT矛盾~~ | Document Contract追加で解消 | ✅ 完了 |

---

## 5. 是正完了チェックリスト

### Tier 1セキュリティ緊急（即時対応）

- [ ] organization_idフィルタ114箇所修正（personsスキーマ変更含む）
- [ ] RLSポリシー52テーブル拡大
- [ ] API認証ミドルウェア(JWT)実装
- [ ] Cloud Run認証統一（11サービス→認証必須化）
- [ ] ILIKEパターンインジェクション修正（12+ファイル）
- [ ] Supabase ANON key Secret Manager移行
- [ ] 組織分離テスト完了

### 是正完了

- [x] LLM Brain層の常駐化 ✅ **2026-01-31完了**（100%、本番稼働中）
- [x] Context Builder層実装 ✅ **2026-01-31完了**（100%）
- [x] 外部サービス障害対応手順追加 ✅ **2026-01-30完了**
- [x] テストカバレッジCI/CD追加 ✅ **2026-01-30完了**

### 継続的改善

- [ ] E2Eテストシナリオ拡充
- [ ] パフォーマンステスト自動化
- [x] コスト監視・アラート設定 ✅ **2026-01-30仕様定義完了**（09章 11.8 + CI/CD基盤、実装はPhase 4）

---

## 6. 関連ドキュメント

| ドキュメント | 参照内容 |
|-------------|---------|
| SECURITY_AUDIT_ORGANIZATION_ID.md | organization_id監査詳細 |
| RLS_POLICY_DESIGN.md | RLSポリシー設計 |
| DESIGN_IMPLEMENTATION_GAP_REPORT.md | 設計vs実装の乖離詳細 |
| OPERATIONS_RUNBOOK.md | 運用手順 |
| DISASTER_DRILL_PLAN.md | 障害訓練計画 |

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-01-30 | 初版作成（18件のリスク是正計画策定） |
| 2026-01-30 | 是正完了: CLAUDE.md/25章矛盾解消、外部サービス障害対応、マイグレーション失敗対応、テストカバレッジCI/CD、コスト上限テスト、DDoS対応、バックアップ復旧テスト（計11件完了） |
| **2026-02-08** | **全面再監査: org_id漏れ23→114箇所、RLS 8→52テーブル要対応、LLM Brain 15%→100%是正完了、Context Builder 30%→100%是正完了、ILIKEインジェクション脆弱性追加** |

---

**このファイルについての質問は、Tech Leadに連絡してください。**
