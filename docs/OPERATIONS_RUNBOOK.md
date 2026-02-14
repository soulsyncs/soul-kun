# 運用Runbook

**作成日:** 2026-01-30
**目的:** 本番運用時の障害対応・緊急手順を定義

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | 本番運用時の障害対応・緊急手順の定義 |
| **書くこと** | 緊急停止手順、障害対応フロー、権限事故対応、復旧手順 |
| **書かないこと** | 設計原則（→CLAUDE.md）、詳細実装（→04章）、コード規約（→09章）、脳アーキテクチャ（→25章） |
| **SoT（この文書が正）** | 緊急停止手順、権限事故対応、監査ログ閲覧手順 |
| **Owner** | SRE / インフラ担当（連絡先: #infra チャンネル） |
| **関連リンク** | [CLAUDE.md](../CLAUDE.md)、[security_and_bcp_guide](security_and_bcp_guide.md)、[Design Coverage Matrix](DESIGN_COVERAGE_MATRIX.md) |

---

## 1. 緊急停止手順

> ⚠️ **インフラ構成変更時の注意**
>
> 本セクションのコマンドは現在のインフラ構成（Cloud Run, Cloud Functions, PostgreSQL）に依存しています。
> **インフラ構成を変更した場合は、本セクションを最優先で更新してください。**
> 古いコマンドが残っていると、緊急時に停止できない事故につながります。

### 1.1 LLM Brain緊急停止

**トリガー条件:**
- LLMが不適切な応答を繰り返す
- コストが異常に増加している
- セキュリティインシデントが発生

**停止手順:**

```bash
# 1. 環境変数でLLM呼び出しを無効化
export USE_BRAIN_ARCHITECTURE=false

# 2. Cloud Runサービスを停止
gcloud run services update soul-kun-api --no-traffic

# 3. 緊急連絡（カズさんへ）
# Slack: #emergency
# 電話: [緊急連絡先]
```

**復旧手順:**

```bash
# 1. 原因特定・修正完了後
export USE_BRAIN_ARCHITECTURE=true

# 2. ステージング環境で動作確認

# 3. 本番トラフィック復旧
gcloud run services update soul-kun-api --to-revisions=LATEST=100
```

### 1.2 API緊急停止

**停止手順:**

```bash
# Cloud Run全サービス停止（トラフィック遮断）
gcloud run services update chatwork-webhook --no-traffic --region=asia-northeast1
gcloud run services update proactive-monitor --no-traffic --region=asia-northeast1
gcloud run services update soulkun-mcp-server --no-traffic --region=asia-northeast1
gcloud run services update soulkun-mobile-api --no-traffic --region=asia-northeast1
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

## 9. Alarm→Runbook対応表

### 9.1 アラート一覧と初動対応

| アラート名 | 発火条件 | 深刻度 | 初動対応 | 参照セクション |
|-----------|---------|--------|---------|---------------|
| `llm_cost_warning` | LLM APIコスト日額 > 5,000円 | 警告 | 原因調査、不要リクエスト特定 | セクション5.2 |
| `llm_cost_critical` | LLM APIコスト日額 > 10,000円 | 緊急 | LLM呼び出し一時停止検討 | セクション5.2, 1.1 |
| `api_error_rate_high` | エラー率 > 5%（5分間） | 警告 | ログ確認、影響範囲特定 | セクション2.2 |
| `api_error_rate_critical` | エラー率 > 20%（5分間） | 緊急 | 障害対応フロー開始 | セクション2.2 |
| `db_connection_failed` | DB接続失敗 | 緊急 | DB状態確認、復旧手順 | セクション1.3 |
| `rate_limit_exceeded` | レート制限超過（1分間100回以上） | 警告 | 該当ユーザー/IP特定 | セクション6 |
| `unauthorized_access` | 権限外アクセス試行 | 緊急 | セッション無効化、監査ログ保全 | セクション3 |
| `llm_inappropriate_response` | 不適切応答検知 | 緊急 | LLM Brain緊急停止検討 | セクション1.1 |
| `pii_leak_detected` | PII漏洩検知 | 緊急 | 該当API停止、データ保全 | セクション7, 3 |

### 9.2 アラート未発火でも確認すべき定期チェック

| チェック項目 | 頻度 | 確認方法 | 異常時の参照 |
|-------------|------|---------|-------------|
| LLMコスト推移 | 毎日 | Cloud Billingダッシュボード | セクション5 |
| エラーログ | 毎日 | Cloud Logging | セクション2 |
| 監査ログ（高権限操作） | 週次 | `SELECT * FROM audit_logs WHERE action IN ('delete', 'update_permission')` | セクション4 |
| レート制限近接ユーザー | 週次 | アクセスログ分析 | セクション6 |

### 9.3 エスカレーションルール

```
アラート受信
    ↓
深刻度が「警告」→ Slack #dev に通知、24時間以内対応
深刻度が「緊急」→ Slack #emergency + カズさん直接連絡、即時対応
    ↓
30分以内に原因特定できない場合 → P1エスカレーション（セクション2.1参照）
```

---

## 10. 監視KPI（最低限の指標）

### 10.1 必須監視KPI

| KPI | 計測方法 | 正常範囲 | アラート閾値 | 確認頻度 |
|-----|---------|---------|-------------|---------|
| **LLM応答時間（p95）** | Cloud Monitoring | < 5秒 | > 10秒 | リアルタイム |
| **LLMエラー率** | エラーログカウント / 総リクエスト | < 1% | > 5% | 5分間隔 |
| **API成功率** | 2xx / 総リクエスト | > 99% | < 95% | 5分間隔 |
| **DB接続数** | PostgreSQL監視 | < 80% of max | > 90% of max | 1分間隔 |
| **LLM日次コスト** | Cloud Billing | < 2,000円 | > 5,000円 | 毎日 |

### 10.2 ビジネスKPI（週次確認）

| KPI | 計測方法 | 目標 | 備考 |
|-----|---------|------|------|
| **脳経由率** | 脳API呼び出し / 全ユーザーリクエスト | 100% | バイパス検知 |
| **確認フロー発動率** | 確認質問発生 / 曖昧な入力 | 適正（高すぎも低すぎもNG） | 月次で傾向分析 |
| **権限拒否発生率** | 権限エラー / 総アクセス | < 1% | 高い場合は権限設計見直し |
| **Memory利用率** | Memory保存 / 会話数 | 適正範囲内 | 保存しすぎ/しなさすぎ検知 |

### 10.3 ダッシュボード構成

```
┌─────────────────────────────────────────────────────────┐
│ ソウルくん 運用ダッシュボード                              │
├─────────────────────────────────────────────────────────┤
│ [リアルタイム]                                           │
│ ・API成功率: 99.2% ✅                                   │
│ ・LLM応答時間(p95): 3.2秒 ✅                            │
│ ・アクティブ接続数: 45/100 ✅                            │
│                                                         │
│ [日次]                                                  │
│ ・LLMコスト: ¥1,850 ✅                                  │
│ ・エラー件数: 12件 ✅                                    │
│ ・権限拒否: 3件 ✅                                       │
│                                                         │
│ [週次トレンド]                                           │
│ ・脳経由率: 100% ✅                                      │
│ ・確認フロー発動率: 15% (先週比 +2%)                     │
└─────────────────────────────────────────────────────────┘
```

### 10.4 監視ツール構成

| 用途 | ツール | 設定場所 |
|------|-------|---------|
| インフラ監視 | Cloud Monitoring | GCPコンソール |
| ログ収集 | Cloud Logging | GCPコンソール |
| コスト監視 | Cloud Billing | GCPコンソール |
| アラート通知 | Cloud Alerting → Slack | #monitoring チャンネル |
| ダッシュボード | Cloud Monitoring Dashboard | GCPコンソール |

---

## 11. organization_id（テナント）管理

### 11.1 現在の状態

| 項目 | 値 |
|------|-----|
| 現在のフェーズ | Phase 3.5（単一テナント） |
| デフォルトテナント | `org_soulsyncs` |
| マルチテナント対応 | フレームワーク実装済み、未有効化 |

### 11.2 テナントアーキテクチャ

```
┌─────────────────────────────────────────────────┐
│ Phase 3.5（現在）: 単一テナント                    │
│                                                 │
│   全データ → organization_id = "org_soulsyncs"   │
│   lib/tenant.py の DEFAULT_TENANT_ID を使用       │
└─────────────────────────────────────────────────┘
          ↓ Phase 4 移行時
┌─────────────────────────────────────────────────┐
│ Phase 4: マルチテナント                          │
│                                                 │
│   顧客A → organization_id = "org_customer_a"    │
│   顧客B → organization_id = "org_customer_b"    │
│   社内  → organization_id = "org_soulsyncs"     │
│                                                 │
│   リクエストヘッダー X-Tenant-ID でテナント指定   │
└─────────────────────────────────────────────────┘
```

### 11.3 テナント初期化手順

**新規テナント追加時（Phase 4以降）:**

```sql
-- 1. organizationsテーブルに追加
INSERT INTO organizations (id, name, plan, is_active, created_at)
VALUES (
    'org_customer_xxx',
    '株式会社〇〇',
    'standard',
    true,
    NOW()
);

-- 2. 管理者ユーザーを作成
INSERT INTO users (id, organization_id, email, name, role_level)
VALUES (
    'usr_admin_xxx',
    'org_customer_xxx',
    'admin@customer.com',
    '管理者',
    6  -- 代表レベル
);

-- 3. デフォルト部署を作成
INSERT INTO departments (id, organization_id, name, path, level)
VALUES (
    'dept_root_xxx',
    'org_customer_xxx',
    '全社',
    'root',
    0
);
```

### 11.4 テナント分離の保証

**Row Level Security（RLS）による強制:**

```sql
-- 全テーブルにRLSポリシーを適用
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tasks
    USING (organization_id = current_setting('app.current_tenant'));
```

**アプリケーション層での保証（lib/tenant.py）:**

```python
# 全クエリでテナントフィルタを強制
with TenantContext(organization_id):
    # このブロック内では organization_id がフィルタされる
    tasks = await get_tasks()  # 自テナントのみ取得
```

### 11.5 移行時の注意事項

| リスク | 対策 |
|--------|------|
| 既存データの organization_id が空 | 移行スクリプトで `org_soulsyncs` を設定 |
| 新規テーブルに organization_id がない | PRレビューでチェック（10の鉄則 #1） |
| クロステナントアクセス | `validate_tenant_access()` で拒否 |
| テナント削除時のデータ残留 | 論理削除 + 30日後に物理削除 |

### 11.6 テナント関連のコード参照先

| 機能 | ファイル |
|------|---------|
| テナントコンテキスト管理 | `lib/tenant.py` |
| アクセス制御 | `api/app/services/access_control.py` |
| 6段階権限レベル | `api/app/services/access_control.py` L6-12 |
| RLSポリシー | `migrations/` 配下 |

---

## 12. 外部サービス障害対応【2026-01-30追加】

### 12.1 Google Drive API障害

**検知方法:**
- Cloud Monitoringアラート「Google Drive sync error rate > 10%」
- ユーザー報告「ドキュメントが同期されない」

**対応手順:**

| ステップ | アクション | コマンド/手順 |
|---------|-----------|--------------|
| 1 | Google Workspaceステータス確認 | https://www.google.com/appsstatus/dashboard/ |
| 2 | API割り当て確認 | GCPコンソール → API → Google Drive API → 割り当て |
| 3 | 同期キュー滞留確認 | `SELECT COUNT(*) FROM document_sync_queue WHERE status = 'pending'` |
| 4 | 影響範囲特定 | 滞留開始時刻〜現在の同期対象ドキュメント数 |
| 5-A | Google障害の場合 | フォールバックモード有効化（下記参照） |
| 5-B | 割り当て超過の場合 | 割り当て引き上げ申請 or 同期間隔を延長 |
| 6 | 復旧確認 | 同期キューが正常に消化されることを確認 |

**フォールバックモード:**
```bash
# 同期を一時停止し、ユーザーへの通知を設定
gcloud functions deploy sync-google-drive \
  --update-env-vars SYNC_ENABLED=false,FALLBACK_MESSAGE="Google Driveとの同期を一時停止中です"
```

**復旧後の確認:**
- [ ] 滞留していたドキュメントが同期された
- [ ] 新規アップロードが正常に処理される
- [ ] ベクトル検索に新規ドキュメントが反映される

---

### 12.2 Pinecone障害

**検知方法:**
- Cloud Monitoringアラート「Pinecone query latency > 5s」
- ユーザー報告「ナレッジ検索が遅い/動かない」

**対応手順:**

| ステップ | アクション | コマンド/手順 |
|---------|-----------|--------------|
| 1 | Pineconeステータス確認 | https://status.pinecone.io/ |
| 2 | インデックス状態確認 | Pineconeコンソール → Index → Status |
| 3 | 接続テスト | `curl -X GET "https://{index}-{project}.svc.{environment}.pinecone.io/describe_index_stats"` |
| 4-A | Pinecone障害の場合 | フォールバックモード有効化 |
| 4-B | インデックス問題の場合 | インデックス再構築検討 |
| 5 | 復旧確認 | ナレッジ検索の応答時間が正常に戻る |

**フォールバックモード（ナレッジ検索なしで応答）:**
```python
# 環境変数で制御
PINECONE_FALLBACK_ENABLED=true
PINECONE_FALLBACK_MESSAGE="現在ナレッジ検索が一時的に利用できません。基本的な応答のみ可能です。"
```

**ユーザーへの通知:**
- 「ナレッジベースが一時的に利用できないため、一般的な回答のみ可能です」と説明

---

### 12.3 DNS障害

**検知方法:**
- Cloud Monitoringアラート「DNS resolution failures」
- 全サービスが突然応答しなくなる

**対応手順:**

| ステップ | アクション | コマンド/手順 |
|---------|-----------|--------------|
| 1 | DNS解決テスト | `dig api.soulsyncs.jp` |
| 2 | Cloud DNSステータス確認 | GCPコンソール → Network Services → Cloud DNS |
| 3 | 代替DNS確認 | `dig @8.8.8.8 api.soulsyncs.jp` |
| 4-A | Cloud DNS障害の場合 | 代替DNSの設定を検討 |
| 4-B | ドメイン問題の場合 | ドメインレジストラ確認 |
| 5 | 復旧確認 | 全サービスへのアクセス確認 |

**緊急時の直接IP接続（非推奨・最終手段）:**
```bash
# Cloud RunのURLを直接使用
curl https://chatwork-webhook-xxxxx-an.a.run.app/health
```

---

## 13. インフラ障害対応【2026-01-30追加】

### 13.1 メモリリーク対応

**検知方法:**
- Cloud Monitoringアラート「Container memory usage > 80%」
- Cloud Runインスタンスの頻繁な再起動

**対応手順:**

| ステップ | アクション | コマンド/手順 |
|---------|-----------|--------------|
| 1 | メモリ使用量確認 | GCPコンソール → Cloud Run → メトリクス → Memory utilization |
| 2 | 異常インスタンス特定 | ログでOOMKillerのパターンを検索 |
| 3 | 一時対処（再起動） | 新リビジョンのデプロイまたはトラフィック切り替え |
| 4 | 根本原因調査 | ログ分析、プロファイリング |
| 5 | 修正デプロイ | 修正版をデプロイ |

**メモリ監視閾値:**
| 閾値 | アクション |
|------|-----------|
| 70% | 警告アラート |
| 80% | 重大アラート、調査開始 |
| 90% | 緊急対応、再起動検討 |

**一時的なメモリ増加:**
```bash
gcloud run services update chatwork-webhook \
  --memory 2Gi  # 1Gi → 2Gi
```

---

### 13.2 ディスク容量不足

**検知方法:**
- Cloud Monitoringアラート「Cloud SQL disk usage > 80%」

**対応手順:**

| ステップ | アクション | コマンド/手順 |
|---------|-----------|--------------|
| 1 | 使用量確認 | GCPコンソール → Cloud SQL → 概要 |
| 2 | 大きなテーブル特定 | `SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;` |
| 3-A | 古いデータ削除可能 | cleanup-old-data Cloud Functionを手動実行 |
| 3-B | 削除不可 | ストレージ自動拡張を確認/有効化 |
| 4 | 復旧確認 | 使用率が80%未満に低下 |

**ストレージ自動拡張確認:**
```bash
gcloud sql instances describe soulkun-db --format="value(settings.storageAutoResize)"
# true であれば自動拡張有効
```

---

## 14. DBマイグレーション障害対応【2026-01-30追加】

### 14.1 マイグレーション失敗時の対応

**検知方法:**
- デプロイパイプラインでマイグレーションステップが失敗
- アプリケーション起動時のDB接続エラー

**対応手順:**

| ステップ | アクション | コマンド/手順 |
|---------|-----------|--------------|
| 1 | エラー内容確認 | マイグレーションログを確認 |
| 2 | 現在のスキーマ状態確認 | `SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 5;` |
| 3 | 影響範囲特定 | 失敗したマイグレーションの変更内容を確認 |
| 4-A | ロールバック可能 | ロールバックマイグレーション実行 |
| 4-B | ロールバック不可 | 手動修正（下記参照） |
| 5 | 復旧確認 | アプリケーションが正常に起動 |

**ロールバック手順:**
```bash
# Alembicの場合
alembic downgrade -1

# 手動ロールバック（最終手段）
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f rollback_migration_xxx.sql
```

**マイグレーション前チェックリスト:**
- [ ] テスト環境で実行済み
- [ ] ロールバックスクリプトを準備
- [ ] バックアップを取得
- [ ] メンテナンス時間帯を確保（破壊的変更の場合）

---

### 14.2 マイグレーション実行のベストプラクティス

**本番マイグレーション手順:**
1. **事前準備**
   - バックアップ取得（自動バックアップ + オンデマンド）
   - ロールバックスクリプト準備
   - テスト環境での検証完了

2. **実行**
   - 低トラフィック時間帯（深夜または早朝）
   - マイグレーション実行
   - アプリケーション再起動

3. **確認**
   - 主要機能の動作確認
   - エラーログ監視（15分間）
   - パフォーマンス影響確認

---

## 15. DDoS攻撃対応【2026-01-30追加】

### 15.1 検知と初動

**検知方法:**
- Cloud Monitoringアラート「Request rate > 10x normal」
- Cloud Armorログで異常パターン検出
- ユーザー報告「サービスが遅い/使えない」

**対応手順:**

| ステップ | アクション | 時間目標 |
|---------|-----------|---------|
| 1 | 攻撃パターン特定 | 5分 |
| 2 | Cloud Armor緊急ルール適用 | 10分 |
| 3 | 影響サービスの確認 | 15分 |
| 4 | 必要に応じてGCPサポートへ連絡 | 20分 |
| 5 | 継続的な監視 | 復旧まで |

### 15.2 Cloud Armorルール設定

**事前設定（推奨）:**
```bash
# レート制限ルールの作成
gcloud compute security-policies rules create 1000 \
  --security-policy=soulkun-policy \
  --expression="true" \
  --action=rate-based-ban \
  --rate-limit-threshold-count=100 \
  --rate-limit-threshold-interval-sec=60 \
  --ban-duration-sec=600
```

**緊急時のIPブロック:**
```bash
# 特定IPからのアクセスをブロック
gcloud compute security-policies rules create 100 \
  --security-policy=soulkun-policy \
  --src-ip-ranges="1.2.3.4/32" \
  --action=deny-403
```

**緊急時の地域ブロック（最終手段）:**
```bash
# 特定地域からのアクセスをブロック
gcloud compute security-policies rules create 200 \
  --security-policy=soulkun-policy \
  --expression="origin.region_code == 'XX'" \
  --action=deny-403
```

### 15.3 復旧と事後対応

**復旧確認:**
- [ ] リクエストレートが正常に戻った
- [ ] 正規ユーザーがアクセスできる
- [ ] エラー率が正常範囲

**事後対応:**
- [ ] 攻撃パターンの分析
- [ ] 恒久的なCloud Armorルール追加
- [ ] インシデントレポート作成

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-01-30 | 初版作成（Design Coverage Matrixの漏れ対応） |
| 2026-01-30 | セクション9追加（Alarm→Runbook対応表） |
| 2026-01-30 | セクション10追加（監視KPI） |
| 2026-01-30 | セクション11追加（organization_id管理） |
| 2026-01-30 | セクション12追加（外部サービス障害対応: Google Drive, Pinecone, DNS） |
| 2026-01-30 | セクション13追加（インフラ障害対応: メモリリーク, ディスク容量） |
| 2026-01-30 | セクション14追加（DBマイグレーション障害対応） |
| 2026-01-30 | セクション15追加（DDoS攻撃対応） |

---

**このファイルについての質問は、CLAUDE.mdを参照してください。**
