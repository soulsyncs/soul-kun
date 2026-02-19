# 32章 管理ダッシュボード設計

## Document Contract

| 項目 | 内容 |
|------|------|
| **この文書の役割** | ソウルくん管理ダッシュボードの設計SoT |
| **SoT** | フロントエンド構成、認証フロー、APIエンドポイント仕様、セキュリティ要件 |
| **Owner** | CTO / エンジニアリングチーム |
| **更新トリガー** | 画面追加、API変更、認証方式変更、セキュリティ要件変更 |
| **関連** | [CLAUDE.md](../CLAUDE.md)（設計OS）、[04章](04_api_and_security.md)（API設計）、[25章](25_llm_native_brain_architecture.md)（脳設計） |

---

## 1. 概要

### 1-1. 目的

管理者（Level 5以上）がソウルくんの稼働状況をリアルタイムに把握するためのWebダッシュボード。

### 1-2. ミッションとの整合性

> 「人でなくてもできることは全部テクノロジーに任せる」（CLAUDE.md §6-1）

従来、カズさんが手動で確認していた以下の項目を自動化・可視化する：
- AI利用コスト（日次・月次）
- Brain（AI脳）のパフォーマンス（レイテンシ、エラー率、会話数）
- メンバーの登録状況・ウェルネス・目標進捗
- 組織階層・部署別KPI
- プロアクティブAI活動・インサイト・ミーティング記録

### 1-3. Brainバイパスの正当性

CLAUDE.md §1 は「全入力・全出力は脳を通る。バイパス禁止」と定めるが、管理ダッシュボードは以下の理由で正当な例外：

| 条件 | 管理ダッシュボード |
|------|-------------------|
| **データ方向** | 読み取り専用（DBから集計データを取得） |
| **対象** | 管理者のみ（Level 5+） |
| **判断の有無** | なし（数値の表示のみ、AIによる判断を含まない） |
| **メッセージ送信** | なし（ChatWorkやユーザーへの能動的出力なし） |

Brain は「会話の判断」を司る。管理ダッシュボードは「数値の閲覧」を提供する。役割が異なるためバイパスではない。

---

## 2. システム構成

```
┌─────────────┐     HTTPS      ┌──────────────┐     HTTPS     ┌──────────────┐
│   Browser   │ ─────────────> │   Vercel     │ ────────────> │  Cloud Run   │
│  (React)    │                │  (静的配信)   │               │  (FastAPI)   │
└─────────────┘                └──────────────┘               └──────────────┘
                                                                      │
                                                                      │ SQL
                                                                      ▼
                                                               ┌──────────────┐
                                                               │  Cloud SQL   │
                                                               │  PostgreSQL  │
                                                               │ soulkun_tasks│
                                                               └──────────────┘
```

### 2-1. 技術スタック

| レイヤー | 技術 | バージョン |
|---------|------|-----------|
| **フレームワーク** | React | 19.2 |
| **言語** | TypeScript | 5.9 |
| **ビルド** | Vite | 7.3 |
| **ルーティング** | TanStack Router | 1.159 |
| **データ取得** | TanStack Query | 5.90 |
| **スタイリング** | Tailwind CSS | 4.1 |
| **UIコンポーネント** | shadcn/ui (Radix UI) | 3.8 |
| **チャート** | Recharts | 3.7 |
| **アイコン** | Lucide React | 0.564 |
| **バリデーション** | Zod | 4.3 |
| **テスト** | Vitest + React Testing Library | 4.0 / 16.3 |

### 2-2. デプロイ構成

| 項目 | 内容 |
|------|------|
| **フロントエンド** | Vercel（`admin-dashboard/` から自動デプロイ） |
| **バックエンド** | Cloud Run `soul-kun-admin-api`（asia-northeast1） |
| **データベース** | Cloud SQL `soulkun_tasks`（既存スキーマを利用） |
| **認証基盤** | Google Identity Services（OAuth 2.0） |

---

## 3. 認証・認可

### 3-1. 認証フロー

```
Browser                    Vercel (React)            Cloud Run (FastAPI)      Google
   │                            │                           │                    │
   ├─ 1. /login にアクセス ─────►                           │                    │
   │                            │                           │                    │
   ├─ 2. "Googleでログイン"クリック ──────────────────────────────────────────────►
   │                            │                           │                    │
   │◄─ 3. Google ID Token ──────────────────────────────────────────────────────┤
   │                            │                           │                    │
   ├─ 4. POST /admin/auth/google ──────────────────────────►                    │
   │     { id_token: "..." }    │                           │                    │
   │                            │                           │                    │
   │◄─ 5. access_token + Set-Cookie(httpOnly) ──────────────┤                    │
   │                            │                           │                    │
   ├─ 6. GET /admin/auth/me ───────────────────────────────►                    │
   │     (Bearer token + Cookie)│                           │                    │
   │                            │                           │                    │
   │◄─ 7. ユーザー情報 ─────────────────────────────────────┤                    │
   │                            │                           │                    │
   ├─ 8. / (ダッシュボード) へリダイレクト                    │                    │
```

### 3-2. 認可ルール

| 条件 | レスポンス |
|------|-----------|
| 未認証 | 401 Unauthorized |
| 認証済み・Level 4以下 | 403 Forbidden |
| 認証済み・Level 5以上 | 200 OK（データ返却） |

### 3-3. トークン管理

| 項目 | 方式 |
|------|------|
| **プライマリ** | httpOnly Cookie（XSS耐性あり） |
| **フォールバック** | Bearer token（メモリ内保持、localStorageに保存しない） |
| **有効期限** | 7日（JWT exp） |
| **リフレッシュ** | ページロード時に `GET /admin/auth/me` で検証 |
| **SameSite** | `Lax`（CSRF防御。通常のナビゲーションは許可、クロスサイトPOSTはブロック） |
| **Secure** | 本番環境では `Secure` フラグ必須（HTTPS通信のみ） |
| **CSRF対策** | SameSite=Lax + Bearer tokenの併用。状態変更操作はBearerトークン検証も実施 |

---

## 4. 画面構成

**合計15画面**（2026-02-19時点の実装済み一覧）

### 4-1. ルーティング

| パス | ページ名 | 認証 | カテゴリ |
|------|---------|------|---------|
| `/login` | ログイン | 不要 | 認証 |
| `/` | ダッシュボード | 必要 | 経営KPI |
| `/org-chart` | 組織図 | 必要 | 組織 |
| `/members` | メンバー | 必要 | 組織 |
| `/goals` | 目標管理 | 必要 | 組織 |
| `/wellness` | ウェルネス | 必要 | 組織 |
| `/tasks` | タスク | 必要 | 組織 |
| `/brain` | AI脳分析 | 必要 | AI分析 |
| `/insights` | インサイト | 必要 | AI分析 |
| `/meetings` | ミーティング | 必要 | AI分析 |
| `/proactive` | プロアクティブ | 必要 | AI分析 |
| `/teachings` | CEO教え | 必要 | AI設定 |
| `/costs` | コスト管理 | 必要 | 運用 |
| `/integrations` | 連携設定 | 必要 | 運用 |
| `/system` | システムヘルス | 必要 | 運用 |

### 4-2. ダッシュボード（`/`）

経営者向けトップページ。全社のAI活用状況を一目で把握する。

**KPIカード（6枚）:**

| KPI | データソース | ツールチップ |
|-----|-------------|-------------|
| 会話数 | brain_metrics.conversations | ソウルくんがユーザーと行った会話の回数 |
| 平均応答時間 | brain_metrics.avg_latency_ms | 質問を受けてから返答するまでの平均時間 |
| エラー率 | brain_metrics.error_rate | エラーが発生した割合 |
| 本日のコスト | dashboard_summary.total_cost_today | 今日のAI利用にかかった費用（日本円） |
| 予算残高 | dashboard_summary.monthly_budget_remaining | 今月の残り予算（日本円） |
| アクティブアラート | dashboard_summary.active_alerts_count | 対応が必要な警告の数 |

**チャート:** 会話数（棒）、レイテンシ（面）、コスト（面）の3タブ切替

**情報カード:** 最近のアラート、最近のインサイト

### 4-3. 組織図（`/org-chart`）

会社の組織階層をツリー形式で可視化する。

- 部署ツリー表示（親子関係）
- 部署の作成・編集・削除
- 部署詳細（所属メンバー、責任者）

### 4-4. メンバー（`/members`）

全社員の一覧と詳細情報の管理。

- 検索（名前またはメール、デバウンス付き）
- テーブル（名前、部署、役職、レベル、登録日）
- ページネーション（20件/ページ）
- メンバー詳細・部署異動操作

### 4-5. 目標管理（`/goals`）

OKR形式の目標を組織・部署・個人別に管理する。

- 目標一覧（状態フィルタ: active/completed/cancelled）
- 期間別フィルタ（annual/quarterly/monthly）
- 目標詳細（説明、進捗率、達成期限）
- 目標統計（`/admin/goals/stats`）

### 4-6. ウェルネス（`/wellness`）

メンバーの感情・体調アラートを管理する。

- 感情アラート一覧（リスクレベル: high/medium/low）
- アラートステータス（open/acknowledged/resolved）
- 感情トレンドグラフ（部署別・期間別）

### 4-7. タスク（`/tasks`）

AIが抽出・管理するタスクの一覧とKPI。

- タスク概要統計（pending/in_progress/completed/overdue）
- タスク一覧（ソース別フィルタ: chatwork/zoom/manual等）
- ページネーション（20件/ページ）

### 4-8. AI脳分析（`/brain`）

Brain（AI脳）のパフォーマンス分析と判断ログ。

- 期間切替（7日 / 14日 / 30日）
- サマリーカード（総会話数、平均レイテンシ、総コスト）
- 日別メトリクスチャート（会話数 / レイテンシ / エラー率のタブ切替）
- 最近の判断ログテーブル（日時、アクション、確信度、処理時間）

### 4-9. インサイト（`/insights`）

AIが自動抽出した組織インサイトと質問パターン。

- インサイト一覧（重要度別フィルタ: high/medium/low）
- 質問パターン（頻出カテゴリ上位）
- 週次レポート（AI自動生成サマリー）

### 4-10. ミーティング（`/meetings`）

Zoom等のミーティング記録とAI議事録。

- ミーティング一覧（ステータスフィルタ）
- ミーティング詳細（AI議事録、アクションアイテム）
- 参加者一覧

### 4-11. プロアクティブ（`/proactive`）

AIが自律的に実行したアクション（通知・提案等）の履歴。

- プロアクティブアクション一覧（トリガー種別フィルタ）
- 実行統計（`/admin/proactive/stats`）

### 4-12. CEO教え（`/teachings`）

経営者が登録した「ソウルくんへの教え」（AIの判断基準）の管理。

- 教え一覧（カテゴリ別フィルタ、有効/無効フィルタ）
- 教えの競合検出（矛盾する指示の可視化）
- 利用統計（使われた回数・最終使用日）

### 4-13. コスト管理（`/costs`）

AI利用コストの詳細分析と予算管理。

- サマリーカード（30日合計、日次平均、今月、予算状況バー）
- 日別コスト棒グラフ（30日間）
- コスト内訳（モデル別の円グラフ＋テーブル / ティア別テーブル）
- 月次サマリーテーブル
- 全金額表示は **日本円（¥）**

### 4-14. 連携設定（`/integrations`）

外部サービス（Google Calendar等）との連携状態管理。

- Google Calendarの接続状態
- OAuth接続・切断操作

### 4-15. システムヘルス（`/system`）

AIシステムの稼働状態監視と緊急停止操作。

- **緊急停止パネル**（稼働中 = 緑 / 停止中 = 赤、2段階確認付き）
- ヘルスサマリー（総会話数、ユニークユーザー、応答時間、エラー数）
- メトリクス推移テーブル（7/14/30日間）
- 自己診断一覧（AIによる自己評価スコアと課題）

---

## 5. API エンドポイント

全エンドポイントは `/api/v1/admin/` 配下。`organization_id` フィルタ必須（鉄則#1）。

### 5-1. 認証

| メソッド | パス | 説明 | レート制限 |
|---------|------|------|-----------|
| POST | `/admin/auth/google` | Google ID Token でログイン | **10回/分** |
| POST | `/admin/auth/token-login` | Bearer Token でログイン | **10回/分** |
| GET | `/admin/auth/me` | 現在のユーザー情報取得 | 100回/分 |
| POST | `/admin/auth/logout` | ログアウト（Cookie クリア） | 100回/分 |

### 5-2. ダッシュボード

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/dashboard/summary` | `period` (today/7d/30d) | KPI、アラート、インサイト |

### 5-3. 組織図・部署

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/departments` | なし | 部署ツリー |
| GET | `/admin/departments/{dept_id}` | なし | 部署詳細 |
| POST | `/admin/departments` | body | 部署作成 |
| PUT | `/admin/departments/{dept_id}` | body | 部署更新 |
| DELETE | `/admin/departments/{dept_id}` | なし | 部署削除 |

### 5-4. メンバー

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/members` | `search`, `dept_id`, `limit`, `offset` | メンバー一覧 |
| GET | `/admin/members/{user_id}` | なし | メンバー詳細 |
| GET | `/admin/members/{user_id}/detail` | なし | メンバー完全詳細（目標・タスク含む） |
| PUT | `/admin/members/{user_id}` | body | メンバー更新 |
| PUT | `/admin/members/{user_id}/departments` | body | 部署異動 |

### 5-5. 目標管理

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/goals` | `status`, `department_id`, `period_type`, `limit`, `offset` | 目標一覧 |
| GET | `/admin/goals/{goal_id}` | なし | 目標詳細 |
| GET | `/admin/goals/stats` | なし | 目標統計 |

### 5-6. ウェルネス

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/wellness/alerts` | `risk_level`, `status`, `limit`, `offset` | 感情アラート一覧 |
| GET | `/admin/wellness/trends` | `days`, `department_id` | 感情トレンド |

### 5-7. タスク

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/tasks/overview` | なし | タスク概要統計 |
| GET | `/admin/tasks/list` | `source`, `limit`, `offset` | タスク一覧 |

### 5-8. AI脳分析

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/brain/metrics` | `days` (1-30) | 日別メトリクス |
| GET | `/admin/brain/logs` | `limit`, `offset` | 判断ログ |

### 5-9. インサイト

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/insights` | `importance`, `status`, `limit`, `offset` | インサイト一覧 |
| GET | `/admin/insights/patterns` | `limit` | 質問パターン |
| GET | `/admin/insights/weekly-reports` | `limit` | 週次レポート |

### 5-10. ミーティング

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/meetings` | `status`, `limit`, `offset` | ミーティング一覧 |
| GET | `/admin/meetings/{meeting_id}` | なし | ミーティング詳細 |

### 5-11. プロアクティブ

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/proactive/actions` | `trigger_type`, `limit`, `offset` | アクション一覧 |
| GET | `/admin/proactive/stats` | なし | プロアクティブ統計 |

### 5-12. CEO教え

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/teachings` | `category`, `active_only`, `limit`, `offset` | 教え一覧 |
| GET | `/admin/teachings/conflicts` | `limit` | 競合検出 |
| GET | `/admin/teachings/usage-stats` | なし | 利用統計 |

### 5-13. コスト

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/costs/daily` | `days` (1-90) | 日別コスト |
| GET | `/admin/costs/monthly` | なし | 月次サマリー |
| GET | `/admin/costs/breakdown` | `days` (1-90) | モデル別・ティア別内訳 |

### 5-14. 連携設定

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/admin/integrations/google-calendar/status` | Google Calendar連携状態 |
| GET | `/admin/integrations/google-calendar/connect` | OAuth認証URL取得 |
| POST | `/admin/integrations/google-calendar/disconnect` | 連携解除 |

### 5-15. システムヘルス

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/admin/system/health` | ヘルスサマリー（会話数、応答時間等） |
| GET | `/admin/system/metrics` | メトリクス推移（`?days=7/14/30`） |
| GET | `/admin/system/diagnoses` | 自己診断一覧 |

### 5-16. 緊急停止

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/admin/emergency-stop/status` | 現在の停止状態取得 |
| POST | `/admin/emergency-stop/activate` | 緊急停止の有効化（全Tool実行をブロック） |
| POST | `/admin/emergency-stop/deactivate` | 緊急停止の解除 |

---

## 6. セキュリティ要件

### 6-1. CLAUDE.md 鉄則との対応

| 鉄則# | 対応 |
|--------|------|
| #1 organization_id | 全SQLクエリに `organization_id` フィルタ適用 |
| #4 認証必須 | Google OAuth + JWT。Level 5以上のみアクセス可 |
| #5 ページネーション | メンバーリスト: 20件/ページ。ログ: 50件/ページ |
| #8 機密情報除外 | エラーレスポンスにスタックトレースや内部情報を含めない |
| #9 SQLパラメータ化 | パラメータバインディングを使用（pg8000/asyncpg等、利用ドライバに準拠） |

### 6-2. PII保護

| 項目 | 方針 |
|------|------|
| **表示OK** | メンバー名、部署、役職（社内管理ツールのため） |
| **表示NG** | チャット本文、パスワード、APIキー |
| **ログNG** | 個人名、メールアドレス（鉄則#8、§9-3）。`mask_email()` で隠蔽済み（lib/logging.py） |
| **検索クエリ** | `search` パラメータにメールが含まれる場合、アクセスログから除外またはマスキングが必要 |

### 6-3. CSP（Content Security Policy）

`index.html` の `<meta>` タグで設定：
- `default-src 'self'`
- `script-src 'self' https://accounts.google.com https://apis.google.com`
- `connect-src 'self' https://accounts.google.com https://*.cloudfunctions.net https://*.run.app`
- `object-src 'none'`

### 6-4. レート制限（実装済み）

| エンドポイント | 制限 | 実装 |
|-------------|------|------|
| `/admin/auth/google`, `/admin/auth/token-login` | **10回/分** | slowapi @limiter.limit("10/minute") |
| 全管理API（上記以外） | **100回/分** | slowapi SlowAPIMiddleware default_limits |
| `/health` | 制限なし | @limiter.exempt |

**IP抽出方式**: GCP Cloud Run 対応（`X-Forwarded-For` 末尾エントリを使用）

---

## 7. 国際化（i18n）

### 7-1. 現在の方針

**日本語ハードコード** を採用。理由：
- ユーザーは全員日本語話者（株式会社ソウルシンクス社員）
- i18nフレームワーク導入はPhase 2以降（外販時）

### 7-2. 日本語化済み項目

- `index.html`: `lang="ja"`, `<title>ソウルくん管理画面</title>`
- 全ページ: ヘッダー、テーブルヘッダー、ラベル、ボタン、エラーメッセージ
- ツールチップ: 全KPIカード、全セクションタイトルに初心者向け説明を追加
- サイドバー: ナビゲーション項目、ユーザー情報表示
- 通貨表示: 全コスト表示は日本円（¥）。`toFixed(0)` で整数表示

---

## 8. テスト戦略

### 8-1. フロントエンドテスト

| レイヤー | ツール | カバレッジ目標 |
|---------|--------|-------------|
| ユニット | Vitest + RTL | 60% |
| コンポーネント | Vitest + RTL | 主要コンポーネント（KPIカード等） |
| E2E | Playwright（将来） | ログイン→ダッシュボード閲覧 |

### 8-2. バックエンドテスト

| レイヤー | ツール | カバレッジ目標 |
|---------|--------|-------------|
| ユニット | pytest | 80% |
| 結合 | pytest + Cloud SQL Proxy | 主要クエリ |

---

## 9. 将来の拡張計画

| Phase | 機能 | 優先度 |
|-------|------|--------|
| 2 | CSVエクスポート | 高 |
| 2 | 予算アラート（Slack/メール通知） | 高 |
| 2 | 経営者向けKPI追加（ROI・全社目標進捗・トップ3緊急案件） | 高 |
| 2 | 組織図ドリルダウン（部署クリック→目標/ウェルネス表示） | 中 |
| 2 | ダークモード | 中 |
| 2 | モバイルレスポンシブ最適化 | 中 |
| 3 | ユーザー管理（招待・権限変更） | 中 |
| 3 | 監査ログ画面 | 中 |
| 3 | WebSocket リアルタイム更新 | 低 |
| 4 | i18n（多言語対応） | 低（外販時） |
| 4 | マルチ組織切替 | 低（外販時） |

---

## 10. ディレクトリ構成

```
admin-dashboard/
├── public/
│   └── vite.svg
├── src/
│   ├── main.tsx                     # エントリーポイント
│   ├── index.css                    # Tailwind CSS
│   ├── App.tsx                      # ルーター設定（TanStack Router）
│   ├── lib/
│   │   ├── api.ts                   # APIクライアント（認証付き）
│   │   ├── api.test.ts              # APIテスト
│   │   └── utils.ts                 # cn() ユーティリティ
│   ├── hooks/
│   │   ├── use-auth.tsx             # AuthProvider + useAuth フック
│   │   ├── use-auth.test.tsx        # 認証テスト
│   │   └── use-system.ts            # システムヘルス + 緊急停止フック
│   ├── types/
│   │   └── api.ts                   # 型定義（バックエンドPydanticと対応）
│   ├── components/
│   │   ├── ui/                      # shadcn/ui コンポーネント
│   │   │   ├── badge.tsx
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── info-tooltip.tsx     # ツールチップ（初心者向け説明）
│   │   │   ├── input.tsx
│   │   │   ├── separator.tsx
│   │   │   ├── skeleton.tsx
│   │   │   ├── table.tsx
│   │   │   ├── tabs.tsx
│   │   │   └── tooltip.tsx
│   │   ├── layout/
│   │   │   ├── app-layout.tsx       # メインレイアウト
│   │   │   └── sidebar.tsx          # サイドバーナビゲーション（15画面）
│   │   └── dashboard/
│   │       ├── kpi-card.tsx         # KPIメトリクスカード
│   │       └── kpi-card.test.tsx    # KPIカードテスト
│   ├── pages/
│   │   ├── login.tsx                # Google OAuthログイン
│   │   ├── dashboard.tsx            # ダッシュボード（KPI・チャート）
│   │   ├── org-chart.tsx            # 組織図（部署ツリー）
│   │   ├── members.tsx              # メンバー一覧・詳細
│   │   ├── goals.tsx                # 目標管理（OKR）
│   │   ├── wellness.tsx             # ウェルネス・感情アラート
│   │   ├── tasks.tsx                # タスク一覧
│   │   ├── brain.tsx                # AI脳分析
│   │   ├── insights.tsx             # インサイト・質問パターン
│   │   ├── meetings.tsx             # ミーティング・AI議事録
│   │   ├── proactive.tsx            # プロアクティブアクション履歴
│   │   ├── teachings.tsx            # CEO教え管理
│   │   ├── costs.tsx                # コスト管理
│   │   ├── integrations.tsx         # 連携設定
│   │   └── system.tsx               # システムヘルス・緊急停止
│   └── test/
│       └── setup.ts                 # Vitest セットアップ
├── index.html                       # HTMLテンプレート（CSP設定含む）
├── package.json
├── tsconfig.json
├── vite.config.ts
├── vercel.json                      # Vercelデプロイ設定
└── .env.example                     # 環境変数テンプレート
```

---

**文書バージョン**: 2.0
**最終更新**: 2026-02-19
**更新内容**: Phase C-2 — 5画面記載から15画面の実態に完全更新。APIエンドポイント・レート制限・緊急停止を追記。
**作成者**: Claude Sonnet 4.6 + Kazu
