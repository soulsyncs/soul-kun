# 第6章 Phase 3 Googleドライブ連携 詳細設計書

**バージョン:** v1.0.0
**作成日:** 2026-01-19
**最終更新:** 2026-01-19
**ステータス:** 設計完了・実装準備完了

---

## 目次

1. [概要と目的](#1-概要と目的)
2. [アーキテクチャ設計](#2-アーキテクチャ設計)
3. [Googleドライブフォルダ構造設計](#3-googleドライブフォルダ構造設計)
4. [データベース追加設計](#4-データベース追加設計)
5. [Googleドライブ監視ジョブ設計](#5-googleドライブ監視ジョブ設計)
6. [フォルダ→権限マッピング設計](#6-フォルダ権限マッピング設計)
7. [ドキュメント処理フロー設計](#7-ドキュメント処理フロー設計)
8. [エラーハンドリング設計](#8-エラーハンドリング設計)
9. [運用設計](#9-運用設計)
10. [セキュリティ設計](#10-セキュリティ設計)
11. [テスト設計](#11-テスト設計)
12. [実装チェックリスト](#12-実装チェックリスト)

---

## 1. 概要と目的

### 1.1 本設計書の位置づけ

本設計書は、Phase 3詳細設計書（05_phase3_knowledge_detailed_design.md）の補遺として、
Googleドライブ連携機能の詳細設計を定義します。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Phase 3 設計書構成                                │
└─────────────────────────────────────────────────────────────────────────┘

05_phase3_knowledge_detailed_design.md
├── データベース設計（documents, document_chunks, etc.）
├── Pinecone統合設計
├── API設計（検索、フィードバック）
├── 処理フロー設計
└── Phase 3.5連携設計

06_phase3_google_drive_integration.md（本書）
├── Googleドライブ連携アーキテクチャ
├── フォルダ構造設計
├── 監視ジョブ設計
├── フォルダ→権限マッピング
└── 運用・セキュリティ設計
```

### 1.2 実現する機能

**カズさんの要望：**
> 「Googleドライブに資料を格納して、ソウルくんが自動で汲み取りに行く。
>  Googleドライブに格納する情報を変えていけば更新も楽ちん」

**本設計で実現すること：**

| # | 機能 | 詳細 |
|---|------|------|
| 1 | **自動取り込み** | Googleドライブにファイルを追加すると、5分以内にソウルくんの知識に反映 |
| 2 | **自動更新** | ファイルを更新すると、自動的に再取り込み |
| 3 | **自動削除** | ファイルを削除すると、Pineconeからも削除 |
| 4 | **フォルダ→権限** | フォルダ構造で機密区分（public/internal/confidential）を自動設定 |
| 5 | **部署別アクセス** | 部署フォルダに入れると、その部署のみアクセス可能 |

### 1.3 設計原則

| # | 原則 | 本設計での適用 |
|---|------|--------------|
| 1 | **シンプルな運用** | 社員はGoogleドライブにファイルを入れるだけ |
| 2 | **自動化優先** | 手動操作を最小化（監視ジョブで自動処理） |
| 3 | **フォルダ＝権限** | フォルダ構造がそのまま権限設定になる |
| 4 | **失敗に強い** | エラー時はリトライ、ログ記録、アラート |
| 5 | **10の鉄則準拠** | organization_id、監査ログ、etc. |

---

## 2. アーキテクチャ設計

### 2.1 全体アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          Googleドライブ連携 全体アーキテクチャ                             │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                                    [社員]
                                      │
                                      │ ファイルをアップロード
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                               Google Drive                                               │
│                                                                                          │
│   📁 ソウルくん用フォルダ（ROOT_FOLDER_ID）                                               │
│   ├── 📁 全社共有（public）                                                              │
│   │   ├── 📁 会社紹介（category: A）                                                     │
│   │   └── 📁 サービス情報（category: F）                                                 │
│   ├── 📁 社員限定（internal）                                                            │
│   │   ├── 📁 MVV・理念（category: A）                                                    │
│   │   └── 📁 業務マニュアル（category: B）                                               │
│   └── 📁 部署別（confidential）                                                          │
│       ├── 📁 営業部（department_id: dept_sales）                                         │
│       └── 📁 総務部（department_id: dept_admin）                                         │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ Google Drive API
                                      │ (Changes API)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              Cloud Scheduler                                             │
│                         (5分ごとにトリガー)                                               │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              Cloud Functions                                             │
│                        (watch_google_drive)                                              │
│                                                                                          │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐                       │
│   │ 1. 変更検知      │ → │ 2. ファイル処理  │ → │ 3. インデックス │                       │
│   │                 │   │                 │   │                 │                       │
│   │ ・新規ファイル   │   │ ・ダウンロード   │   │ ・チャンク化    │                       │
│   │ ・更新ファイル   │   │ ・テキスト抽出   │   │ ・エンベディング│                       │
│   │ ・削除ファイル   │   │ ・権限決定      │   │ ・Pinecone登録 │                       │
│   └─────────────────┘   └─────────────────┘   └─────────────────┘                       │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                          ┌───────────┴───────────┐
                          │                       │
                          ▼                       ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│         Cloud SQL               │   │          Pinecone               │
│        (PostgreSQL)             │   │       (ベクターDB)               │
│                                 │   │                                 │
│ ・documents                     │   │ ・soulkun-knowledge             │
│ ・document_versions             │   │   (インデックス)                 │
│ ・document_chunks               │   │                                 │
│ ・google_drive_sync_logs        │   │ ・org_soulsyncs                 │
│                                 │   │   (Namespace)                   │
└─────────────────────────────────┘   └─────────────────────────────────┘
                          │                       │
                          └───────────┬───────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              FastAPI (Cloud Run)                                         │
│                                                                                          │
│   POST /api/v1/knowledge/search                                                          │
│   ├── ユーザー認証                                                                        │
│   ├── アクセス可能部署の計算（Phase 3.5連携）                                              │
│   ├── Pinecone検索（メタデータフィルタ）                                                  │
│   ├── 回答生成（GPT-4）                                                                  │
│   └── レスポンス（回答 + 出典 + 注意書き）                                                │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                                   [ユーザー]
                              「経費精算のやり方は？」
                                      ↓
                              「経費精算は以下の手順で...
                               （出典: 経費精算マニュアル p.5）」
```

### 2.2 コンポーネント一覧

| コンポーネント | 役割 | 技術 |
|--------------|------|------|
| **Google Drive** | ドキュメント格納場所 | Google Workspace |
| **Cloud Scheduler** | 定期実行トリガー | GCP |
| **Cloud Functions** | 監視ジョブ実行 | Python 3.11 |
| **Cloud SQL** | メタデータ格納 | PostgreSQL 15 |
| **Pinecone** | ベクター検索 | Pinecone Starter |
| **Cloud Run** | API提供 | FastAPI |
| **OpenAI** | エンベディング・回答生成 | text-embedding-3-small, GPT-4 |

### 2.3 データフロー

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              データフロー詳細                                             │
└─────────────────────────────────────────────────────────────────────────────────────────┘

【ファイル追加時】
1. 社員がGoogleドライブにファイルをアップロード
2. Cloud Scheduler が5分ごとに監視ジョブをトリガー
3. Cloud Functions が Google Drive API Changes を呼び出し
4. 新規ファイルを検知
5. ファイルをダウンロード
6. フォルダパスから classification と department_id を決定
7. テキスト抽出（PDF: PyMuPDF, DOCX: python-docx）
8. チャンク分割（1000文字、200文字オーバーラップ）
9. エンベディング生成（OpenAI text-embedding-3-small）
10. PostgreSQL に documents, document_chunks を保存
11. Pinecone にベクターを upsert

【ファイル更新時】
1-4. 同上
5. 更新されたファイルを検知
6. 既存のドキュメントIDを取得
7. 新バージョンを作成（document_versions）
8. 旧チャンクをソフトデリート
9. 新チャンクを作成
10. Pinecone の旧ベクターを削除、新ベクターを upsert

【ファイル削除時】
1-4. 同上
5. 削除されたファイルを検知
6. documents をソフトデリート（deleted_at = NOW()）
7. Pinecone からベクターを削除
```

---

## 3. Googleドライブフォルダ構造設計

### 3.1 推奨フォルダ構造

```
📁 ソウルくん用フォルダ（ROOT_FOLDER_ID）
│
├── 📁 全社共有                          ← classification: "public"
│   │                                      誰でも閲覧可能
│   ├── 📁 会社紹介                      ← category: "A"
│   │   ├── 会社概要.pdf
│   │   └── 沿革.docx
│   │
│   └── 📁 サービス情報                  ← category: "F"
│       ├── サービス一覧.pdf
│       └── 料金表.xlsx
│
├── 📁 社員限定                          ← classification: "internal"
│   │                                      社員のみ閲覧可能
│   ├── 📁 MVV・理念                     ← category: "A"
│   │   ├── ミッション・ビジョン.pdf
│   │   └── 行動指針.docx
│   │
│   ├── 📁 業務マニュアル                ← category: "B"
│   │   ├── 経費精算マニュアル.pdf
│   │   ├── 出張申請ガイド.docx
│   │   └── 勤怠入力マニュアル.pdf
│   │
│   └── 📁 テンプレート                  ← category: "D"
│       ├── 議事録テンプレート.docx
│       └── 報告書テンプレート.xlsx
│
├── 📁 役員限定                          ← classification: "restricted"
│   │                                      役員のみ閲覧可能
│   └── 📁 経営情報
│       ├── 経営計画.pdf
│       └── 財務報告.xlsx
│
└── 📁 部署別                            ← classification: "confidential"
    │                                      該当部署のみ閲覧可能
    ├── 📁 営業部                        ← department_id: "dept_sales"
    │   ├── 📁 営業マニュアル            ← category: "B"
    │   │   └── 営業トークスクリプト.pdf
    │   └── 📁 顧客情報                  ← category: "E"
    │       └── 顧客対応ルール.docx
    │
    ├── 📁 総務部                        ← department_id: "dept_admin"
    │   └── 📁 就業規則                  ← category: "C"
    │       └── 就業規則_2026.pdf
    │
    └── 📁 開発部                        ← department_id: "dept_dev"
        └── 📁 開発ガイド                ← category: "B"
            └── コーディング規約.md
```

### 3.2 フォルダ命名規則

| レベル | フォルダ名 | 役割 |
|-------|----------|------|
| **Level 1** | ソウルくん用フォルダ | ルートフォルダ（ROOT_FOLDER_ID） |
| **Level 2** | 全社共有 / 社員限定 / 役員限定 / 部署別 | **機密区分**を決定 |
| **Level 3** | 部署名（営業部、総務部など） | **部署ID**を決定（Level 2が「部署別」の場合） |
| **Level 3-4** | カテゴリ名（マニュアル、理念など） | **カテゴリ**を決定 |

### 3.3 サポートするファイル形式

| 形式 | 拡張子 | テキスト抽出方法 |
|------|-------|----------------|
| PDF | .pdf | PyMuPDF (fitz) |
| Word | .docx, .doc | python-docx |
| テキスト | .txt | そのまま |
| Markdown | .md | そのまま |
| HTML | .html | BeautifulSoup |
| Excel | .xlsx, .xls | openpyxl（テキストのみ） |
| PowerPoint | .pptx, .ppt | python-pptx |

### 3.4 除外するファイル

| 除外条件 | 理由 |
|---------|------|
| ファイル名が `.` で始まる | 隠しファイル |
| ファイル名が `~$` で始まる | Office一時ファイル |
| 拡張子が `.tmp`, `.bak` | 一時ファイル |
| ファイルサイズが 50MB 超 | 処理負荷 |
| Google Docs形式 | エクスポートが必要（将来対応） |

---

## 4. データベース追加設計

### 4.1 documents テーブルへの追加カラム

```sql
-- documents テーブルへの追加カラム（Googleドライブ連携用）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS google_drive_file_id VARCHAR(255);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS google_drive_folder_path TEXT[];
ALTER TABLE documents ADD COLUMN IF NOT EXISTS google_drive_web_view_link TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS google_drive_last_modified TIMESTAMPTZ;

-- インデックス
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_drive_file_id
ON documents(organization_id, google_drive_file_id)
WHERE google_drive_file_id IS NOT NULL;

-- コメント
COMMENT ON COLUMN documents.google_drive_file_id IS
'GoogleドライブのファイルID。
Googleドライブ連携時に使用。NULLの場合は手動アップロード。';

COMMENT ON COLUMN documents.google_drive_folder_path IS
'Googleドライブのフォルダパス（配列）。
例: ["ソウルくん用フォルダ", "社員限定", "業務マニュアル"]
権限決定（classification, department_id）に使用。';

COMMENT ON COLUMN documents.google_drive_web_view_link IS
'Googleドライブでのファイル閲覧URL。
出典表示で使用。';

COMMENT ON COLUMN documents.google_drive_last_modified IS
'Googleドライブでの最終更新日時。
更新検知に使用（この値より新しいmodifiedTimeを持つファイルを更新対象とする）。';
```

### 4.2 google_drive_sync_logs テーブル（新規）

```sql
-- Googleドライブ同期ログテーブル
CREATE TABLE google_drive_sync_logs (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === 同期情報 ===
    sync_id VARCHAR(100) UNIQUE NOT NULL,           -- sync_20260119_100000_abc123
    sync_type VARCHAR(50) NOT NULL,                 -- 'scheduled', 'manual', 'initial'

    -- === 処理統計 ===
    files_checked INT DEFAULT 0,                    -- チェックしたファイル数
    files_added INT DEFAULT 0,                      -- 追加したファイル数
    files_updated INT DEFAULT 0,                    -- 更新したファイル数
    files_deleted INT DEFAULT 0,                    -- 削除したファイル数
    files_skipped INT DEFAULT 0,                    -- スキップしたファイル数
    files_failed INT DEFAULT 0,                     -- 失敗したファイル数

    -- === ステータス ===
    status VARCHAR(50) NOT NULL DEFAULT 'in_progress',
    -- 'in_progress': 実行中
    -- 'completed': 完了
    -- 'completed_with_errors': エラーありで完了
    -- 'failed': 失敗

    -- === エラー情報 ===
    error_code VARCHAR(100),
    error_message TEXT,
    error_details JSONB,
    failed_files JSONB,                             -- 失敗したファイルのリスト

    -- === タイミング ===
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    duration_ms INT,

    -- === Google Drive API情報 ===
    start_page_token VARCHAR(255),                  -- 同期開始時のページトークン
    new_page_token VARCHAR(255),                    -- 同期完了後のページトークン
    root_folder_id VARCHAR(255),                    -- 監視対象のルートフォルダID

    -- === メタデータ ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- === 制約 ===
    CONSTRAINT valid_sync_status CHECK (
        status IN ('in_progress', 'completed', 'completed_with_errors', 'failed')
    )
);

-- インデックス
CREATE INDEX idx_drive_sync_logs_org ON google_drive_sync_logs(organization_id);
CREATE INDEX idx_drive_sync_logs_status ON google_drive_sync_logs(status);
CREATE INDEX idx_drive_sync_logs_started ON google_drive_sync_logs(started_at DESC);

-- コメント
COMMENT ON TABLE google_drive_sync_logs IS
'Googleドライブ同期ジョブの実行ログ。
5分ごとの定期実行の記録と、エラー追跡に使用。';

COMMENT ON COLUMN google_drive_sync_logs.start_page_token IS
'Google Drive API Changes のページトークン。
前回の同期以降の変更を取得するために使用。';
```

### 4.3 google_drive_sync_state テーブル（新規）

```sql
-- Googleドライブ同期状態テーブル（ページトークンの永続化）
CREATE TABLE google_drive_sync_state (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === 同期状態 ===
    root_folder_id VARCHAR(255) NOT NULL,           -- 監視対象のルートフォルダID
    page_token VARCHAR(255) NOT NULL,               -- 次回同期開始時のページトークン
    last_sync_at TIMESTAMPTZ,                       -- 最後に同期した日時
    last_sync_id UUID REFERENCES google_drive_sync_logs(id),

    -- === メタデータ ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- === 制約 ===
    CONSTRAINT unique_org_folder UNIQUE (organization_id, root_folder_id)
);

-- コメント
COMMENT ON TABLE google_drive_sync_state IS
'Googleドライブ同期の状態管理テーブル。
組織×フォルダごとにページトークンを保持し、差分同期を実現。';

COMMENT ON COLUMN google_drive_sync_state.page_token IS
'Google Drive API Changes のページトークン。
このトークン以降の変更を次回同期で取得する。';
```

### 4.4 ER図（追加部分）

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        Googleドライブ連携 ER図（追加部分）                                │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────┐
│       organizations         │
│        (テナント)            │
├─────────────────────────────┤
│ id (PK)                     │
│ name                        │
└─────────────────────────────┘
         │
         │ 1:N
         ▼
┌─────────────────────────────┐          ┌─────────────────────────────┐
│   google_drive_sync_state   │          │   google_drive_sync_logs    │
│      (同期状態)              │          │       (同期ログ)             │
├─────────────────────────────┤          ├─────────────────────────────┤
│ id (PK)                     │          │ id (PK)                     │
│ organization_id (FK)        │          │ organization_id (FK)        │
│ root_folder_id              │          │ sync_id                     │
│ page_token                  │◀─────────│ start_page_token            │
│ last_sync_at                │          │ new_page_token              │
│ last_sync_id (FK) ──────────┼─────────▶│ status                      │
└─────────────────────────────┘          │ files_added                 │
                                         │ files_updated               │
                                         │ files_deleted               │
                                         │ failed_files                │
                                         └─────────────────────────────┘

┌─────────────────────────────┐
│         documents           │
│      (ドキュメント)          │
├─────────────────────────────┤
│ id (PK)                     │
│ organization_id (FK)        │
│ title                       │
│ category                    │
│ classification              │
│ department_id (FK)          │
│ ...                         │
│ ─────────────────────────── │
│ 【Googleドライブ連携用】     │
│ google_drive_file_id  ◀─────┼──── GoogleドライブのファイルID
│ google_drive_folder_path    │     フォルダパス配列
│ google_drive_web_view_link  │     閲覧URL
│ google_drive_last_modified  │     最終更新日時
└─────────────────────────────┘
```

---

## 5. Googleドライブ監視ジョブ設計

### 5.1 監視ジョブの概要

| 項目 | 値 |
|------|-----|
| **実行環境** | Cloud Functions (Python 3.11) |
| **トリガー** | Cloud Scheduler (5分ごと) |
| **タイムアウト** | 540秒（9分） |
| **メモリ** | 512MB |
| **リトライ** | 最大3回（指数バックオフ） |

### 5.2 監視ジョブのフロー

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           監視ジョブ処理フロー                                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

[Cloud Scheduler]
      │
      │ 5分ごとにトリガー
      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           Cloud Functions: watch_google_drive                            │
│                                                                                          │
│  ┌─────────────────────┐                                                                │
│  │ 1. 初期化            │                                                                │
│  │                     │                                                                │
│  │ ・環境変数読み込み   │                                                                │
│  │ ・DB接続            │                                                                │
│  │ ・同期ログ作成      │                                                                │
│  └──────────┬──────────┘                                                                │
│             │                                                                            │
│             ▼                                                                            │
│  ┌─────────────────────┐                                                                │
│  │ 2. ページトークン取得 │                                                                │
│  │                     │                                                                │
│  │ google_drive_sync_  │                                                                │
│  │ state から取得      │                                                                │
│  │                     │                                                                │
│  │ 初回の場合:         │                                                                │
│  │ getStartPageToken() │                                                                │
│  └──────────┬──────────┘                                                                │
│             │                                                                            │
│             ▼                                                                            │
│  ┌─────────────────────┐                                                                │
│  │ 3. 変更リスト取得    │                                                                │
│  │                     │                                                                │
│  │ Google Drive API    │                                                                │
│  │ changes().list()    │                                                                │
│  │                     │                                                                │
│  │ ・新規ファイル       │                                                                │
│  │ ・更新ファイル       │                                                                │
│  │ ・削除ファイル       │                                                                │
│  └──────────┬──────────┘                                                                │
│             │                                                                            │
│             ▼                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │ 4. 各ファイルを処理                                                               │   │
│  │                                                                                   │   │
│  │  ┌───────────────────────────────────────────────────────────────────────────┐  │   │
│  │  │ 4.1 フォルダパス取得                                                        │  │   │
│  │  │     ・親フォルダを再帰的に取得                                              │  │   │
│  │  │     ・["ソウルくん用フォルダ", "社員限定", "業務マニュアル"]                │  │   │
│  │  └───────────────────────────────────────────────────────────────────────────┘  │   │
│  │                              │                                                    │   │
│  │                              ▼                                                    │   │
│  │  ┌───────────────────────────────────────────────────────────────────────────┐  │   │
│  │  │ 4.2 権限決定                                                                │  │   │
│  │  │     ・classification = determine_classification(folder_path)               │  │   │
│  │  │     ・department_id = determine_department_id(folder_path)                 │  │   │
│  │  │     ・category = determine_category(folder_path)                           │  │   │
│  │  └───────────────────────────────────────────────────────────────────────────┘  │   │
│  │                              │                                                    │   │
│  │                              ▼                                                    │   │
│  │  ┌───────────────────────────────────────────────────────────────────────────┐  │   │
│  │  │ 4.3 ファイル処理（追加/更新/削除）                                          │  │   │
│  │  │                                                                             │  │   │
│  │  │  [追加の場合]                                                               │  │   │
│  │  │  ・ファイルダウンロード                                                     │  │   │
│  │  │  ・テキスト抽出                                                             │  │   │
│  │  │  ・チャンク分割                                                             │  │   │
│  │  │  ・エンベディング生成                                                       │  │   │
│  │  │  ・DB保存（documents, document_chunks）                                    │  │   │
│  │  │  ・Pinecone upsert                                                         │  │   │
│  │  │                                                                             │  │   │
│  │  │  [更新の場合]                                                               │  │   │
│  │  │  ・既存ドキュメント取得                                                     │  │   │
│  │  │  ・新バージョン作成                                                         │  │   │
│  │  │  ・旧チャンクを非アクティブ化                                               │  │   │
│  │  │  ・新チャンク作成（追加と同様）                                             │  │   │
│  │  │  ・Pinecone 旧ベクター削除 → 新ベクター upsert                             │  │   │
│  │  │                                                                             │  │   │
│  │  │  [削除の場合]                                                               │  │   │
│  │  │  ・documents.deleted_at = NOW()                                            │  │   │
│  │  │  ・Pinecone からベクター削除                                               │  │   │
│  │  └───────────────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                                   │   │
│  └───────────────────────────────────────────────────────────────────────────────────┘   │
│             │                                                                            │
│             ▼                                                                            │
│  ┌─────────────────────┐                                                                │
│  │ 5. ページトークン保存 │                                                                │
│  │                     │                                                                │
│  │ google_drive_sync_  │                                                                │
│  │ state を更新        │                                                                │
│  └──────────┬──────────┘                                                                │
│             │                                                                            │
│             ▼                                                                            │
│  ┌─────────────────────┐                                                                │
│  │ 6. 同期ログ完了      │                                                                │
│  │                     │                                                                │
│  │ ・status = completed│                                                                │
│  │ ・統計情報を記録    │                                                                │
│  └─────────────────────┘                                                                │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Cloud Scheduler設定

```yaml
# cloud_scheduler/watch_google_drive.yaml

name: watch-google-drive-soulsyncs
description: Googleドライブの変更を監視してソウルくんのナレッジDBに反映

# 5分ごとに実行
schedule: "*/5 * * * *"
timeZone: Asia/Tokyo

# ターゲット設定
target:
  type: http
  uri: https://asia-northeast1-soulsyncs-prod.cloudfunctions.net/watch_google_drive
  httpMethod: POST
  headers:
    Content-Type: application/json
  body: |
    {
      "organization_id": "org_soulsyncs",
      "root_folder_id": "YOUR_ROOT_FOLDER_ID"
    }
  oidcToken:
    serviceAccountEmail: scheduler-sa@soulsyncs-prod.iam.gserviceaccount.com

# リトライ設定
retryConfig:
  retryCount: 3
  minBackoffDuration: 10s
  maxBackoffDuration: 300s
  maxDoublings: 3

# 重複実行防止
attemptDeadline: 540s  # 9分（Cloud Functionsの最大タイムアウト）
```

### 5.4 環境変数

```bash
# Cloud Functions 環境変数

# === 必須 ===
ORGANIZATION_ID=org_soulsyncs
ROOT_FOLDER_ID=1ABC...XYZ                          # Googleドライブのルートフォルダ ID
GOOGLE_SERVICE_ACCOUNT_KEY_PATH=/secrets/sa-key.json

# === データベース ===
DATABASE_URL=postgresql://user:pass@host:5432/soulkun
DATABASE_POOL_SIZE=5

# === Pinecone ===
PINECONE_API_KEY=sk-...
PINECONE_ENVIRONMENT=us-east-1-aws
PINECONE_INDEX_NAME=soulkun-knowledge

# === OpenAI ===
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# === 設定 ===
CHUNK_SIZE=1000                                    # チャンクサイズ（文字数）
CHUNK_OVERLAP=200                                  # チャンクオーバーラップ（文字数）
MAX_FILE_SIZE_MB=50                                # 最大ファイルサイズ
SYNC_INTERVAL_MINUTES=5                            # 同期間隔
```

---

## 6. フォルダ→権限マッピング設計

### 6.1 マッピング設定ファイル

```python
# config/folder_mapping.py

"""
Googleドライブのフォルダ構造と権限のマッピング設定

【重要】
このファイルを変更することで、フォルダ→権限の対応をカスタマイズできます。
変更後は監視ジョブの再デプロイが必要です。

【Phase 3.5連携】
Phase 3.5（組織階層）完成後は、DEPARTMENT_MAPをDBから動的に取得するように変更します。
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class FolderMapping:
    """フォルダマッピング設定"""

    # === 機密区分マッピング ===
    # キー: フォルダ名（大文字小文字を区別しない）
    # 値: classification
    CLASSIFICATION_MAP: dict[str, str] = None

    # === カテゴリマッピング ===
    # キー: フォルダ名に含まれるキーワード
    # 値: category
    CATEGORY_MAP: dict[str, str] = None

    # === 部署IDマッピング ===
    # キー: フォルダ名
    # 値: department_id
    # ※ Phase 3.5連携後はDBから動的取得
    DEPARTMENT_MAP: dict[str, str] = None

    def __post_init__(self):
        if self.CLASSIFICATION_MAP is None:
            self.CLASSIFICATION_MAP = {
                # === Level 2 フォルダ → 機密区分 ===
                # 日本語
                "全社共有": "public",
                "社員限定": "internal",
                "役員限定": "restricted",
                "部署別": "confidential",

                # 英語（バックアップ）
                "public": "public",
                "internal": "internal",
                "restricted": "restricted",
                "confidential": "confidential",
            }

        if self.CATEGORY_MAP is None:
            self.CATEGORY_MAP = {
                # === カテゴリA: 理念・哲学 ===
                "mvv": "A",
                "理念": "A",
                "ミッション": "A",
                "ビジョン": "A",
                "バリュー": "A",
                "会社紹介": "A",
                "会社概要": "A",
                "沿革": "A",
                "経営": "A",

                # === カテゴリB: 業務マニュアル ===
                "マニュアル": "B",
                "手順書": "B",
                "ガイド": "B",
                "手引き": "B",
                "規定": "B",

                # === カテゴリC: 就業規則 ===
                "就業規則": "C",
                "人事": "C",
                "勤怠": "C",
                "給与": "C",
                "福利厚生": "C",

                # === カテゴリD: テンプレート ===
                "テンプレート": "D",
                "ひな形": "D",
                "フォーマット": "D",
                "書式": "D",

                # === カテゴリE: 顧客情報 ===
                "顧客": "E",
                "クライアント": "E",
                "取引先": "E",

                # === カテゴリF: サービス情報 ===
                "サービス": "F",
                "料金": "F",
                "プラン": "F",
                "製品": "F",
            }

        if self.DEPARTMENT_MAP is None:
            self.DEPARTMENT_MAP = {
                # === 部署名 → 部署ID ===
                # ※ Phase 3.5連携後はDBから動的取得に変更
                "営業部": "dept_sales",
                "総務部": "dept_admin",
                "開発部": "dept_dev",
                "人事部": "dept_hr",
                "経理部": "dept_finance",
                "マーケティング部": "dept_marketing",
            }


# デフォルト値
DEFAULT_CLASSIFICATION = "internal"
DEFAULT_CATEGORY = "B"
DEFAULT_DEPARTMENT_ID = None


# シングルトンインスタンス
_mapping_instance: Optional[FolderMapping] = None


def get_folder_mapping() -> FolderMapping:
    """フォルダマッピング設定を取得"""
    global _mapping_instance
    if _mapping_instance is None:
        _mapping_instance = FolderMapping()
    return _mapping_instance
```

### 6.2 マッピング処理ロジック

```python
# lib/folder_mapper.py

"""
フォルダパスから classification, category, department_id を決定するロジック
"""

from typing import Optional
from config.folder_mapping import (
    get_folder_mapping,
    DEFAULT_CLASSIFICATION,
    DEFAULT_CATEGORY,
    DEFAULT_DEPARTMENT_ID
)


class FolderMapper:
    """フォルダ→権限マッピングクラス"""

    def __init__(self, organization_id: str):
        self.organization_id = organization_id
        self.mapping = get_folder_mapping()

    def determine_classification(self, folder_path: list[str]) -> str:
        """
        フォルダパスから機密区分を決定

        Args:
            folder_path: フォルダ名のリスト
                例: ["ソウルくん用フォルダ", "社員限定", "業務マニュアル"]

        Returns:
            classification: "public", "internal", "confidential", "restricted"

        決定ロジック:
        1. フォルダパスを上から順にチェック
        2. CLASSIFICATION_MAP に一致するフォルダ名があれば、その値を返す
        3. 一致するものがなければデフォルト値（internal）を返す
        """
        for folder_name in folder_path:
            # 大文字小文字を区別しない
            folder_name_lower = folder_name.lower()

            for key, classification in self.mapping.CLASSIFICATION_MAP.items():
                if key.lower() == folder_name_lower:
                    return classification

        return DEFAULT_CLASSIFICATION

    def determine_category(self, folder_path: list[str]) -> str:
        """
        フォルダパスからカテゴリを決定

        Args:
            folder_path: フォルダ名のリスト

        Returns:
            category: "A", "B", "C", "D", "E", "F"

        決定ロジック:
        1. フォルダパスを上から順にチェック
        2. CATEGORY_MAP のキーワードがフォルダ名に含まれていれば、その値を返す
        3. 一致するものがなければデフォルト値（B）を返す
        """
        for folder_name in folder_path:
            folder_name_lower = folder_name.lower()

            for keyword, category in self.mapping.CATEGORY_MAP.items():
                if keyword.lower() in folder_name_lower:
                    return category

        return DEFAULT_CATEGORY

    def determine_department_id(self, folder_path: list[str]) -> Optional[str]:
        """
        フォルダパスから部署IDを決定

        Args:
            folder_path: フォルダ名のリスト

        Returns:
            department_id: 部署ID または None

        決定ロジック:
        1. classification が "confidential" でない場合は None を返す
        2. フォルダパスを上から順にチェック
        3. DEPARTMENT_MAP に一致するフォルダ名があれば、その値を返す
        4. 一致するものがなければ None を返す

        【Phase 3.5連携】
        Phase 3.5完成後は、DEPARTMENT_MAP をDBから動的に取得するように変更。
        """
        # confidential でない場合は部署IDは不要
        classification = self.determine_classification(folder_path)
        if classification != "confidential":
            return DEFAULT_DEPARTMENT_ID

        for folder_name in folder_path:
            folder_name_normalized = folder_name.strip()

            if folder_name_normalized in self.mapping.DEPARTMENT_MAP:
                return self.mapping.DEPARTMENT_MAP[folder_name_normalized]

        return DEFAULT_DEPARTMENT_ID

    def map_folder_to_permissions(
        self,
        folder_path: list[str]
    ) -> dict:
        """
        フォルダパスから全ての権限情報を取得

        Args:
            folder_path: フォルダ名のリスト

        Returns:
            {
                "classification": "internal",
                "category": "B",
                "department_id": None
            }
        """
        return {
            "classification": self.determine_classification(folder_path),
            "category": self.determine_category(folder_path),
            "department_id": self.determine_department_id(folder_path)
        }


# === 使用例 ===
#
# mapper = FolderMapper("org_soulsyncs")
#
# # 例1: 社員限定の業務マニュアル
# path1 = ["ソウルくん用フォルダ", "社員限定", "業務マニュアル"]
# result1 = mapper.map_folder_to_permissions(path1)
# # → {"classification": "internal", "category": "B", "department_id": None}
#
# # 例2: 営業部の顧客情報
# path2 = ["ソウルくん用フォルダ", "部署別", "営業部", "顧客情報"]
# result2 = mapper.map_folder_to_permissions(path2)
# # → {"classification": "confidential", "category": "E", "department_id": "dept_sales"}
```

---

## 7. ドキュメント処理フロー設計

### 7.1 テキスト抽出

```python
# lib/text_extractor.py

"""
各種ファイル形式からテキストを抽出するモジュール
"""

import io
from abc import ABC, abstractmethod
from typing import Optional
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from pptx import Presentation
from openpyxl import load_workbook
from bs4 import BeautifulSoup


class TextExtractor(ABC):
    """テキスト抽出の基底クラス"""

    @abstractmethod
    def extract(self, content: bytes) -> str:
        """ファイルからテキストを抽出"""
        pass

    @abstractmethod
    def extract_with_metadata(self, content: bytes) -> dict:
        """テキストとメタデータを抽出"""
        pass


class PDFExtractor(TextExtractor):
    """PDFからテキストを抽出"""

    def extract(self, content: bytes) -> str:
        """PDFからテキストを抽出"""
        doc = fitz.open(stream=content, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text

    def extract_with_metadata(self, content: bytes) -> dict:
        """PDFからテキストとメタデータを抽出"""
        doc = fitz.open(stream=content, filetype="pdf")

        pages = []
        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text()
            pages.append({
                "page_number": page_num,
                "text": page_text,
                "char_count": len(page_text)
            })

        metadata = {
            "total_pages": len(doc),
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "creation_date": doc.metadata.get("creationDate", ""),
        }

        doc.close()

        return {
            "text": "\n".join([p["text"] for p in pages]),
            "pages": pages,
            "metadata": metadata
        }


class DocxExtractor(TextExtractor):
    """Word文書からテキストを抽出"""

    def extract(self, content: bytes) -> str:
        """DOCXからテキストを抽出"""
        doc = DocxDocument(io.BytesIO(content))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text

    def extract_with_metadata(self, content: bytes) -> dict:
        """DOCXからテキストとメタデータを抽出"""
        doc = DocxDocument(io.BytesIO(content))

        paragraphs = []
        for i, para in enumerate(doc.paragraphs):
            if para.text.strip():
                paragraphs.append({
                    "index": i,
                    "text": para.text,
                    "style": para.style.name if para.style else None
                })

        # 見出しを抽出
        headings = [
            p for p in paragraphs
            if p["style"] and "Heading" in p["style"]
        ]

        metadata = {
            "total_paragraphs": len(paragraphs),
            "headings": headings,
            "author": doc.core_properties.author,
            "title": doc.core_properties.title,
            "created": str(doc.core_properties.created) if doc.core_properties.created else None,
            "modified": str(doc.core_properties.modified) if doc.core_properties.modified else None,
        }

        return {
            "text": "\n".join([p["text"] for p in paragraphs]),
            "paragraphs": paragraphs,
            "metadata": metadata
        }


class TextFileExtractor(TextExtractor):
    """テキストファイルからテキストを抽出"""

    def extract(self, content: bytes) -> str:
        """TXT/MDからテキストを抽出"""
        # UTF-8を試し、失敗したらShift-JISを試す
        for encoding in ["utf-8", "shift-jis", "cp932", "euc-jp"]:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue

        # 最後の手段: errors='replace'
        return content.decode("utf-8", errors="replace")

    def extract_with_metadata(self, content: bytes) -> dict:
        """TXT/MDからテキストとメタデータを抽出"""
        text = self.extract(content)

        lines = text.split("\n")

        # Markdownの見出しを抽出
        headings = []
        for i, line in enumerate(lines):
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                heading_text = line.lstrip("#").strip()
                headings.append({
                    "line_number": i + 1,
                    "level": level,
                    "text": heading_text
                })

        return {
            "text": text,
            "metadata": {
                "total_lines": len(lines),
                "total_chars": len(text),
                "headings": headings
            }
        }


class HTMLExtractor(TextExtractor):
    """HTMLからテキストを抽出"""

    def extract(self, content: bytes) -> str:
        """HTMLからテキストを抽出"""
        soup = BeautifulSoup(content, "html.parser")

        # スクリプトとスタイルを除去
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        return soup.get_text(separator="\n", strip=True)

    def extract_with_metadata(self, content: bytes) -> dict:
        """HTMLからテキストとメタデータを抽出"""
        soup = BeautifulSoup(content, "html.parser")

        # タイトルを取得
        title = soup.title.string if soup.title else ""

        # 見出しを抽出
        headings = []
        for level in range(1, 7):
            for heading in soup.find_all(f"h{level}"):
                headings.append({
                    "level": level,
                    "text": heading.get_text(strip=True)
                })

        # スクリプトとスタイルを除去
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        return {
            "text": text,
            "metadata": {
                "title": title,
                "headings": headings,
                "total_chars": len(text)
            }
        }


class ExcelExtractor(TextExtractor):
    """Excelからテキストを抽出"""

    def extract(self, content: bytes) -> str:
        """XLSXからテキストを抽出"""
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)

        texts = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows():
                row_texts = []
                for cell in row:
                    if cell.value is not None:
                        row_texts.append(str(cell.value))
                if row_texts:
                    texts.append("\t".join(row_texts))

        wb.close()
        return "\n".join(texts)

    def extract_with_metadata(self, content: bytes) -> dict:
        """XLSXからテキストとメタデータを抽出"""
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)

        sheets = []
        all_text = []

        for sheet in wb.worksheets:
            sheet_text = []
            for row in sheet.iter_rows():
                row_texts = []
                for cell in row:
                    if cell.value is not None:
                        row_texts.append(str(cell.value))
                if row_texts:
                    sheet_text.append("\t".join(row_texts))

            sheets.append({
                "name": sheet.title,
                "text": "\n".join(sheet_text)
            })
            all_text.extend(sheet_text)

        wb.close()

        return {
            "text": "\n".join(all_text),
            "metadata": {
                "total_sheets": len(sheets),
                "sheets": sheets
            }
        }


class PowerPointExtractor(TextExtractor):
    """PowerPointからテキストを抽出"""

    def extract(self, content: bytes) -> str:
        """PPTXからテキストを抽出"""
        prs = Presentation(io.BytesIO(content))

        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    texts.append(shape.text)

        return "\n".join(texts)

    def extract_with_metadata(self, content: bytes) -> dict:
        """PPTXからテキストとメタデータを抽出"""
        prs = Presentation(io.BytesIO(content))

        slides = []
        all_text = []

        for slide_num, slide in enumerate(prs.slides, start=1):
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    slide_text.append(shape.text)

            slides.append({
                "slide_number": slide_num,
                "text": "\n".join(slide_text)
            })
            all_text.extend(slide_text)

        return {
            "text": "\n".join(all_text),
            "metadata": {
                "total_slides": len(slides),
                "slides": slides
            }
        }


# === ファクトリ関数 ===

EXTRACTOR_MAP = {
    "pdf": PDFExtractor,
    "docx": DocxExtractor,
    "doc": DocxExtractor,  # python-docx は .doc も読める場合がある
    "txt": TextFileExtractor,
    "md": TextFileExtractor,
    "html": HTMLExtractor,
    "htm": HTMLExtractor,
    "xlsx": ExcelExtractor,
    "xls": ExcelExtractor,
    "pptx": PowerPointExtractor,
    "ppt": PowerPointExtractor,
}


def get_extractor(file_type: str) -> Optional[TextExtractor]:
    """
    ファイル形式に対応するエクストラクターを取得

    Args:
        file_type: ファイル拡張子（小文字）

    Returns:
        TextExtractor または None
    """
    extractor_class = EXTRACTOR_MAP.get(file_type.lower())
    if extractor_class:
        return extractor_class()
    return None


def extract_text(content: bytes, file_type: str) -> str:
    """
    ファイルからテキストを抽出

    Args:
        content: ファイルのバイナリデータ
        file_type: ファイル拡張子

    Returns:
        抽出されたテキスト

    Raises:
        ValueError: サポートされていないファイル形式
    """
    extractor = get_extractor(file_type)
    if extractor is None:
        raise ValueError(f"サポートされていないファイル形式: {file_type}")
    return extractor.extract(content)


def extract_text_with_metadata(content: bytes, file_type: str) -> dict:
    """
    ファイルからテキストとメタデータを抽出

    Args:
        content: ファイルのバイナリデータ
        file_type: ファイル拡張子

    Returns:
        {"text": str, "metadata": dict, ...}

    Raises:
        ValueError: サポートされていないファイル形式
    """
    extractor = get_extractor(file_type)
    if extractor is None:
        raise ValueError(f"サポートされていないファイル形式: {file_type}")
    return extractor.extract_with_metadata(content)
```

### 7.2 チャンク分割

```python
# lib/chunker.py

"""
テキストをチャンクに分割するモジュール

チャンク分割戦略:
1. セマンティックな区切り（見出し、段落）を優先
2. 文の途中で切らない
3. オーバーラップで文脈を保持
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Chunk:
    """チャンクデータ"""
    index: int                          # チャンク番号（0始まり）
    content: str                        # チャンクのテキスト
    char_count: int                     # 文字数
    start_position: int                 # 元文書での開始位置
    end_position: int                   # 元文書での終了位置
    page_number: Optional[int] = None   # ページ番号（PDFの場合）
    section_title: Optional[str] = None # セクションタイトル
    section_hierarchy: list[str] = None # セクション階層


class TextChunker:
    """テキストをチャンクに分割するクラス"""

    # セマンティックな区切り文字（優先度順）
    SEPARATORS = [
        "\n## ",      # Markdown H2
        "\n### ",     # Markdown H3
        "\n#### ",    # Markdown H4
        "\n\n",       # 空行（段落区切り）
        "\n",         # 改行
        "。",         # 日本語文末
        "．",         # 日本語ピリオド（全角）
        ". ",         # 英語文末
        "！",         # 日本語感嘆符
        "？",         # 日本語疑問符
        "! ",         # 英語感嘆符
        "? ",         # 英語疑問符
        "、",         # 日本語読点
        ", ",         # 英語コンマ
        " ",          # スペース
        "",           # 最後の手段（文字単位）
    ]

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        min_chunk_size: int = 100
    ):
        """
        Args:
            chunk_size: チャンクの最大文字数
            chunk_overlap: チャンク間のオーバーラップ文字数
            min_chunk_size: チャンクの最小文字数（これより短いチャンクは前のチャンクに結合）
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def split(self, text: str) -> list[Chunk]:
        """
        テキストをチャンクに分割

        Args:
            text: 分割するテキスト

        Returns:
            チャンクのリスト
        """
        if not text or len(text) == 0:
            return []

        # 見出しを抽出
        headings = self._extract_headings(text)

        # 分割
        raw_chunks = self._split_text(text)

        # チャンクオブジェクトを作成
        chunks = []
        current_position = 0
        current_heading = None
        current_hierarchy = []

        for i, chunk_text in enumerate(raw_chunks):
            # このチャンクに含まれる見出しを更新
            chunk_start = text.find(chunk_text, current_position)
            chunk_end = chunk_start + len(chunk_text)

            for heading in headings:
                if heading["position"] >= chunk_start and heading["position"] < chunk_end:
                    current_heading = heading["text"]
                    current_hierarchy = heading["hierarchy"]

            chunk = Chunk(
                index=i,
                content=chunk_text,
                char_count=len(chunk_text),
                start_position=chunk_start,
                end_position=chunk_end,
                section_title=current_heading,
                section_hierarchy=current_hierarchy.copy() if current_hierarchy else []
            )
            chunks.append(chunk)

            current_position = chunk_end - self.chunk_overlap

        return chunks

    def split_with_pages(
        self,
        pages: list[dict]
    ) -> list[Chunk]:
        """
        ページ情報付きのテキストをチャンクに分割（PDF用）

        Args:
            pages: [{"page_number": 1, "text": "..."}]

        Returns:
            チャンクのリスト（page_number付き）
        """
        chunks = []
        chunk_index = 0

        for page in pages:
            page_number = page["page_number"]
            page_text = page["text"]

            # ページ内でチャンク分割
            page_chunks = self._split_text(page_text)

            current_position = 0
            for chunk_text in page_chunks:
                chunk_start = page_text.find(chunk_text, current_position)
                chunk_end = chunk_start + len(chunk_text)

                chunk = Chunk(
                    index=chunk_index,
                    content=chunk_text,
                    char_count=len(chunk_text),
                    start_position=chunk_start,
                    end_position=chunk_end,
                    page_number=page_number
                )
                chunks.append(chunk)

                chunk_index += 1
                current_position = chunk_end - self.chunk_overlap

        return chunks

    def _split_text(self, text: str) -> list[str]:
        """
        テキストを分割（再帰的）
        """
        if len(text) <= self.chunk_size:
            return [text]

        # 各セパレータで分割を試みる
        for separator in self.SEPARATORS:
            if separator == "":
                # 最後の手段: 文字数で強制分割
                return self._split_by_length(text)

            if separator in text:
                splits = self._split_by_separator(text, separator)
                if len(splits) > 1:
                    # 再帰的に分割
                    result = []
                    for split in splits:
                        result.extend(self._split_text(split))
                    return self._merge_small_chunks(result)

        # どのセパレータでも分割できない場合
        return self._split_by_length(text)

    def _split_by_separator(self, text: str, separator: str) -> list[str]:
        """セパレータで分割"""
        splits = text.split(separator)

        # セパレータを復元（最後以外）
        result = []
        for i, split in enumerate(splits):
            if i < len(splits) - 1:
                result.append(split + separator)
            else:
                result.append(split)

        return [s for s in result if s.strip()]

    def _split_by_length(self, text: str) -> list[str]:
        """文字数で強制分割"""
        chunks = []
        for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
            chunk = text[i:i + self.chunk_size]
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    def _merge_small_chunks(self, chunks: list[str]) -> list[str]:
        """小さすぎるチャンクを前のチャンクに結合"""
        if not chunks:
            return chunks

        result = [chunks[0]]

        for chunk in chunks[1:]:
            if len(chunk) < self.min_chunk_size and result:
                result[-1] += chunk
            else:
                result.append(chunk)

        return result

    def _extract_headings(self, text: str) -> list[dict]:
        """見出しを抽出"""
        headings = []

        # Markdown形式の見出し
        md_heading_pattern = r'^(#{1,6})\s+(.+)$'
        for match in re.finditer(md_heading_pattern, text, re.MULTILINE):
            level = len(match.group(1))
            heading_text = match.group(2)
            position = match.start()

            # 階層を構築
            hierarchy = [heading_text]  # 簡易版

            headings.append({
                "level": level,
                "text": heading_text,
                "position": position,
                "hierarchy": hierarchy
            })

        return headings
```

---

## 8. エラーハンドリング設計

### 8.1 エラー種別と対応

| エラー種別 | エラーコード | 対応 | リトライ |
|-----------|------------|------|---------|
| Google Drive API接続エラー | GD_001 | ログ記録、アラート | 3回 |
| ファイルダウンロード失敗 | GD_002 | ログ記録、スキップ | 3回 |
| フォルダパス取得失敗 | GD_003 | ログ記録、スキップ | 3回 |
| テキスト抽出失敗 | DOC_001 | ログ記録、スキップ | なし |
| サポートされていない形式 | DOC_002 | ログ記録、スキップ | なし |
| ファイルサイズ超過 | DOC_003 | ログ記録、スキップ | なし |
| OpenAI API接続エラー | OAI_001 | ログ記録、アラート | 3回 |
| エンベディング生成失敗 | OAI_002 | ログ記録、スキップ | 3回 |
| Pinecone接続エラー | PC_001 | ログ記録、アラート | 3回 |
| Pinecone upsert失敗 | PC_002 | ログ記録、アラート | 3回 |
| DB接続エラー | DB_001 | ログ記録、アラート | 3回 |
| DB保存失敗 | DB_002 | ロールバック、アラート | 3回 |

### 8.2 リトライ戦略

```python
# lib/retry.py

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from google.api_core.exceptions import GoogleAPIError
from openai import APIError as OpenAIAPIError
from pinecone.exceptions import PineconeException


# Google Drive API用リトライデコレータ
google_drive_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(GoogleAPIError)
)

# OpenAI API用リトライデコレータ
openai_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(OpenAIAPIError)
)

# Pinecone用リトライデコレータ
pinecone_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(PineconeException)
)
```

### 8.3 アラート設定

```python
# lib/alerting.py

import os
from lib.chatwork import ChatworkClient


ALERT_ROOM_ID = os.getenv("ALERT_CHATWORK_ROOM_ID")


async def send_alert(
    title: str,
    message: str,
    severity: str = "warning",  # "info", "warning", "error", "critical"
    details: dict = None
):
    """
    アラートを送信

    Args:
        title: アラートタイトル
        message: アラートメッセージ
        severity: 深刻度
        details: 詳細情報
    """
    severity_emoji = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "❌",
        "critical": "🚨"
    }

    emoji = severity_emoji.get(severity, "ℹ️")

    alert_message = f"""
{emoji} {title}

{message}
"""

    if details:
        alert_message += "\n詳細:\n"
        for key, value in details.items():
            alert_message += f"・{key}: {value}\n"

    client = ChatworkClient()
    await client.send_message(
        room_id=ALERT_ROOM_ID,
        message=alert_message
    )
```

---

## 9. 運用設計

### 9.1 監視項目

| 項目 | 監視方法 | 閾値 | アラート |
|------|---------|------|---------|
| 監視ジョブの実行 | Cloud Monitoring | 15分以上実行されていない | Chatwork通知 |
| 同期エラー率 | google_drive_sync_logs | 5%以上 | Chatwork通知 |
| 処理時間 | google_drive_sync_logs.duration_ms | 5分以上 | Chatwork通知 |
| Pinecone ベクター数 | Pinecone Console | 100万超 | Chatwork通知 |
| エンベディングコスト | OpenAI Dashboard | $50/日超 | Chatwork通知 |

### 9.2 ログ設計

```python
# lib/logging_config.py

import logging
import json
from datetime import datetime


class StructuredLogger:
    """構造化ログを出力するロガー"""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

    def _log(self, level: str, message: str, **kwargs):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "service": "watch_google_drive",
            **kwargs
        }
        self.logger.log(
            getattr(logging, level.upper()),
            json.dumps(log_entry, ensure_ascii=False)
        )

    def info(self, message: str, **kwargs):
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("error", message, **kwargs)


# 使用例
# logger = StructuredLogger("watch_google_drive")
# logger.info("ファイル処理完了", file_id="abc123", file_name="manual.pdf", duration_ms=1500)
```

### 9.3 運用手順書

```markdown
# Googleドライブ連携 運用手順書

## 日次確認

1. Cloud Console → Cloud Functions → watch_google_drive の実行ログを確認
2. エラーがないことを確認
3. google_drive_sync_logs テーブルで同期状況を確認

## ファイルが反映されない場合

1. Googleドライブでファイルが正しいフォルダにあるか確認
2. ファイル形式がサポートされているか確認（PDF, DOCX, TXT, MD, HTML, XLSX, PPTX）
3. ファイルサイズが50MB以下か確認
4. google_drive_sync_logs でエラーがないか確認
5. 問題が解決しない場合は、手動で監視ジョブを実行

## 手動で監視ジョブを実行

```bash
gcloud functions call watch_google_drive \
  --data '{"organization_id": "org_soulsyncs", "root_folder_id": "YOUR_FOLDER_ID"}'
```

## フォルダ構造を変更する場合

1. config/folder_mapping.py を編集
2. Cloud Functions を再デプロイ
3. 既存ファイルの権限を更新する場合は、フルシンクを実行

## フルシンク（全ファイル再取り込み）

```bash
gcloud functions call watch_google_drive \
  --data '{"organization_id": "org_soulsyncs", "root_folder_id": "YOUR_FOLDER_ID", "full_sync": true}'
```

注意: フルシンクは全ファイルを再処理するため、時間がかかります。
```

---

## 10. セキュリティ設計

### 10.1 認証・認可

| 対象 | 認証方式 | 認可 |
|------|---------|------|
| Google Drive API | サービスアカウント | 読み取り専用（drive.readonly） |
| Cloud Functions | Cloud Scheduler（OIDC） | 特定のサービスアカウントのみ実行可 |
| Cloud SQL | IAM認証 | 特定のサービスアカウントのみ接続可 |
| Pinecone | API Key | Secret Manager で管理 |
| OpenAI | API Key | Secret Manager で管理 |

### 10.2 データ保護

| 対象 | 保護方法 |
|------|---------|
| Googleドライブのファイル | ダウンロード後、処理完了次第メモリから削除 |
| API Key | Secret Manager で管理、コードに含めない |
| DB接続情報 | Secret Manager で管理 |
| ログ | 機密情報（ファイル内容）を含めない |

### 10.3 監査ログ

```python
# 10の鉄則 #3: 監査ログ

# Googleドライブ同期の監査ログ
await AuditLog.create(
    organization_id=organization_id,
    user_id=None,  # システム処理
    action="google_drive_sync",
    resource_type="document",
    resource_id=document_id,
    details={
        "sync_id": sync_id,
        "file_id": google_drive_file_id,
        "operation": "add" | "update" | "delete",
        "classification": classification,
        "department_id": department_id
    }
)
```

---

## 11. テスト設計

### 11.1 テストケース

| # | テストケース | 期待結果 |
|---|-------------|---------|
| 1 | PDF追加 | documents, document_chunks, Pinecone に登録 |
| 2 | DOCX追加 | documents, document_chunks, Pinecone に登録 |
| 3 | TXT追加 | documents, document_chunks, Pinecone に登録 |
| 4 | 50MB超ファイル | スキップ、ログに記録 |
| 5 | サポート外形式（exe） | スキップ、ログに記録 |
| 6 | ファイル更新 | 新バージョン作成、Pinecone更新 |
| 7 | ファイル削除 | ソフトデリート、Pinecone削除 |
| 8 | フォルダ移動 | classification, department_id更新 |
| 9 | 全社共有フォルダ | classification = "public" |
| 10 | 社員限定フォルダ | classification = "internal" |
| 11 | 部署別フォルダ | classification = "confidential", department_id設定 |
| 12 | Google Drive API障害 | リトライ、アラート |
| 13 | OpenAI API障害 | リトライ、アラート |
| 14 | Pinecone障害 | リトライ、アラート |

### 11.2 テストデータ

```python
# tests/fixtures/google_drive.py

TEST_FILES = [
    {
        "file_id": "test_file_001",
        "name": "経費精算マニュアル.pdf",
        "mime_type": "application/pdf",
        "folder_path": ["ソウルくん用フォルダ", "社員限定", "業務マニュアル"],
        "expected": {
            "classification": "internal",
            "category": "B",
            "department_id": None
        }
    },
    {
        "file_id": "test_file_002",
        "name": "営業トークスクリプト.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "folder_path": ["ソウルくん用フォルダ", "部署別", "営業部", "営業マニュアル"],
        "expected": {
            "classification": "confidential",
            "category": "B",
            "department_id": "dept_sales"
        }
    }
]
```

---

## 12. 実装チェックリスト

### 12.1 データベース

- [ ] documents テーブルへの追加カラム（google_drive_*）
- [ ] google_drive_sync_logs テーブル作成
- [ ] google_drive_sync_state テーブル作成
- [ ] インデックス作成
- [ ] マイグレーション実行

### 12.2 共通ライブラリ

- [ ] lib/google_drive.py（Google Drive API連携）
- [ ] lib/folder_mapper.py（フォルダ→権限マッピング）
- [ ] lib/text_extractor.py（テキスト抽出）
- [ ] lib/chunker.py（チャンク分割）
- [ ] lib/retry.py（リトライ戦略）
- [ ] lib/alerting.py（アラート送信）
- [ ] config/folder_mapping.py（マッピング設定）

### 12.3 Cloud Functions

- [ ] watch_google_drive/main.py（監視ジョブ）
- [ ] watch_google_drive/requirements.txt
- [ ] cloud_scheduler/watch_google_drive.yaml

### 12.4 設定

- [ ] 環境変数設定
- [ ] Secret Manager にAPIキー登録
- [ ] サービスアカウント設定
- [ ] Googleドライブのフォルダ共有設定

### 12.5 テスト

- [ ] ユニットテスト
- [ ] 統合テスト
- [ ] E2Eテスト

### 12.6 運用

- [ ] Cloud Monitoring設定
- [ ] アラート設定
- [ ] 運用手順書

---

**[📁 目次に戻る](00_README.md)**
