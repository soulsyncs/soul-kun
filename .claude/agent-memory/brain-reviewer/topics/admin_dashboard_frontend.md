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
