# Google Drive Admin API レビュー結果 (2026-02-21)

## 対象ファイル
- `api/app/api/v1/admin/drive_routes.py` (新規)
- `api/app/schemas/admin.py` (DriveFileItem/DriveFilesResponse/DriveSyncStatusResponse/DriveUploadResponse 追加)
- `lib/google_drive.py` (upload_file メソッド追加)

## CRITICAL 発見事項

### C-1: `lib/google_drive.py` OAuth スコープが `drive.readonly`（アップロード不可）
- 全コンストラクタ（4パターン全て）が `'https://www.googleapis.com/auth/drive.readonly'` を使用
- `upload_file()` は `files().create()` を呼ぶが、readonly スコープでは 403 forbidden になる
- 本番でアップロードは必ず失敗する
- 修正: `'https://www.googleapis.com/auth/drive'` (フルアクセス) または `'https://www.googleapis.com/auth/drive.file'`（自分が作成したファイルのみ）に変更が必要
- **注意**: drive.readonly を変更するとダウンロード用クライアント（sync watcherなど）の認証スコープも変わる。`_get_drive_client()` が upload/download 両方に使われているため。

### C-2: `drive_routes.py` line 309: `mime_type` カラムが `documents` テーブルに存在しない
- SELECT: `google_drive_file_id, file_name, mime_type, file_type` — `mime_type` は db_schema.json に存在しない
- db_schema.json の documents テーブル: id, organization_id, title, description, file_path, file_type, file_size, classification, category, department_id, is_active, created/updated_at, created_by, updated_by, file_name, file_size_bytes, file_hash, google_drive_file_id, google_drive_folder_path, google_drive_web_view_link, google_drive_last_modified, processing_status, file_url, metadata, current_version, processing_error, processed_at, total_chunks, total_pages, deleted_at, is_searchable
- `mime_type` カラムなし。ダウンロードエンドポイントが本番で `column "mime_type" does not exist` エラーになる
- 修正: `file_type` のみ使用してMIMEタイプを推定するか、`file_url` や `metadata` から取得する

### C-3: upload INSERT が `conn.commit()` を使っているが SQLAlchemy Core の `with pool.connect()` はautocommit/rollbackをwith文で制御
- `pool.connect()` の `with` ブロックでは明示的 commit が必要 → `conn.commit()` は正しい
- ただし Drive へのアップロード成功後にDBがエラーになった場合の処理（line 477-480）で
  `except` が DBエラーを飲み込んで `document_id=None` のまま `log_audit_event` と `DriveUploadResponse` を返す
  → Drive にファイルがあるがDBには記録なし、かつ audit ログは成功扱い → データ不整合
  → ただしコメントに「ウォッチャーが後で拾う」とあり、設計的な選択。CRITICAL 扱いにはしなかったが要確認。

## WARNING 発見事項

### W-1: `async def` 関数内で同期 `pool.connect()` を直接呼び出している（チェックリスト#6）
- `get_drive_files`, `get_drive_sync_status`, `download_drive_file`, `upload_drive_file` — 全て `async def` だが `pool.connect()` は同期ブロッキング呼び出し
- admin dashboard は §1-1 例外として許容されているが、CLAUDE.md 22項目チェック #6 違反
- 他の admin routes (`brain_routes.py`, `dashboard_routes.py` など) も同じパターン — PRE-EXISTING

### W-2: `details={"org_id": organization_id}` を audit log に記録（鉄則#8相当）
- `get_drive_files` line 217: `details={"org_id": organization_id, "total": total}`
- `download_drive_file` line 347: `details={"org_id": organization_id}`
- `upload_drive_file` line 488: `details={"org_id": organization_id, "classification": classification}`
- organization_id (UUID) が audit_logs テーブルの details フィールドに記録される
- 鉄則#8「エラーに機密情報を含めない」の audit log 版。UUID は疑似匿名だが、他のadmin routesとの整合性確認が必要
- 他の admin routes でも同パターン確認 → PRE-EXISTING

### W-3: `upload_drive_file` でファイルサイズが HTTP 413 エラーメッセージに露出
- line 398-400: `detail=f"ファイルサイズが上限（20MB）を超えています（{len(content) // 1024 // 1024}MB）"`
- ファイルサイズ（MB）をユーザーに返すのは UX 上は合理的。鉄則#8の「内部パス・ユーザーID」ではないため SUGGESTION レベル

### W-4: Content-Disposition ヘッダーの ASCII 以外のファイル名（RFC 5987非準拠）
- line 353: `f'attachment; filename="{safe_name}"'` で safe_name に日本語が含まれる場合、RFC 2183 違反
- `\n` と `"` のみ除去だが URL エンコードなし
- ブラウザ依存で文字化けする可能性
- 修正: `filename*=UTF-8''` エンコーディング使用（RFC 5987）または `urllib.parse.quote(safe_name)`

### W-5: `_get_drive_client()` が毎回 Secret Manager を呼び出す（キャッシュなし）
- `download_drive_file` と `upload_drive_file` それぞれでモジュールレベルのキャッシュなし
- Secret Manager API 呼び出しはレイテンシが高い（~200ms）
- TTL 付きキャッシュが望ましい（鉄則#6: デフォルト5分）

### W-6: `DriveFileItem.title` が `Optional[str]` でなく `str` — Null の場合に検証エラー
- db_schema.json: `documents.title = character varying`（nullable: 不明）
- documents テーブルに title が NULL で入っている行がある場合、Pydantic バリデーションエラーになる
- `Optional[str]` が安全

## SUGGESTION 発見事項

### S-1: `documents` テーブルの INSERT に `mime_type` カラムがないため、ダウンロード時に content_type を推定できない
- アップロード時に mime_type を保存したい場合、`metadata` JSONB に入れるか `file_url` 代用
- 現在は `file_type` (拡張子) からクライアント側で推定するしかない

### S-2: `_UPLOAD_FOLDER_ID` が空文字の場合、`target_folder = None` になりルートにアップロード
- Drive のルートフォルダに誰でも見られる可能性。`GOOGLE_DRIVE_UPLOAD_FOLDER_ID` 未設定時の警告ログを出すべき

### S-3: `DriveFilesResponse.total` フィールド名（`total`）が他のスキーマ（`total_count`）と不統一
- `MembersListResponse.total_count`, `BrainLogsResponse.total_count` など他は `total_count`
- 命名の統一が望ましい（breaking changeになるが設計段階なので今のうちに直す）

### S-4: テストがない
- `drive_routes.py` に対するユニットテスト/統合テストが確認できなかった
- 特に C-1(スコープ)、C-2(mime_typeカラム)は実行時エラーになるためテストで事前検出すべきだった

## db_schema.json 確認結果（documents テーブル）
確認済みカラム一覧（存在する）:
- id, organization_id, title, description, file_path, file_type, file_size, classification, category
- department_id, is_active, created_at, updated_at, created_by, updated_by
- file_name, file_size_bytes, file_hash
- google_drive_file_id, google_drive_folder_path, google_drive_web_view_link, google_drive_last_modified
- processing_status, file_url, metadata, current_version, processing_error, processed_at
- total_chunks, total_pages, deleted_at, is_searchable

存在しないカラム（コードで参照）:
- `mime_type` — 存在しない！（C-2）

## 3コピー同期
- `lib/google_drive.py` の `upload_file` 追加 → `chatwork-webhook/lib/google_drive.py` と `proactive-monitor/lib/google_drive.py` も同期が必要
- `drive_routes.py` は `api/` にのみ存在（lib/ でないため同期不要）
