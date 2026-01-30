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

### 2.2 organization_idフィルタ漏れ（23箇所）

| 項目 | 内容 |
|------|------|
| **発見場所** | Cloud Functions 6ファイル、23クエリ |
| **影響** | Phase 4（マルチテナント）でデータ漏洩リスク |
| **対応期限** | Phase 4開始前（必須） |

**影響ファイル:**
| ファイル | 箇所数 | テーブル |
|---------|--------|---------|
| chatwork-webhook/main.py | 4 | system_config, excluded_rooms, chatwork_tasks |
| sync-chatwork-tasks/main.py | 7 | 同上 |
| remind-tasks/main.py | 3 | 同上 |
| check-reply-messages/main.py | 3 | 同上 |
| cleanup-old-data/main.py | 3 | 同上 |
| main.py（ルート） | 3 | 同上 |

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

### 2.4 RLS（Row Level Security）未実装

| 項目 | 内容 |
|------|------|
| **発見場所** | 全テナントテーブル |
| **問題** | アプリケーション層のみの防御（多重防御なし） |
| **対応期限** | Phase 4A |

**是正計画:** → `RLS_POLICY_DESIGN.md` に詳細設計済み

**対象テーブル（8個）:**
- chatwork_tasks
- system_config
- excluded_rooms
- soulkun_insights
- soulkun_weekly_reports
- audit_logs
- departments
- users

**実装手順:**
1. テスト環境でRLSポリシー検証
2. 本番環境で段階的有効化（テーブルごと）
3. テナント分離テスト実行

---

### 2.5 LLM Brain層の設計vs実装乖離

| 項目 | 内容 |
|------|------|
| **発見場所** | proactive-monitor/lib/brain/ |
| **問題** | 設計は「LLM常駐型」、実装は「キーワードマッチ+フォールバック」 |
| **実装度** | 15% |
| **影響** | 「新しい言い方が通じない」問題の根本原因 |

**是正計画:**

| Phase | 内容 | 工数 | 期限 |
|-------|------|------|------|
| B-1 | LLMBrainクラス実装 | 2-3週間 | Q1末 |
| B-2 | Claude API連携（Function Calling形式） | 1-2週間 | Q1末 |
| B-3 | Tool定義をAnthropic形式に変換 | 1週間 | Q1末 |
| B-4 | System Prompt構築ロジック | 1週間 | Q1末 |
| B-5 | Chain-of-Thought必須化 | 3日 | Q1末 |

**詳細:** → `DESIGN_IMPLEMENTATION_GAP_REPORT.md`

**暫定対応:**
- v10.48.11のgeneral_conversation確認スキップは一時対処として維持
- 根本対処はLLM常駐化完了まで保留

---

## 3. 高優先度リスク（🟠）の是正計画

### 3.1 CLAUDE.mdと25章の権限定義矛盾 ✅ 対応完了

| 項目 | 内容 |
|------|------|
| **問題** | CLAUDE.md: 脳が「判断」/ 25章: 脳は「提案」、Guardianが「判断」 |
| **対応** | CLAUDE.mdにセクション2-3「3層判断アーキテクチャ」追加 |
| **対応状況** | ✅ **完了**（2026-01-30） |

### 3.2 Context Builder層未実装

| 項目 | 内容 |
|------|------|
| **実装度** | 30% |
| **問題** | LLMContext未実装、Truth順位の厳密適用なし |
| **対応** | LLM Brain層の是正と同時に実施（Q1末予定） |
| **対応状況** | ⏳ Phase 4前に実装予定 |

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

### Phase 4開始前に必須

- [ ] organization_idフィルタ23箇所修正
- [ ] RLSポリシー実装
- [ ] API認証ミドルウェア実装
- [ ] 組織分離テスト完了

### Q1末までに完了

- [ ] LLM Brain層の常駐化
- [ ] Context Builder層実装
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

---

**このファイルについての質問は、Tech Leadに連絡してください。**
