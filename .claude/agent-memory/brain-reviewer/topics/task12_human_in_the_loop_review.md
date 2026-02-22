# TASK-12 Human-in-the-loop Learning Pattern Review

## レビュー対象 (2026-02-22)

- `api/app/schemas/admin.py`: LearningPatternEntry / LearningPatternsResponse / ValidatePatternRequest / ValidatePatternResponse 追加
- `api/app/api/v1/admin/brain_routes.py`: GET /brain/learning/patterns + PATCH /brain/learning/patterns/{id}/validate 追加
- `admin-dashboard/src/pages/brain-learning.tsx`: 新規フロントエンドページ

## 判定: CONDITIONAL PASS

### CRITICAL (0件)
なし。データ漏洩・DB破壊・認証バイパスのリスクなし。

### WARNING (3件)

#### W-1: f-string SQL (鉄則#9 準拠ライン)
- **場所**: `brain_routes.py` line 358, 383
- `text(f"""... {where_clause} ...""")` を使用
- `where_clause` は Python の bool (unvalidated_only) のみで変化。ユーザー入力は直接入らない。
- FastAPI の `Query(bool)` が型検証するため、SQLインジェクションリスクは実質ゼロ。
- **ただし**: 鉄則#9「SQLはパラメータ化」の精神に反する。将来的に where_clause 生成ロジックが拡張された際のリスク。
- **推奨修正**: `if unvalidated_only: where_extra = "AND is_validated = false" else: where_extra = ""` としてパラメータ化した文字列定数に変換する。あるいは2つの別 SQL を用意する。

#### W-2: Human-in-the-loop 設計意図とBrain参照ロジックの不一致
- **場所**: `brain_routes.py` ドキュメント vs `lib/brain/outcome_learning/repository.py` line 560-603
- `brain_routes.py` ドキュメント: "承認: is_validated=true → 本番の判断に反映"
- `repository.py` の `find_applicable_patterns()`: `is_active = true` のみフィルタ。`is_validated` を見ていない。
- → **未承認パターン（is_validated=false）も Brain が本番で使う**
- 現状の設計は「却下（is_active=false）のみが無効化手段」であり、承認は "任意の確認マーク" にすぎない。
- ドキュメントが誤解を生む。管理者は「承認すれば反映される」と理解するが、実際は承認前から使われる。
- **推奨対応**: 設計選択の明確化が必要。
  - Option A: `find_applicable_patterns` に `AND (is_validated = true OR is_validated IS NULL)` を追加（Human-in-the-loop を厳格に運用）
  - Option B: ドキュメントを修正して「承認は確認マーク。却下のみが無効化手段。」と明記する
  - どちらが正しい設計意図かは実装者が判断すること。

#### W-3: validate 操作の権限レベル (CLAUDE.md §1-1)
- **場所**: `brain_routes.py` line 475 `user: UserContext = Depends(require_admin)`
- validate_learning_pattern（書き込み）が Level 5 (require_admin)
- CLAUDE.md §1-1: 書き込み操作は「Level 6（代表/CFO）のみ、または Level 5以上（操作内容による）」
- Brain の判断パターンを変更する操作 → Level 6 が適切という解釈も成立
- drive.py アップロード（Level 6）/ メンバー削除（Level 6）との一貫性を確認要
- **現状**: 他の "ナレッジ・設定変更" 系は Level 5 で実装されているケースもある
- **推奨**: 設計判断をコメントに明記する（"Brain状態変更だが管理者全員が実行可能とする"）

### SUGGESTION (3件)

#### S-1: フロントエンドのページネーション未実装
- `brain-learning.tsx` は常に `getLearningPatterns(!showAll)` （デフォルト limit=50）を使用
- offset を進めるコントロールなし。51件目以降のパターンをフロントで表示できない。
- バックエンドはページネーション対応済み（limit/offset パラメータあり）
- 鉄則#5 の閾値（1000件）未満なので blocking ではない
- 推奨: 「次の50件」ボタン追加、または total_count >= 50 の場合に警告表示

#### S-2: org_id の UUID キャスト一貫性
- `brain_routes.py`: `organization_id = :org_id` (暗黙キャスト)
- `repository.py`: `CAST(:organization_id AS uuid)` (明示的)
- `brain_outcome_patterns.organization_id` は UUID型
- PostgreSQL は text→uuid の暗黙キャストを行う（動作は正しい）
- repository.py は明示的キャストを使っており、brain_routes.py との不一致
- 推奨: `CAST(:org_id AS uuid)` に統一（既存の他ルートも同様）

#### S-3: テストカバレッジ欠如
- 新エンドポイント（GET /brain/learning/patterns, PATCH /validate）のテストなし
- `tests/test_brain_outcome_learning.py` はあるが API レイヤーのテストなし
- 推奨: `tests/test_admin_brain_routes.py` 追加（少なくとも 404/200/403 パターン）

## 確認済み OK 事項

- brain_outcome_patterns テーブル: db_schema.json に存在確認。全 SELECT/UPDATE カラムが実在。
- org_id フィルタ: GET/PATCH 全クエリに AND organization_id = :org_id あり（鉄則#1 OK）
- 監査ログ: GET も PATCH も log_audit_event 呼び出しあり（鉄則#3 OK）
- 認証: require_admin（Level 5+）+ JWT + DB権限確認（鉄則#4 OK）
- PII: pattern_content（JSONB）は SELECT 対象外。返却フィールドは統計値のみ（鉄則#8 OK）
- 鉄則#10: トランザクション内 API 呼び出しなし（OK）
- §1-1 適用: 管理ダッシュボード例外（Brain 経由不要）の条件を全て満たす
  - 読み取り専用エンドポイントあり、管理者限定、AI判断なし、能動的出力なし
  - 書き込み（validate）: 管理者限定、Brain状態の変更、AI判断なし、能動的出力なし → 適用OK
- フロントエンド: JSX 自動エスケープ（XSSなし）、エラー表示は err.message のみ
- フロントエンド: `validateMutation.isPending` で二重送信防止（OK）
- TypeScript 型定義: `api.ts` と `types/api.ts` の型が一致（OK）
- `staleTime: 60_000`（1分）→ 長すぎないか？ 承認後の即時反映を邪魔する可能性あるが、invalidateQueries で対処済み

## brain_outcome_patterns スキーマメモ

- UUID型: id, organization_id, promoted_to_learning_id
- VARCHAR型: pattern_type, pattern_category, scope, scope_target_id
- JSONB: pattern_content（PII含む可能性、今回は SELECT から除外済み）
- Boolean: is_active, is_validated
- Timestamp: validated_at, created_at, updated_at, promoted_at, last_effectiveness_check
- Numeric: success_rate, confidence_score, effectiveness_score
