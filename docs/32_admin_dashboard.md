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
- メンバーの登録状況
- 予算消化状況

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

### 4-1. ルーティング

| パス | ページ | 認証 | 説明 |
|------|--------|------|------|
| `/login` | ログイン | 不要 | Google OAuth ログイン |
| `/` | ダッシュボード | 必要 | KPI、アラート、インサイト、推移チャート |
| `/brain` | AI脳分析 | 必要 | Brain メトリクス、判断ログ |
| `/costs` | コスト管理 | 必要 | 日次・月次コスト、予算、内訳 |
| `/members` | メンバー | 必要 | メンバー一覧、検索、ページネーション |

### 4-2. ダッシュボード画面（`/`）

**KPIカード（6枚）:**

| KPI | データソース | ツールチップ |
|-----|-------------|-------------|
| 会話数 | brain_metrics.conversations | ソウルくんがユーザーと行った会話の回数 |
| 平均応答時間 | brain_metrics.avg_latency_ms | 質問を受けてから返答するまでの平均時間 |
| エラー率 | brain_metrics.error_rate | エラーが発生した割合 |
| 本日のコスト | dashboard_summary.total_cost_today | 今日のAI利用にかかった費用 |
| 予算残高 | dashboard_summary.monthly_budget_remaining | 今月の残り予算 |
| アクティブアラート | dashboard_summary.active_alerts_count | 対応が必要な警告の数 |

**チャート:** 会話数（棒）、レイテンシ（面）、コスト（面）の3タブ切替

**情報カード:** 最近のアラート、最近のインサイト

### 4-3. AI脳分析画面（`/brain`）

- 期間切替（7日 / 14日 / 30日）
- サマリーカード（総会話数、平均レイテンシ、総コスト）
- 日別メトリクスチャート（会話数 / レイテンシ / エラー率のタブ切替）
- 最近の判断ログテーブル（日時、アクション、確信度、処理時間）

### 4-4. コスト管理画面（`/costs`）

- サマリーカード（30日合計、日次平均、今月、予算状況バー）
- 日別コスト棒グラフ（30日間）
- コスト内訳（モデル別の円グラフ＋テーブル / ティア別テーブル）
- 月次サマリーテーブル

### 4-5. メンバー画面（`/members`）

- 検索（名前またはメール、`useDeferredValue` でデバウンス）
- テーブル（名前、部署、役職、レベル、登録日）
- ページネーション（20件/ページ）

---

## 5. API エンドポイント

全エンドポイントは `/api/v1/admin/` 配下。`organization_id` フィルタ必須（鉄則#1）。

### 5-1. 認証

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/admin/auth/google` | Google ID Token でログイン |
| POST | `/admin/auth/token-login` | Bearer Token でログイン |
| GET | `/admin/auth/me` | 現在のユーザー情報取得 |
| POST | `/admin/auth/logout` | ログアウト（Cookie クリア） |

### 5-2. ダッシュボード

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/dashboard/summary` | `period` (today/7d/30d) | KPI、アラート、インサイト |

### 5-3. AI脳分析

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/brain/metrics` | `days` (1-30) | 日別メトリクス |
| GET | `/admin/brain/logs` | `limit`, `offset` | 判断ログ |

### 5-4. コスト

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/costs/daily` | `days` (1-90) | 日別コスト |
| GET | `/admin/costs/monthly` | なし | 月次サマリー |
| GET | `/admin/costs/breakdown` | `days` (1-90) | モデル別・ティア別内訳 |

### 5-5. メンバー

| メソッド | パス | パラメータ | 説明 |
|---------|------|-----------|------|
| GET | `/admin/members` | `search`, `limit`, `offset` | メンバー一覧 |
| GET | `/admin/members/{user_id}` | なし | メンバー詳細 |

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
| **ログNG** | 個人名、メールアドレス（鉄則#8、§9-3） |
| **検索クエリ** | `search` パラメータにメールが含まれる場合、アクセスログから除外またはマスキングが必要。Cloud Runのアクセスログにクエリパラメータが記録されるため |

### 6-3. CSP（Content Security Policy）

`index.html` の `<meta>` タグで設定：
- `default-src 'self'`
- `script-src 'self' https://accounts.google.com https://apis.google.com`
- `connect-src 'self' https://accounts.google.com https://*.cloudfunctions.net https://*.run.app`
- `object-src 'none'`

### 6-4. 今後追加すべきセキュリティ

| 項目 | 優先度 | フェーズ | 説明 |
|------|--------|---------|------|
| Rate Limiting | **最高** | 1.1 | 認証エンドポイント（`/admin/auth/*`）に 10req/min/IP。トークンリプレイ攻撃の防止 |
| クエリパラメータのPIIマスキング | 高 | 1.1 | Cloud Runアクセスログから `search` パラメータを除外・マスキング |
| Audit Log | 中 | 2 | 管理画面アクセスログ記録 |
| RBAC拡張 | 低 | 3 | Level 5 と Level 6 の表示差分 |

---

## 7. 国際化（i18n）

### 7-1. 現在の方針

Phase 1 では **日本語ハードコード** を採用。理由：
- ユーザーは全員日本語話者（株式会社ソウルシンクス社員）
- i18nフレームワーク導入はPhase 2以降（外販時）

### 7-2. 日本語化済み項目

- `index.html`: `lang="ja"`, `<title>ソウルくん管理画面</title>`
- 全ページ: ヘッダー、テーブルヘッダー、ラベル、ボタン、エラーメッセージ
- ツールチップ: 全KPIカード、全セクションタイトルに初心者向け説明を追加
- サイドバー: ナビゲーション項目、ユーザー情報表示

---

## 8. テスト戦略

### 8-1. フロントエンドテスト

| レイヤー | ツール | カバレッジ目標 |
|---------|--------|-------------|
| ユニット | Vitest + RTL | 60% |
| コンポーネント | Vitest + RTL | 主要コンポーネント |
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
│   │   └── use-auth.test.tsx        # 認証テスト
│   ├── types/
│   │   └── api.ts                   # 型定義（バックエンドPydanticと対応）
│   ├── components/
│   │   ├── ui/                      # shadcn/ui コンポーネント
│   │   │   ├── badge.tsx
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── info-tooltip.tsx     # ツールチップ（初心者向け説明）
│   │   │   ├── separator.tsx
│   │   │   ├── table.tsx
│   │   │   ├── tabs.tsx
│   │   │   └── tooltip.tsx
│   │   ├── layout/
│   │   │   ├── app-layout.tsx       # メインレイアウト
│   │   │   └── sidebar.tsx          # サイドバーナビゲーション
│   │   └── dashboard/
│   │       ├── kpi-card.tsx         # KPIメトリクスカード
│   │       └── kpi-card.test.tsx    # KPIカードテスト
│   ├── pages/
│   │   ├── login.tsx                # Google OAuthログイン
│   │   ├── dashboard.tsx            # ダッシュボード
│   │   ├── brain.tsx                # AI脳分析
│   │   ├── costs.tsx                # コスト管理
│   │   └── members.tsx              # メンバー一覧
│   └── test/
│       └── setup.ts                 # Vitest セットアップ
├── index.html                       # HTMLテンプレート（CSP設定含む）
├── package.json
├── tsconfig.json
├── vite.config.ts
├── vercel.json                      # Vercelデプロイ設定
├── DESIGN.md                        # 詳細設計（レガシー、本文書に統合予定）
└── .env.example                     # 環境変数テンプレート
```

---

**文書バージョン**: 1.0
**最終更新**: 2026-02-15
**作成者**: Claude Opus 4.6 + Kazu
