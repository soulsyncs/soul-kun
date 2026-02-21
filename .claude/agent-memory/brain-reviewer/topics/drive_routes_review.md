# Google Drive Admin API レビュー結果

## 対象ファイル
- `api/app/api/v1/admin/drive_routes.py`
- `api/app/schemas/admin.py` (DriveFileItem/DriveFilesResponse/DriveSyncStatusResponse/DriveUploadResponse)
- `lib/google_drive.py` (upload_file メソッド追加)

---

## 初回レビュー (2026-02-21) — 旧コード（同期 pool.connect() 直呼び出し版）

### 修正済みの CRITICAL（現在は解決）
- C-1: `lib/google_drive.py` OAuth スコープが `drive.readonly` — `writable` パラメータ追加で修正済み
- C-2: `drive_routes.py` SELECT で `mime_type` カラムを参照 — `file_type` のみに修正済み
- W-4: Content-Disposition が RFC 5987 非準拠 — `filename*=UTF-8''` エンコーディングに修正済み

---

## 2回目レビュー (2026-02-22) — asyncio.to_thread() リファクタリング版

### 変更内容
- async 関数内の同期 `pool.connect()` を 4 つの同期ヘルパー関数に切り出し
- 各ヘルパーを `asyncio.to_thread()` で呼び出すように変更
- `_get_drive_client()` も `asyncio.to_thread()` 経由に変更
- RLS `set_config` とクエリを同一コネクション内に統合

### CRITICAL: なし

### WARNING (3件)

#### W-1: 動的 WHERE 句の f-string 組み立て（将来の安全性リスク）
- `_sync_list_drive_files` の `where_clauses` を `" AND ".join()` で組み立て、`text(f"... WHERE {where_sql}")` で使用
- 現在は `where_clauses` の全要素がハードコード固定文字列 + ユーザー入力はバインドパラメータ → SQLインジェクションなし
- ただし将来誰かが `where_clauses.append(f"title = '{user_input}'")` を追加すると即座に脆弱になる
- 推奨: コメントで「where_clauses に直接ユーザー入力を入れてはいけない」旨を明記

#### W-2: Drive アップロード後 DB 記録失敗時の孤立ファイル
- Drive にファイルが存在するが DB に記録がない状態が発生しうる
- コメントに「ウォッチャーが後で拾う」とあるが、watch-google-drive の実際の動作確認が必要
- `drive_file.id` を WARNING ログに直接記録している（内部ID漏洩は軽微）
- 監査ログ `drive_file_uploaded_db_failed` は記録されるので追跡可能

#### W-5: MIME チェックが空文字の場合スキップされる
- `if content_type and content_type not in _ALLOWED_MIME_TYPES:` — `content_type=""` ならチェックスキップ
- 拡張子チェック（`_ALLOWED_EXTENSIONS`）は必ず実行されるため完全バイパスではないが、セキュリティ上の抜け穴

### SUGGESTION (4件)
- S-1: `_EXT_TO_MIME` 辞書が関数本体内に定義（毎回再作成）→ モジュールレベルに移動推奨
- S-2: `urllib.parse` の import が関数本体内（line 423）→ モジュール先頭に移動推奨
- S-3: `sync_pinecone_metadata` 内の `PineconeClient()` のテナント分離確認（`org_id` は明示的に渡している）
- S-4: `log_audit_event` の `details` に `org_id` UUID を含めるのは他 admin routes と一貫したパターン（問題なし）

### 正常確認済み項目
- 全エンドポイント認証: require_admin(Level 5+) / require_editor(Level 6+) — OK
- organization_id フィルタ: 全 4 ヘルパーに明示的フィルタあり — OK
- RLS set_config: 同一コネクション内で先行実行 — OK
- パラメータ化 SQL: バインドパラメータ使用 — OK
- 監査ログ: 全エンドポイントで log_audit_event() — OK
- ページネーション: per_page 最大 100 件 — OK
- エラーメッセージ: type(e).__name__ のみ — OK
- トランザクション外 API 呼び出し: Drive API は DB クローズ後に呼び出し — OK
- asyncio.to_thread(): 全同期ヘルパーに適用 — OK
- writable スコープ: _get_drive_client(writable=True) でアップロード用スコープ切り替え — OK
- file_type のみ SELECT: mime_type カラム不在に対応済み — OK
- RFC 5987 Content-Disposition: filename*=UTF-8'' 形式 — OK
- _sync_record_drive_upload の conn.commit(): set_config(is_local=true) + commit でRLSリセット正しい — OK

## db_schema.json documents テーブル確認結果
- organization_id: uuid 型 → INSERT の CAST(:org_id AS UUID) 正しい、SELECT の = :org_id も自動キャストで動作
- department_id: uuid 型 → WHERE department_id = CAST(:dept_id AS UUID) 正しい
- file_size_bytes: bigint — INSERT で使用している（file_size と両方存在するが問題なし）
- mime_type: 存在しない（修正済み）

## drive_routes.py の asyncio パターン（確認済み）
- `_get_drive_client()`: 同期関数（Secret Manager 同期 I/O）→ asyncio.to_thread() 経由 OK
- `drive_client.download_file()`: async def → FastAPI のイベントループで直接 await OK
- `drive_client.upload_file()`: async def → FastAPI のイベントループで直接 await OK
- パターン: `await asyncio.to_thread(同期初期化)` → `await async_method()` は正しい組み合わせ
