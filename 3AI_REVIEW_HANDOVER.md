# ソウル君 3AIレビュー引き継ぎ文書

**作成日:** 2026-02-18
**作成者:** Claude Opus 4.6 / Codex (GPT-5.2) / Gemini の3AI合議
**目的:** ソウル君プロジェクト担当のClaude Codeへの完全な引き継ぎ
**依頼者:** 古舘様（代表）

---

## この文書の使い方

この文書は3つのAI（Claude・Codex・Gemini）が合同でソウル君プロジェクトを分析した結果をまとめたものです。担当のClaude Codeはこの文書を読み、記載された順序で修正・改良を実行してください。

**重要ルール:**
- 修正の際は既存の `CLAUDE.md` の鉄則（特に鉄則#11「推測で直すな、計測が先」）を必ず守ること
- バグ修正は3AI合議プロセスに従うこと
- 各修正はPRを作成し、テストが全件パスしてからマージすること

---

## 第1部: 現状の総合診断（3AI合議結果）

### 重要な追記（2026-02-18 追加調査結果）

3AIレビュー時点（IMPLEMENTATION_STATUS.md 2026-02-08版）では「Tier 1緊急」としていたセキュリティ問題の一部が、**2026-02-08〜02-14の間に修正済み**であることが追加調査で判明しました。以下が是正状況です：

| 項目 | 2/8時点の状態 | 現在の是正状況 |
|------|-------------|--------------|
| org_idフィルター漏れ（114箇所） | 未修正 | **全箇所修正完了**（PR #421, 2026-02-08） |
| API認証ミドルウェア（0件） | 未実装 | **JWT認証実装完了**（`api/app/deps/auth.py`新規作成） |
| Cloud Run認証（11/12公開） | 未修正 | **11サービス認証必須化完了** |
| RLS（31/83テーブル） | 不完全 | **48テーブル追加完了**（54+テーブルRLS有効） |
| ILIKEインジェクション | 脆弱 | **`escape_ilike()` + ESCAPE対応完了** |
| TODO/FIXME（152件） | 未対応 | 段階対応中（未完了） |

**ただし、以下の注意点があります：**
- IMPLEMENTATION_STATUS.md は2026-02-08のまま更新されていないため、最新状態との齟齬がある
- 各修正の本番反映状況（デプロイ済みかどうか）は個別に確認が必要
- cloudbuild.yaml に `--allow-unauthenticated` フラグが残っている（Cloud Run自体は公開、認証はアプリレベルJWTで実施）

### 通信簿（3AI合議 + 追加調査による修正版）

| 項目 | 評価 | 解説 |
|------|------|------|
| テスト | **B-** | 9,187件あり、テナント分離テスト・ILIKEエスケープテスト・API認証テストも追加済み。ただしAI回答品質の自動テストは弱い |
| 設計書 | **B** | 54ファイル以上と非常に充実。ただし設計と実装にズレがある部分あり（MVV検証のハードコード等） |
| AI品質管理 | **C** | Langfuse導入は開始済みだが、AIの回答品質の定量評価・ハルシネーション検知・プロンプトバージョン管理がない |
| セキュリティ | **C-** | JWT認証・RLS・org_idフィルターは修正済み。ただしcloudbuild.yamlの`--allow-unauthenticated`残存、SLO未定義、ランブック不十分 |
| 監視 | **C** | observability.pyは存在するがDB永続化未実装。proactive-monitorはデフォルト無効 |
| 本番との一致 | **D** | ステージング環境なし。開発で動くが本番で動かない状態 |
| デプロイ | **B** | Cloud Build自動デプロイはOK。ロールバック・カナリアリリースが未整備 |

### 3AIが一致して指摘した最大の問題

> **「機能は十分に作られている。問題は、それが本番で安全かつ確実に動く状態になっていないこと」**

---

## 第2部: セキュリティの確認と残存課題

### 概要: セキュリティの大部分は修正済み

追加調査により、IMPLEMENTATION_STATUS.md（2026-02-08時点）で「Tier 1緊急」とされていた主要セキュリティ問題は**2026-02-08〜02-14の間にほぼ修正済み**であることが判明しました。ただし、以下の確認・追加作業が必要です。

### 2-1. API認証の確認と統一

**是正状況:** `api/app/deps/auth.py` にJWT認証ミドルウェアが実装済み
**残存課題:** 以下を確認・対応すること

1. **全エンドポイントにJWT認証が適用されているか確認する**
   - `chatwork-webhook/main.py` — ChatWork Webhookの受信（これはWebhook側の認証方式）
   - `report-generator/main.py` — CORS設定が `Access-Control-Allow-Origin: *`（全オリジン許可）のまま。本番では制限が必要
   - `mcp-server/server.py` — MCP接続の認証
   - `mobile-api/main.py` — モバイルAPIの認証
2. **認証の統一性を確認する** — サービスごとにバラバラな認証になっていないか
3. **テスト:** `tests/test_api_auth.py` が存在することを確認済み。テスト内容が全エンドポイントをカバーしているか確認

---

### 2-2. Cloud Run サービスの認証状態を確認

**是正状況:** 11サービスの認証必須化が完了との記録あり
**残存課題:**

1. **cloudbuild.yaml に `--allow-unauthenticated` フラグが残っている**
   - 現在のcloudbuild.yamlのデプロイステップにこのフラグがある
   - Cloud Run自体は公開状態のまま、認証はアプリレベル（JWT）で実施している可能性
   - **確認:** `gcloud run services list --region=asia-northeast1` で各サービスの認証設定を確認
   - **判断:** Cloud Run IAM認証にするか、アプリレベルJWT認証で十分かを判断
2. **cloudbuild.yaml の更新が必要な場合は修正**
3. **docs/31_emergency_procedures.md と docs/OPERATIONS_RUNBOOK.md に緊急停止手順が既に記載されていることを確認済み**

---

### 2-3. org_id フィルターの修正確認

**是正状況:** PR #421（2026-02-08）、PR #423, #425, #426（2026-02-09）で全箇所修正完了との記録あり
**残存課題:**

1. **修正が確実に全箇所に適用されているか再確認する**
   ```
   grep -rn "SELECT\|INSERT\|UPDATE\|DELETE" lib/ chatwork-webhook/ --include="*.py" | grep -v "org_id\|organization_id\|test_\|__pycache__" | head -50
   ```
2. `tests/test_org_isolation.py` と `tests/test_tenant.py` が存在することを確認済み — テスト内容のカバレッジを確認
3. **IMPLEMENTATION_STATUS.md の更新が必要** — 現在2026-02-08版のままで、2/9の修正が反映されていない

---

### 2-4. RLS（Row Level Security）の確認

**是正状況:** Phase 4A（2026-02-09）で48テーブル追加完了。54+テーブルでRLS有効との記録
**残存課題:**

1. **現在のRLS有効テーブル数を本番DBで確認する**
   ```sql
   SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
   ```
2. まだRLSが無効なテーブルがあれば有効化する
3. IMPLEMENTATION_STATUS.md を最新状態に更新する

---

### 2-5. ILIKE インジェクション対策の確認

**是正状況:** `escape_ilike()` + `ESCAPE '\\\\'` 対応が全ファイルに適用済みとの記録
**確認済みファイル:**
- `lib/brain/hybrid_search.py`（行69に `escape_ilike()` 定義）
- `lib/person_service.py`（行161-163, 255, 272でESCAPE使用）
- その他: `memory/auto_knowledge.py`, `memory/conversation_search.py`, `brain/drive_tool.py`, `brain/memory_access.py`, `brain/operations/data_ops.py` 等
- `tests/test_ilike_escape.py` が存在

**残存課題:**
1. `escape_ilike()` が共通ユーティリティとして1箇所で定義され、全箇所から参照されているか確認（重複定義がないか）
2. 新規コードでILIKEを追加する際のガイドラインをCLAUDE.mdに追加

---

### 2-6. SQLインジェクション全般の対策

**現状:** CLAUDE.md 鉄則#9「SQLはパラメータ化」が定められているが、完全には守られていない可能性

**修正方法:**
1. 全SQLクエリをスキャンして非パラメータ化クエリを検出
   ```
   grep -rn "f\".*SELECT\|f\".*INSERT\|f\".*UPDATE\|f\".*DELETE" lib/ chatwork-webhook/ --include="*.py"
   ```
2. f-string等で動的に構築されているSQL文をすべてパラメータ化
3. `scripts/validate_sql_columns.sh` の検証対象に安全性チェックを追加

---

## 第3部: 重要修正事項（セキュリティの次に対応）

### 3-1. 監視（Observability）のDB永続化

**現状:** `lib/brain/observability.py`（441行）は存在するが、DB永続化が未実装
**設計実装ギャップ:** DESIGN_IMPLEMENTATION_GAP_REPORT.md で「Observability: 60%」

**修正方法:**
1. observability_logsテーブルを作成（マイグレーション追加）
2. `observability.py` のログ出力をDBに永続化する処理を追加
3. ダッシュボードからログを参照できるAPIを作成
4. エラー発生時の通知（ChatWork/Slackへのアラート）を実装

---

### 3-2. Langfuse（AIトレーシング）の本格稼働

**現状:** PR #508でLangfuse基盤がマージ済み。`lib/brain/langfuse_integration.py` にobserveデコレータあり。`core/message_processing.py` の49行目で使用中
**課題:** 基盤のみで、全面的な計測はまだ

**修正方法:**
1. 全LLM呼び出し箇所にLangfuseトレースを追加
2. コスト・レイテンシの自動記録を有効化
3. プロンプトのバージョン管理をLangfuseのPrompt Management機能で行う
4. ダッシュボードでの可視化を設定

---

### 3-3. ステージング環境の構築

**現状:** ステージング環境なし。開発→本番直行
**3AI一致の指摘:** これが「開発では動くが本番で動かない」の根本原因の一つ

**修正方法:**
1. GCPプロジェクト `soulkun-staging` を新規作成するか、同プロジェクト内にstagingサービスを作成
2. Cloud SQL のステージングインスタンスを作成（本番のデータ構造を複製、データはテスト用に差し替え）
3. `cloudbuild-staging.yaml` を作成（developブランチへのpushでステージングにデプロイ）
4. ステージング環境で動作確認してからmainにマージする運用フローを確立

---

### 3-4. 障害対応手順書（ランブック）の整備

**現状:** `docs/31_emergency_procedures.md` に緊急対応手順の一部あり。ただし網羅的なランブックではない

**修正方法:**
1. `docs/40_runbook.md` を新規作成
2. 以下のシナリオごとに手順を記載:
   - Cloud Runサービスがダウンした場合
   - Cloud SQLが応答しない場合
   - LLM API（OpenRouter）が応答しない場合
   - ChatWork Webhookが受信できない場合
   - 異常なコスト発生が検知された場合
   - セキュリティインシデント発生時
3. 各手順に「誰が」「何を」「どの順番で」やるかを明記
4. 復旧確認の手順を含める

---

### 3-5. SLO/SLA の設計

**現状:** 応答時間やエラー率の目標値が定義されていない

**修正方法:**
1. `docs/41_slo_design.md` を新規作成
2. 以下のSLOを定義:
   - 応答時間: ChatWorkメッセージ受信から返信まで XX秒以内（目標を決める）
   - 可用性: 99.X% 以上
   - エラー率: X% 以下
   - LLMコスト: 月額 XX万円以内
3. SLO計測のための監視設定を追加
4. SLO違反時のアラート設定

---

## 第4部: AI品質の改善（プロとして当たり前の基準達成）

### 4-1. プロンプトのバージョン管理

**現状:** `lib/brain/llm_brain.py` の238-274行目にシステムプロンプトが直書き。変更履歴の管理なし

**現在のシステムプロンプト内容:**
```
あなたは「ソウルくん」。株式会社ソウルシンクスの公式AI。
狼をモチーフにした、会社を守り、人を支える存在。
```
話し方ルール: 全文語尾に「ウル」「ウル！」「ウル？」「ウル〜」をつける
6つの役割: 社長の分身、社長の鏡、最高経営パートナー、会社を守るAI、世界最高のパートナー、世界最高の秘書

**修正方法:**
1. プロンプトを外部ファイル化する（`lib/brain/prompts/` ディレクトリ作成）
2. プロンプトにバージョン番号をつける（v1.0.0, v1.1.0 等）
3. Langfuseのプロンプト管理機能と連携する
4. プロンプト変更時に回帰テスト（既存の回答品質が下がらないかチェック）を自動実行する仕組みを作る

---

### 4-2. AI回答品質の定量評価（評価データセット）

**現状:** `promptfoo/` ディレクトリが存在し、`promptfooconfig.yaml` と `test_cases.yaml` がある
**課題:** テストケースの充実度が不明、定期実行の仕組みがない

**修正方法:**
1. `promptfoo/test_cases.yaml` のテストケースを充実させる（最低100パターン以上）
   - タスク作成系: 20パターン
   - 質問応答系: 20パターン
   - MVV/選択理論に沿った判断系: 20パターン
   - キャラクター性（語尾「ウル」等）の検証: 20パターン
   - 承認フロー系: 10パターン
   - エッジケース（想定外入力）: 10パターン
2. CI/CDに組み込んでプロンプト変更時に自動実行
3. 評価結果をLangfuseに記録
4. MVV準拠率を数値化して毎日計測

---

### 4-3. ハルシネーション（AIの嘘）対策

**現状:** Guardian LayerにMVV違反チェックはあるが、事実の正確性チェック（ハルシネーション検知）は弱い

**修正方法:**
1. `lib/brain/hallucination_detector.py` を新規作成
2. 以下のチェックを実装:
   - 社員名・部署名がDB上に存在するか照合
   - 数値（売上、タスク数等）がDB上のデータと一致するか照合
   - 日付の妥当性チェック
3. Guardian Layerのパイプラインに組み込む
4. 事実確認ができない内容には「確認が必要です」と付ける

---

### 4-4. AIコスト・レイテンシの監視

**現状:** `admin-dashboard/src/pages/costs.tsx`（465行）が存在するが、バックエンドAPIとの接続が不明

**修正方法:**
1. 全LLM呼び出しでコスト（トークン数×単価）とレイテンシ（応答時間）を記録する
2. 月額コストの上限を設定し、超過時にアラートを送信
3. ダッシュボードでリアルタイム表示（costs.tsxを完成させる）
4. 異常なコスト発生（1リクエストで高額等）を検知する仕組みを追加

**現在のモデル単価（参考）:**
- LLM Brain判断: OpenRouter経由 `openai/gpt-5.2`
- 一般補助処理: `google/gemini-3-flash-preview`
- Embedding: `models/text-embedding-004`
- フォールバック: `claude-opus-4-5-20250101`

---

## 第5部: キャラクター性（MVV・選択理論）の強化

### 5-1. MVV検証の専用モジュール化

**現状:** `lib/brain/guardian.py` にMVV（ミッション・ビジョン・バリュー）と選択理論の5欲求がハードコードされている
**IMPLEMENTATION_STATUS.md:** Phase 2C MVV検証は70%（guardian.pyにハードコード、専用モジュール未分離）

**現在guardian.pyに定義されている内容:**
- Mission: 「可能性の解放」。違反 = 「可能性を否定する」「限界を決めつける」
- Vision: 「前を向く全ての人の可能性を解放し続け、心で繋がる未来」
- Values: 選択理論（5つの基本的欲求）に基づく行動指針
  - 生存・愛所属・力・自由・楽しみ
  - 各欲求に「valid_approaches（OK対応）」と「violations（違反する対応）」が定義済み

**修正方法:**
1. `lib/brain/mvv_validator.py` を新規作成し、guardian.pyからMVV検証ロジックを分離
2. MVVの定義をDB化またはJSON外部ファイル化（変更を容易にするため）
3. Guardian Layerのパイプラインで以下の順序でチェック:
   - ① セキュリティチェック（既存）
   - ② MVV準拠チェック（新規分離）
   - ③ 選択理論準拠チェック（新規分離）
   - ④ 確信度チェック（既存）
4. MVV違反が検知された場合、回答を生成し直す仕組みを追加
5. `lib/brain/mvv_context.py` が既に存在するため、これとの統合を検討

---

### 5-2. キャラクター性の返答前チェック機能

**現状:** システムプロンプトで語尾「ウル」等を指示しているが、LLMが従わない場合に検知・修正する仕組みがない

**修正方法:**
1. `lib/brain/character_validator.py` を新規作成
2. 返答送信前に以下をチェック:
   - 語尾に「ウル」「ウル！」「ウル？」「ウル〜」があるか
   - 相手の名前を呼んでいるか
   - 攻撃的・否定的な表現がないか
   - 3〜5文の適切な長さか
3. チェックに失敗した場合、LLMに再生成を指示する
4. キャラクター準拠率を日次で計測し記録する

---

### 5-3. 社長の判断パターンの蓄積と学習

**現状:** `lib/brain/ceo_learning.py` が存在（CEO教え＆守護者層、Phase 2D完了）。`lib/brain/ceo_teaching_repository.py` もあり

**修正方法:**
1. 既存のCEO教え機能が本番で正しく動作しているか確認
2. 社長の判断パターンの具体例を10〜20件、DBに登録する
   例:
   - 「スタッフから有給申請が来たら → 基本OK、繁忙期は要相談」
   - 「クレーム対応 → まず謝罪、すぐ社長に報告」
   - 「新規提案 → まず受け止めて、メリット・デメリットを整理」
3. LLM Brainが判断する際にCEO教えを参照するフローが確実に動いているかテスト

---

## 第6部: 承認フローの完全実装

### 6-1. 承認ゲートの本番検証

**現状:** `lib/brain/approval_gate.py` が2026-02-17に新規作成済み
**3段階判定:**
- `AUTO_APPROVE`: 低リスク → そのまま実行
- `REQUIRE_CONFIRMATION`: 中リスク → Level 5以上に確認
- `REQUIRE_DOUBLE_CHECK`: 高リスク → 社長承認 + 番人ダブルチェック

**修正方法:**
1. 本番環境で承認フローが正しく動作しているかを全パターンでテスト
2. 承認リクエストと承認結果を全件DBに記録する
3. 承認待ちが放置された場合の自動リマインド機能を追加
4. 代理承認者の設定機能を追加
5. 承認のタイムアウト（一定時間以内に承認されない場合の自動エスカレーション）を実装

### 6-2. 権限レベルの実装確認

**設計済みの6段階:**
| レベル | 役職 | 閲覧範囲 |
|--------|------|---------|
| 1 | 業務委託 | 自部署のみ（制限あり） |
| 2 | 一般社員 | 自部署のみ |
| 3 | リーダー/課長 | 自部署 + 直下部署 |
| 4 | 幹部/部長 | 自部署 + 配下全部署 |
| 5 | 管理部/取締役 | 全組織（最高機密除く） |
| 6 | 代表/CFO | 全組織・全情報 |

**修正方法:**
1. 各ユーザーの権限レベルがDBに正しく設定されているか確認
2. 管理者判定が `ADMIN_ACCOUNT_ID = "1728974"` の単純比較になっている問題を修正 → 複数管理者対応
3. 各権限レベルで閲覧・操作範囲が正しく制限されているかテスト
4. 権限変更のログを記録する

---

## 第7部: 新機能追加（既存機能の安定化後に着手）

### 7-1. 日報・週報の自動まとめ

**現状:**
- `report-generator/main.py` に `POST /daily-report` と `POST /weekly-report` が存在
- `lib/brain/daily_log.py` に日次活動集計機能あり
- `weekly-summary/main.py` にタスク集計機能あり（Cloud Function）
- これらが本番で正しく動いているかは未確認

**修正方法:**
1. まず既存の日報・週報機能が本番で動作しているか確認
2. 動いていない場合、以下を修正:
   - Cloud Scheduler のジョブが正しく設定されているか確認
   - report-generator がデプロイされているか確認
   - DB接続が正常か確認
3. 日報・週報の内容を充実させる:
   - チャットワークのやり取り要約を追加
   - 完了タスクのリストを追加
   - 未対応の質問・依頼のリストを追加
   - 社長向けの「今日のハイライト3行」サマリーを追加
4. 配信先の設定（社長用ルーム、各スタッフ用ルーム）

---

### 7-2. 会議アジェンダの自動作成

**現状:** Phase C（会議系）は70%。Zoom議事録はPR #448でマージ済み（2026-02-10）。MVP1（会議前準備支援、Phase C+）は未着手

**Zoom議事録の本番稼働に必要な残作業:**
1. Zoom Marketplace でServer-to-Server OAuth App 作成（`recording:read:admin` スコープ）
2. Secret Manager への3つの鍵の登録
3. `cloudbuild.yaml` への `ENABLE_ZOOM_MEETING_MINUTES=true` 追加
4. フィーチャーフラグ（`capability_bridge.py`）の有効化:
   - `ENABLE_MEETING_TRANSCRIPTION`: False → True
   - `ENABLE_MEETING_MINUTES`: False → True

**会議アジェンダ自動作成の実装方法:**
1. Googleカレンダーから会議予定を取得
2. 会議に関連するチャットワークの未解決事項を収集
3. AIが「議題リスト + 時間配分 + 担当者」形式でアジェンダを生成
4. 参加者に事前配布

---

### 7-3. メール連携（Gmail）

**修正方法:**
1. Gmail API連携を実装
2. 受信メール → 要約 → チャットワークで報告
3. 「○○と返信して」でメール送信
4. 重要度判定（即通知/日次まとめ/スキップ）

---

### 7-4. カレンダー連携（Googleカレンダー）

**修正方法:**
1. Google Calendar API連携を実装
2. 「来週火曜にミーティング入れて」→ 自動登録 + 相手に通知
3. 予定の衝突チェック
4. 毎朝「今日の予定」をチャットワークで報告

---

### 7-5. 経費・請求書処理

**修正方法:**
1. 請求書PDF読み取り機能（Phase M1のPDF処理機能を活用）
2. 読み取った内容をDBに記録
3. 「今月の経費まとめて」で一覧生成
4. 承認待ちの経費をリマインド

---

### 7-6. 資料作成の代行

**現状:** Phase G（生成系）が80%。Google Sheets/Slides連携のTODOが残っている
**フィーチャーフラグ:** `ENABLE_GOOGLE_SHEETS: True`、`ENABLE_GOOGLE_SLIDES: True`

**修正方法:**
1. Google Slides API連携のTODOを完了させる
2. テンプレートベースの資料自動生成を実装
3. 「○○の提案資料作って」でスライド自動生成

---

## 第8部: 管理ダッシュボード（スマホ対応）

### 8-1. 管理ダッシュボードの現状

**現状:**
- `admin-dashboard/` ディレクトリが存在（React/Vite）
- 15ページ分のコンポーネントが作成済み（合計4,148行）:
  - dashboard.tsx（371行）— ダッシュボード
  - brain.tsx（343行）— AI脳の状態
  - costs.tsx（465行）— コスト管理
  - goals.tsx（272行）— 目標管理
  - insights.tsx（239行）— インサイト
  - integrations.tsx（198行）— 外部連携
  - login.tsx（200行）— ログイン
  - meetings.tsx（201行）— 会議
  - members.tsx（309行）— メンバー
  - org-chart.tsx（264行）— 組織図
  - proactive.tsx（199行）— 能動的監視
  - system.tsx（296行）— システム
  - tasks.tsx（232行）— タスク
  - teachings.tsx（280行）— CEO教え
  - wellness.tsx（279行）— ウェルネス
- 設計書: `docs/32_admin_dashboard.md`
- **課題:** バックエンドAPIとの接続、本番デプロイが未完了の可能性

**修正方法:**
1. バックエンドAPI（`api/` FastAPI）との接続を完了させる
2. レスポンシブデザイン（スマホ対応）を確認・修正
3. PWA（Progressive Web App）化して、スマホのホーム画面に追加できるようにする
4. まずは以下の3機能を優先してスマホから使えるようにする:
   - 承認機能
   - システム稼働状況の確認
   - 緊急停止ボタン
5. Cloud Runにデプロイ
6. 認証を追加（このダッシュボードは特にセキュリティが重要）

---

## 第9部: 自律運用の段階的実装

### 9-1. 自己診断機能（Phase 1）

**修正方法:**
1. エラー発生時にソウル君が自動で原因を調査する仕組みを追加
2. 調査結果を開発者にレポートとして送信
3. エラーのパターン分析（同じエラーが繰り返されていないか）

### 9-2. 修正案の提案（Phase 2）

**修正方法:**
1. エラーの原因を特定した後、修正案を自動で生成
2. 修正案にはテストコードも含める
3. PRの下書きを自動作成

### 9-3. 人間承認付き自動修正（Phase 3）

**修正方法:**
1. 開発者がPRをレビュー・承認する
2. 承認後にCI/CDで自動テスト → マージ → デプロイ
3. **絶対に守るルール: 人間の最終承認を省略しないこと**

---

## 第10部: 本番環境の既存インフラ状況

### Cloud Functions（18個）

| 関数名 | 状態 | 用途 |
|--------|------|------|
| chatwork-webhook | ACTIVE | メインWebhook |
| chatwork-main | ACTIVE | ChatWork API |
| remind-tasks | ACTIVE | タスクリマインド（土日祝スキップ） |
| sync-chatwork-tasks | ACTIVE | タスク同期（毎時） |
| check-reply-messages | ACTIVE | 返信チェック（5分毎） |
| cleanup-old-data | ACTIVE | 古いデータ削除（毎日3時） |
| pattern-detection | ACTIVE | A1〜A4検知統合 |
| personalization-detection | ACTIVE | A2属人化検出（毎日6時） |
| bottleneck-detection | ACTIVE | A3ボトルネック検出（毎日8時） |
| weekly-report | ACTIVE | 週次レポート（月曜9時） |
| goal-daily-check | ACTIVE | 目標チェック（毎日17時） |
| goal-daily-reminder | ACTIVE | 目標リマインド（毎日18時） |
| goal-morning-feedback | ACTIVE | 朝フィードバック（毎日8時） |
| goal-consecutive-unanswered | ACTIVE | 連続未回答検出（毎日9時） |
| watch_google_drive | ACTIVE | Google Drive監視 |
| sync-room-members | ACTIVE | ルームメンバー同期（月曜8時） |
| update-schema | ACTIVE | スキーマ更新 |
| schema-patch | FAILED | 廃止予定 |

### Cloud Scheduler（19個）

| ジョブ名 | スケジュール | 状態 |
|----------|------------|------|
| check-reply-messages-job | 5分毎 | ENABLED |
| sync-chatwork-tasks-job | 毎時 | ENABLED |
| sync-done-tasks-job | 4時間毎 | ENABLED |
| remind-tasks-job | 毎日08:30 | ENABLED |
| cleanup-old-data-job | 毎日03:00 | ENABLED |
| personalization-detection-daily | 毎日06:00 | ENABLED |
| bottleneck-detection-daily | 毎日08:00 | ENABLED |
| emotion-detection-daily | 毎日10:00 | ENABLED |
| pattern-detection-hourly | 毎時15分 | ENABLED |
| weekly-report-monday | 月曜09:00 | ENABLED |
| goal-daily-check-job | 毎日17:00 | ENABLED |
| goal-daily-reminder-job | 毎日18:00 | ENABLED |
| goal-morning-feedback-job | 毎日08:00 | ENABLED |
| goal-consecutive-unanswered-job | 毎日09:00 | ENABLED |
| daily-reminder-job | 毎日18:00 | ENABLED |
| weekly-summary-job | 金曜18:00 | ENABLED |
| weekly-summary-manager-job | 金曜18:05 | ENABLED |
| sync-room-members-job | 月曜08:00 | ENABLED |
| soulkun-task-polling | 5分毎 | PAUSED |

### フィーチャーフラグ（capability_bridge.py）

| フラグ | 状態 | 備考 |
|--------|------|------|
| ENABLE_IMAGE_PROCESSING | True | 有効 |
| ENABLE_PDF_PROCESSING | True | 有効 |
| ENABLE_URL_PROCESSING | True | 有効 |
| ENABLE_AUDIO_PROCESSING | False | Phase M2まで無効 |
| ENABLE_VIDEO_PROCESSING | False | コスト高で無効 |
| ENABLE_DOCUMENT_GENERATION | True | 有効 |
| ENABLE_IMAGE_GENERATION | True | 有効 |
| ENABLE_VIDEO_GENERATION | False | コスト高で無効 |
| ENABLE_DEEP_RESEARCH | True | 有効 |
| ENABLE_GOOGLE_SHEETS | True | 有効 |
| ENABLE_GOOGLE_SLIDES | True | 有効 |
| ENABLE_CEO_FEEDBACK | True | 有効 |
| ENABLE_MEETING_TRANSCRIPTION | False | Phase C MVP0で有効化予定 |
| ENABLE_MEETING_MINUTES | False | Phase C MVP1で有効化予定 |

### proactive-monitorの状態

| 環境変数 | デフォルト値 | 備考 |
|----------|------------|------|
| USE_PROACTIVE_MONITOR | false | デフォルト無効 |
| PROACTIVE_DRY_RUN | true | デフォルトDRY RUN |

---

## 第11部: 技術的負債の棚卸し

### TODO/FIXME の整理（152件、73ファイル）

これらは「後で直す」と書かれた箇所です。全件を棚卸しして優先度をつける必要があります。

**実施方法:**
```
grep -rn "TODO\|FIXME" lib/ chatwork-webhook/ --include="*.py" | grep -v "__pycache__\|test_"
```

**分類基準:**
- **即時対応:** セキュリティ関連のTODO
- **短期対応:** 機能不完全のTODO（スタブ実装等）
- **中期対応:** リファクタリング・最適化のTODO
- **削除可能:** 既に対応済みだがTODOコメントが残っているもの

### 設計と実装のギャップ（DESIGN_IMPLEMENTATION_GAP_REPORT.md）

| 層 | 実装度 | 残タスク |
|----|--------|---------|
| Context Builder | 100% | なし |
| LLM Brain | 100% | なし |
| Guardian Layer | 100% | なし |
| Authorization Gate | 100% | TOOL_REQUIRED_LEVELS未定義 |
| Observability | 60% | DB永続化未実装 |
| Tool Executor | 70% | 一部手動のまま |

---

## 第12部: 作業の優先順位（3AI合議による推奨順序）

### 即座に着手すべき（Week 1-2）

| # | やること | 理由 |
|---|---------|------|
| 1 | セキュリティ修正の本番反映確認（第2部全体） | 修正は完了しているが本番デプロイ状況・実際の動作確認が必要 |
| 2 | IMPLEMENTATION_STATUS.md の最新化 | 2026-02-08版のまま止まっており、2/9以降の修正が反映されていない |
| 3 | 全機能の本番動作確認 | 既存機能が本番で正しく動いているか1つずつチェック |
| 4 | 監視のDB永続化（第3部 3-1） | 問題発生時の原因追跡ができない |
| 5 | Langfuse本格稼働（第3部 3-2） | AIのコスト・品質管理ができない |

### 次に着手すべき（Week 3-4）

| # | やること | 理由 |
|---|---------|------|
| 6 | 監視のDB永続化（第3部 3-1） | 問題発生時の原因追跡 |
| 7 | Langfuse本格稼働（第3部 3-2） | AIのコスト・品質管理 |
| 8 | ステージング環境構築（第3部 3-3） | 本番障害の防止 |
| 9 | ランブック作成（第3部 3-4） | 障害時の迅速な対応 |

### その次に着手すべき（Week 5-8）

| # | やること | 理由 |
|---|---------|------|
| 10 | プロンプトバージョン管理（第4部 4-1） | AI品質の安定化 |
| 11 | AI評価データセット充実（第4部 4-2） | 品質の定量管理 |
| 12 | MVV検証の専用モジュール化（第5部 5-1） | キャラクター性の確実な担保 |
| 13 | 承認フローの本番検証（第6部 6-1） | 承認漏れの防止 |
| 14 | 管理ダッシュボード完成（第8部） | スマホからの管理 |

### 安定化後に着手（Week 9以降）

| # | やること | 理由 |
|---|---------|------|
| 15 | 日報・週報自動まとめ（第7部 7-1） | スタッフの業務効率化 |
| 16 | 会議アジェンダ自動作成（第7部 7-2） | 会議の生産性向上 |
| 17 | メール・カレンダー連携（第7部 7-3, 7-4） | 秘書機能の拡充 |
| 18 | 自律運用機能（第9部） | 長期的な自動化 |

---

## 第13部: 経営者向けチェックリスト（進捗管理用）

作業の進捗を確認する際に使用してください。

| # | チェック項目 | 現状 | 対応後の目標 |
|---|------------|------|------------|
| 1 | 全APIに認証があるか | 不合格 | 合格 |
| 2 | 他社の情報が見えないか | 不合格 | 合格 |
| 3 | 安全性チェックが自動化されているか | 不合格 | 合格 |
| 4 | 障害対応マニュアルがあるか | 不合格 | 合格 |
| 5 | テストが大事なところを検査しているか | 不合格 | 合格 |
| 6 | 本番前のリハーサル環境があるか | 不合格 | 合格 |
| 7 | AIの性能を客観的に測れるか | 不合格 | 合格 |
| 8 | AIが嘘をつく対策があるか | 不合格 | 合格 |
| 9 | 設計図と実際が一致しているか | 不合格 | 合格 |
| 10 | AIのコストと速度を見張っているか | 不合格 | 合格 |
| 11 | 「後で直す」を計画的に消しているか | 不合格 | 合格 |
| 12 | AIへの指示書が管理されているか | 不合格 | 合格 |

---

## 付録A: 参照すべき既存ドキュメント

| ファイル | 内容 |
|---------|------|
| CLAUDE.md | 設計OS（全ての判断基準） |
| PROGRESS.md | 進捗履歴（3,000行超） |
| IMPLEMENTATION_STATUS.md | 実装状況の正直な評価 |
| DESIGN_IMPLEMENTATION_GAP_REPORT.md | 設計と実装のギャップ |
| docs/25_llm_native_brain_architecture.md | 脳の詳細設計 |
| docs/30_strategic_improvement_plan_3ai.md | 3AI戦略改善計画 |
| docs/31_emergency_procedures.md | 緊急対応手順 |
| docs/32_admin_dashboard.md | ダッシュボード設計 |

## 付録B: 3AIレビューの原文へのアクセス

この引き継ぎ文書の元となった3AIレビューの詳細は、ブレストプロジェクト（`/Users/kikubookair/quick-topics/qt-251f6bbc/`）の会話履歴に含まれています。

---

*この文書は Claude Opus 4.6 / Codex (GPT-5.2) / Gemini の3AI合議により作成されました。*
*最終更新: 2026-02-18*
