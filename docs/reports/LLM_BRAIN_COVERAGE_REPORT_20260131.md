# LLM Brain テストカバレッジレポート

**作成日:** 2026-01-31
**対象バージョン:** v10.50.0
**テスト数:** 167テスト（全パス）

---

## 1. サマリー

| ファイル | 行数 | 未カバー | カバレッジ | 評価 |
|----------|------|----------|------------|------|
| **llm_brain.py** | 280 | 48 | **83%** | ✅ 良好 |
| **tool_converter.py** | 117 | 12 | **90%** | ✅ 優秀 |
| **guardian_layer.py** | 167 | 38 | **77%** | ⚠️ 改善推奨 |
| **context_builder.py** | 287 | 67 | **77%** | ⚠️ 改善推奨 |
| **state_manager.py** | 314 | 178 | **43%** | ❌ 要改善 |
| **constants.py** | 85 | 8 | **91%** | ✅ 優秀 |

**全体カバレッジ（lib/brain全体）:** 28%
**LLM Brain コアファイルのみ:** 75%

---

## 2. 詳細分析

### 2.1 llm_brain.py (83%)

**カバー済み:**
- ToolCall, ConfidenceScores, LLMBrainResult データクラス
- LLMBrain初期化・閾値設定
- process() メソッド（モック使用）
- 確信度抽出ロジック
- System Prompt構築
- Tool変換ロジック
- エラーハンドリング（レート制限、無効レスポンス）
- ファクトリ関数

**未カバー（要テスト追加）:**
| 行番号 | 内容 | 優先度 |
|--------|------|--------|
| 717-767 | `_call_openrouter()` HTTP呼び出し | 高 |
| 793-836 | `_call_anthropic()` HTTP呼び出し | 高 |
| 879-881 | ストリーミングレスポンス処理 | 中 |
| 1016-1024 | レスポンス解析エッジケース | 中 |
| 1161-1166 | エラーリカバリー | 低 |

### 2.2 tool_converter.py (90%)

**カバー済み:**
- 基本初期化
- 型マッピング
- convert_all() / convert_one()
- 必須パラメータ処理
- 危険操作判定
- 確認要否判定

**未カバー:**
| 行番号 | 内容 | 優先度 |
|--------|------|--------|
| 131-132, 140-142 | エッジケース（空パラメータ） | 低 |
| 277-278 | 日付フォーマットヒント | 低 |

### 2.3 guardian_layer.py (77%)

**カバー済み:**
- GuardianAction, GuardianResult データクラス
- 危険操作定義
- セキュリティNGパターン
- check() メソッド基本フロー
- 確認質問生成

**未カバー（要テスト追加）:**
| 行番号 | 内容 | 優先度 |
|--------|------|--------|
| 409-426 | `_check_amount_and_recipients()` | 高 |
| 431-440 | `_check_consistency()` | 高 |
| 466-510 | `_check_date_validity()` | 高 |
| 355-360 | CEO教示の適用ロジック | 中 |
| 572 | メトリクス記録 | 低 |

### 2.4 context_builder.py (77%)

**カバー済み:**
- Message, UserPreferences, PersonInfo, TaskInfo, GoalInfo, CEOTeaching, SessionState データクラス
- LLMContext 基本構築
- to_prompt_string() 基本出力

**未カバー:**
| 行番号 | 内容 | 優先度 |
|--------|------|--------|
| 423-451 | DB連携（タスク取得） | 中 |
| 511-630 | 会話履歴取得 | 中 |
| 669-685 | CEO教示取得 | 中 |

### 2.5 state_manager.py (43%)

**カバー済み:**
- LLMSessionMode, LLMPendingAction, LLMSessionState データクラス
- LLMStateManager 初期化
- 承認/拒否キーワード判定
- get_llm_session()（モック使用）
- set_pending_action() / clear_pending_action()
- handle_confirmation_response()

**未カバー（要テスト追加）:**
| 行番号 | 内容 | 優先度 |
|--------|------|--------|
| 119-186 | BrainStateManager.get_current_state() DB操作 | 高 |
| 222-305 | BrainStateManager.transition_to() DB操作 | 高 |
| 345-378 | BrainStateManager._clear_state_sync() | 中 |
| 406-506 | BrainStateManager.update_step() | 中 |
| 523-540 | cleanup_expired_states() | 低 |

---

## 3. テスト追加計画

### 3.1 優先度：高（次スプリントで対応）

#### A. API呼び出しテスト（llm_brain.py）

```python
# tests/test_llm_brain_api_calls.py

class TestOpenRouterAPICall:
    """OpenRouter API呼び出しのテスト"""

    @patch('httpx.AsyncClient.post')
    async def test_call_openrouter_success(self):
        """正常なAPI呼び出し"""

    @patch('httpx.AsyncClient.post')
    async def test_call_openrouter_rate_limit(self):
        """レート制限エラーのリトライ"""

    @patch('httpx.AsyncClient.post')
    async def test_call_openrouter_timeout(self):
        """タイムアウト処理"""

class TestAnthropicAPICall:
    """Anthropic API呼び出しのテスト"""

    @patch('anthropic.AsyncAnthropic')
    async def test_call_anthropic_success(self):
        """正常なAPI呼び出し"""

    @patch('anthropic.AsyncAnthropic')
    async def test_call_anthropic_invalid_api_key(self):
        """無効なAPIキー"""
```

#### B. Guardian Layer検証テスト（guardian_layer.py）

```python
# tests/test_llm_brain_guardian_validation.py

class TestAmountAndRecipientsCheck:
    """金額・宛先の妥当性検証"""

    def test_check_high_amount_requires_confirmation(self):
        """高額操作は確認が必要"""

    def test_check_many_recipients_requires_confirmation(self):
        """多数の宛先への送信は確認が必要"""

class TestConsistencyCheck:
    """パラメータ整合性検証"""

    def test_check_conflicting_parameters(self):
        """矛盾するパラメータの検出"""

class TestDateValidityCheck:
    """日付妥当性検証"""

    def test_check_past_date_warning(self):
        """過去日付の警告"""

    def test_check_far_future_date_warning(self):
        """遠い未来の日付の警告"""
```

### 3.2 優先度：中（2スプリント内で対応）

- context_builder.py のDB連携テスト（モック使用）
- state_manager.py のDB操作テスト（モック使用）
- ストリーミングレスポンス処理テスト

### 3.3 優先度：低（将来対応）

- メトリクス記録テスト
- 日付フォーマットヒントテスト
- エラーリカバリーテスト

---

## 4. 推奨アクション

1. **即座に対応:** API呼び出しのモックテスト追加（Task #8）
2. **今週中:** Guardian Layer検証メソッドのテスト追加
3. **来週:** state_manager.py のカバレッジ向上（目標: 70%）
4. **継続:** 全体カバレッジを50%以上に引き上げ

---

## 5. 付録: カバレッジ実行コマンド

```bash
# LLM Brainコアファイルのみ
python3 -m pytest tests/test_llm_brain*.py \
  --cov=lib/brain/llm_brain \
  --cov=lib/brain/guardian_layer \
  --cov=lib/brain/tool_converter \
  --cov=lib/brain/context_builder \
  --cov=lib/brain/state_manager \
  --cov-report=term-missing \
  --cov-report=html:coverage_html

# lib/brain全体
python3 -m pytest tests/test_llm_brain*.py \
  --cov=lib/brain \
  --cov-report=term-missing
```
