# 大規模修繕計画レポート

**作成日**: 2026年1月31日
**作成者**: Claude（技術調査）
**対象**: カズさん（経営者）

---

## 目次

1. [今起きていること（1分でわかる要約）](#1-今起きていること1分でわかる要約)
2. [発見した全ての問題](#2-発見した全ての問題)
3. [なぜこうなったのか（根本原因）](#3-なぜこうなったのか根本原因)
4. [修繕計画：やるべきこと](#4-修繕計画やるべきこと)
5. [再発防止策](#5-再発防止策)
6. [メリット・デメリット・効果・リスク](#6-メリットデメリット効果リスク)

---

## 1. 今起きていること（1分でわかる要約）

### 例え話で説明

**「新しい脳みそ（LLM Brain）が開発されたが、本番サーバーにはまだ届いていない」**

```
イメージ:

【開発室】                    【本番サーバー（実際に動いているところ）】
┌─────────────────┐          ┌─────────────────┐
│ 新しい脳 (LLM Brain)  │          │ 古い脳 (SoulkunBrain) │
│ ✅ 完成している   │  ❌未配送  │ ← 今もこれが動いている │
│ ✅ テスト済み     │ ───────→ │                        │
│ ✅ 240テストパス  │          │ 手足も古いまま        │
└─────────────────┘          └─────────────────┘
        lib/brain/                   chatwork-webhook/lib/brain/
```

**結果**:
- せっかく作った新しい賢い脳が使われていない
- ユーザーへの返答が「不十分」と感じる
- 本番でエラーが発生している

---

## 2. 発見した全ての問題

### 2-1. 本番に存在しないファイル（6個）

新しく作ったのに、本番サーバーにコピーされていないファイル：

| ファイル名 | 行数 | 役割 | 影響 |
|-----------|------|------|------|
| `llm_brain.py` | 1,248行 | **新しい脳の本体**（GPT-5.2で考える） | これがないと賢い回答ができない |
| `context_builder.py` | 685行 | 脳に渡す情報を整理 | 会話の文脈がわからない |
| `guardian_layer.py` | 607行 | 危険な操作をチェック | 安全確認が不十分 |
| `tool_converter.py` | 555行 | 手足を脳に接続 | 手足が動かない |
| `monitoring.py` | 711行 | 脳の動きを監視 | 問題が見つけられない |
| `truth_resolver.py` | 583行 | 正しいデータを選ぶ | 間違った情報を使う可能性 |

### 2-2. 古いバージョンのファイル（10個以上）

開発版では更新されたのに、本番は古いまま：

| ファイル名 | 問題 | 本番で起きるエラー |
|-----------|------|-------------------|
| `ceo_teaching_repository.py` | UUID検証がない、search_relevantメソッドがない | "invalid input syntax for type uuid" エラー |
| `state_manager.py` | LLMStateManagerクラスがない | "has no attribute 'get_current_state'" エラー |
| `core.py` | LLM Brain初期化コードがない | 新しい脳が起動しない |
| `constants.py` | LLM Brain用の設定がない | 設定値が見つからない |
| その他6ファイル | 細かい修正が反映されていない | 動作不良 |

### 2-3. 本番で確認したエラー（ログ分析結果）

実際にCloud Loggingから取得したエラー（500件のログを分析）：

| エラー内容 | 発生回数 | 原因 |
|-----------|---------|------|
| `CEOTeachingRepository` has no `search_relevant` | 17回 | ファイル未同期 |
| `LLMStateManager` has no `get_current_state` | 17回 | ファイル未同期 |
| UUID format error "org_soulsyncs" | 17回 | 検証コード未同期 |
| `No module named 'pytz'` | 7回 | 依存ライブラリ不足 |

### 2-4. main.pyの問題

```
【開発版 main.py】               【本番版 chatwork-webhook/main.py】
ENABLE_LLM_BRAIN=true で         LLM Brainの記述が
新しい脳を使う設定あり    ≠     まったくない（古い脳だけ）
```

**つまり**: 本番では新しい脳を使う設定すらない

---

## 3. なぜこうなったのか（根本原因）

### 3-1. 自動チェックの対象外だった

GitHubのCI/CD（自動チェック機能）は以下をチェックしている：

```yaml
# .github/workflows/quality-checks.yml の設定

チェック対象:
  ✅ lib/text_utils.py
  ✅ lib/goal_setting.py
  ✅ lib/mvv_context.py
  ✅ lib/report_generator.py
  ✅ lib/audit.py
  ✅ lib/memory/* (ディレクトリ)
  ✅ lib/detection/* (ディレクトリ)
  ❌ lib/brain/*  ← これがチェックされていなかった！
```

**結果**: lib/brain/ を変更しても、「本番と違う」という警告が出なかった

### 3-2. デプロイ手順書がなかった

- chatwork-webhook のデプロイ用スクリプト（deploy.sh）が存在しない
- 他のCloud Functions（sync-chatwork-tasks等）にはデプロイスクリプトがある
- chatwork-webhookだけ手動デプロイの可能性

### 3-3. 2つの lib/brain/ が存在する

```
プロジェクトの構造:

soul-kun/
├── lib/brain/           ← 開発用（新しいコードをここで書く）
└── chatwork-webhook/
    └── lib/brain/       ← 本番用（Cloud Functionsにデプロイされる）
```

この2つを手動で同期する必要があったが、忘れられていた

---

## 4. 修繕計画：やるべきこと

### Phase 1: 緊急対応（即座に実施）

| # | タスク | 所要時間 | 効果 |
|---|--------|---------|------|
| 1-1 | 6個の不足ファイルをコピー | 5分 | 新しい脳が動くようになる |
| 1-2 | 10個の古いファイルを更新 | 10分 | エラーが止まる |
| 1-3 | requirements.txtを更新 | 2分 | pytzエラーが止まる |
| 1-4 | ローカルでテスト実行 | 5分 | 問題ないことを確認 |

**実行コマンド（コピー）**:
```bash
# 不足ファイルをコピー
cp lib/brain/context_builder.py chatwork-webhook/lib/brain/
cp lib/brain/guardian_layer.py chatwork-webhook/lib/brain/
cp lib/brain/llm_brain.py chatwork-webhook/lib/brain/
cp lib/brain/monitoring.py chatwork-webhook/lib/brain/
cp lib/brain/tool_converter.py chatwork-webhook/lib/brain/
cp lib/brain/truth_resolver.py chatwork-webhook/lib/brain/

# 古いファイルを更新
cp lib/brain/ceo_teaching_repository.py chatwork-webhook/lib/brain/
cp lib/brain/constants.py chatwork-webhook/lib/brain/
cp lib/brain/core.py chatwork-webhook/lib/brain/
cp lib/brain/state_manager.py chatwork-webhook/lib/brain/
# ...その他のファイル
```

### Phase 2: デプロイ（本番反映）

| # | タスク | 所要時間 | 効果 |
|---|--------|---------|------|
| 2-1 | Cloud Functionsにデプロイ | 5分 | 本番に新しい脳が入る |
| 2-2 | ログ監視で動作確認 | 10分 | エラーが減ったことを確認 |
| 2-3 | 実際にメッセージを送って確認 | 5分 | 返答が良くなったことを確認 |

### Phase 3: 再発防止（今後のため）

| # | タスク | 所要時間 | 効果 |
|---|--------|---------|------|
| 3-1 | CI/CDにlib/brain/チェックを追加 | 15分 | 今後は自動で差分警告 |
| 3-2 | デプロイスクリプトを作成 | 20分 | 手動ミスを防ぐ |
| 3-3 | ドキュメント更新 | 10分 | 作業手順を明確化 |

---

## 5. 再発防止策

### 5-1. CI/CDの自動チェックを追加

**やること**: `.github/workflows/quality-checks.yml` に lib/brain/ のチェックを追加

**効果**:
- PRを出したときに「lib/brain/ が本番と違います」と警告が出る
- マージする前に必ず同期するようになる

**追加するコード**:
```yaml
# lib/brain/ ディレクトリ全体のチェック
echo "📦 [9/9] brain/ directory (NEW)"
for file in lib/brain/*.py; do
  if [ -f "$file" ]; then
    basename=$(basename "$file")
    check_sync "$file" "chatwork-webhook/lib/brain/$basename" || ERRORS_FOUND=1
  fi
done
```

### 5-2. デプロイスクリプトの作成

**やること**: `chatwork-webhook/deploy.sh` を作成

**内容**:
```bash
#!/bin/bash
# chatwork-webhookデプロイスクリプト

# 1. lib/brain/ の同期確認
echo "🔍 Checking lib/brain/ sync..."
if ! diff -rq lib/brain chatwork-webhook/lib/brain --exclude=__pycache__ > /dev/null 2>&1; then
    echo "❌ lib/brain/ is out of sync! Please sync first."
    exit 1
fi

# 2. テスト実行
echo "🧪 Running tests..."
pytest tests/ -v --tb=short

# 3. デプロイ
echo "🚀 Deploying to Cloud Functions..."
gcloud functions deploy chatwork-webhook \
    --source=chatwork-webhook \
    --runtime=python311 \
    --trigger-http \
    --region=asia-northeast1
```

**効果**:
- デプロイ前に自動で同期チェック
- 同期していなければデプロイを止める
- 手動ミスが起きない

### 5-3. 同期スクリプトの作成

**やること**: `scripts/sync_lib_brain.sh` を作成

**内容**:
```bash
#!/bin/bash
# lib/brain/ を chatwork-webhook/lib/brain/ に同期

echo "🔄 Syncing lib/brain/ to chatwork-webhook/lib/brain/..."

# 同期（__pycache__は除外）
rsync -av --exclude='__pycache__' lib/brain/ chatwork-webhook/lib/brain/

echo "✅ Sync complete!"
echo "📋 Changed files:"
diff -rq lib/brain chatwork-webhook/lib/brain --exclude=__pycache__ || echo "All files are in sync"
```

### 5-4. 将来の抜本的改善（検討事項）

| 案 | 説明 | メリット | デメリット |
|---|------|---------|-----------|
| **案A**: シンボリックリンク | chatwork-webhook/lib/brain/ を lib/brain/ へのリンクにする | 常に同期 | Cloud Functionsで動くか要確認 |
| **案B**: モノレポ構造 | lib/ を1箇所に統一、パッケージとしてインストール | 根本解決 | 大規模リファクタリング必要 |
| **案C**: 自動コピー | pre-commitフックで自動コピー | 簡単 | 忘れる可能性残る |

**推奨**: まずは5-1〜5-3を実施、その後案Bを検討

---

## 6. メリット・デメリット・効果・リスク

### 6-1. 修繕を実施した場合

| 項目 | 内容 |
|------|------|
| **メリット** | |
| ✅ 新しい脳が動く | GPT-5.2による賢い回答が可能に |
| ✅ エラーが止まる | 本番のエラーログがクリーンに |
| ✅ 返答品質向上 | 「不十分」と感じていた回答が改善 |
| ✅ 監視機能が使える | 問題を早期発見できる |
| **デメリット** | |
| ⚠️ デプロイ作業が必要 | 本番への反映作業が発生 |
| ⚠️ 一時的な不安定化の可能性 | デプロイ直後に予期せぬ問題が出る可能性 |
| **効果** | |
| 📈 応答品質 | 大幅向上（LLM Brainの能力が使える） |
| 📉 エラー率 | 大幅減少（58件/500件 → ほぼ0に） |
| **リスク** | |
| 🔴 低 | テスト済みコードなので低リスク |

### 6-2. 修繕をしなかった場合

| 項目 | 内容 |
|------|------|
| **デメリット（問題が続く）** | |
| ❌ エラーが続く | 毎日17件以上のエラーが発生し続ける |
| ❌ 返答品質が低いまま | ユーザー満足度が下がる |
| ❌ 開発の無駄 | 240テスト分の開発努力が無駄に |
| ❌ 問題が見つけられない | 監視機能がないため障害対応が遅れる |
| **リスク** | |
| 🔴 高 | 時間が経つほど修正が難しくなる |

### 6-3. 再発防止策を実施した場合

| 項目 | 内容 |
|------|------|
| **メリット** | |
| ✅ 同じミスが起きない | 自動チェックで警告される |
| ✅ デプロイが安全に | スクリプトで手順が標準化 |
| ✅ 作業時間短縮 | 手動確認が不要に |
| **コスト** | |
| 💰 初期: 45分程度 | 一度だけの設定作業 |
| 💰 継続: 0分 | 自動で動く |

### 6-4. 再発防止策を実施しなかった場合

| 項目 | 内容 |
|------|------|
| **リスク** | |
| 🔴 また同じことが起きる | lib/brain/を更新しても本番に反映されない |
| 🔴 他のディレクトリでも起きうる | 似たパターンの見落としが発生 |
| 🔴 障害対応が増える | 定期的に同様の問題が発生 |

---

## 最終推奨

**今すぐやるべきこと（優先順位順）**:

1. **Phase 1 実施**（所要時間: 約20分）
   - ファイルコピー・同期
   - ローカルテスト確認

2. **Phase 2 実施**（所要時間: 約20分）
   - 本番デプロイ
   - 動作確認

3. **Phase 3 実施**（所要時間: 約45分）
   - 再発防止策の設定
   - ドキュメント更新

**合計所要時間**: 約1.5時間

**期待効果**:
- 新しい脳が本番で動く
- エラーが止まる
- 返答品質が向上する
- 今後同じミスが起きなくなる

---

## 付録: 差分ファイル一覧

```
【本番に存在しないファイル】
lib/brain/context_builder.py      → chatwork-webhook/lib/brain/ にない
lib/brain/guardian_layer.py       → chatwork-webhook/lib/brain/ にない
lib/brain/llm_brain.py            → chatwork-webhook/lib/brain/ にない
lib/brain/monitoring.py           → chatwork-webhook/lib/brain/ にない
lib/brain/tool_converter.py       → chatwork-webhook/lib/brain/ にない
lib/brain/truth_resolver.py       → chatwork-webhook/lib/brain/ にない

【内容が異なるファイル】
lib/brain/__init__.py             ≠ chatwork-webhook/lib/brain/__init__.py
lib/brain/ceo_teaching_repository.py ≠ chatwork-webhook/lib/brain/ceo_teaching_repository.py
lib/brain/constants.py            ≠ chatwork-webhook/lib/brain/constants.py
lib/brain/core.py                 ≠ chatwork-webhook/lib/brain/core.py
lib/brain/decision.py             ≠ chatwork-webhook/lib/brain/decision.py
lib/brain/execution.py            ≠ chatwork-webhook/lib/brain/execution.py
lib/brain/session_orchestrator.py ≠ chatwork-webhook/lib/brain/session_orchestrator.py
lib/brain/state_manager.py        ≠ chatwork-webhook/lib/brain/state_manager.py
lib/brain/understanding.py        ≠ chatwork-webhook/lib/brain/understanding.py
lib/brain/advanced_judgment/tradeoff_analyzer.py ≠ 対応ファイル
lib/brain/deep_understanding/intent_inference.py ≠ 対応ファイル

【本番にしか存在しないファイル】
chatwork-webhook/lib/brain/handler_wrappers.py ← これは本番専用で正常
```

---

**このレポートについて質問があれば、お知らせください。**
