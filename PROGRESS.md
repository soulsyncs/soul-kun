# PROGRESS.md - ソウルくんプロジェクト進捗記録

**最終更新: 2026-01-30 01:30 JST**

> このファイルは作業履歴・進捗状況を記録するためのファイルです。
> 開発ルールやアーキテクチャについては `CLAUDE.md` を参照してください。

---

## 📋 目次

1. [次回やること](#-次回やること)
2. [Phase一覧と状態](#phase一覧と状態)
3. [本番環境インフラ状態](#本番環境インフラ状態)
4. [直近の主な成果](#直近の主な成果)
5. [関連リポジトリ](#関連リポジトリ)

---

## 🚨 次回やること

### 🔥 最優先タスク（2026-01-29時点）

**main.py 分割の続き（Phase 9以降）** ← 次はここから
- 現在: 7,355行（900行削減済み、10.9%削減）
- 目標: 1,500行以下（あと5,855行削減が必要）
- 次の候補: 大きな関数の別モジュール抽出
  - chatwork_webhook (481行) → lib/webhook_core.py
  - check_reply_messages (345行) → lib/reply_checker.py
  - get_ai_response (315行) → lib/ai_response.py
  - handle_chatwork_task_create (200行) → handlers/task_handler.py へ完全移行

**脳の改善を本番有効化**
- Feature Flagsを段階的に有効化
- モニタリング指標の監視

---

### ✅ 完了したタスク（2026-01-29 夕方）

**脳設計改善: Truth順位実装 & P1意図理解強化** ✅ 全Phase完了

CLAUDE.mdの設計原則（セクション3: データソース優先順位）をコードレベルで強制する仕組みと、
「これ」「あれ」「田中さん」「いつもの」等の曖昧表現の解決機能を実装。

| Phase | 内容 | テスト数 | 新規ファイル |
|-------|------|---------|------------|
| Phase 1 | TruthSource Enum + Feature Flags | 29 | constants.py (拡張) |
| Phase 2 | TruthResolver クラス | 30 | lib/brain/truth_resolver.py |
| Phase 3 | EnhancedPronounResolver | 40 | lib/brain/deep_understanding/pronoun_resolver.py |
| Phase 4 | PersonAliasResolver | 44 | lib/brain/deep_understanding/person_alias.py |
| Phase 5 | ContextExpressionResolver | 41 | lib/brain/deep_understanding/context_expression.py |
| Phase 6 | IntentInferenceEngine統合 | 16 | intent_inference.py (拡張) |
| **合計** | | **200** | |

**主要機能:**

1. **Truth順位（TruthSource）**: データソース優先順位を明示
   - 1位: リアルタイムAPI（ChatWork API等）
   - 2位: DB（正規データ）
   - 3位: 設計書・仕様書
   - 4位: Memory（会話の文脈）
   - 5位: 推測 → **禁止（GuessNotAllowedError）**

2. **EnhancedPronounResolver**: 代名詞解決（コ・ソ・ア系）
   - 「これ」→ 近称（直前の発話、現在のタスク）
   - 「それ」→ 中称（相手の発話、共有コンテキスト）
   - 「あれ」→ 遠称（過去の会話、以前のタスク）
   - 確信度 < 0.7 で確認モード自動発動

3. **PersonAliasResolver**: 人名エイリアス解決
   - 敬称除去: 「田中さん」→「田中」
   - エイリアス生成: 「田中」→「田中さん」「田中くん」
   - 複数候補時は確認モード発動

4. **ContextExpressionResolver**: 文脈依存表現解決
   - 習慣的表現: 「いつもの」→ ユーザーの習慣
   - 参照表現: 「あの件」→ 最近の話題
   - 時間参照: 「この前の」→ 過去のイベント

**Feature Flags（段階的有効化用）:**
```python
FEATURE_FLAG_TRUTH_RESOLVER = "truth_resolver_enabled"       # Phase 2
FEATURE_FLAG_ENHANCED_PRONOUN = "enhanced_pronoun_resolver"  # Phase 3
FEATURE_FLAG_PERSON_ALIAS = "person_alias_resolver"          # Phase 4
FEATURE_FLAG_CONTEXT_EXPRESSION = "context_expression_resolver"  # Phase 5
```

**次のステップ:**
1. 開発環境でFeature Flagsを有効化してテスト
2. 本番環境でshadowモード（ログのみ）で検証
3. 本番環境で段階的に有効化（10% → 50% → 100%）

---

### ✅ main.py分割 Phase 8 完了（2026-01-30 02:00）

**未使用delegate関数・API関数の削除**

徹底的なgrep分析により、定義のみで呼び出しがない未使用関数を特定し削除。

| 削除した関数 | 行数 | 削除理由 |
|------------|------|---------|
| `get_or_create_person()` | 4行 | 未使用delegate（lib/person_service.py使用） |
| `get_oldest_pending_proposal()` | 8行 | 未使用delegate（handler直接使用） |
| `get_proposal_by_id()` | 8行 | 未使用delegate（handler直接使用） |
| `get_latest_pending_proposal()` | 8行 | 未使用delegate（handler直接使用） |
| `approve_proposal()` | 8行 | 未使用delegate（handler直接使用） |
| `reject_proposal()` | 8行 | 未使用delegate（handler直接使用） |
| `get_overdue_days()` | 10行 | 未使用delegate（utils/date_utils.py使用） |
| `_new_get_overdue_days` import | 1行 | 上記削除に伴い不要化 |
| `call_openrouter_api()` | 54行 | 未使用API関数（他のOpenRouter呼び出しは別経路） |
| `handle_general_chat()` | 6行 | 未使用ハンドラー（Noneを返すだけ） |

**行数変化:** 7,475行 → 7,355行 (-120行)
**総削減:** 8,255行 → 7,355行 (-900行、10.9%削減)

---

### ✅ main.py分割 Phase 7 完了（2026-01-30 01:30）

**未使用コード削除とインポート整理**

徹底的なコード分析により、未使用の関数・変数・インポートを特定し削除。

| 削除した項目 | 行数 | 削除理由 |
|------------|------|---------|
| `_get_brain()` 関数 | ~70行 | BrainIntegration経由に完全移行済み |
| `_brain_instance` 変数 | 1行 | `_get_brain()`と共に不要化 |
| 重複 `import os` | 1行 | line 7で既にインポート済み |
| 重複 `import re` | 1行 | line 5で既にインポート済み |
| `USE_NEW_DATE_UTILS` フラグ | 1行 | フォールバック削除済みで不要 |
| `USE_NEW_CHATWORK_UTILS` フラグ | 1行 | フォールバック削除済みで不要 |
| `BOT_ACCOUNT_ID` 定数 | 1行 | MY_ACCOUNT_IDと同一で未使用 |

**分析結果:**
- 100行以上の大関数: 13個（合計2,742行、36.3%）
- コード行: 3,334行（44.2%）
- 非コード行（コメント/docstring/空行）: 4,211行（55.8%）

**行数変化:** 7,545行 → 7,475行 (-70行)
**総削減:** 8,255行 → 7,475行 (-780行、9.4%削減)

---

### ✅ main.py分割 Phase 6 完了（2026-01-30 00:45）

**デッドコード削除とハンドラー簡略化**

未使用の関数・変数を削除し、残りの`if handler:`パターンを簡略化。

| 削除した関数/変数 | 削除理由 |
|-----------------|---------|
| `notify_dm_not_available()` | 呼び出し箇所なし（バッファ追加関数） |
| `get_chatwork_headers()` | 直接ヘッダー構築に置き換え済み |
| `HEADERS` 変数 | 未使用 |

**HANDLERSのlambda簡略化:**
- `handle_announcement_request` - `if handler:`チェック削除

**行数変化:** 7,572行 → 7,545行 (-27行)
**総削減:** 8,255行 → 7,545行 (-710行、8.6%削減)

---

### ✅ main.py分割 Phase 5 完了（2026-01-30 00:15）

**ストレージ層の重複コード削除**

handlers/knowledge_handler.py と main.py の重複コードを削除し、
ハンドラー委譲に統一。v10.33.1でハンドラー必須化を完了。

| 削除した関数/定数 | 削除理由 |
|-----------------|---------|
| `ensure_knowledge_tables()` | handlers/knowledge_handler.py に移行済み |
| `save_knowledge()` | 未使用（handler.handle_learn_knowledge使用） |
| `delete_knowledge()` | ハンドラー委譲に変更 |
| `get_all_knowledge()` | ハンドラー委譲に変更 |
| `get_knowledge_for_prompt()` | ハンドラー委譲に変更 |
| `KNOWLEDGE_LIMIT`, `KNOWLEDGE_VALUE_MAX_LENGTH` | ハンドラーに定義済み |

**追加で簡略化した`if handler:`チェック:**
- `handle_proposal_decision` - 4行削除
- `handle_proposal_by_id` - 4行削除
- `handle_local_learn_knowledge` - 4行削除
- `report_proposal_to_admin` - 4行削除
- `handle_query_company_knowledge` - 4行削除
- `handle_list_knowledge`内 - 3行削減
- `_brain_continue_announcement`内 - 5行削減
- `_brain_handle_announcement_create`内 - 3行削減
- `get_context`内アナウンスチェック - 2行削減

**行数変化:** 7,770行 → 7,572行 (-198行)
**総削減:** 8,255行 → 7,572行 (-683行、8.3%削減)

---

### ✅ main.py分割 Phase 4 完了（2026-01-29 23:30）

**ハンドラーラッパー簡素化**

`v10.32.0: ハンドラー必須化`によりハンドラーは常に利用可能なため、
`if handler:`チェックとエラーハンドリングを削除。

| ハンドラー | 関数数 |
|-----------|--------|
| ProposalHandler | 9関数 |
| TaskHandler | 6関数 |
| GoalHandler | 5関数 |
| MemoryHandler | 3関数 |
| KnowledgeHandler | 2関数 |
| OverdueHandler | 3関数 |
| **合計** | **28関数** |

**行数変化:** 8,006行 → 7,770行 (-236行)

---

### ✅ main.py分割 Phase 3 完了（2026-01-29 22:30）

**デッドコード削除: USE_NEW_*フラグのフォールバック除去**

`USE_NEW_DATE_UTILS = True`と`USE_NEW_CHATWORK_UTILS = True`は常にTrueのため、
フォールバックコード（旧実装）は実行されないデッドコード。これを削除して簡素化。

| 関数 | 削除行数 | 変更内容 |
|------|---------|---------|
| `APICallCounter`クラス | ~20行 | 直接エクスポートに変更 |
| `get_api_call_counter` | ~5行 | 直接呼び出し |
| `reset_api_call_counter` | ~5行 | 直接呼び出し |
| `clear_room_members_cache` | ~4行 | 直接呼び出し |
| `call_chatwork_api_with_retry` | ~50行 | 直接呼び出し |
| `get_room_members_cached` | ~8行 | 直接呼び出し |
| `get_room_members` | ~14行 | 直接呼び出し |
| `is_room_member` | ~5行 | 直接呼び出し |
| `parse_date_from_text` | ~70行 | 直接呼び出し |
| `check_deadline_proximity` | ~27行 | 直接呼び出し |
| `get_overdue_days` | ~22行 | 直接呼び出し |
| **合計** | **~249行** | |

**テスト結果:** chatwork_utils: 23件、date_utils: 23件 → 計46件全テスト合格

**Git統計:** 276行削除、27行追加 → 実質249行削減

---

### ✅ 設計書参照の整備（2026-01-29 21:00）

**コード品質改善: 設計書参照の正確化**

新規実装ファイルのdocstringに記載されている設計書参照を、より正確で詳細なものに修正。
これにより、コードを読む開発者が設計意図を正確に把握できるようになった。

| ファイル | 修正内容 |
|---------|---------|
| `lib/brain/truth_resolver.py` | CLAUDE.md セクション3との対応を明確化 |
| `lib/brain/deep_understanding/pronoun_resolver.py` | docs/13 セクション6, docs/17 Phase 2I, CLAUDE.md セクション4 を明記 |
| `lib/brain/deep_understanding/person_alias.py` | 同上 |
| `lib/brain/deep_understanding/context_expression.py` | 同上 |
| `lib/brain/constants.py` | 各定数がどの設計書セクションに基づくか明記 |

**設計書参照の形式（標準化）:**
```python
【設計書参照】
- docs/13_brain_architecture.md セクション6「理解層」
  - 6.4 曖昧表現の解決パターン
- docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I「理解力強化」
  - 暗黙の意図推測
- CLAUDE.md セクション4「意図の取り違え検知ルール」
  - 確信度70%未満で確認質問
```

**テスト結果:** 184件全テスト合格（2.52秒）

---

### ✅ 完了したタスク（2026-01-29）

**1. システムプロンプト v2.1 本番反映** ✅
- 第11章（機能実行の鉄則）追加
- 第12章（未実装機能への対応）追加
- Feature Flag: ENABLE_SYSTEM_PROMPT_V2=true
- リビジョン: chatwork-webhook-00284-hih

**2. main.py 分割 Phase 1-2** ✅
- utils/chatwork_utils.py 拡張（メッセージ処理関数追加）
- lib/person_service.py 新規作成（人物情報・組織図）
- 8,570行 → 8,255行（315行削減）
- リビジョン: chatwork-webhook-00285-fim

**3. 脳の学習ループ完成（P0）** ✅
- brain_decision_logs テーブル自動作成実装
- 判断ログのDB保存（単一・バッチ）実装
- 低確信度パターン検出実装
- アクション成功率分析実装
- リビジョン: chatwork-webhook-00286-yih

---

**Proactive Monitor 本番有効化** ✅ 完了

| 項目 | 内容 |
|------|------|
| 変更 | `PROACTIVE_DRY_RUN=true` → `PROACTIVE_DRY_RUN=false` |
| リビジョン | proactive-monitor-00021-xev |
| 検証結果 | 53ユーザーチェック、トリガー0件、エラーなし |
| 効果 | ソウルくんが自分から声をかける能力が本番で有効に |

**トリガー条件（本番有効）:**
1. 目標放置: 7日間更新なし → 「目標の進捗、どうですかウル？」
2. タスク山積み: 5件以上遅延 → 「タスクが溜まってるみたいですねウル」
3. 感情変化: ネガティブ継続3日 → 「最近調子どうですかウル？」
4. 目標達成: 直近24時間 → 「おめでとうございますウル！🎉」
5. タスク連続完了: 24時間で3件以上 → 「すごい調子ですウル！」
6. 長期不在: 14日以上 → 「お久しぶりですウル！」

---

**脳アーキテクチャ シンプル化 Phase 1 + Phase 2 完了** ✅

### Phase 1: core.py分割（完了）

| ステップ | 内容 | 削減行数 |
|---------|------|---------|
| Step 1 | memory_manager統合 + 旧コード削除 | -214行 |
| Step 2 | session_orchestrator統合 + 旧コード削除 | -832行 |
| Step 3 | authorization_gate統合 + 旧コード削除 | -201行 |
| **合計** | **53%削減** | **-1,247行** |

**結果:**
- core.py: 2,344行 → **1,097行**
- 本番デプロイ: リビジョン `chatwork-webhook-00283-lac`
- 動作確認: ✅ 正常

### Phase 2: ハンドラー登録の整理（完了）

| 変更 | 内容 |
|------|------|
| 新規作成 | `handlers/registry.py` (1,376行) |
| main.py削減 | 9,774行 → **8,517行** (-1,257行) |
| 命名統一 | `HANDLER_ALIASES`で旧名→新名マッピング |

**目標達成:**
「新機能追加 = 1ファイル追加するだけ」に向けて:
1. `handlers/xxx_handler.py` を作成
2. `handlers/registry.py` のSYSTEM_CAPABILITIESに追加
3. main.pyのHANDLERSに登録（エイリアス自動追加）

**新しいアーキテクチャ:**
```
chatwork-webhook/
├── handlers/
│   ├── registry.py (1,376行) - 機能カタログ一元管理
│   ├── task_handler.py
│   ├── goal_handler.py
│   └── ...
└── main.py (8,517行) - HANDLERS + 処理フロー
```

---

### 2026-01-29 12:32の成果

**Proactive Monitor 本番有効化:** ✅ 完了
> ソウルくんが「自分から声をかける」能力を本番有効化した。
>
> **変更内容:**
> - `PROACTIVE_DRY_RUN=true` → `PROACTIVE_DRY_RUN=false`
> - Cloud Function: proactive-monitor-00021-xev
> - Cloud Scheduler: 毎時30分実行（Asia/Tokyo）
>
> **検証結果:**
> - 53ユーザーチェック完了
> - トリガー検出: 0件（該当条件のユーザーなし）
> - エラー: なし
>
> **安全機構:**
> - クールダウン: 同じトリガーで連続送信防止（24時間〜7日）
> - 時間帯制限: LOW優先度は9-18時のみ
> - 送信先チェック: dm_room_id未設定はスキップ
>
> **ロールバック:**
> ```bash
> gcloud functions deploy proactive-monitor \
>   --region=asia-northeast1 \
>   --source=proactive-monitor \
>   --update-env-vars PROACTIVE_DRY_RUN=true
> ```

---

### 2026-01-30未明の成果

**脳アーキテクチャ シンプル化 全ステップ完了:** ✅
> core.pyを53%削減（2,344行 → 1,097行）し、責務を4ファイルに分離。
>
> **新しいアーキテクチャ:**
> ```
> lib/brain/
> ├── core.py (1,097行) - 脳のコアフロー（理解→判断→実行）
> ├── session_orchestrator.py (780行) - セッション管理
> ├── authorization_gate.py (518行) - 権限評価統括
> └── memory_manager.py (282行) - 記憶・学習・CEO教え
> ```
>
> **実施内容:**
> 1. memory_manager統合: 6メソッドを委譲、旧コード削除 (-214行)
> 2. session_orchestrator統合: 9メソッドを委譲、旧コード削除 (-832行)
> 3. authorization_gate統合: _execute簡素化、旧コード削除 (-201行)
> 4. 各ステップで本番動作確認 → 問題なし
>
> **デプロイ履歴:**
> - 00281: memory_manager統合（初回）
> - 00282: memory_manager旧コード削除
> - 00283: 全統合完了（最終）
>
> **効果:**
> - 可読性向上: 各ファイル500-1100行
> - 保守性向上: 責務が明確に分離
> - 拡張性向上: 新機能追加時の影響範囲が局所化

---

### 2026-01-29夜の成果

**脳アーキテクチャのシンプル化 Phase 1:** ✅ 新ファイル作成完了
> core.py（2,332行）を分割するための新しいファイルを3つ作成。
>
> **発見された事実:**
> - ハンドラー登録は設計どおり機能していた（connection_queryはCapabilityBridge経由で正しく登録済み）
> - 真の問題は**core.pyの肥大化**（2,332行）
> - セッション管理が39%（約900行）を占めていた
>
> **作成したファイル:**
> - `lib/brain/session_orchestrator.py`: セッション管理（目標設定、アナウンス、確認応答、タスク保留）
> - `lib/brain/authorization_gate.py`: 権限評価（Guardian, ValueAuthority, MemoryAuthority）
> - `lib/brain/memory_manager.py`: 記憶・学習・CEO教え管理
>
> **期待される効果（全統合完了後）:**
> - core.py: 2,332行 → 約300行
> - 各ファイルが500行以下で可読性向上
> - 「機能追加 = 1ファイル追加するだけ」の設計原則に準拠

---

### 2026-01-29の成果

**CLAUDE.md v1.1.0 + 設計憲法更新:** ✅ PR #328 マージ完了
> 意図の取り違えを防ぐためのルールを追加。
> - **Truth順位（データソース優先順位）**: API > DB > Docs > Memory > 推測（禁止）
> - **意図取り違え検知ルール**: 確認質問が必要な6条件を明文化
> - **6段階権限レベル**: 組織図システムに合わせた正確な定義
> - **権限判定の責務分離**: Brain（やっていいか）vs AccessControl（見せていいか）
> - **Memory/監査ログの区別**: 覚えるもの・覚えないものを明確化
> - ChatGPTのレビューを参考にフィードバック反映

**Connection Query修正（v10.44.3）:** ✅ マージ＆デプロイ完了
> 「DMできる相手は誰？」が動かなかった問題を修正。
> - 原因: connection_queryがSYSTEM_CAPABILITIESに未登録だった
> - 修正: SYSTEM_CAPABILITIESに追加（ハンドラーはCapabilityBridge経由）
> - PR #320: マージ完了
> - 設計原則「カタログ追加のみで対応」に準拠

**設計見直しの議論:** CLAUDE.md完成、次フェーズへ
> - 2つのハンドラー方式（main.py直接 vs CapabilityBridge）が混在している問題を発見
> - CLAUDE.md v1.1.0が完成したので、次はアーキテクチャのシンプル化に着手可能

---

### 今どこにいるのか？（素人向け説明）

**完了したこと（Phase A）:** ✅ 2026-01-26 完了
> 「カズさんのID」「管理部のチャットルームID」が10個以上のファイルにハードコードされていた。
> これを「データベースから取得する」方式に変えた。これで将来、別の会社でソウルくんを使う時も対応できる。
> chatwork-webhookが本番でDBから設定を取得していることを確認済み。

**完了したこと（Phase C）:** ✅ 2026-01-26 完了
> 15個のFeature Flagが色々なファイルに散らばっていて、どの機能がON/OFFか把握しづらかった。
> これを「1つの設定ファイル（lib/feature_flags.py）」で管理できるようにした。
> 92件のテストで品質を担保。6つのCloud Functionsにコピー済み。

**完了したこと（Phase D）:** ✅ 2026-01-27 完了
> 8ファイルに同じDB接続文字列（INSTANCE_CONNECTION_NAME, DB_NAME, DB_USER）がハードコードされていた。
> これを「lib/db.py + lib/config.py」で一元管理できるようにした。
> USE_LIB_DBフラグによるフォールバック設計で安全にロールバック可能。
> PR #202 マージ後、本番デプロイで完了。

**完了したこと（脳アーキテクチャ本番有効化）:** ✅ 2026-01-27 06:45 JST 完了
> ソウルくんに「脳」を追加し、**本番有効化**した。
> これまでは各機能がバラバラに動いていたが、脳が全てのメッセージを受け取り、判断して、適切な機能を呼び出すようになった。
> `USE_BRAIN_ARCHITECTURE=true`で本番稼働中。
> フォールバック機構（`BRAIN_FALLBACK_ENABLED=true`）により、脳がエラーを起こしても旧コードが自動実行される。
> revision 00195-zot でデプロイ完了。

**完了したこと（Phase 2D CEO Learning）:** ✅ 2026-01-27 完了
> CEOの日常会話から「教え」を自動抽出し、スタッフへのアドバイスに活用する機能を実装した。
> - DBマイグレーション完了（4テーブル、21制約、27インデックス）
> - コード実装完了（ceo_learning.py, ceo_teaching_repository.py, guardian.py）
> - 脳統合完了（core.pyに統合済み）
> - テスト56件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase 2E Learning Foundation）:** ✅ 2026-01-27 完了
> フィードバックから学習する仕組みを構築した。
> - 12ファイル実装完了（lib/brain/learning_foundation/）
> - 学習抽出、権限管理、矛盾検出、効果追跡など
> - テスト119件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase 2F Outcome Learning）:** ✅ 2026-01-27 完了
> 暗黙のフィードバックから学ぶ仕組みを構築した。
> - 8ファイル実装完了（lib/brain/outcome_learning/）
> - 結果追跡、暗黙FB検出、パターン抽出、分析機能
> - テスト32件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase 2G Memory Enhancement）:** ✅ 2026-01-27 完了
> エピソード記憶と知識グラフの基盤を構築した。
> - 5ファイル実装完了（lib/brain/memory_enhancement/）
> - エピソード記憶の保存・想起、知識グラフの構築
> - 7テーブルのDBマイグレーション
> - テスト38件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase 2H Self-Awareness）:** ✅ 2026-01-27 完了
> ソウルくんに「自己認識」能力を追加した。自分の得意・不得意を把握し、確信度を評価できる。
> - 3ファイル実装完了（lib/brain/self_awareness/）
> - 能力スコア追跡（14カテゴリ）
> - 限界認識・記録（10タイプ）
> - 確信度評価（HIGH/MEDIUM/LOW/VERY_LOW）
> - 自己診断機能（日次/週次/月次）
> - 5テーブルのDBマイグレーション
> - テスト41件全パス
> - chatwork-webhookに同期済み

**完了したこと（Model Orchestrator）:** ✅ 2026-01-27 完了
> 全AI呼び出しを統括するModel Orchestratorを実装した。
> - 8ファイル実装完了（lib/brain/model_orchestrator/）
> - 3ティア制（Economy/Standard/Premium）
> - タスク→ティア自動マッピング、キーワード調整
> - 4段階コスト閾値（自動実行/報告/確認/代替案）
> - フォールバックチェーン（障害時自動切替）
> - テスト43件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase M1 Multimodal入力）:** ✅ 2026-01-27 完了
> ソウルくんに「目」を追加した。画像・PDF・URLを理解できるようになった。
> - 12ファイル実装完了（lib/capabilities/multimodal/）
> - 画像処理（Vision API連携、メタデータ抽出、エンティティ抽出）
> - PDF処理（テキスト抽出、OCR対応、ページ分析）
> - URL処理（Webスクレイピング、コンテンツ分析、セキュリティチェック）
> - 脳統合（MultimodalBrainContext）
> - DBマイグレーション（2テーブル）
> - テスト80件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase M2 音声入力）:** ✅ 2026-01-27 完了
> ソウルくんに「耳」を追加した。音声ファイルを聞いて文字起こし・話者分離・要約ができるようになった。
> - 6ファイル変更完了（lib/capabilities/multimodal/）
> - 音声処理（Whisper API連携、文字起こし、話者分離）
> - 要約・キーポイント・アクションアイテム自動抽出
> - 9フォーマット対応（mp3, wav, m4a, webm, mp4, mpeg, mpga, ogg, flac）
> - 最大2時間、25MBまでの音声対応
> - テスト63件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase F1 CEOフィードバック）:** ✅ 2026-01-27 完了
> ソウルくんに「内省」能力を追加した。事実に基づいてCEOにフィードバックを提供できるようになった。
> - 8ファイル実装完了（lib/capabilities/feedback/）
> - FactCollector: タスク・目標・コミュニケーション・チームデータを収集
> - Analyzer: 異常検知・トレンド分析・ポジティブ発見
> - FeedbackGenerator: LLMを使ったフィードバック文章生成
> - FeedbackDelivery: ChatWork配信（クールダウン・日次制限付き）
> - CEOFeedbackEngine: 全コンポーネント統合、5種類のフィードバック対応
> - DBマイグレーション（3テーブル、1ビュー）
> - テスト57件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase 2I 理解力強化）:** ✅ 2026-01-27 完了
> ソウルくんの「理解力」を大幅に強化した。暗黙の意図、組織文脈、感情・ニュアンスを読み取れるようになった。
> - 8ファイル実装完了（lib/brain/deep_understanding/）
> - IntentInferenceEngine: 暗黙の意図推測（代名詞解決、省略補完、婉曲表現解釈）
> - EmotionReader: 感情・緊急度・ニュアンス検出（8カテゴリ+6段階緊急度）
> - VocabularyManager: 組織固有語彙辞書（自動学習機能付き）
> - HistoryAnalyzer: 会話履歴からの文脈復元
> - DeepUnderstanding: 全コンポーネント統合クラス
> - DBマイグレーション（4テーブル、RLS設定、Feature Flags）
> - テスト58件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase 2J 判断力強化）:** ✅ 2026-01-27 完了
> ソウルくんの「判断力」を大幅に強化した。多角的思考、トレードオフ判断、リスク・リターン評価、過去判断との整合性チェックができるようになった。
> - 8ファイル実装完了（lib/brain/advanced_judgment/）
> - OptionEvaluator: 複数選択肢の比較評価（重み付けスコアリング、ランキング）
> - TradeoffAnalyzer: トレードオフの明示化（「Aを取ればBを犠牲に」の言語化）
> - RiskAssessor: リスク・リターンの定量評価（発生確率×影響度、期待値計算）
> - ConsistencyChecker: 過去の判断との整合性チェック（類似判断検索、矛盾検出）
> - AdvancedJudgment: 全コンポーネント統合クラス
> - DBマイグレーション（4テーブル、RLS設定、Feature Flags）
> - テスト実装完了（test_advanced_judgment.py）
> - chatwork-webhookに同期済み

**完了したこと（Phase G2 画像生成）:** ✅ 2026-01-27 完了
> ソウルくんに「手」を追加した（画像版）。DALL-E 3/2を使って画像を生成できるようになった。
> - 6ファイル実装完了（lib/capabilities/generation/）
> - DALL-E 3/2対応（サイズ・品質・スタイル選択可能）
> - プロンプト最適化（日本語→英語変換）
> - コスト計算（¥6〜¥18/枚）
> - テスト47件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase G3 ディープリサーチ）:** ✅ 2026-01-27 完了
> ソウルくんに「調査員」能力を追加した。Perplexityのような深い調査ができるようになった。
> - 1ファイル新規実装（research_engine.py）
> - 既存ファイル更新（constants.py, models.py, exceptions.py, __init__.py）
> - Perplexity API連携（Web検索含むAI応答）
> - 4段階のリサーチ深度（quick/standard/deep/comprehensive）
> - 調査計画生成・情報収集・分析・レポート生成
> - コスト計算（¥50〜¥800程度）
> - テスト49件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase G4 Google Sheets/Slides）:** ✅ 2026-01-28 完了
> ソウルくんがGoogle Sheets/Slidesを読み書きできるようになった。
> - 2ファイル新規実装（google_sheets_client.py, google_slides_client.py）
> - __init__.py更新（エクスポート追加）
> - **Google Sheets機能**:
>   - 読み込み（read_sheet, get_spreadsheet_info, read_all_sheets）
>   - 作成（create_spreadsheet）
>   - 書き込み（write_sheet, append_sheet, clear_sheet）
>   - シート操作（add_sheet, delete_sheet）
>   - 共有（share_spreadsheet）
>   - Markdownテーブル変換
> - **Google Slides機能**:
>   - 読み込み（get_presentation_info, get_presentation_content）
>   - 作成（create_presentation）
>   - スライド追加（add_slide, add_title_slide, add_section_slide）
>   - スライド操作（delete_slide, reorder_slides）
>   - 共有（share_presentation）
>   - Markdown変換
> - テスト56件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase G5 動画生成）:** ✅ 2026-01-28 完了
> ソウルくんに「動画クリエイター」能力を追加した。Runway Gen-3 Alphaを使って動画を生成できるようになった。
> - 2ファイル新規実装（video_generator.py, runway_client.py）
> - 既存ファイル更新（constants.py, models.py, exceptions.py, __init__.py）
> - **Runway Gen-3 Alpha対応**:
>   - Text-to-Video生成
>   - Image-to-Video生成（参照画像から動画）
>   - 解像度選択（720p, 1080p）
>   - 動画長選択（5秒, 10秒）
>   - アスペクト比選択（16:9, 9:16, 1:1）
>   - スタイル選択（realistic, cinematic, anime, creative）
> - **プロンプト最適化**: 日本語→英語変換、動画向け最適化
> - **コスト計算**: ¥25〜¥75/本（秒数・モデルにより変動）
> - **非同期生成**: タスクID発行→ポーリング→完了通知
> - テスト60件全パス
> - chatwork-webhookに同期済み

**完了したこと（Phase 2K 能動性）:** ✅ 2026-01-27 デプロイ完了
> ソウルくんが「自分から声をかける」能力を追加し、**本番デプロイ完了**した。
> - **コード実装完了**: lib/brain/proactive.py（922行、40テスト済み）
> - **DBマイグレーション完了**: 3テーブル + 1ビュー
>   - proactive_action_logs: アクションログ
>   - proactive_cooldowns: クールダウン管理
>   - proactive_settings: 設定
>   - v_proactive_stats: 統計ビュー
> - **Cloud Functionデプロイ完了**: proactive-monitor (revision 00016-kot)
>   - URL: https://asia-northeast1-soulkun-production.cloudfunctions.net/proactive-monitor
>   - メモリ: 512MB, タイムアウト: 540秒
>   - シークレット: DB_PASSWORD, CHATWORK_API_TOKEN, SOULKUN_CHATWORK_TOKEN, OPENAI_API_KEY, OPENROUTER_API_KEY, PINECONE_API_KEY
> - **Cloud Scheduler設定完了**: proactive-monitor-hourly
>   - スケジュール: 毎時30分（Asia/Tokyo）
>   - 状態: ENABLED
> - **現在の動作状態**:
>   - USE_PROACTIVE_MONITOR=true（有効）
>   - PROACTIVE_DRY_RUN=true（ドライランモード、メッセージ送信なし）
> - **トリガー条件**:
>   1. 目標放置（7日間更新なし）
>   2. タスク山積み（5件以上遅延）
>   3. 感情変化（ネガティブ継続3日）
>   4. 質問放置（24時間未回答）
>   5. 目標達成（お祝い）
>   6. 長期不在（14日以上）
> - **本番デプロイ後のバグ修正（2026-01-27）**:
>   - PR #264: DB接続修正（Cloud SQL Connector async対応）

**完了したこと（Phase 2L 実行力強化）:** ✅ 2026-01-28 完了
> ソウルくんに「実行力」を追加した。複雑なタスクを自動分解・計画・実行できるようになった。
> - **5ファイル実装完了**（lib/brain/execution_excellence/）
>   - models.py: データモデル（Enum、SubTask、ExecutionPlan、ProgressReport等）
>   - decomposer.py: TaskDecomposer（タスク自動分解）
>   - planner.py: ExecutionPlanner（実行計画立案、依存関係解析）
>   - executor.py: WorkflowExecutor（ワークフロー実行、品質チェック、例外処理、エスカレーション）
>   - __init__.py: ExecutionExcellence統合クラス
> - **機能一覧**:
>   1. タスク自動分解（複雑なリクエスト→サブタスクに分解）
>   2. 実行計画立案（依存関係解析、トポロジカルソート）
>   3. 進捗自動追跡（閾値ごとに通知）
>   4. 品質チェック（完了率、エラー率、実行時間）
>   5. 例外処理（リトライ、代替案、エスカレーション）
>   6. エスカレーション（自動解決不可時の人間確認）
> - **DBマイグレーション作成**:
>   - execution_plans: 実行計画テーブル
>   - execution_subtasks: サブタスクテーブル
>   - execution_escalations: エスカレーションテーブル
>   - execution_quality_reports: 品質レポートテーブル
> - **Feature Flag追加**: ENABLE_EXECUTION_EXCELLENCE（デフォルト: false）
> - **脳統合完了**: core.pyに統合、複合タスク判定で自動切り替え
> - **テスト31件全パス**
> - **chatwork-webhookに同期済み**
>   - PR #265: スキーマ不一致修正（goal_text→title, assignee_account_id→assigned_to_account_id）
>   - PR #266: タイムゾーン比較エラー修正（AT TIME ZONE 'Asia/Tokyo'追加）
> - **動作確認済み**: 53ユーザーをチェック、エラーなく完了

**完了したこと（Phase 2K バグ修正）:** ✅ 2026-01-28 完了
> proactive-monitorのドライランログを確認し、型不一致バグを発見・修正した。
> - **問題**: `chatwork_tasks.organization_id`（VARCHAR）にUUIDを渡していた
> - **問題**: `chatwork_tasks.assigned_to_account_id`（BIGINT）に文字列を渡していた
> - **問題**: `goals.organization_id`（UUID）に`'org_soulsyncs'`文字列を渡していた
> - **修正内容**:
>   - `_get_chatwork_tasks_org_id()`: UUID → VARCHAR変換
>   - `_get_chatwork_account_id_int()`: 文字列 → BIGINT変換
>   - `_is_valid_uuid()`: UUID検証（CAST前にチェック）
> - **PR #270**: マージ済み、デプロイ完了
> - **動作確認**: 53ユーザーチェック、エラーなし

**完了したこと（Brain-Capability統合基盤）:** ✅ 2026-01-28 実装完了
> 脳と機能モジュール（capabilities）が完全に分断されていた問題を発見し、統合基盤を実装した。
> - **問題**: 脳（lib/brain/）と機能（lib/capabilities/）が一切連携していなかった
> - **解決策**: CapabilityBridgeパターンで橋渡し層を実装
> - **新規ファイル（2ファイル）**:
>   | ファイル | 説明 |
>   |---------|------|
>   | `lib/brain/capability_bridge.py` | 脳と機能の橋渡し層 |
>   | `docs/brain_capability_integration_design.md` | 統合設計書 |
> - **lib/brain/models.py拡張**:
>   - `multimodal_context`: マルチモーダルコンテキスト
>   - `generation_request`: 生成リクエスト
>   - `has_multimodal_content()`, `has_generation_request()`, `get_multimodal_summary()`
> - **テスト**: 28件追加（tests/test_brain_capability_bridge.py）
> - **PR #271**: マージ完了
> - **PR #272**: chatwork-webhook/main.py統合、マージ完了

**完了したこと（Brain-Capability main.py統合）:** ✅ 2026-01-28 完了
> CapabilityBridgeをchatwork-webhookに統合した。
> - **SYSTEM_CAPABILITIES拡張**: generate_document, generate_image, generate_video追加
> - **ハンドラー統合**: _get_brain_integration()とCapabilityBridgeを接続
> - **PR #272**: マージ完了
> - **本番デプロイ**: revision 00216-xac ✅

**完了したこと（chatwork-webhook v10.38.0 デプロイ）:** ✅ 2026-01-28 06:08 UTC 完了
> Brain-Capability統合を本番環境にデプロイした。
> - **旧リビジョン**: chatwork-webhook-00215-lot
> - **新リビジョン**: chatwork-webhook-00216-xac
> - **検証結果**:
>   - CapabilityBridge: 正常ロード
>   - 脳アーキテクチャ: enabled=True
>   - エラー: なし

**完了したこと（CapabilityBridge ハンドラー統合強化）:** ✅ 2026-01-28 完了
> 実装済みだが脳に繋がっていなかった3つの機能をCapabilityBridgeに統合した。
> - **問題**: 以下の実装済み機能が脳のハンドラーに未登録だった
>   - ディープリサーチ（ResearchEngine）
>   - Google Sheets（GoogleSheetsClient）
>   - Google Slides（GoogleSlidesClient）
> - **解決策**: capability_bridge.pyに6つの新ハンドラーを追加
>   | ハンドラー | 機能 |
>   |-----------|------|
>   | `deep_research`, `research`, `investigate` | Perplexity APIを使った深い調査 |
>   | `read_spreadsheet` | スプレッドシート読み込み |
>   | `write_spreadsheet` | スプレッドシート書き込み |
>   | `create_spreadsheet` | スプレッドシート作成 |
>   | `read_presentation` | プレゼンテーション読み込み |
>   | `create_presentation` | プレゼンテーション作成 |
> - **Feature Flags追加**: ENABLE_DEEP_RESEARCH, ENABLE_GOOGLE_SHEETS, ENABLE_GOOGLE_SLIDES
> - **テスト**: 44件（16件追加）全パス
> - **chatwork-webhook同期**: 完了

**完了したこと（chatwork-webhook v10.39.0 デプロイ）:** ✅ 2026-01-28 15:45 JST 完了
> CapabilityBridgeハンドラー統合強化を本番環境にデプロイした。
> - **旧リビジョン**: chatwork-webhook-00216-xac
> - **新リビジョン**: chatwork-webhook-00220-hid
> - **デプロイ過程**:
>   1. revision 00219-hol: デプロイ成功したが、env-vars.yamlがUSE_BRAIN_ARCHITECTUREを上書きし、脳が無効化された
>   2. 環境変数を手動更新: `USE_BRAIN_ARCHITECTURE=true, BRAIN_FALLBACK_ENABLED=true, USE_CAPABILITY_BRIDGE=true`
>   3. revision 00220-hid: 環境変数更新でデプロイ、脳が再有効化された
> - **検証結果**:
>   - 脳アーキテクチャ: enabled=True, mode=true
>   - CapabilityBridge: 正常ロード
>   - 新ハンドラー: 8件登録確認
>   - エラー: なし
> - **追加された機能**:
>   - `調査して`、`リサーチして`→ディープリサーチハンドラー
>   - `スプレッドシート作って/読んで/書いて`→Google Sheetsハンドラー
>   - `スライド作って/読んで`→Google Slidesハンドラー

**実装中（Phase 2L 実行力強化）:** 🔧 2026-01-28 基盤実装完了
> ソウルくんに「完璧にやり遂げる」能力を追加中。複雑なリクエストを自動分解して実行できるようになる。
> - **設計書完成**: docs/21_phase2l_execution_excellence.md（456行）
> - **コード実装完了**: lib/brain/execution_excellence/（5ファイル）
>   - models.py: データモデル（SubTask, ExecutionPlan, ProgressReport等、11種類）
>   - decomposer.py: タスク分解器（ルールベース＋LLMベース）
>   - planner.py: 実行計画立案（依存関係解析、トポロジカルソート、並列グループ特定）
>   - executor.py: ワークフロー実行（進捗追跡、品質チェック、例外処理、エスカレーション）
>   - __init__.py: 統合クラス（ExecutionExcellence）
> - **テスト実装完了**: tests/test_execution_excellence.py（31件全パス）
> - **主要機能**:
>   - タスク自動分解（「〇〇して、△△して」→複数サブタスク）
>   - 依存関係解析＆並列実行
>   - 進捗追跡＆品質チェック
>   - 例外処理＆エスカレーション
> - **Feature Flag**: ENABLE_EXECUTION_EXCELLENCE
> - **残り作業**:
>   1. DBマイグレーション作成（execution_plans, execution_subtasks, execution_escalations）
>   2. lib/brain/__init__.pyへのエクスポート追加
>   3. lib/brain/core.pyへの統合
>   4. chatwork-webhookへの同期
>   5. 本番デプロイ

**完了したこと（v10.40.1 確認判定ロジック修正）:** ✅ 2026-01-28 11:16 UTC デプロイ完了
> 目標設定で「合ってるけど、フィードバックして」と言った際に即座に登録されてしまうバグを修正した。
> - **問題**: 「合ってる」という肯定語のみで確認OKと判定し、「けど」「フィードバック」を無視
> - **修正内容**:
>   - `_is_pure_confirmation()` 関数を追加
>   - 確認 = 肯定語あり AND 否定接続なし AND FB要求なし
>   - BUT_CONNECTOR_PATTERNS: 「けど」「だけど」「でも」等
>   - FEEDBACK_REQUEST_PATTERNS: 「フィードバック」「評価」「教えて」等
> - **ファイル**: `chatwork-webhook/lib/goal_setting.py`
> - **revision**: chatwork-webhook versionId: 3

**完了したこと（神経接続修理 v10.40.1）:** ✅ 2026-01-28 13:05 JST 本番デプロイ完了
> 状態管理を brain_conversation_states に一本化し、「全入力が脳を通る」アーキテクチャを完成。
> - **コミット**: `0a9e0b4` fix(brain): 神経接続修理
> - **PR**: #286
> - **本番リビジョン**: chatwork-webhook-00243-mas
> - **変更内容**:
>   - SoulkunBrain._check_goal_setting_session() を削除（約80行）
>   - GoalHandler._check_dialogue_completed() を brain_conversation_states 参照に変更
>   - brain_dialogue_logs テーブル作成（対話ログ統一管理）
>   - 本番環境で USE_BRAIN_ARCHITECTURE=true 強制
>   - 回帰テスト12件追加
> - **マイグレーション**: brain_dialogue_logs テーブル作成完了（データ移行は対象データなしでスキップ）
> - **注意**: goal_setting_sessions / goal_setting_logs は本番DBに存在しない（別経路で状態管理済み）

**完了したこと（メモリ分離 v10.40.9）:** ✅ 2026-01-28 17:00 JST 本番マイグレーション完了
> ボットペルソナ（ソウルくんの設定）とユーザー個人メモリを分離し、メモリ漏洩を防止。
> - **PR**: #293
> - **コミット履歴**:
>   - `90ae781` feat(memory): メモリ分離とアクセス制御を実装
>   - `9602122` perf(migration): 3-phase structure with CONCURRENTLY indexes
>   - `518edaf` perf(migration): 3-step scope column addition to avoid table rewrite
>   - `06436ee` perf(migration): batch backfill scope to reduce lock risk
> - **新規テーブル**: `bot_persona_memory`（ソウルくんのキャラ設定専用）
> - **カラム追加**: `user_long_term_memory.scope`（PRIVATE/ORG_SHARED）
> - **セキュリティ**: `get_all_for_requester()` でアクセス制御（PRIVATEは本人のみ）
> - **マイグレーション設計**:
>   - Phase 1: DDL（テーブル作成、カラム追加）
>   - Phase 2: データ移行（トランザクション分離）
>   - Phase 3: インデックス作成（CONCURRENTLY）
>   - scope埋め戻し: バッチ10000件/回、テーブルリライト回避
> - **本番結果**: user_long_term_memory 0件、bot_persona_memory 作成完了
> - **テスト**: 67件全パス

**完了したこと（P4 Memory Authority v10.43.0）:** ✅ 2026-01-28 19:00 JST マージ完了
> 長期記憶との矛盾をチェックする最終ゲートキーパー層を実装した。
> - **PR**: #303
> - **新規ファイル**: `lib/brain/memory_authority.py`
> - **テスト**: 43件全パス
> - **判定フロー**: P3 ValueAuthority → P4 MemoryAuthority → 実行
> - **判定結果**:
>   - APPROVE: 矛盾なし、実行OK
>   - BLOCK_AND_SUGGEST: HARD CONFLICT、実行ブロック+代替案
>   - REQUIRE_CONFIRMATION: SOFT CONFLICT、確認が必要
>   - FORCE_MODE_SWITCH: 重大な矛盾、モード強制遷移
> - **設計思想**: 誤ブロック最小化（HARD CONFLICTのみ即ブロック）

**完了したこと（P4 観測モード v10.43.1）:** ✅ 2026-01-28 19:02 JST マージ完了
> SOFT_CONFLICT検出時にログを保存する観測モード機能を実装した。
> - **PR**: #305
> - **新規ファイル**: `lib/brain/memory_authority_logger.py`
> - **テスト**: 29件全パス（P4関連合計72件）
> - **ログ内容**: action, detected_memory_reference, conflict_reason, user_response
> - **設計**: 非同期保存（実行速度に影響なし）
> - **⚠️ 課題**: Cloud Functionsではローカルファイルが非永続。Cloud Logging対応が必要。

**完了したこと（v10.43.0 Persona Layer）:** ✅ 2026-01-28 19:15 JST デプロイ完了
> ソウルくんに「人格レイヤー」を追加した。Company Persona（全ユーザー共通）+ Add-on（個人向け）で一貫した行動指針を注入。
> - **PR**: #302（Persona Layer本体）, #304（ログ修正）, #307（get_pool修正）
> - **新規モジュール**: `chatwork-webhook/lib/persona/`
>   - `__init__.py`: `build_persona_prompt()` メイン関数
>   - `company_base.py`: Company Persona v1（10行の行動指針）
>   - `addon_manager.py`: Add-on CRUD（DB連携）
> - **symlink**: `lib/persona` → `chatwork-webhook/lib/persona`
> - **DBテーブル**: `persona_addons`（Kazu Add-on v1 投入済み）
> - **main.py統合**: `get_ai_response()` に Persona 注入ロジック追加（全5箇所のcall site対応）
> - **安全対策**:
>   - MAX_PERSONA_CHARS = 1200（長さ制限）
>   - account_id が None の場合は Add-on スキップ
>   - DB接続失敗時も会話継続（try/except）
>   - ログは `🎭 Persona injected | addon=yes/no` のみ（個人名非出力）
> - **本番デプロイ**: chatwork_webhook v6
> - **⚠️ バグ修正済み**: `get_db_pool()` → `get_pool()` に修正（#307）

**次回確認事項（v10.43.0 Persona Layer）:**
> - ChatWorkで「おはよう」等の一般会話を送信し、ログで `🎭 Persona injected | addon=yes` を確認する
> - カズ以外のアカウントで送信し、`addon=no` になることを確認する

**🔴 テスト待ち（v10.40.18 長期記憶 router_guard）:** 2026-01-29 11:00 JST
> v10.40.14〜v10.40.18でrouter_guardによる長期記憶の保存・取得パターンを実装した。
> **テスト手順:**
> 1. Chatworkで「俺の人生軸は挑戦」を送信
> 2. 「軸を確認して」を送信
> 3. 長期記憶が返ってくるか確認（「挑戦」が含まれていれば成功）
>
> **今後の方針:**
> - **推奨**: 段階的改善（インクリメンタル修正）
> - **理由**: コアアーキテクチャは健全（セキュリティ8/10）、問題は局所的
> - **Priority 1修正**: user_preferencesアクセス制御、エラーメッセージサニタイズ、audit_logs記録

---

## 🔧 障害報告書: v10.40.1〜v10.40.2（2026-01-28）

### 【他のAI向け】この報告書について
将来このプロジェクトに関わるAI（Claude等）向けに、今回発生した問題と解決方法を詳細に記録する。同様の問題が発生した場合の参考にすること。

---

### 障害①: brain_dialogue_logs テーブル未作成

**発生日時:** 2026-01-28 13:16 JST

**現象:**
```
relation "brain_dialogue_logs" does not exist
```
- 目標設定で「目標設定したい」と送ると上記エラーが発生
- ソウルくんが「エラーが発生したウル」と応答

**原因:**
- v10.40.1のコードは `brain_dialogue_logs` テーブルを参照する設計
- しかし、マイグレーション（`migrations/neural_connection_repair.sql`）が本番DBで未実行だった
- PROGRESS.mdには「マイグレーション完了」と記載されていたが、実際は未完了

**解決方法:**
```python
# 本番DBに接続してマイグレーション実行
CREATE TABLE IF NOT EXISTS brain_dialogue_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    chatwork_account_id VARCHAR(50) NOT NULL,
    room_id VARCHAR(50) NOT NULL,
    state_type VARCHAR(50) NOT NULL,
    state_step VARCHAR(50) NOT NULL,
    step_attempt INTEGER NOT NULL DEFAULT 1,
    user_message TEXT,
    ai_response TEXT,
    detected_pattern VARCHAR(100),
    evaluation_result JSONB,
    feedback_given BOOLEAN DEFAULT FALSE,
    result VARCHAR(50),
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
-- + インデックス3つ
-- + goal_setting_logs から 30件のデータ移行
```

**教訓:**
- マイグレーションは必ず本番DBで実行されたことを `SELECT COUNT(*) FROM table_name` 等で確認する
- PROGRESS.mdに「完了」と書く前に、実際にテーブルが存在するか確認する

---

### 障害②: UnderstandingResult.inferred_action 属性エラー

**発生日時:** 2026-01-28 13:19 JST

**現象:**
```
'UnderstandingResult' object has no attribute 'inferred_action'
```
- 目標設定中に意図理解が常に失敗
- ログに `Goal setting intent understanding failed` が出続ける

**原因:**
- `lib/brain/core.py` で `understanding.inferred_action` を参照
- しかし `UnderstandingResult` クラス（`lib/brain/models.py`）には `inferred_action` 属性が存在しない
- 正しくは `intent` 属性を使うべきだった

**該当コード（修正前）:**
```python
# lib/brain/core.py:831
inferred_action = understanding.inferred_action if understanding else None

# lib/brain/core.py:1082
inferred_action = understanding.inferred_action if understanding else "general_conversation"
params = understanding.extracted_params if understanding else {}
```

**解決方法:**
```python
# lib/brain/core.py:831
inferred_action = understanding.intent if understanding else None

# lib/brain/core.py:1082
inferred_action = understanding.intent if understanding else "general_conversation"
params = understanding.entities if understanding else {}
```

**修正ファイル:**
- `lib/brain/core.py`
- `chatwork-webhook/lib/brain/core.py`

**教訓:**
- 新しいクラスを使う際は、そのクラスの属性を必ず確認する
- IDEの補完や型チェックを活用してこのようなミスを防ぐ

---

### 障害③: confirm stepで同じ要約が無限ループ

**発生日時:** 2026-01-28 13:20 JST

**現象:**
- confirm stepでユーザーが「これでいい？正しい？」と聞くと、同じ要約&OK確認を繰り返す
- 「もう一度目標設定したい」と言っても同じ応答が返る

**原因:**
- `_is_pure_confirmation()` がフィードバック要求を検出して False を返す → 正常
- しかし、False の場合の処理が「修正リクエスト」として LLM 解析 → 同じ要約を再表示
- フィードバック要求と修正リクエストが区別されていなかった

**該当コード（修正前）:**
```python
# lib/goal_setting.py confirm step
if is_confirmed:
    # 登録処理
else:
    # 修正リクエストの可能性（すべてここに来る）
    extracted = self._analyze_long_response_with_llm(user_message, session)
    response = self._generate_understanding_response(...)  # 同じ要約
```

**解決方法:**
```python
# lib/goal_setting.py confirm step
if is_confirmed:
    # 登録処理
else:
    # v10.40.2: フィードバック要求/迷い・不安の場合は「導きの対話」へ
    is_feedback_request = _has_feedback_request(user_message)
    is_doubt_anxiety = _has_doubt_or_anxiety(user_message)

    if is_feedback_request or is_doubt_anxiety:
        # 導きの対話（目標の質チェック）
        response = self._generate_quality_check_response(
            session, user_message, pattern_type
        )
        return {..., "pattern": pattern_type}

    # それ以外は修正リクエストとして処理
    extracted = self._analyze_long_response_with_llm(user_message, session)
    response = self._generate_understanding_response(...)
```

**追加した機能:**
1. `DOUBT_ANXIETY_PATTERNS`: 迷い・不安パターン定義
2. `_has_doubt_or_anxiety()`: 迷い・不安検出関数
3. `_generate_quality_check_response()`: 導きの対話（目標の質チェック）応答生成
4. `TEMPLATES["quality_check"]`: 導きの対話用テンプレート

**設計思想（重要）:**
- フィードバック要求/迷い・不安時は「導きの対話」に分岐
- 心理的安全性を確保（「正解はない」「完璧じゃなくていい」）
- 目標の質を上げる質問を最大2つ提示
- 最後に選択を促す（「登録する？調整する？」）
- 詰問・ジャッジ禁止（設計書 docs/11_organizational_theory_guidelines.md 参照）

**修正ファイル:**
- `lib/goal_setting.py`
- `chatwork-webhook/lib/goal_setting.py`
- `tests/test_goal_setting.py`（テスト8件追加）

**テスト要件:**
- confirm stepで「これでいい？」→ 導きの対話へ（同じconfirmを繰り返さない）
- 「OK」「はい」→ 目標登録へ進む

---

### 本番デプロイ履歴

| 日時 | リビジョン | 内容 |
|------|-----------|------|
| 13:05 | chatwork-webhook-00243-mas | v10.40.1 神経接続修理（brain_conversation_states一本化） |
| 13:34 | chatwork-webhook-00244-ted | UnderstandingResult属性修正 |
| 13:48 | chatwork-webhook-00245-tix | v10.40.2 導きの対話（目標の質チェック） |

---

### 関連ファイル一覧

将来このコードを修正する際は、以下のファイルを確認すること：

| ファイル | 役割 |
|---------|------|
| `lib/goal_setting.py` | 目標設定対話フロー実装（マスター） |
| `chatwork-webhook/lib/goal_setting.py` | 本番用コピー（lib/と同期必須） |
| `lib/brain/core.py` | 脳アーキテクチャ（意図理解・判断） |
| `lib/brain/models.py` | UnderstandingResult等のモデル定義 |
| `docs/05_phase2-5_goal_achievement.md` | 目標達成支援の設計書 |
| `docs/11_organizational_theory_guidelines.md` | 組織論ガイドライン（NG行動一覧） |
| `tests/test_goal_setting.py` | 目標設定テスト（121件） |

---

**次にやること:**
> 1. **v10.40.2の動作確認** - ChatWorkで「目標設定したい」→「これでいい？」のフローをテスト
> 2. **Phase 2Kドライラン監視** - 問題なければ`PROACTIVE_DRY_RUN=false`に変更
> 3. **生成機能テスト** - 「資料作成して」「画像作成して」の動作確認

---

### 優先順位付きタスクリスト

| 優先度 | タスク | 理由 | 状態 |
|--------|--------|------|------|
| ~~★★★~~ | ~~Phase A: 管理者設定のDB化~~ | ~~Phase 4（マルチテナント）の前提条件~~ | ✅ **完了 (v10.30.1)** |
| ~~★★★~~ | ~~Phase C: Feature Flag集約~~ | ~~15個のフラグが散らばっていて保守性が悪い~~ | ✅ **完了 (v10.31.0)** |
| ~~★★☆~~ | ~~Phase D: 接続設定集約~~ | ~~8ファイルに同じDB接続文字列がある~~ | ✅ **完了 (v10.31.1)** |
| ~~★★☆~~ | ~~脳アーキテクチャ本番有効化~~ | ~~シャドウモード稼働中 → 段階的ロールアウト~~ | ✅ **完了 (v10.31.3)** |
| ~~★★★~~ | ~~Phase 2D CEO Learning~~ | ~~DB・コード・統合完了~~ | ✅ **完了 (v10.32.1)** |
| ~~★★★~~ | ~~Phase 2E Learning Foundation~~ | ~~12ファイル・119テスト完了~~ | ✅ **完了** |
| ~~★★★~~ | ~~Phase 2F 結果からの学習~~ | ~~8ファイル・32テスト完了~~ | ✅ **完了** |
| ~~★★★~~ | ~~Phase 2G 記憶の強化~~ | ~~5ファイル・38テスト完了~~ | ✅ **完了** |
| ~~★★★~~ | ~~Phase 2H 自己認識~~ | ~~3ファイル・41テスト完了~~ | ✅ **完了** |
| ~~★★★~~ | ~~Phase 2I 理解力強化~~ | ~~8ファイル・58テスト完了~~ | ✅ **完了** |
| ~~★★★~~ | ~~Phase 2J 判断力強化~~ | ~~8ファイル実装完了~~ | ✅ **完了** |
| ~~★★★~~ | ~~Phase F1 CEOフィードバック~~ | ~~8ファイル・57テスト完了~~ | ✅ **完了** |
| ~~★★☆~~ | ~~Phase G2 画像生成~~ | ~~DALL-E連携・47テスト完了~~ | ✅ **完了** |
| ~~★★☆~~ | ~~Phase G3 ディープリサーチ~~ | ~~Perplexity連携・49テスト完了~~ | ✅ **完了** |
| ~~★★☆~~ | ~~Phase G4 Google Sheets/Slides~~ | ~~読み書き機能・56テスト完了~~ | ✅ **完了** |
| ~~★★★~~ | ~~Phase 2K 能動性~~ | ~~proactive-monitor CF本番デプロイ~~ | ✅ **完了** |
| **★★☆** | **Phase 2Kドライラン監視** | ログ確認後、PROACTIVE_DRY_RUN=falseに変更 | 📋 待機中 |
| **★★☆** | **本番ログ監視・旧コード削除** | 脳の判断ログを確認、問題なければ旧コード削除 | 📋 待機中 |

---

## Phase一覧と状態

| Phase | 名称 | 状態 | 完了日 | 備考 |
|-------|------|------|--------|------|
| 1 | タスク管理基盤 | ✅ 完了 | 2025-12 | ChatWork連携、リマインド |
| 1-B | タスク検知・監視 | ✅ 完了 | 2026-01 | v10.1.4で完了、notification_logs |
| 2 | AI応答・評価機能 | ✅ 完了 | 2025-12 | GPT-4連携 |
| 2 A1 | パターン検知 | ✅ 完了 | 2026-01-23 | v10.18.0、高頻度質問検知 |
| 2 A2 | 属人化検出 | ✅ 完了 | 2026-01-24 | PR #49、BCPリスク可視化 |
| 2 A3 | ボトルネック検出 | ✅ 完了 | 2026-01-24 | PR #51、期限超過・タスク集中検出 |
| 2 A4 | 感情変化検出 | ✅ 完了 | 2026-01-24 | v10.20.0、PR #59、本番デプロイ完了 |
| 2 B | 覚える能力 | ✅ 完了 | 2026-01-24 | v10.21.0、PR #68、通常会話統合完了 |
| 2.5 | 目標達成支援 | ✅ 完了 | 2026-01-24 | v10.22.5、PR #77、終了コマンド追加 |
| 2C-1 | MVV・組織論的行動指針 | ✅ 完了 | 2026-01-24 | v10.22.3、PR #74、本番デプロイ完了 |
| 2C-2 | 日報・週報自動生成 | ✅ 完了 | 2026-01-24 | v10.23.2、PR #84、Phase 2.5+MVV統合 |
| 3 | ナレッジ検索 | ✅ 完了 | 2026-01 | v10.13.3、ハイブリッド検索 |
| 3.5 | 組織階層連携 | ✅ 完了 | 2026-01-25 | 6段階権限、役職ドロップダウン |
| X | アナウンス機能 | ✅ 完了 | 2026-01-25 | v10.26.0、PR #127/PR #129/PR #130 |
| C | 会議系 | 📋 未着手 | - | 議事録自動化（Q3予定） |
| C+ | 会議前準備支援 | 📋 未着手 | - | Phase C完了後 |
| 2D | CEO教え＆守護者層 | ✅ 完了 | 2026-01-27 | v10.32.1、DB+コード+統合+56テスト完了 |
| 2E | 学習基盤 | ✅ 完了 | 2026-01-27 | 12ファイル・119テスト完了 |
| 2F | 結果からの学習 | ✅ 完了 | 2026-01-27 | 8ファイル・32テスト完了 |
| 2G | 記憶の強化 | ✅ 完了 | 2026-01-27 | 5ファイル・38テスト完了 |
| 2H | 自己認識 | ✅ 完了 | 2026-01-27 | 3ファイル・41テスト完了 |
| 2I | 理解力強化 | ✅ 完了 | 2026-01-27 | 8ファイル・58テスト完了 |
| 2J | 判断力強化 | ✅ 完了 | 2026-01-27 | 8ファイル・テスト完了、DBマイグレ済み |
| 2K | 能動性 | ✅ 完了 | 2026-01-27 | proactive.py 922行・40テスト・DB3テーブル・CF本番デプロイ済み |
| 2L | 実行力強化 | 📋 計画中 | - | 2026年8-9月予定 |
| 2M | 対人力強化 | 📋 計画中 | - | 2026年9-10月予定 |
| 2N | 自己最適化 | 📋 計画中 | - | 2026年10-11月予定 |
| 2O | 統合・創発 | 📋 計画中 | - | 2026年11-12月予定 |
| **SM** | **スマートモデル管理** | 📋 設計完了 | - | 最新AIモデル最適コスト利用（3-4週間） |
| **M1** | **Multimodal入力** | ✅ 完了 | 2026-01-27 | 画像/PDF/URL読み込み（Phase M1完了） |
| **M2** | **音声入力** | ✅ 完了 | 2026-01-27 | 音声文字起こし・話者分離（Phase M2完了） |
| **G1** | **文書生成** | ✅ 完了 | 2026-01-27 | 7ファイル・84テスト完了（Phase G1完了） |
| **G2-G4** | **画像/リサーチ/動画** | 📋 設計完了 | - | 画像/動画生成、ディープリサーチ |
| **App1** | **議事録自動生成** | ✅ 完了 | 2026-01-27 | M2+G1統合アプリ、42テスト完了 |
| **F1** | **CEO Feedback** | ✅ 完了 | 2026-01-27 | 8ファイル・57テスト完了（Phase F1完了） |
| **AA** | **Autonomous Agent** | 📋 設計完了 | - | 自律エージェント（6-8週間） |
| 4A | テナント分離 | 📋 未着手 | - | RLS、マルチテナント |
| 4B | 外部連携API | 📋 未着手 | - | 公開API |

---

## 本番環境インフラ状態

**最終確認: 2026-01-28**

### Cloud Functions（18個）

| 関数名 | 状態 | 用途 | 最終更新 |
|--------|------|------|----------|
| chatwork-webhook | ACTIVE | メインWebhook (revision 00220-hid) | 2026-01-28 |
| chatwork-main | ACTIVE | Chatwork API | 2026-01-24 |
| remind-tasks | ACTIVE | タスクリマインド（土日祝スキップ） | 2026-01-25 |
| sync-chatwork-tasks | ACTIVE | タスク同期 | 2026-01-25 |
| check-reply-messages | ACTIVE | 返信チェック | 2026-01-24 |
| cleanup-old-data | ACTIVE | 古いデータ削除 | 2026-01-24 |
| pattern-detection | ACTIVE | A1〜A4検知統合 | 2026-01-24 |
| personalization-detection | ACTIVE | A2属人化検出 | 2026-01-24 |
| bottleneck-detection | ACTIVE | A3ボトルネック検出 | 2026-01-24 |
| weekly-report | ACTIVE | 週次レポート | 2026-01-24 |
| goal-daily-check | ACTIVE | 目標デイリーチェック | 2026-01-24 |
| goal-daily-reminder | ACTIVE | 目標リマインド | 2026-01-24 |
| goal-morning-feedback | ACTIVE | 朝のフィードバック | 2026-01-24 |
| goal-consecutive-unanswered | ACTIVE | 連続未回答検出 | 2026-01-24 |
| watch_google_drive | ACTIVE | Google Drive監視 | 2026-01-21 |
| sync-room-members | ACTIVE | ルームメンバー同期 | 2026-01-18 |
| update-schema | ACTIVE | スキーマ更新 | 2025-12-25 |
| schema-patch | FAILED | （廃止予定） | 2025-12-25 |

### Cloud Scheduler（19個）

| ジョブ名 | スケジュール | 状態 | 用途 |
|----------|--------------|------|------|
| check-reply-messages-job | */5 * * * * | ENABLED | 5分毎返信チェック |
| sync-chatwork-tasks-job | 0 * * * * | ENABLED | 毎時タスク同期 |
| sync-done-tasks-job | 0 */4 * * * | ENABLED | 4時間毎完了タスク同期 |
| remind-tasks-job | 30 8 * * * | ENABLED | 毎日 08:30 リマインド |
| cleanup-old-data-job | 0 3 * * * | ENABLED | 毎日 03:00 クリーンアップ |
| personalization-detection-daily | 0 6 * * * | ENABLED | 毎日 06:00 A2属人化検出 |
| bottleneck-detection-daily | 0 8 * * * | ENABLED | 毎日 08:00 A3ボトルネック検出 |
| emotion-detection-daily | 0 10 * * * | ENABLED | 毎日 10:00 A4感情変化検出 |
| pattern-detection-hourly | 15 * * * * | ENABLED | 毎時15分 A1パターン検知 |
| weekly-report-monday | 0 9 * * 1 | ENABLED | 毎週月曜 09:00 週次レポート |
| goal-daily-check-job | 0 17 * * * | ENABLED | 毎日 17:00 目標チェック |
| goal-daily-reminder-job | 0 18 * * * | ENABLED | 毎日 18:00 目標リマインド |
| goal-morning-feedback-job | 0 8 * * * | ENABLED | 毎日 08:00 朝フィードバック |
| goal-consecutive-unanswered-job | 0 9 * * * | ENABLED | 毎日 09:00 連続未回答チェック |
| daily-reminder-job | 0 18 * * * | ENABLED | 毎日 18:00 デイリーリマインド |
| weekly-summary-job | 0 18 * * 5 | ENABLED | 毎週金曜 18:00 週次サマリー |
| weekly-summary-manager-job | 5 18 * * 5 | ENABLED | 毎週金曜 18:05 マネージャーサマリー |
| sync-room-members-job | 0 8 * * 1 | ENABLED | 毎週月曜 08:00 メンバー同期 |
| soulkun-task-polling | */5 * * * * | PAUSED | （一時停止中） |

---

## 直近の主な成果

### 2026-01-29

- **08:30 JST**: v10.46.0 脳中心のObservability Layer ✅ **PR #324, #326 デプロイ完了**
  - **概要**: 鉄則3「脳が判断し、機能は実行するだけ」に基づき、全観測ログを脳が統一管理
  - **新規ファイル**:
    - `lib/brain/observability.py`: 観測機能の中核モジュール（441行）
    - `tests/test_brain_observability.py`: 24テストケース
  - **変更ファイル**:
    - `lib/brain/core.py`: SoulkunBrainにobservability統合
    - `chatwork-webhook/lib/persona/__init__.py`: 統一フォーマット対応
  - **機能**:
    - `ContextType` enum: persona, mvv, ceo_teaching, ng_pattern, basic_need, intent, route
    - `BrainObservability` class: log_context, log_intent, log_execution
    - 将来のDB永続化対応（バッファサイズ1000件制限付き）
  - **ログフォーマット**:
    ```
    🧠 ctx=intent path=goal_handler applied=yes account=12345 ({'intent': 'goal_registration', 'confidence': 0.95})
    🔀 ctx=route path=goal_handler applied=yes account=12345 ({'success': True, 'time_ms': 150})
    🎭 ctx=persona path=get_ai_response applied=yes account=12345 ({'addon': True})
    ```
  - **コードレビュー対応**: print() → logger.info()、バッファサイズ制限追加
  - **ダブルチェック**: lib/brain/ 同期漏れ発見・修正（PR #326）
  - **Revision**: `chatwork-webhook-00280-daf`

- **11:00 JST**: v10.40.14〜v10.40.18 長期記憶（人生軸・価値観）バグ修正シリーズ ✅ **PR #313, #316, #319, #322, #323 デプロイ完了**
  - **概要**: 「俺の人生軸は挑戦」等の長期記憶を保存・取得できるようにする修正シリーズ
  - **v10.40.14 (PR #313)**: router_guard追加（save patterns）
    - AI司令塔より前にパターンマッチングで`save_memory`を強制
    - 「一般会話でいいウル？」ループ防止
    - Revision: `chatwork-webhook-00270-duv`
  - **v10.40.15 (PR #316)**: テーブル自動作成 + UUID修正
    - `_ensure_long_term_table()`: コールドスタート時にCREATE TABLE IF NOT EXISTS
    - `int(user_result[0])` → `str(user_result[0])`: UUID型エラー修正
    - Revision: `chatwork-webhook-00275-tes`
  - **v10.40.16 (PR #319)**: SQLカラム名バグ修正
    - `SELECT user_id` → `SELECT id`（usersテーブルのPKはid）
    - Revision: `chatwork-webhook-00277-vas`
  - **v10.40.17 (PR #322)**: list_knowledgeリダイレクト試行
    - `_brain_handle_list_knowledge`で長期記憶クエリパターン検出
    - ※結果的にHANDLERSマッピングの問題で動作せず
    - Revision: `chatwork-webhook-00278-foh`
  - **v10.40.18 (PR #323)**: router_guard追加（query patterns）
    - 「軸を確認して」等のクエリパターンをrouter_guardで検出
    - AI司令塔をバイパスして直接`_handle_query_long_term_memory`を呼び出し
    - Revision: `chatwork-webhook-00279-cay`
  - **テスト待ち**: Chatworkで「軸を確認して」が長期記憶を返すか確認必要
  - **セキュリティレビュー実施**: 8/10スコア、段階的改善を推奨

### 2026-01-28

- **19:10 JST**: v10.40.13 長期記憶判定をbrain無効時にも対応 ✅ **PR #306 デプロイ完了**
  - **問題**: `USE_BRAIN_ARCHITECTURE=false`時、古い`handle_save_memory`が使われ、`is_long_term_memory_request()`が呼ばれていなかった
  - **原因**: brain有効時のみ`_brain_handle_save_memory`が使われる設計だった
  - **修正**: 古い`handle_save_memory`にも長期記憶判定ロジックを追加
  - **動作**: `is_long_term_memory_request()` → True → `user_long_term_memory`へ保存
  - **デバッグログ追加**: `🔍 [save_memory DEBUG] is_long_term=..., save_to=...`
  - **Revision**: `chatwork-webhook-00264-few`
  - **次回**: Chatworkでテスト送信 → ログで保存先確認

- **18:46 JST**: v10.40.12 人生軸・価値観パターン拡張 ✅ **PR #301 マージ完了**
  - **追加パターン**: 「人生軸は」「俺の軸は」「私の価値観は」「大事にしているのは」
  - **成功メッセージ**: 「大事な軸、ちゃんと覚えたウル！これからの会話に活かすウルね🐺✨」
  - **テスト**: 72件全パス
  - **Revision**: `chatwork-webhook-00263-vuf`

- **19:30 JST**: P4 Memory Authority 観測モード - 本番検証完了 ✅ **調査報告**
  - **結論**: v10.43.1は本番デプロイ済み、ただしログ永続化に問題あり
  - **検証結果**:
    - ✅ PR #305 (v10.43.1) はmainにマージ済み
    - ✅ chatwork-webhook は 2026-01-28T10:08:54Z にデプロイ済み
    - ❌ ログ保存パス `logs/memory_authority/` はCloud Functionsで非永続（インスタンス再起動で消失）
  - **推奨対応**: Cloud Loggingへの出力に変更（コスト最小、実装容易）
  - **優先度**: 中（観測データが蓄積されないと精度改善に使えない）
  - **次回タスク**: 「P4 観測ログ Cloud Logging 対応」で継続

- **19:02 JST**: P4 Memory Authority 観測モード実装 (v10.43.1) ✅ **PR #305 マージ完了**
  - **概要**: SOFT_CONFLICT検出時にログを保存する観測モード機能
  - **新規ファイル**:
    - `lib/brain/memory_authority_logger.py`: ログ保存クラス
    - `tests/test_memory_authority_logger.py`: 29テスト
  - **ログ内容**: action, detected_memory_reference, conflict_reason, user_response
  - **設計**: 非同期保存（asyncio.create_task）で実行速度に影響なし
  - **テスト**: P4関連72件パス（P4本体:43 + ロガー:29）
  - **判定ロジック変更**: なし（観測のみ）

- **17:15 JST**: goal_setting v10.40.7 - state_step二重設定SQLエラー修正 ✅ **PR #289**
  - **原因**: `_update_session()`でstatus='completed'とcurrent_step両方指定時、state_stepが2回設定されてPostgreSQLエラー
  - **エラー**: `multiple assignments to same column "state_step"`
  - **修正**: if-elif構造に変更してstatus='completed'時はcurrent_stepの設定をスキップ
  - **テスト**: 139件全パス（+3件追加: TestUpdateSessionSQL）
  - **デプロイ**: chatwork-webhook revision 00237-lgr

- **16:30 JST**: goal_setting v10.40.6 - confirm無限ループ完全防止パッチ ✅ **PR #287**
  - **概要**: confirmステップでLLM解析失敗時に同じ要約を繰り返さないよう修正
  - **変更内容**:
    - `lib/goal_setting.py`:
      - confirmステップのロジック整理（長文 かつ LLM抽出成功 かつ 有効な修正あり → 要約更新、それ以外 → 導きの対話へ）
      - `has_valid_updates`による明示的チェック追加
      - DOUBT_ANXIETY_PATTERNSに「微妙」「うーん」「びみょう」を追加
      - patternを`clarification_fallback`に変更
    - `lib/brain/core.py`:
      - v10.40.5: STOP_WORDS/continuation_intents/短文継続ルールの整理
  - **テスト**: 136件全パス（+3件追加: TestConfirmFallback）
  - **デプロイ**: chatwork-webhook revision 00236-pbh

- **14:30 JST**: goal_setting v10.40.3 - リスタートバグ修正 & フェーズ自動判定 ✅
  - **概要**: 2つのバグ修正と1つの機能改善
  - **修正1: セッション継続ガード**
    - 問題: goal_settingセッション中に「目標」を含む回答をすると、intent=goal_setting_startと推論されてセッションがリスタートしていた
    - 原因: `_is_different_intent_from_goal_setting()`で`goal_setting_start`が`goal_actions`に含まれていなかった
    - 修正: `goal_actions`リストに`goal_setting_start`を追加し、`"goal" in inferred_action.lower()`で全goal関連intentを保護
  - **修正2: 明示的リスタート検出**
    - 問題: 明示的なリスタート要求（「もう一度」「やり直したい」等）と通常回答の区別がなかった
    - 修正: `RESTART_PATTERNS`と`_wants_restart()`関数を追加し、明示的リスタート時のみセッションをクリア
  - **機能追加: フェーズ自動判定**
    - ユーザー発話からWHY/WHAT/HOWの充足度を自動判定
    - 既に情報が含まれているフェーズはスキップ
    - テーマが検出された場合、具体化に絞った質問を生成
    - 例: 「SNS発信とAI開発と組織化に力を入れる」→「この3テーマのうち、まず今月達成したい成果を教えて」
  - **修正ファイル**:
    - `lib/brain/core.py`: `goal_actions`リスト修正
    - `lib/goal_setting.py`: `RESTART_PATTERNS`, `_wants_restart()`, `_infer_fulfilled_phases()`, `_get_next_unfulfilled_step()`, `_extract_themes_from_message()`, `_accept_and_proceed()`修正
    - `chatwork-webhook/lib/`: 同期
  - **テスト**: 133件全パス（+9件追加: リスタート検出、フェーズ判定、テーマ抽出）

- **09:35 JST**: chatwork-webhook v10.39.2 本番デプロイ ✅ **revision 00227-fdg**
  - **概要**: 目標設定セッション中でも脳がユーザーの意図を汲み取るように改善
  - **背景**: ユーザーが目標設定中に別の話題を振っても、以前は機械的に目標設定を続行していた
  - **変更内容**:
    - `lib/brain/core.py`:
      - `_continue_goal_setting()`: 意図理解ステップを追加
      - `_is_different_intent_from_goal_setting()`: 目標設定の回答か別の意図かを判定
      - `_handle_interrupted_goal_setting()`: 中断処理とフォローアップメッセージ
    - `chatwork-webhook/main.py`:
      - `_brain_interrupt_goal_setting()`: 中断セッションの保存
      - `_brain_get_interrupted_goal_setting()`: 中断セッションの取得
      - `_brain_resume_goal_setting()`: 中断セッションの再開
      - handlers辞書に3つのハンドラーを登録
    - `Procfile`: functions-frameworkを使用するよう追加（Cloud Runデプロイ対応）
  - **効果**:
    - 脳の7原則「脳が意図を理解する」に完全準拠
    - ユーザーが途中で話題を変えても自然に対応
    - 中断されたセッションは記憶され「目標設定の続き」で再開可能
    - フォローアップメッセージ（例: 「さっきの目標設定はWHATまで進んでたウル。続きやる？」）
  - **テスト**: 構文チェックパス、25ハンドラー関数全て定義確認
  - **デプロイ**: Cloud Run（Procfile + functions-framework）
  - **旧リビジョン**: chatwork-webhook-00233-hit
  - **新リビジョン**: chatwork-webhook-00227-fdg

- **09:05 JST**: chatwork-webhook v10.39.1 本番デプロイ ✅ **revision 00233-hit** **PR #282**
  - **概要**: 3つのTODOセッション継続メソッドを完全実装
  - **変更内容**:
    - `lib/brain/core.py`: `_continue_goal_setting()`, `_continue_announcement()`, `_continue_task_pending()` を実装
    - `chatwork-webhook/lib/brain/core.py`: 同様に実装
    - `chatwork-webhook/main.py`: セッション継続ハンドラー関数を追加
      - `_brain_continue_goal_setting()`: GoalSettingDialogueと連携
      - `_brain_continue_announcement()`: AnnouncementHandlerと連携
      - `_brain_continue_task_pending()`: handle_pending_task_followup()と連携
    - handlers辞書に3つのセッション継続ハンドラーを登録
  - **設計**:
    - 脳の7原則「脳が判断し、機能は実行するだけ」に準拠
    - handlersを通じて既存のハンドラーを呼び出す設計
    - ハンドラー未登録時のフォールバックメッセージを実装
    - エラー時のセッションクリア処理を実装
  - **テスト**: 342テストパス（脳アーキテクチャ関連全て）
  - **CI**: 4チェック全てSUCCESS
  - **セキュリティレビュー**: 重大な問題なし
  - **コードレビュー**: 承認済み
  - **脳アーキテクチャ完成度**: 82% → 95%（セッション継続完了）
  - **旧リビジョン**: chatwork-webhook-00223-vt7
  - **新リビジョン**: chatwork-webhook-00233-hit
  - **デプロイ方法**: Cloud Functions gen2（gcloud functions deploy）

- **17:35 JST**: chatwork-webhook v10.39.0 本番デプロイ ✅ **revision 00223-vt7** **PR #279**
  - **概要**: バイパス処理を脳の中に統合（7原則準拠）
  - **変更内容**:
    - BrainIntegration.process_message() に bypass_handlers パラメータ追加
    - _call_bypass_handler() メソッド追加
    - main.py にバイパスハンドラー関数追加（_bypass_handle_goal_session, _bypass_handle_announcement）
    - main.py の脳より先のバイパスチェックを削除
  - **効果**:
    - 脳の7原則「全ての入力は脳を通る」に準拠
    - 目標設定セッション、アナウンス機能が脳を通って処理される
  - **旧リビジョン**: chatwork-webhook-00222（推定）
  - **新リビジョン**: chatwork-webhook-00223-vt7
  - **プロジェクト**: soulkun-production（※soulkun-chatworkではない）

- **07:18 JST**: chatwork-webhook v10.38.1 本番デプロイ ✅ **revision 00225-tel** **PR #278**
  - **概要**: 目標設定対話で長文入力時にエラーが発生するバグを修正
  - **原因**: `_update_session()` の `current_step` パラメータが必須だったが、LLM解析後に回答のみを更新する際に渡されていなかった
  - **修正内容**:
    - `current_step` をオプショナルパラメータ (`= None`) に変更
    - 渡された場合のみ UPDATE 文に含めるように条件分岐を追加
  - **影響ファイル**:
    - `chatwork-webhook/lib/goal_setting.py`
    - `lib/goal_setting.py`
    - `proactive-monitor/lib/goal_setting.py`

- **15:08 JST**: chatwork-webhook v10.38.0 本番デプロイ ✅ **revision 00216-xac**
  - **概要**: Brain-Capability統合を本番環境にデプロイ
  - **変更内容**:
    - CapabilityBridgeインポート・初期化追加
    - SYSTEM_CAPABILITIESに生成機能追加（generate_document, generate_image, generate_video）
    - _get_brain_integration()にCapabilityBridgeハンドラー統合
  - **検証結果**:
    - CapabilityBridge: 正常ロード
    - 脳アーキテクチャ: enabled=True
    - エラー: なし
  - **旧リビジョン**: chatwork-webhook-00215-lot
  - **新リビジョン**: chatwork-webhook-00216-xac

- **11:00 JST**: Brain-Capability main.py統合 ✅ **PR #272 マージ完了**
  - **概要**: CapabilityBridge を chatwork-webhook/main.py に統合
  - **SYSTEM_CAPABILITIES拡張**:
    - `generate_document`: 文書生成（Google Docs）
    - `generate_image`: 画像生成（DALL-E）
    - `generate_video`: 動画生成（Runway Gen-3、デフォルト無効）
    - `create_document`: generate_documentのエイリアス
  - **脳統合**: `_get_brain_integration()` に CapabilityBridge ハンドラーを追加
  - **テスト**: 3327件パス

- **10:30 JST**: Brain-Capability統合基盤 実装完了 ✅ **PR #271 マージ完了**
  - **概要**: 脳と機能モジュールが完全に分断されていた問題を発見し、橋渡し層を実装
  - **問題**: `lib/brain/`と`lib/capabilities/`の間にゼロインポート・ゼロ連携だった
  - **解決策**: CapabilityBridgeパターンで統合
  - **新規ファイル**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/brain/capability_bridge.py` | CapabilityBridge（マルチモーダル前処理、生成ハンドラー） |
    | `docs/brain_capability_integration_design.md` | 統合設計書（226行） |
  - **lib/brain/models.py拡張**:
    - `multimodal_context`, `generation_request` フィールド追加
    - `has_multimodal_content()`, `has_generation_request()`, `get_multimodal_summary()` メソッド追加
  - **主な機能**:
    - `preprocess_message()`: 添付ファイルのマルチモーダル前処理
    - `get_capability_handlers()`: 生成機能ハンドラー取得（document, image, video, feedback）
    - `GENERATION_CAPABILITIES`: 生成機能の定義（キーワード、パラメータ、確認フロー）
    - `DEFAULT_FEATURE_FLAGS`: 機能フラグ管理
  - **テスト**: 28件追加（`tests/test_brain_capability_bridge.py`）
  - **同期**: chatwork-webhook/lib/brain/に同期済み
  - **次のステップ**: PR #271マージ後、chatwork-webhook/main.pyへの統合

- **09:30 JST**: Phase 2K proactive-monitor バグ修正 ✅ **PR #270 マージ・デプロイ完了**
  - **概要**: ドライランログで発見した型不一致バグを修正し、本番デプロイ完了
  - **発見したバグ**:
    - `chatwork_tasks.organization_id` (VARCHAR) にUUID文字列を渡していた
    - `chatwork_tasks.assigned_to_account_id` (BIGINT) に文字列を渡していた
    - `goals.organization_id` (UUID) に`'org_soulsyncs'`文字列を渡していた
  - **修正内容** (`lib/brain/proactive.py`):
    - `ORGANIZATION_UUID_TO_SLUG` 定数追加（UUID→slugマッピング）
    - `_get_chatwork_tasks_org_id()` メソッド追加（UUID→VARCHAR変換）
    - `_get_chatwork_account_id_int()` メソッド追加（str→BIGINT変換）
    - `_is_valid_uuid()` メソッド追加（CAST前のUUID検証）
    - 5つのチェックメソッドのクエリを修正
  - **テスト**: 9件追加、49件全パス
  - **デプロイ**: proactive-monitor Cloud Function更新完了
  - **動作確認**: 53ユーザーチェック、エラーなし

### 2026-01-27

- **21:50 JST**: CEO Learning バグ修正 ✅ **CEO教えが保存されるようになった**
  - **問題**: `ceo_teachings` テーブルの `ceo_user_id` (UUID型) に ChatWork `account_id` (文字列) を渡していたためDB保存が失敗していた
  - **原因調査**:
    - Memory Framework と Brain の違いを調査
    - CEO Learning 機能は実装済みだが、型不一致で保存されていないことを発見
    - `ceo_teachings` テーブル存在確認済み、データ0件
    - 菊地さんのユーザーレコード存在確認済み (UUID: adceb2f4-69d4-40b1-baa2-fe47375525e6)
  - **修正内容**:
    - `_get_user_id_from_account_id` メソッド追加（ChatWork ID → UUID 変換）
    - `process_ceo_message` で保存前に user_id を取得
    - `_create_teaching_from_extracted` の引数を user_id に変更
  - **PR**: #268 マージ済み
  - **デプロイ**: chatwork-webhook revision 00215-lot

- **23:30 JST**: App1 議事録自動生成アプリ 実装完了 ✅ **次世代能力 App1 完全完了**
  - **概要**: Phase M2（音声入力）とPhase G1（文書生成）を統合し、音声ファイルから議事録を自動生成するアプリを実装
  - **設計書**: `docs/20_next_generation_capabilities.md` セクション7
  - **新規ファイル（6ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/capabilities/apps/__init__.py` | アプリ層パッケージ初期化 |
    | `lib/capabilities/apps/meeting_minutes/__init__.py` | パッケージエクスポート（40+エクスポート） |
    | `lib/capabilities/apps/meeting_minutes/constants.py` | MeetingType, MinutesStatus等Enum、プロンプト、セクション構成 |
    | `lib/capabilities/apps/meeting_minutes/models.py` | MeetingMinutesRequest, MeetingMinutesResult, MeetingAnalysis等 |
    | `lib/capabilities/apps/meeting_minutes/meeting_minutes_generator.py` | MeetingMinutesGenerator（M2+G1統合クラス） |
  - **Phase M2への追加（前提条件として実施）**:
    - `lib/capabilities/multimodal/constants.py`: AudioType, TranscriptionStatus, SpeakerLabel追加
    - `lib/capabilities/multimodal/exceptions.py`: 音声処理例外9種追加
    - `lib/capabilities/multimodal/models.py`: Speaker, TranscriptSegment, AudioMetadata, AudioAnalysisResult追加
    - `lib/capabilities/multimodal/__init__.py`: 音声関連エクスポート追加
  - **主な機能**:
    - 会議タイプ自動判定（10種類: 定例、プロジェクト、ブレスト、1on1等）
    - 会議タイプ別のセクション構成自動選択
    - 音声→文字起こし→分析→議事録生成の一貫処理
    - アクションアイテム・決定事項の自動抽出
    - Google Docsへの自動出力
    - 確認フロー対応（require_confirmation=True）
    - コスト計算・追跡
  - **テスト**: 42件全パス（`tests/test_meeting_minutes.py`）
  - **同期**: chatwork-webhook/lib/capabilities/apps/meeting_minutes/に同期済み

- **23:00 JST**: Phase G1 文書生成能力 実装完了 ✅ **次世代能力 Phase G1 完全完了**
  - **概要**: ソウルくんに「手」を追加。Google Docsで文書（報告書、提案書、議事録等）を自動生成できるようになった
  - **設計書**: `docs/20_next_generation_capabilities.md` セクション6.3
  - **新規ファイル（7ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/capabilities/generation/__init__.py` | パッケージエクスポート（70+エクスポート） |
    | `lib/capabilities/generation/constants.py` | Enum定義（DocumentType, GenerationStatus等）、テンプレート設定 |
    | `lib/capabilities/generation/exceptions.py` | 例外クラス（20種類: ValidationError, GoogleDocsCreateError等） |
    | `lib/capabilities/generation/models.py` | データモデル（DocumentRequest, DocumentResult, DocumentOutline等） |
    | `lib/capabilities/generation/base.py` | BaseGenerator、LLMClient（OpenRouter API連携） |
    | `lib/capabilities/generation/document_generator.py` | DocumentGenerator（アウトライン生成、セクション生成） |
    | `lib/capabilities/generation/google_docs_client.py` | GoogleDocsClient（Google Docs API連携） |
  - **主な機能**:
    - 文書タイプ自動判定（12種類: 提案書、報告書、議事録、マニュアル等）
    - アウトライン生成（LLM連携、確認フロー付き）
    - セクションごとの内容生成（品質レベル: Draft/Standard/High/Premium）
    - Google Docsへの自動出力（Markdown→Docs変換）
    - 共有設定（フォルダ移動、権限設定）
    - コスト計算・追跡
  - **テスト**: 84件全パス（`tests/test_generation.py`）
  - **同期**: chatwork-webhook/lib/capabilities/generation/に同期済み

- **22:15 JST**: Phase M2 音声入力能力 実装完了 ✅ **次世代能力 Phase M2 完全完了**
  - **概要**: ソウルくんに「耳」を追加。音声ファイルを聞いて文字起こし・話者分離・要約ができるようになった
  - **設計書**: `docs/20_next_generation_capabilities.md` セクション5.6
  - **変更ファイル（6ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/capabilities/multimodal/constants.py` | 音声関連定数追加（AudioType, TranscriptionStatus, SpeakerLabel, サポートフォーマット） |
    | `lib/capabilities/multimodal/exceptions.py` | 音声関連例外追加（9種類: AudioProcessingError, WhisperAPIError等） |
    | `lib/capabilities/multimodal/models.py` | 音声データモデル追加（Speaker, TranscriptSegment, AudioMetadata, AudioAnalysisResult） |
    | `lib/capabilities/multimodal/audio_processor.py` | **新規** AudioProcessor（Whisper API連携、文字起こし、話者分離、要約生成） |
    | `lib/capabilities/multimodal/coordinator.py` | 音声処理統合（AttachmentType.AUDIO対応） |
    | `lib/capabilities/multimodal/__init__.py` | 音声エクスポート追加 |
  - **主な機能**:
    - 音声文字起こし（OpenAI Whisper API連携）
    - 9フォーマット対応（mp3, wav, m4a, webm, mp4, mpeg, mpga, ogg, flac）
    - 話者分離（Speaker Diarization）
    - 要約・キーポイント・アクションアイテム自動抽出
    - 音声タイプ自動判定（会議、ボイスメモ、インタビュー、講義等）
    - 最大2時間、25MBまでの音声対応
  - **テスト**: 63件全パス（`tests/test_audio.py`）
  - **同期**: chatwork-webhook/lib/capabilities/multimodal/に同期済み

- **21:00 JST**: Phase F1 CEOフィードバックシステム 実装完了 ✅ **次世代能力 Phase F1 完全完了**
  - **概要**: ソウルくんに「内省」能力を追加。事実に基づいてCEOにフィードバックを提供できるようになった
  - **設計書**: `docs/20_next_generation_capabilities.md` セクション8
  - **新規ファイル（8ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/capabilities/feedback/__init__.py` | パッケージエクスポート（60+エクスポート） |
    | `lib/capabilities/feedback/constants.py` | Enum定義、テンプレート、Feature Flag |
    | `lib/capabilities/feedback/models.py` | ファクト・分析・フィードバックモデル |
    | `lib/capabilities/feedback/fact_collector.py` | FactCollector（データ収集） |
    | `lib/capabilities/feedback/analyzer.py` | Analyzer（異常検知・トレンド分析） |
    | `lib/capabilities/feedback/feedback_generator.py` | FeedbackGenerator（LLMフィードバック生成） |
    | `lib/capabilities/feedback/delivery.py` | FeedbackDelivery（ChatWork配信） |
    | `lib/capabilities/feedback/ceo_feedback_engine.py` | CEOFeedbackEngine（統合クラス） |
  - **DBマイグレーション**: `migrations/phase_f1_ceo_feedback.sql`
    - `feedback_deliveries`: 配信ログ（18カラム、6インデックス）
    - `feedback_settings`: フィードバック設定（20カラム、3インデックス）
    - `feedback_alert_cooldowns`: アラートクールダウン管理（9カラム、2インデックス）
    - `feedback_delivery_stats`: 配信統計ビュー
  - **主な機能**:
    - デイリーダイジェスト（毎朝8:00）
    - ウィークリーレビュー（毎週月曜9:00）
    - マンスリーインサイト（毎月1日9:00）
    - リアルタイムアラート（異常検知時）
    - オンデマンド分析（「最近どう？」）
  - **フィードバック原則（6つ）**:
    1. 事実ファースト - 「〜と思います」ではなく「〜というデータがあります」
    2. 数字で語る - 具体的な数値変化を提示
    3. 比較を入れる - 先週比、先月比、過去パターンとの比較
    4. 仮説は仮説と明示 - 「〜かもしれません」と断定しない
    5. アクション提案 - 問題提起だけでなく「こうしては？」まで
    6. ポジティブも伝える - 良いことも報告
  - **テスト**: 57件全パス（`tests/test_feedback.py`）
  - **同期**: chatwork-webhook/lib/capabilities/feedback/に同期済み

- **18:00 JST**: Phase M1 脳との統合 実装完了 ✅ **次世代能力 Phase M1 完全完了**
  - **概要**: Multimodal処理を脳（SoulkunBrain）と統合
  - **新規ファイル（2ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/capabilities/multimodal/coordinator.py` | MultimodalCoordinator（処理統括） |
    | `lib/capabilities/multimodal/brain_integration.py` | 脳統合関数・コンテキスト |
  - **主な機能**:
    - MultimodalCoordinator: ファイルタイプ判定、プロセッサー選択、並列処理
    - EnrichedMessage: 元メッセージ+マルチモーダル結果の統合
    - MultimodalBrainContext: 脳が参照するマルチモーダルコンテキスト
    - handle_chatwork_message_with_attachments: ChatWork連携用統合関数
  - **テスト**: 80件全パス（+25件追加）
  - **同期**: chatwork-webhook/lib/capabilities/multimodal/に同期済み

- **17:45 JST**: Phase M1 Multimodal入力能力 実装完了 ✅ **次世代能力 1/4 完了**
  - **概要**: ソウルくんに「目」を追加。画像・PDF・URLを理解できるようになった
  - **設計書**: `docs/20_next_generation_capabilities.md` セクション5
  - **新規ファイル（10ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/capabilities/__init__.py` | 能力層パッケージ初期化 |
    | `lib/capabilities/multimodal/__init__.py` | パッケージエクスポート |
    | `lib/capabilities/multimodal/constants.py` | Enum定義、制限値、Vision APIモデル |
    | `lib/capabilities/multimodal/exceptions.py` | 25種類の例外クラス、デコレータ |
    | `lib/capabilities/multimodal/models.py` | 15種類のデータモデル |
    | `lib/capabilities/multimodal/base.py` | BaseMultimodalProcessor、VisionAPIClient |
    | `lib/capabilities/multimodal/image_processor.py` | ImageProcessor（Vision API連携） |
    | `lib/capabilities/multimodal/pdf_processor.py` | PDFProcessor（テキスト/OCR対応） |
    | `lib/capabilities/multimodal/url_processor.py` | URLProcessor（セキュリティチェック付き） |
  - **DBマイグレーション**: `migrations/phase_m1_multimodal.sql`
    - `multimodal_processing_logs`: 処理ログ（26カラム、8インデックス、RLS）
    - `multimodal_extracted_entities`: 抽出エンティティ（14カラム、7インデックス）
    - `v_multimodal_stats`: 統計情報ビュー
    - `cleanup_old_multimodal_logs()`: クリーンアップ関数
  - **主な機能**:
    - 画像処理: フォーマット検証、メタデータ抽出、Vision API分析、エンティティ抽出
    - PDF処理: テキスト/スキャン判定、pypdf抽出、OCR対応、ページ分析
    - URL処理: セキュリティチェック、HTMLパース、コンテンツ分析、タイプ判定
    - 共通: 処理ログ記録、エンティティ正規化、コスト追跡
  - **テスト**: 55件全パス（`tests/test_multimodal.py`）
  - **同期**: chatwork-webhook/lib/capabilities/に同期済み

- **17:30 JST**: Phase 2G Memory Enhancement 実装完了 ✅ **脳みそ完全化計画 4/11 完了**
  - **概要**: エピソード記憶と知識グラフの基盤を構築
  - **設計書**: `docs/17_brain_completion_roadmap.md` セクション Phase 2G
  - **新規ファイル（5ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/brain/memory_enhancement/__init__.py` | BrainMemoryEnhancement統合クラス |
    | `lib/brain/memory_enhancement/constants.py` | Enum定義、閾値定数 |
    | `lib/brain/memory_enhancement/models.py` | Episode, KnowledgeNode, KnowledgeEdge等 |
    | `lib/brain/memory_enhancement/episode_repository.py` | EpisodeRepository（エピソード永続化） |
    | `lib/brain/memory_enhancement/knowledge_graph.py` | KnowledgeGraph（知識グラフ管理） |
  - **DBマイグレーション**: `migrations/phase2g_memory_enhancement.sql`
    - `brain_episodes`: エピソード記憶（17カラム、5インデックス）
    - `brain_episode_entities`: エピソード-エンティティ関連（9カラム、2インデックス）
    - `brain_knowledge_nodes`: 知識グラフノード（14カラム、4インデックス）
    - `brain_knowledge_edges`: 知識グラフエッジ（15カラム、3インデックス）
    - `brain_temporal_events`: 時系列イベント（15カラム、4インデックス）
    - `brain_temporal_comparisons`: 時系列比較（17カラム、2インデックス）
    - `brain_memory_consolidations`: 記憶統合ログ（14カラム、3インデックス）
  - **主な機能**:
    - エピソード記憶の保存・想起（キーワード、エンティティ、時間ベース）
    - 知識グラフの構築（ノード、エッジ、サブグラフ取得）
    - 記憶の減衰・忘却（人間の記憶をモデル化）
    - 便利メソッド（record_achievement, record_failure等）
  - **テスト**: 38件全パス
  - **同期**: chatwork-webhook/lib/brain/memory_enhancement/に同期済み
  - **脳みそ完全化計画 進捗**: 4/11 Phase完了（2D, 2E, 2F, 2G）

- **18:00 JST**: Phase 2F Outcome Learning 実装完了 ✅ **脳みそ完全化計画 3/11 完了**
  - **概要**: 暗黙のフィードバックから学ぶ仕組みを構築
  - **設計書**: `docs/17_brain_completion_roadmap.md` セクション Phase 2F
  - **新規ファイル（8ファイル）**:
    | ファイル | 説明 |
    |---------|------|
    | `lib/brain/outcome_learning/__init__.py` | BrainOutcomeLearning統合クラス |
    | `lib/brain/outcome_learning/constants.py` | Enum定義、閾値定数 |
    | `lib/brain/outcome_learning/models.py` | OutcomeEvent, OutcomePattern等 |
    | `lib/brain/outcome_learning/repository.py` | OutcomeRepository（DB永続化） |
    | `lib/brain/outcome_learning/tracker.py` | OutcomeTracker（行動結果追跡） |
    | `lib/brain/outcome_learning/implicit_detector.py` | ImplicitFeedbackDetector（暗黙FB検出） |
    | `lib/brain/outcome_learning/pattern_extractor.py` | PatternExtractor（成功パターン抽出） |
    | `lib/brain/outcome_learning/analyzer.py` | OutcomeAnalyzer（結果分析） |
  - **DBマイグレーション**: `migrations/phase2f_outcome_learning.sql`
    - `brain_outcome_events`: 行動結果イベント記録（15カラム、4インデックス）
    - `brain_outcome_patterns`: 成功/失敗パターン保存（16カラム、5インデックス）
  - **主な機能**:
    - 通知・提案のイベント記録と結果追跡
    - 暗黙フィードバック検出（採用/無視/遅延/拒否）
    - 時間帯・曜日パターンの自動抽出
    - 確信度計算（Wilson score interval簡易版）
    - パターンの学習への昇格（brain_learningsと連携）
  - **テスト**: 32件全パス
  - **同期**: chatwork-webhook/lib/brain/outcome_learning/に同期済み
  - **脳みそ完全化計画 進捗**: 3/11 Phase完了（2D, 2E, 2F）

- **17:00 JST**: 次世代能力設計書 作成完了 ✅ **docs/20_next_generation_capabilities.md**
  - **概要**: ソウルくんを「会社を一番理解し、デジタル上で何でもできるAI」に進化させるための設計書
  - **含まれるPhase**:
    - **スマートモデル管理**: 最新AIモデルを最適コストで利用（3-4週間）
    - **Phase M (Multimodal)**: 画像/PDF/URL読み込み（4-5週間）
    - **Phase G (Generation)**: 資料/画像/動画生成、ディープリサーチ（5-6週間）
    - **Phase F (Feedback)**: CEOへの事実ベースフィードバック（4-5週間）
    - **Phase AA (Autonomous Agent)**: 自律エージェント、バックグラウンド実行（6-8週間）
  - **設計原則**: 統合 > 構築（AIを自作せず既存APIを賢く統合）
  - **脳との関係**: 脳の構造を変えずに能力を追加（並行開発可能）
  - **合計工数**: 22-28週間
  - **関連更新**: docs/02_phase_overview.md に次世代能力群を追加

- **15:45 JST**: Phase 2D/2E 本番デプロイ + pg8000互換性修正 ✅ **PR #242 マージ完了**
  - **実施者**: Claude Code
  - **概要**: Phase 2D（CEO Learning）とPhase 2E（Learning Foundation）を本番デプロイ、pg8000 SQL構文互換性問題を修正
  - **本番デプロイ**:
    - chatwork-webhook revision **00214-dah**
    - brain_conversation_states DBテーブル作成
    - Phase 2D/2E機能が本番稼働開始
  - **pg8000互換性修正**（6ファイル）:
    | ファイル | 修正内容 |
    |---------|---------|
    | lib/memory/conversation_search.py | `:entities::jsonb` → `CAST(:entities AS jsonb)` |
    | lib/memory/user_preference.py | `:pref_value::jsonb` → `CAST(:pref_value AS jsonb)` |
    | lib/brain/memory_access.py | `:org_id::uuid` → `CAST(:org_id AS uuid)` (5箇所) |
    | chatwork-webhook/lib/* | 上記ファイルの同期 |
  - **DBマイグレーション**: brain_conversation_statesテーブル作成（13カラム、3インデックス、トリガー）
  - **Quality Checks**: 4/4 パス
  - **10の鉄則準拠**: SQL構文修正のみ、organization_idフィルタ維持

- **16:30 JST**: Phase 2D + Phase 2E 完了確認 ✅ **脳みそ完全化計画 2/11 完了**
  - **概要**: Phase 2D（CEO Learning）とPhase 2E（Learning Foundation）の完了を確認
  - **Phase 2D CEO Learning**:
    | 項目 | 状態 | 詳細 |
    |------|------|------|
    | DBマイグレーション | ✅ 完了 | 4テーブル、21制約、27インデックス |
    | コード実装 | ✅ 完了 | ceo_learning.py, ceo_teaching_repository.py, guardian.py |
    | 脳統合 | ✅ 完了 | core.pyにCEOLearningService, GuardianService統合 |
    | テスト | ✅ 完了 | 56件全パス |
    | 同期 | ✅ 完了 | chatwork-webhook/lib/brain/に同期済み |
  - **Phase 2E Learning Foundation**:
    | 項目 | 状態 | 詳細 |
    |------|------|------|
    | コード実装 | ✅ 完了 | 12ファイル（lib/brain/learning_foundation/） |
    | テスト | ✅ 完了 | 119件全パス |
    | 同期 | ✅ 完了 | chatwork-webhook/lib/brain/learning_foundation/に同期済み |
  - **Phase 2E ファイル一覧**:
    - `__init__.py` (19KB) - エクスポート
    - `applier.py` (24KB) - 学習適用
    - `authority_resolver.py` (16KB) - 権限解決
    - `conflict_detector.py` (18KB) - 矛盾検出
    - `constants.py` (11KB) - 定数
    - `detector.py` (20KB) - 学習検出
    - `effectiveness_tracker.py` (19KB) - 効果追跡
    - `extractor.py` (17KB) - 学習抽出
    - `manager.py` (21KB) - 学習管理
    - `models.py` (19KB) - データモデル
    - `patterns.py` (20KB) - パターン
    - `repository.py` (37KB) - リポジトリ
  - **脳みそ完全化計画 進捗**: 2/11 Phase完了（2D, 2E）
  - **次のステップ**: Phase 2F（結果からの学習）の実装

- **15:00 JST**: Ultimate Brain Phase 3 - Multi-Agent System (v10.37.0) ✅ **PR #239 マージ完了**
  - **概要**: 脳アーキテクチャの「究極の脳」Phase 3実装 - マルチエージェントシステム
  - **設計書**: `docs/19_ultimate_brain_architecture.md` セクション5.3
  - **新規ファイル（9ファイル、計6,364行）**:
    | ファイル | 行数 | 説明 |
    |---------|------|------|
    | `lib/brain/agents/__init__.py` | 301 | エクスポート定義 |
    | `lib/brain/agents/base.py` | 801 | 基盤クラス（AgentType, BaseAgent, AgentMessage等） |
    | `lib/brain/agents/orchestrator.py` | 784 | 全エージェントを統括する脳 |
    | `lib/brain/agents/task_expert.py` | 772 | タスク管理の専門家 |
    | `lib/brain/agents/goal_expert.py` | 826 | 目標達成支援の専門家 |
    | `lib/brain/agents/knowledge_expert.py` | 555 | ナレッジ管理の専門家 |
    | `lib/brain/agents/hr_expert.py` | 706 | 人事・労務の専門家 |
    | `lib/brain/agents/emotion_expert.py` | 836 | 感情ケアの専門家 |
    | `lib/brain/agents/organization_expert.py` | 783 | 組織構造の専門家 |
  - **追加機能**:
    - 7種類の専門家エージェント群
    - エージェント間通信プロトコル（AgentMessage, AgentResponse）
    - 能力ベースのルーティング（キーワードスコアリング）
    - 並列実行サポート
  - **関連モジュール（同時追加）**:
    - `lib/brain/learning_loop.py`: 学習ループ（失敗分析・改善提案）
    - `lib/brain/org_graph.py`: 組織グラフ（人間関係・信頼度追跡）
  - **効果**: ソウルくんが専門家エージェントを持ち、より適切な担当者に処理を委譲できるようになった
  - **テスト**: 102件のユニットテスト（全パス）、全体2513件パス
  - **10の鉄則準拠**: organization_id必須、フォールバック設計、エラー分離

- **14:00 JST**: Ultimate Brain Phase 2 - Confidence, Episodic Memory, Proactive (v10.35.0) ✅ **PR #237 マージ完了**
  - **概要**: 脳アーキテクチャの「究極の脳」Phase 2実装 - 確信度・記憶・能動性
  - **確信度キャリブレーション** (`lib/brain/confidence.py` - 532行):
    - RiskLevel: HIGH=0.85, NORMAL=0.70, LOW=0.50の3段階閾値
    - ConfidenceAction: EXECUTE/CONFIRM/CLARIFY/DECLINEの4段階判断
    - 曖昧表現検出（AMBIGUOUS_PATTERNS）
    - 確認メッセージテンプレート（CONFIRMATION_TEMPLATES）
  - **エピソード記憶** (`lib/brain/episodic_memory.py` - 679行):
    - EpisodeType: 達成/失敗/決定/対話/学習/感情の6種類
    - 忘却係数（DECAY_RATE_PER_DAY=0.02）で時間経過で記憶が薄れる
    - キーワード・エンティティ・時間によるマルチモーダル想起
    - 重要度スコア計算（基本値+キーワード+感情ボーナス）
    - 便利メソッド: record_achievement(), record_failure(), record_learning()
  - **能動的モニタリング** (`lib/brain/proactive.py` - 950行):
    - TriggerType: 目標放置(7日)/タスク山積み(5件)/感情変化(3日)/目標達成/質問未回答/長期不在/習慣途絶
    - メッセージクールダウン（GOAL_ABANDONED: 72h, TASK_OVERLOAD: 48h, EMOTION: 24h）
    - DMルームへの自動メッセージ送信（dry_runモードあり）
    - ProactiveMessageType: follow_up, encouragement, reminder, celebration, check_in
  - **効果**: ソウルくんが「判断に自信がない時は確認」「重要な出来事を記憶」「自らユーザーに声をかける」能力を獲得
  - **テスト**: 93件（confidence: 18件, episodic_memory: 35件, proactive: 40件）、全体693件パス

- **13:40 JST**: Ultimate Brain Phase 1 - Chain-of-Thought & Self-Critique (v10.34.0) ✅ **PR #235 マージ完了**
  - **概要**: 脳アーキテクチャの「究極の脳」Phase 1実装 - 思考連鎖と自己批判
  - **設計書**: `docs/19_ultimate_brain_architecture.md`（新規）
  - **Chain-of-Thought** (`lib/brain/chain_of_thought.py` - 450行):
    - 5ステップ思考連鎖で入力を段階的に分析
    - 入力分類（8種: question, request, report, confirmation, emotion, chat, command, unknown）
    - 構造分析（疑問文、命令文、否定形、条件形）
    - 意図推論（キーワードマッチング + ネガティブキーワード）
    - コンテキスト照合（状態依存の判断）
    - 結論導出（確信度ベース）
  - **Self-Critique** (`lib/brain/self_critique.py` - 580行):
    - 6品質基準で回答を評価・改善
    - relevance（関連性）、completeness（完全性）、consistency（一貫性）
    - tone（ソウルくんらしさ - ウル表現）、actionability（実行可能性）、safety（機密情報検出）
  - **効果**: 「目標設定として繋がってる？」のような曖昧な入力を正しく解釈
  - **テスト**: 90件（chain_of_thought: 44件, self_critique: 46件）、全体2199件パス

- **18:30 JST**: Phase 1 旧コード削除 (v10.33.0) ✅ **PR #224 マージ完了**
  - **概要**: chatwork-webhook/main.pyから不要になった旧コード（フォールバック、未使用関数）を削除
  - **削減結果**: main.py 9,198行 → 8,751行 (**-447行削減**)
  - **削除内容**:
    - ハンドラーインポートフォールバック（7個）
    - ハンドラー初期化フラグチェック（7箇所）
    - USE_ANNOUNCEMENT_FEATURE参照（3箇所）
    - ユーティリティフォールバック（date_utils, chatwork_utils）
    - 未使用ナレッジ関数（4関数、約320行）
    - 未使用ラッパー関数（notify_proposal_result）
  - **設計書**: docs/16_old_code_removal_plan.md
  - **備考**: 目標500行に対し447行。execute_action()フォールバックはPhase 2で削除予定

- **12:00 JST**: Phase 2E-2O 脳みそ完全化計画 ロードマップ文書化 ✅ **PR #223 マージ完了**
  - **概要**: 超絶優秀な秘書の脳を作るための10フェーズ計画を文書化
  - **作成**: `docs/17_brain_completion_roadmap.md`（466行）
  - **更新**: `docs/02_phase_overview.md`（Phase 2E-2O追加）、`PROGRESS.md`（Phase一覧更新）
  - **Phase一覧**: 2E学習基盤 → 2F結果学習 → 2G記憶強化 → 2H自己認識 → 2I理解力 → 2J判断力 → 2K能動性 → 2L実行力 → 2M対人力 → 2N自己最適化 → 2O統合創発
  - **期間**: 2026年1月〜12月

- **11:45 JST**: lib/ 同期監査 + 相対インポート統一 (v10.32.2) ✅ **PR #226 マージ完了**
  - **概要**: 全9つのCloud Functionsのlib/ディレクトリを包括的に監査し、相対インポートに統一
  - **発見事項**: chatwork-webhookのv10.31.4改善（相対インポート）がルートlib/に未反映だった
  - **修正内容**:
    - `lib/db.py`: `from lib.config` → `from .config`（googleapiclient警告修正）
    - `lib/secrets.py`: `from lib.config` → `from .config`
    - `lib/admin_config.py`: `from lib.db` → `from .db`
  - **同期**: 8つのCloud Functionsに`db.py`, `secrets.py`を同期
  - **監査結果**: 107ファイル中98件同期済み、9件は意図的差分（__init__.py）
  - **監査レポート**: `docs/lib_sync_audit_report_20260127.md`

- **10:40 JST**: Phase 2D CEO Learning & Guardian 実装 (v10.32.1) ✅ **PR #220/PR #221 マージ完了**
  - **概要**: CEOの日常会話から「教え」を抽出し、スタッフへのアドバイスに活用する機能
  - **PR #220**: Phase 2D基盤実装
    - `lib/brain/ceo_learning.py`: CEOLearningService（教え抽出、カテゴリ分類）
    - `lib/brain/guardian.py`: GuardianService（MVV・選択理論・SDT検証）
    - `lib/brain/ceo_teaching_repository.py`: CEOTeachingRepository（CRUD操作）
    - `lib/brain/models.py`: 15のTeachingCategory、CEOTeaching、CEOTeachingContext
    - `migrations/phase2d_ceo_learning.sql`: DBテーブル定義
    - 56件のユニットテスト
  - **PR #221**: SoulkunBrain統合
    - `lib/brain/core.py`: CEO Learning層の初期化・処理統合
    - CEOからのメッセージで教え抽出（非同期・非ブロッキング）
    - 関連CEO教えをコンテキストに自動追加
  - **表現ルール**: 「カズさんが言っていた」→「ソウルシンクスとして大事にしていること」
  - **テスト**: 481件のbrainテスト全パス、1,951件全体テストパス

- **15:30 JST**: CLAUDE.md プラグインメイン化リファクタリング ✅ **PR #218 マージ完了**
  - everything-claude-codeプラグインをメイン開発フレームワークとして明示
  - CLAUDE.md: 2899行 → 335行（ソウルくん固有ルールのみ）
  - PROGRESS.md: 新規作成（294行、進捗記録を分離）
  - 合計78%削減（2899行 → 629行）

- **12:30 JST**: ハンドラーフォールバック削除 (v10.32.0) ✅ **PR #216 マージ完了**
  - chatwork-webhook/main.pyから旧ハンドラーフォールバックコードを削除し、約1,749行を削減
  - 6ハンドラー、33関数のフォールバック削除

- **11:00 JST**: Claude Code開発環境改善 ✅ **設定完了**
  - everything-claude-codeプラグインをインストール
  - Agents（10種）、Commands（15種）、Skills（14種）、Hooks（自動実行）

- **10:30 JST**: 目標設定機能 DB制約修正 + 開始キーワード検出 (v10.31.6) ✅ **PR #213 マージ完了**
  - DB制約違反修正: `cancelled` → `abandoned`
  - 開始キーワード検出: 「目標設定したい」等で新規セッション開始

- **10:15 JST**: Phase 2D設計書「会社の教えとして伝える」原則追加 ✅ **PR #212 マージ完了**

- **08:00 JST**: 脳アーキテクチャ本番バグ2件修正 (v10.31.5) ✅ **本番デプロイ完了**
  - SQL構文エラー（state_manager.py）: `:state_data::jsonb` → `CAST(:state_data AS jsonb)`
  - dict属性エラー（understanding.py）: dict/オブジェクト両対応に変更

- **07:15 JST**: googleapiclient警告修正 (v10.31.4) ✅ **本番デプロイ完了**
  - 31ファイルの絶対インポートを相対インポートに変更

- **06:45 JST**: 脳アーキテクチャ 本番有効化 (v10.31.3) ✅ **本番デプロイ完了**
  - `USE_BRAIN_ARCHITECTURE=true`で本番稼働開始

- **06:05 JST**: 脳アーキテクチャ シャドウモードデプロイ (v10.31.2) ✅ **本番デプロイ完了**

- **03:30 JST**: Phase 2D CEO Learning 設計書修正 ✅ **完了**

- **00:45 JST**: Phase D 接続設定集約 (v10.31.1) ✅ **本番デプロイ完了**
  - 8つのmain.pyからハードコードされたDB接続設定を削除
  - lib/db.py + lib/config.pyで一元管理

### 2026-01-26

- **22:30 JST**: Phase B 脳アーキテクチャ CAPABILITY_KEYWORDS統合 (v10.30.0) ✅ **PR #198 マージ完了**

- **22:00 JST**: Phase C Feature Flag集約 (v10.31.0) ✅ **完了**
  - lib/feature_flags.py新規作成（525行）
  - 22フラグを5カテゴリで管理

- **21:15 JST**: Phase A 管理者設定のDB化 本番デプロイ (v10.30.1) ✅ **本番デプロイ完了**
  - organization_admin_configsテーブル作成

- **21:00 JST**: 脳アーキテクチャ本番統合 (v10.29.0) ✅ **PR #170 マージ完了**

- **19:46 JST**: Phase 4準備 - ユーザーテーブル設計修正 (v10.30.0) ✅ **本番デプロイ完了**

- **19:45 JST**: Google Drive権限管理 監査ログ・キャッシュ・テナント分離改善 (v10.28.0) ✅ **PR #194 マージ完了**

- **17:35 JST**: 脳アーキテクチャ アクション名不整合修正 (v10.29.9) ✅ **本番デプロイ完了**

- **15:45 JST**: org-chart × Soul-kun ChatWork ID連携 (v10.29.1) ✅ **本番適用完了**

- **15:15 JST**: Google Drive 認識できないフォルダ アラート機能 (v10.28.0) ✅ **本番デプロイ完了**

- **14:10 JST**: Google Drive 動的部署マッピング pg8000互換性修正 (v10.27.5) ✅ **本番デプロイ完了**

- **13:30 JST**: 脳アーキテクチャ Phase H 完了 (v10.28.8) ✅ **全Phase完了**

- **12:30 JST**: 脳アーキテクチャ Phase B 完了 (v10.28.1) ✅ **PR #161 マージ完了**

- **11:55 JST**: 脳アーキテクチャ Phase A 完了 (v10.28.0) ✅ **PR #160 マージ完了**

- **10:30 JST**: CI/CD強化 - デバッグprint検出 (v10.27.3) ✅ **PR #152 マージ完了**

- **10:25 JST**: v10.27.2 本番デプロイ完了 ✅ **6つのCloud Functions**

- **10:15 JST**: デバッグprint文削除 (v10.27.2) ✅ **PR #148 マージ完了**

- **07:45 JST**: アナウンス タスク対象者指定バグ修正 (v10.26.3) ✅ **本番デプロイ完了**

- **07:35 JST**: アナウンス確認フロー メッセージ修正機能 (v10.26.2) ✅ **本番デプロイ完了**

- **07:22 JST**: アナウンス機能 MVVベースメッセージ変換 + BUG-003修正 (v10.26.1) ✅ **本番デプロイ完了**

- **07:15 JST**: タスク要約 AI summary優先使用 (v10.27.0) ✅ **本番デプロイ完了**

- **06:28 JST**: アナウンス機能ルームマッチングバグ修正 (BUG-002) ✅ **本番デプロイ完了**

### 2026-01-25

- **21:00 JST**: Phase X DBマイグレーション実行完了 ✅ **本番環境適用**

- **20:35 JST**: PR #131〜#133 マージ完了 ✅

- **20:10 JST**: Phase X アナウンス機能 本番デプロイ完了 (v10.26.0) ✅ **PR #127/PR #129/PR #130**

- **18:30 JST**: タスク要約 助詞終了バグ修正 (v10.25.5) ✅ **本番デプロイ完了**

- **17:15 JST**: タスクsummaryバリデーション強化 (v10.25.1) ✅ **PR #118**

- **16:00 JST**: テスト修正 1033件全パス達成 ✅ **PR #113**

- **15:30 JST**: タスク要約切り詰めバグ 完全修正 ✅ **PR #108, #111, #112**

- **14:45 JST**: org-chart 完璧プラン設計書 v2.0.0 ✅ **PR #109**

- **14:30 JST**: Phase 3.5 バグ修正 + 96件テスト追加 ✅ **PR #102**

- **12:22 JST**: google-genai SDK移行 本番デプロイ完了 ✅ **PR #101**

- **12:15 JST**: google-genai SDK移行 ✅ **PR #99**

- **11:45 JST**: Pinecone IDパースのバグ修正 ✅ **PR #97**

- **11:10 JST**: 土日祝日リマインドスキップ機能 本番デプロイ完了 ✅ **PR #95**

- **10:50 JST**: タスク要約途切れバグ修正 本番デプロイ完了 ✅ **PR #93**

- **10:25 JST**: Phase 4前リファクタリング 本番デプロイ完了 ✅ **v10.24.7**

### 2026-01-24以前

詳細は `docs/CHANGELOG.md` を参照してください。

---

## 関連リポジトリ

| リポジトリ | 用途 | パス |
|-----------|------|------|
| soul-kun | メインバックエンド | `/Users/kikubookair/soul-kun` |
| org-chart | 組織図フロントエンド | `/Users/kikubookair/Desktop/org-chart` |

---

## 進捗記録の更新ルール

作業完了時、このファイルを更新してください：

### 更新タイミング
- PRをマージした時
- 新機能を実装した時
- バグ修正を完了した時
- 本番デプロイを実行した時

### 記録フォーマット
```markdown
- **HH:MM JST**: [作業タイトル] (バージョン) ✅ **完了/PR #XX**
  - 概要（1-2行）
```

### 更新手順
1. 「直近の主な成果」の該当日付の**先頭**に新しいエントリを追加
2. 最終更新日時を更新
3. 関連するPhase一覧の状態を更新（該当する場合）
