# 運用Runbook

**作成日:** 2026-01-30
**目的:** 本番運用時の障害対応・緊急手順を定義

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | 本番運用時の障害対応・緊急手順の定義 |
| **書くこと** | 緊急停止手順、障害対応フロー、権限事故対応、復旧手順 |
| **書かないこと** | 設計原則（→CLAUDE.md）、詳細実装（→04章、09章） |
| **SoT（この文書が正）** | 緊急停止手順、権限事故対応、監査ログ閲覧手順 |
| **Owner** | カズさん（代表） |
| **関連リンク** | [CLAUDE.md](../CLAUDE.md)、[security_and_bcp_guide](security_and_bcp_guide.md)、[Design Coverage Matrix](DESIGN_COVERAGE_MATRIX.md) |

---

## 1. 緊急停止手順

### 1.1 LLM Brain緊急停止

**トリガー条件:**
- LLMが不適切な応答を繰り返す
- コストが異常に増加している
- セキュリティインシデントが発生

**停止手順:**

```bash
# 1. 環境変数でLLM呼び出しを無効化
export LLM_ENABLED=false

# 2. Cloud Runサービスを停止
gcloud run services update soul-kun-api --no-traffic

# 3. 緊急連絡（カズさんへ）
# Slack: #emergency
# 電話: [緊急連絡先]
```

**復旧手順:**

```bash
# 1. 原因特定・修正完了後
export LLM_ENABLED=true

# 2. ステージング環境で動作確認

# 3. 本番トラフィック復旧
gcloud run services update soul-kun-api --to-revisions=LATEST=100
```

### 1.2 API緊急停止

**停止手順:**

```bash
# Cloud Run全停止
gcloud run services update soul-kun-api --no-traffic

# Cloud Functions停止
gcloud functions deploy chatwork-webhook --no-allow-unauthenticated
```

### 1.3 データベース緊急対応

**読み取り専用モードへの切り替え:**

```sql
-- 書き込み停止（緊急時のみ）
ALTER DATABASE soul_kun SET default_transaction_read_only = on;

-- 復旧
ALTER DATABASE soul_kun SET default_transaction_read_only = off;
```

---

## 2. 障害対応フロー

### 2.1 障害レベル定義

| レベル | 定義 | 対応時間 | エスカレーション |
|--------|------|---------|-----------------|
| P1（緊急） | サービス全停止、データ漏洩 | 即時 | カズさん直接連絡 |
| P2（重大） | 主要機能停止、パフォーマンス著しく低下 | 1時間以内 | Slack #emergency |
| P3（通常） | 一部機能不具合 | 24時間以内 | Slack #dev |
| P4（軽微） | UI不具合、軽微なバグ | 次回リリース | GitHub Issue |

### 2.2 障害対応手順

```
1. 検知 → 2. 切り分け → 3. 一次対応 → 4. 根本対応 → 5. 報告
```

**1. 検知**
- アラート受信（Cloud Monitoring）
- ユーザー報告（ChatWork）
- 監視ダッシュボード

**2. 切り分け**
- どの層で問題が発生しているか特定
  - LLM Brain？Guardian Layer？DB？外部API？

**3. 一次対応**
- 影響範囲の限定（該当機能の無効化）
- ユーザーへの通知

**4. 根本対応**
- 原因特定・修正
- テスト
- デプロイ

**5. 報告**
- 障害報告書作成
- 再発防止策

---

## 3. 権限事故対応

### 3.1 権限事故の種類

| 事故タイプ | 定義 | 深刻度 |
|-----------|------|--------|
| 権限昇格 | 本来見えないデータが見えた | P1 |
| 権限漏洩 | 他組織のデータが見えた | P1 |
| 権限不足 | 本来見えるべきデータが見えない | P3 |

### 3.2 権限事故発生時の対応

**即時対応（P1）:**

1. 該当ユーザーのセッション無効化
2. 該当APIエンドポイントの一時停止
3. 監査ログの保全

**調査:**

```sql
-- 該当ユーザーのアクセスログ確認
SELECT * FROM audit_logs
WHERE user_id = '[該当ユーザーID]'
AND created_at >= '[事故発生時刻]'
ORDER BY created_at DESC;

-- 該当リソースへのアクセス確認
SELECT * FROM audit_logs
WHERE resource_id = '[該当リソースID]'
AND created_at >= '[事故発生時刻]'
ORDER BY created_at DESC;
```

**報告:**

- 影響を受けたユーザーへの通知
- 必要に応じて個人情報保護委員会への報告

---

## 4. 監査ログ閲覧手順

### 4.1 監査ログの検索

```sql
-- 特定ユーザーの操作履歴
SELECT
    action,
    resource_type,
    resource_id,
    created_at
FROM audit_logs
WHERE user_id = '[ユーザーID]'
ORDER BY created_at DESC
LIMIT 100;

-- 特定期間の高権限操作
SELECT *
FROM audit_logs
WHERE action IN ('delete', 'update_permission', 'export')
AND created_at BETWEEN '[開始日時]' AND '[終了日時]';
```

### 4.2 監査ログの保全

**証拠保全が必要な場合:**

```bash
# ログのエクスポート
pg_dump -t audit_logs --data-only > audit_logs_backup_$(date +%Y%m%d).sql

# Cloud Storageへ保存
gsutil cp audit_logs_backup_*.sql gs://soul-kun-backups/audit/
```

---

## 5. コスト異常時の対応

### 5.1 コストアラート閾値

| 項目 | 通常 | 警告（黄） | 危険（赤） |
|------|------|----------|----------|
| LLM API（日） | 〜2,000円 | 5,000円 | 10,000円 |
| Cloud Run（日） | 〜500円 | 1,000円 | 2,000円 |
| DB（日） | 〜500円 | 1,000円 | 2,000円 |

### 5.2 コスト異常時の対応

**警告レベル:**
- 原因調査（どのAPIが多いか）
- 不要なリクエストの特定

**危険レベル:**
- レート制限の強化
- 必要に応じてLLM呼び出しの一時停止

---

## 6. レート制限

### 6.1 レート制限ルール

| エンドポイント | 制限 | 単位 |
|--------------|------|------|
| 全API（認証済み） | 100リクエスト | /分/ユーザー |
| LLM呼び出し | 20リクエスト | /分/ユーザー |
| 検索API | 30リクエスト | /分/ユーザー |
| 管理API | 10リクエスト | /分/ユーザー |

### 6.2 レート制限超過時の応答

```json
{
  "error": "rate_limit_exceeded",
  "message": "リクエスト数が上限を超えました。しばらくお待ちください。",
  "retry_after": 60
}
```

HTTPステータス: `429 Too Many Requests`

### 6.3 レート制限の実装

```python
from fastapi import HTTPException
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

# エンドポイントに適用
@app.get("/api/v1/search", dependencies=[Depends(RateLimiter(times=30, seconds=60))])
async def search():
    pass
```

---

## 7. PII処理ガイドライン

### 7.1 PIIの定義

| カテゴリ | 例 | 処理ルール |
|---------|-----|----------|
| 直接識別子 | 氏名、メールアドレス、電話番号 | 原則保存禁止、必要時は暗号化 |
| 間接識別子 | 社員番号、部署名 | 内部利用のみ、外部出力時はマスキング |
| 機密情報 | 給与、評価、健康情報 | 保存禁止、ログ出力禁止 |

### 7.2 マスキングルール

| データ種類 | マスキング例 |
|-----------|-------------|
| メールアドレス | `t***@example.com` |
| 電話番号 | `090-****-1234` |
| 氏名 | `田中 *` |

### 7.3 PII削除手順

**ユーザーからの削除依頼時:**

```sql
-- 1. 該当ユーザーのMemoryを削除
DELETE FROM memories WHERE user_id = '[ユーザーID]';

-- 2. 監査ログは保持（ただしPIIはマスキング済み）
-- 監査ログの削除は法的要件に基づいて判断

-- 3. 削除完了の記録
INSERT INTO deletion_requests (user_id, requested_at, completed_at)
VALUES ('[ユーザーID]', NOW(), NOW());
```

### 7.4 PII保持期間

| データ種類 | 保持期間 | 根拠 |
|-----------|---------|------|
| 会話履歴（要約） | 1年 | 業務上の必要性 |
| 監査ログ | 1年 | セキュリティ要件 |
| Memory（嗜好情報） | 退職まで | 業務上の必要性 |
| 削除されたユーザーデータ | 即時削除 | 個人情報保護法 |

---

## 8. 失敗時の挙動（全体原則）

### 8.1 原則

> **「失敗しても安全に、ユーザーに迷惑をかけない」**

### 8.2 レイヤー別の失敗ハンドリング

| レイヤー | 失敗時の挙動 |
|---------|-------------|
| LLM Brain | 「すみません、うまく理解できませんでした」と応答 |
| Guardian Layer | 操作を拒否し、理由を説明 |
| Authorization Gate | アクセス拒否、監査ログに記録 |
| DB | トランザクションロールバック、エラー通知 |
| 外部API | リトライ（最大3回）、タイムアウト（30秒） |

### 8.3 エラーメッセージの原則

**ユーザー向け:**
- 技術用語を使わない
- 何が起きたか、何をすべきかを伝える
- 機密情報を含めない

**例:**
```
❌ "DatabaseError: connection refused to host 10.0.0.5:5432"
✅ "一時的な問題が発生しました。しばらくしてからもう一度お試しください。"
```

**ログ向け:**
- 技術的な詳細を含める
- スタックトレースを含める
- ただしPIIはマスキング

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-01-30 | 初版作成（Design Coverage Matrixの漏れ対応） |

---

**このファイルについての質問は、CLAUDE.mdを参照してください。**
