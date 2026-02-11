# AGENTS.md - ソウルくんプロジェクト AIエージェント指示書

**このファイルはAIコードレビューエージェント（Codex, Claude Code, Gemini等）が
PRレビュー時に参照する共通指示書です。**

---

## プロジェクト概要

ソウルくんは、株式会社ソウルシンクスの社内AIアシスタント。
ChatWorkを通じて社員と対話し、タスク管理・ナレッジ検索・議事録生成等を行う。

- **言語**: Python 3.11+
- **インフラ**: GCP (Cloud Functions Gen2, Cloud SQL PostgreSQL, Pinecone)
- **アーキテクチャ**: LLM Brain（GPT-5.2）が全判断を行い、各機能は実行のみ

---

## 絶対ルール（違反は即FAIL）

1. **organization_idフィルタ必須**: 全てのSELECT/INSERT/UPDATE/DELETEにorganization_idフィルタがあること
2. **Brain bypass禁止**: 全入出力は脳(Brain)を通る。機能が直接テンプレート送信してはいけない
3. **SQLパラメータ化必須**: 文字列結合でSQLを組み立てない。`text("SELECT ... WHERE id = :id"), {"id": val}` パターンを使う
4. **PII漏洩禁止**: ログ・debug_info・DB保存に個人情報（名前、メール、電話、メッセージ本文）を含めない。エラーログは `type(e).__name__` のみ
5. **asyncブロッキング禁止**: `async def` 内で `pool.connect()` 等の同期I/Oを直接呼ばない。`asyncio.to_thread()` で包む
6. **RLS型キャスト整合**: VARCHARカラムに `::uuid` キャストしない（本番障害の実績あり）。`::text` を使う
7. **デプロイ時 `--set-env-vars` 禁止**: 必ず `--update-env-vars` を使う（全環境変数上書き事故の防止）
8. **lib/ 3コピー同期**: `lib/` の変更は `chatwork-webhook/lib/` と `proactive-monitor/lib/` にも反映必須

---

## コーディング規約

### DB接続パターン
```python
# OK: asyncio.to_thread() で包む
def _sync_query():
    with pool.connect() as conn:
        conn.execute(text("SELECT set_config(...)"), {"org_id": org_id})
        result = conn.execute(text("SELECT ..."))
        conn.execute(text("SELECT set_config(..., NULL, false)"))
        return result
result = await asyncio.to_thread(_sync_query)

# NG: async def 内で直接 pool.connect()
async def bad_example():
    with pool.connect() as conn:  # ブロッキング！
        ...
```

### RLSパターン
```python
# OK: set_config + クエリ + リセットを同一コネクション内
with pool.connect() as conn:
    conn.execute(text("SELECT set_config('app.current_organization_id', :org, false)"), {"org": org_id})
    result = conn.execute(text("SELECT * FROM tasks WHERE organization_id = :org"), {"org": org_id})
    conn.execute(text("SELECT set_config('app.current_organization_id', NULL, false)"))

# NG: set_config とクエリを別スレッドで実行（RLS無効になる）
await asyncio.to_thread(set_config_call)  # Thread A
await asyncio.to_thread(query_call)        # Thread B（RLS未適用！）
```

### fire-and-forget パターン
```python
# OK: _fire_and_forget() で参照保持 + エラーコールバック
_fire_and_forget(some_coroutine())

# NG: asyncio.create_task() 直接使用（参照消失でGCされる）
asyncio.create_task(some_coroutine())
```

---

## テスト

```bash
# ユニットテスト（8,921件）
python3 -m pytest tests/ -v

# 結合テスト（本物のPostgreSQL必要）
docker compose -f tests/integration/docker-compose.yml up -d
TEST_DATABASE_URL="postgresql+pg8000://test_user:test_pass@localhost:15432/test_db" \
  python3 -m pytest tests/integration/ -v
```

---

## ディレクトリ構造

```
lib/                        # 共通ライブラリ（SoT）
  brain/                    # LLM Brain（判断エンジン）
    core.py                 # Brain本体
    llm_brain.py            # OpenRouter API呼び出し
    context_builder.py      # プロンプト構築
    memory_access.py        # DB読み取り
    state_manager.py        # 状態管理
    models.py               # ドメインモデル（GoalInfo等のSoT）
    constants.py            # 定数定義
    env_config.py           # 環境変数名（SoT）
  channels/                 # チャネルアダプター
  meetings/                 # 会議・議事録
  detection/                # パターン検出
chatwork-webhook/           # Cloud Function: ChatWork Webhook
  lib/                      # ← lib/ のミラーコピー
  main.py                   # エントリーポイント
proactive-monitor/          # Cloud Function: 能動的モニタリング
  lib/                      # ← lib/ のミラーコピー
tests/                      # ユニットテスト
  integration/              # 結合テスト（本物のDB使用）
scripts/                    # 運用スクリプト
  safe_deploy.sh            # 4段階安全デプロイ
  rollback.sh               # 1分以内ロールバック
  sync_lib.sh               # lib/同期
  validate_sql_columns.sh   # SQLカラム検証
docs/                       # 設計書
```

---

## レビュー観点（優先順）

1. **セキュリティ**: SQLi, XSS, 認証バイパス, PII漏洩, OWASP Top 10
2. **データ安全性**: org_idフィルタ, RLS整合, トランザクション安全性
3. **可用性**: asyncブロッキング, 接続プール枯渇, 無限ループ, リソースリーク
4. **正確性**: ロジックエラー, エッジケース, 冪等性
5. **設計整合性**: Brain bypass, Truth順位, CLAUDE.md準拠
6. **コード品質**: エラーハンドリング, テストカバレッジ, 型安全性
