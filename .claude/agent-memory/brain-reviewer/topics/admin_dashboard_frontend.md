# admin-dashboard フロントエンドレビューパターン

## Phase A-1: 通貨表示バグ修正（$→¥）— branch fix/currency-display-jpy (reviewed 2026-02-19)

### 変更ファイル（4件）
- `admin-dashboard/src/components/dashboard/kpi-card.tsx`: `format="currency"` の formatValue関数
- `admin-dashboard/src/pages/costs.tsx`: 13箇所の $ 表示すべてを ¥ に変更
- `admin-dashboard/src/pages/dashboard.tsx`: YAxis/Tooltip/ツールチップテキスト
- `admin-dashboard/src/pages/brain.tsx`: コストカードのツールチップと表示値

### CRITICAL: テスト乖離（C-1）
- `admin-dashboard/src/components/dashboard/kpi-card.test.tsx` line 22:
  - テストは `$42.50` を期待しているが、修正後コードは `¥43` を返す（`toFixed(0)` で四捨五入）
  - マージ前に必ず修正必要

### 網羅性確認結果（2026-02-19 確定）
- `$` ベースコスト表示の残存箇所: 0件（全 .tsx 検索済み）
- `format="currency"` を使う箇所: dashboard.tsx の2箇所のみ（本日のコスト・予算残高）
- `admin/app/schemas/admin.py` の "（USD）" 表記: 既に存在しない（前回記録は古い情報）

### JPY 表示の正当性
- `toFixed(0)` は JPY として正しい（最小単位=1円、小数点不要）
- バックエンドの `cost_jpy` は INTEGER 型（costs_routes.py）
- 代替案: `Math.round()` の方が意図が明確だが、同結果なので SUGGESTION レベル
- 改善余地: 大きな金額のケタ区切り（`toLocaleString()` 使用）は別途対応推奨

### 注意: dashboard.tsx の予算残高カード
- `本日のコスト`（tooltip: "日本円"に更新済み）
- `予算残高`（tooltip: 通貨単位の記述なし — WARNING として指摘）

### 注意: costs.tsx の予算進捗バーテキスト（line 210-211）
```tsx
¥{currentMonth.total_cost.toFixed(0)} / ¥
{currentMonth.budget.toFixed(0)}
```
JSX の改行で `¥` の後にスペースが入る可能性あり（実レンダリング要確認）

## admin-dashboard 全般パターン

- フロントエンド変更は Brain architecture / org_id チェック N/A
- セキュリティチェック: XSS (JSX は自動エスケープ)、認証バイパスなし（管理者限定 §1-1例外）
- テストフレームワーク: Vitest + @testing-library/react
- 22項目チェックリスト: #1, #2, #3, #4, #16, #17 が主な適用対象
- 横展開チェック (#17): 通貨表示の場合 `format="currency"` を全 .tsx で grep する

## Phase B: Google Drive 管理フロントエンドレビュー (2026-02-21)

### 対象ファイル
- `admin-dashboard/src/pages/google-drive.tsx` (新規)
- `admin-dashboard/src/hooks/use-drive.ts` (新規)
- `admin-dashboard/src/lib/api.ts` (drive: セクション追加)

### WARNING 発見事項

#### W-1: api.ts line 681-683 — sessionStorageから直接トークンを再取得（`_bearerToken`モジュール変数を参照せず）
- `downloadFile()` と `uploadFile()` が `sessionStorage.getItem('soulkun_admin_token')` を直接使う
- `_bearerToken` モジュール変数（`clearBearerToken()` でクリアされる）とは独立して動作
- ログアウト後に sessionStorage だけクリアされず `_bearerToken` のみクリアした場合、ダウンロード/アップロードが無認証で走るリスクがある
- 実際: `clearBearerToken()` は sessionStorage.removeItem も呼ぶので現状は OK だが、設計的二重管理が脆弱
- 推奨修正: 既存の `_bearerToken` モジュール変数（既に sessionStorage と同期済み）を直接参照するか、`downloadFile/uploadFile` を `fetchWithAuth` 経由に統一する

#### W-2: google-drive.tsx line 507 — `google_drive_web_view_link` を href にそのまま使用（XSSリスク）
- バックエンドが返す `google_drive_web_view_link` は外部サービス(Google)のURL
- JSX `<a href={file.google_drive_web_view_link}>` は `javascript:` スキームを許可してしまう
- React は href の `javascript:` をブロックしない（JSX の自動エスケープは属性値スキームを検査しない）
- DBに悪意ある値が入った場合に XSS になる
- 推奨: `href` 設定前に `new URL(link).protocol` が `https:` であることを確認するガード追加

#### W-3: google-drive.tsx line 124 — 拡張子チェックのみでMIMEタイプ検証なし（フロントエンド）
- フロントエンドは拡張子ベースの検証のみ。バックエンドはMIMEタイプも検証しているが、フロントは `file.type` を使わない
- 攻撃者がファイルの content-type を偽装できる（Fileオブジェクトの type は拡張子から推定されることが多い）
- 実害: バックエンドのMIME検証が最終防衛線なので、フロント側のMIME未検証は Defense-in-Depth の欠如として WARNING レベル

#### W-4: google-drive.tsx line 191 — アップロード成功後にモーダルを閉じてもキャッシュ更新タイミングにラグ
- `useUploadDriveFile.onSuccess` で `queryClient.invalidateQueries({ queryKey: ['drive'] })`
- ユーザーが「閉じる」を押すと `setShowUpload(false)` だが、モーダル内の `isSuccess` UI を見てから閉じるまで一覧は古いキャッシュを表示したまま
- UX 問題のみ、セキュリティ問題ではない

### SUGGESTION 発見事項

#### S-1: google-drive.tsx line 53-57 — `formatFileSize` が 0 を `-` と表示
- `if (!bytes)` は 0 も falsy として扱う。0 バイトのファイルは "-" と表示される
- `if (bytes === null || bytes === undefined)` の方が意図が明確

#### S-2: api.ts — drive.getFiles() で queryString 構築ロジックが他のエンドポイント（goals, wellness 等）と異なる
- 他は `URLSearchParams` + `if (params?.xxx)` で構築している
- `drive.getFiles` も同パターンだが `fetchWithAuth` の `params:` オプションを使っていない（直接 URL に付加）
- 動作は同等だが不統一

#### S-3: use-drive.ts — `useDriveSyncStatus` の staleTime 5分は同期状態の頻繁な確認ユースケースには長い
- 同期エラーを素早く確認したい運用シナリオでは 1分程度が望ましい

#### S-4: google-drive.tsx — UploadModal の classification select に型ガードなし
- `setClassification` は `string` 型のみ。選択肢外の値を TypeScript が防げない
- `'public' | 'internal' | 'restricted' | 'confidential'` のユニオン型にすべき

### 確認済みOK事項
- 権限チェック: `canUpload = (user?.role_level ?? 0) >= 6` — Level 6以上のみアップロードボタン表示 (OK)
- ページネーション: `PER_PAGE = 20`, チェック `total > PER_PAGE` で条件表示 (OK)
- ファイルサイズ上限: フロント 20MB, バックエンド 20MB 一致 (OK)
- 拡張子ホワイトリスト: フロント `ALLOWED_EXTENSIONS` とバックエンド `_ALLOWED_EXTENSIONS` 一致 (OK)
- エラー表示: `err.message` のみ使用（スタックトレース非露出）(OK)
- ドラッグアンドドロップ: `handleDrop` が `handleFilePick` と同じバリデーション経由 (OK)
- XHR progress bar: `XMLHttpRequest.upload.progress` イベント正しく使用 (OK)
- `rel="noopener noreferrer"`: `target="_blank"` リンクに付与済み (OK)
