# Phase 2 進化版: A4 感情変化検出 - 詳細設計書

**バージョン:** v1.0
**作成日:** 2026-01-24
**作成者:** Claude Code（経営参謀・SE・PM）
**ステータス:** 実装完了

---

## 1. エグゼクティブサマリー

### 1.1 この設計書の目的

**A4 感情変化検出**は、Phase 2進化版「24機能」のA群（気づく能力）の第4弾として、**従業員のメッセージから感情の変化を検出し、メンタルヘルスリスクを早期に可視化する機能**です。

### 1.2 3行で要約

1. **何をするか**: ソウルくんへのメッセージを分析し、従業員の感情変化（悪化・回復）を検出
2. **なぜ必要か**: 早期発見で離職防止・生産性向上。「人にしかできないケア」を支援するAI機能
3. **どう作るか**: room_messages分析 → LLM感情スコアリング → `emotion_alerts` に保存 → 管理者に通知

### 1.3 期待される効果

| 指標 | 現状 | 導入後 | 改善率 |
|------|------|--------|--------|
| メンタル不調の早期発見 | 発覚時（手遅れ） | 兆候段階 | **大幅改善** |
| 離職リスクの可視化 | なし | 自動検出 | **新規** |
| 面談機会の適切化 | 定期的（形式的） | 必要時（実質的） | **効率化** |

### 1.4 プライバシー・倫理的配慮

**重要**: この機能は従業員のメンタルヘルスに関わるセンシティブな機能です。

| 原則 | 実装 |
|------|------|
| **プライバシー最優先** | 全データはCONFIDENTIAL分類、DBレベルで強制 |
| **管理者のみ通知** | 本人には直接通知しない |
| **メッセージ本文非保存** | 感情スコアのみ保存、本文はDBに残さない |
| **支援的フレーミング** | 「監視」ではなく「ウェルネスチェック」 |

---

## 2. 全体設計との整合性

### 2.1 Phase 2進化版における位置づけ

```
Phase 2 進化版（24機能）
├─ A. 気づく能力（4機能）
│   ├─ A1. パターン検出 ✅ 完了
│   ├─ A2. 属人化検出 ✅ 完了
│   ├─ A3. ボトルネック検出 ✅ 完了
│   └─ ★ A4. 感情変化検出 ← 本設計書のスコープ ✅ 完了
├─ B. 覚える能力（4機能）
├─ C. 先読みする能力（4機能）
├─ D. つなぐ能力（3機能）
├─ E. 育てる能力（3機能）
├─ F. 自動化能力（3機能）
├─ G. 進化する能力（3機能）
└─ H. 守る能力（2機能）
```

### 2.2 既存Phaseとの連携

| Phase | 連携内容 |
|-------|---------|
| Phase 1 | room_messages - メッセージデータの分析対象 |
| Phase 1-B | notification_logs - 通知の冪等性を共有 |
| Phase 2 A1 | soulkun_insights - インサイト統合 |
| Phase 3.5 | 組織階層 - 部署ごとの感情トレンド分析 |

---

## 3. 機能設計

### 3.1 機能概要

```
┌─────────────────────────────────────────────────────────────┐
│                   A4 感情変化検出フロー                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  【入力】                                                   │
│  room_messages テーブル（直近14日間）                       │
│       ↓                                                     │
│  【処理1】アクティブユーザーの特定                          │
│  - 分析期間内に5件以上メッセージがあるユーザー              │
│       ↓                                                     │
│  【処理2】感情スコア分析                                    │
│  - LLM（Gemini 3 Flash）でメッセージを分析                  │
│  - -1.0（非常にネガティブ）〜 1.0（非常にポジティブ）       │
│  - emotion_scores テーブルに保存                            │
│       ↓                                                     │
│  【処理3】感情変化検出                                      │
│  - ベースラインスコア（過去30日平均）との比較               │
│  - 急激な悪化、継続的なネガティブを検出                     │
│       ↓                                                     │
│  【処理4】アラートDB更新                                    │
│  - emotion_alerts テーブルに記録                            │
│  - soulkun_insights に登録（critical/high）                 │
│       ↓                                                     │
│  【出力】                                                   │
│  管理者に通知（本人には通知しない）                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 検出パラメータ

| パラメータ | デフォルト値 | 説明 | 変更可能 |
|-----------|------------|------|---------|
| EMOTION_ANALYSIS_WINDOW_DAYS | 14日 | 分析対象期間 | ○ |
| EMOTION_BASELINE_WINDOW_DAYS | 30日 | ベースライン計算期間 | ○ |
| MIN_MESSAGES_FOR_EMOTION | 5件 | 分析に必要な最小メッセージ数 | ○ |
| SENTIMENT_DROP_CRITICAL | 0.4 | Critical判定の悪化閾値 | ○ |
| SENTIMENT_DROP_HIGH | 0.3 | High判定の悪化閾値 | ○ |
| SUSTAINED_NEGATIVE_CRITICAL_DAYS | 7日 | Critical判定の継続日数 | ○ |
| SUSTAINED_NEGATIVE_HIGH_DAYS | 5日 | High判定の継続日数 | ○ |
| NEGATIVE_SCORE_THRESHOLD | -0.2 | ネガティブ判定の閾値 | ○ |
| VERY_NEGATIVE_SCORE_THRESHOLD | -0.5 | 非常にネガティブ判定の閾値 | ○ |

### 3.3 リスクレベル判定ロジック

```python
def determine_risk_level(baseline, current, consecutive_days):
    score_drop = baseline - current

    # Critical条件
    if score_drop >= 0.4 and consecutive_days >= 3:
        return CRITICAL
    if current <= -0.5 and consecutive_days >= 7:
        return CRITICAL

    # High条件
    if score_drop >= 0.3 and consecutive_days >= 2:
        return HIGH
    if current <= -0.3 and consecutive_days >= 5:
        return HIGH

    # Medium条件
    if score_drop >= 0.2:
        return MEDIUM
    if current <= -0.2 and consecutive_days >= 3:
        return MEDIUM

    return LOW
```

### 3.4 アラートタイプ

| タイプ | 説明 | 通知条件 |
|--------|------|---------|
| `sudden_drop` | 急激な感情悪化 | 0.3以上のスコア低下 |
| `sustained_negative` | 継続的なネガティブ | 3日以上連続でネガティブ |
| `high_volatility` | 感情の不安定さ | 大きな波がある |
| `recovery` | 回復 | ネガティブからの回復（ポジティブ変化） |

---

## 4. データベース設計

### 4.1 emotion_scores テーブル

メッセージごとの感情分析結果を保存。

```sql
CREATE TABLE emotion_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    message_id BIGINT NOT NULL,
    room_id BIGINT NOT NULL,
    user_id UUID NOT NULL,

    sentiment_score DECIMAL(4,3) NOT NULL,  -- -1.000〜1.000
    sentiment_label VARCHAR(20) NOT NULL,    -- very_negative/negative/neutral/positive/very_positive
    confidence DECIMAL(4,3),
    detected_emotions TEXT[],                -- ['frustration', 'anxiety']
    analysis_model VARCHAR(100),

    message_time TIMESTAMPTZ NOT NULL,
    analyzed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    classification VARCHAR(20) DEFAULT 'confidential'
        CHECK (classification = 'confidential'),  -- 常にCONFIDENTIAL

    UNIQUE(organization_id, message_id)
);
```

### 4.2 emotion_alerts テーブル

検出されたアラートを保存。

```sql
CREATE TABLE emotion_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id UUID NOT NULL,
    user_name VARCHAR(255),
    department_id UUID,

    alert_type VARCHAR(50) NOT NULL,  -- sudden_drop/sustained_negative/high_volatility/recovery
    risk_level VARCHAR(20) NOT NULL,  -- critical/high/medium/low

    baseline_score DECIMAL(4,3),
    current_score DECIMAL(4,3),
    score_change DECIMAL(4,3),
    consecutive_negative_days INT,

    analysis_start_date DATE NOT NULL,
    analysis_end_date DATE NOT NULL,

    message_count INT,
    negative_message_count INT,
    evidence JSONB DEFAULT '{}',  -- 統計のみ、メッセージ本文は含めない

    status VARCHAR(20) DEFAULT 'active',
    classification VARCHAR(20) DEFAULT 'confidential'
        CHECK (classification = 'confidential'),  -- 常にCONFIDENTIAL

    UNIQUE(organization_id, user_id, alert_type, analysis_start_date)
);
```

### 4.3 インデックス

```sql
-- emotion_scores
CREATE INDEX idx_emotion_scores_user_time ON emotion_scores(organization_id, user_id, message_time DESC);
CREATE INDEX idx_emotion_scores_negative ON emotion_scores(organization_id, sentiment_label)
    WHERE sentiment_label IN ('negative', 'very_negative');

-- emotion_alerts
CREATE INDEX idx_emotion_alerts_org_level ON emotion_alerts(organization_id, risk_level);
CREATE INDEX idx_emotion_alerts_status ON emotion_alerts(organization_id, status) WHERE status = 'active';
```

---

## 5. LLM統合

### 5.1 感情分析プロンプト

```python
SENTIMENT_ANALYSIS_PROMPT = """あなたは職場メッセージの感情分析専門家です。
以下のメッセージの感情トーンを分析し、JSON形式で返してください。

分析ポイント:
- 全体的な感情トーン（ポジティブ/ニュートラル/ネガティブ）
- 検出された感情（不満、不安、疲労、焦り、喜び等）
- 信頼度（分析の確実性）

出力形式（JSONのみ）:
{
  "sentiment_score": -1.0〜1.0の数値,
  "sentiment_label": "very_negative" | "negative" | "neutral" | "positive" | "very_positive",
  "detected_emotions": ["感情1", "感情2"],
  "confidence": 0.0〜1.0の数値
}

メッセージ:
"""
```

### 5.2 使用モデル

| モデル | 用途 | コスト |
|--------|------|--------|
| google/gemini-3-flash-preview | 感情分析（デフォルト） | 低コスト |

---

## 6. 実装ファイル

| ファイル | 内容 |
|---------|------|
| `lib/detection/constants.py` | A4パラメータ、Enum定義 |
| `lib/detection/emotion_detector.py` | EmotionDetectorクラス |
| `lib/detection/__init__.py` | エクスポート定義 |
| `pattern-detection/main.py` | emotion_detectionエンドポイント |
| `migrations/phase2_a4_emotion_detection.sql` | DBスキーマ |

---

## 7. Cloud Function / Scheduler

### 7.1 エンドポイント

```
POST /emotion-detection
```

### 7.2 Cloud Scheduler設定

```bash
gcloud scheduler jobs create http emotion-detection-daily \
  --schedule="0 10 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://REGION-PROJECT.cloudfunctions.net/emotion-detection" \
  --http-method=POST
```

実行タイミング: **毎日 10:00 JST**（A2/A3の後）

---

## 8. 10の鉄則への準拠

| 鉄則 | A4での対応 |
|------|----------|
| 1. organization_id | ✅ 全テーブルに含む |
| 2. RLS | ✅ Phase 4で有効化予定 |
| 3. 監査ログ | ✅ CONFIDENTIAL以上で記録 |
| 4. API認証 | ✅ Bearer Token必須 |
| 5. ページネーション | ✅ 必要に応じて実装 |
| 6. キャッシュTTL | ⏳ Phase 4で導入 |
| 7. APIバージョニング | ✅ /api/v1/ |
| 8. エラーに機密情報なし | ✅ サニタイズ実装 |
| 9. SQLパラメータ化 | ✅ プレースホルダ使用 |
| 10. トランザクション内API禁止 | ✅ LLM呼び出しは分離 |

---

## 9. 今後の拡張予定

### 9.1 Phase 2.5との連携

- 目標設定対話中の感情分析
- 目標未達時のメンタル変化検出

### 9.2 チームレベル分析

- 部署ごとの感情トレンド
- チーム全体のモチベーション可視化

### 9.3 予防的アラート

- 過去パターンからのリスク予測
- 早期介入の提案

---

## 変更履歴

| バージョン | 日付 | 変更者 | 変更内容 |
|-----------|------|--------|---------|
| v1.0 | 2026-01-24 | Claude Code | 初版作成 |
