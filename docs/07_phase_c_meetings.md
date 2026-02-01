# Phase C: 会議系（議事録自動化）設計書

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | Phase C（会議・議事録自動化）の設計書 |
| **書くこと** | Phase Cのスケジュール、機能概要、価値指標 |
| **書かないこと** | 実装詳細（→専用設計書）、AI文字起こしの技術詳細 |
| **SoT（この文書が正）** | Phase Cのスケジュール、MVP定義 |
| **Owner** | Tech Lead |
| **更新トリガー** | Phase Cの計画変更時 |

---

## 2.2.7 Phase C: 会議系（議事録自動化）【v10.1追加】

### ■ Phase Cの位置づけ

**Phase Cの配置と運用詳細は、別紙「v10.1 Addendum - Phase C配置最終決定 v1.1（2026-01-15）」を参照してください。**

### ■ Phase Cの概要

**実装スケジュール:**

| フェーズ | 時期 | 内容 | 工数（実質） |
|---------|------|------|-------------|
| **MVP0** | Q3 Week 1-2 | Zoom/Meet連携、文字起こし、社内実証開始 | 40h（AI活用） |
| **MVP1** | Q3 Week 5-6 | 議事録自動生成、タスク統合、完全自動化 | 50h（AI活用） |
| **Phase C2** | Q4以降 | ナレッジ化、決定事項追跡 | 2026年内見送り |

**Phase Cの価値:**

| 指標 | 数値 | 備考 |
|------|------|------|
| 社内削減効果 | 年間117万円 | 実測ベースで更新 |
| 社内開発コスト | 55万円 | 110h × 5,000円/h |
| ROI | 113% | 投資回収期間6ヶ月 |
| BPaaS外販 | Phase 3.6とセット販売可能 | 組織図+AI+議事録 |

### ■ Phase Cで実現すること

| # | 機能 | 説明 | MVP |
|---|------|------|-----|
| 1 | Zoom/Meet連携 | 会議録画の自動取得 | MVP0 |
| 2 | 文字起こし | Whisper APIで自動文字起こし | MVP0 |
| 3 | ChatWork投稿 | 文字起こし結果を自動投稿 | MVP0 |
| 4 | 議事録生成 | GPT-4で議事録を自動作成 | MVP1 |
| 5 | タスク統合 | アクションアイテムをタスク化 | MVP1 |
| 6 | ナレッジ化 | 議事録をナレッジDBに登録 | Phase C2 |
| 7 | 決定事項追跡 | 決定事項の進捗管理 | Phase C2 |

### ■ Phase Cの技術スタック

| 要素 | 技術 | 理由 |
|------|------|------|
| 会議録画 | Zoom API, Google Meet API | 既存ツールと連携 |
| 文字起こし | OpenAI Whisper API | 精度が高い |
| 議事録生成 | GPT-4 | 議事録の品質が高い |
| ストレージ | Google Cloud Storage | 録画保存用 |
| データベース | Cloud SQL (PostgreSQL) | 既存システムと統一 |

### ■ 会議録音のPII保護設計【v10.55追加】

会議録音は個人情報を多量に含むため、厳格なPII保護が必要です。

#### 同意取得ルール

| 段階 | 内容 | 実装 |
|------|------|------|
| **事前同意** | 会議参加者全員に録音の同意を取得 | 会議開始時にボット発言で通知 |
| **明示的表示** | 録音中であることを常時表示 | Zoom/Meet上に「Recording」表示確認 |
| **オプトアウト** | 録音を拒否した参加者への対応 | その参加者の音声はマスキング処理 |
| **同意記録** | 誰がいつ同意したかを記録 | `meeting_consent_logs`テーブルに保存 |

```python
# 同意取得のテンプレートメッセージ
RECORDING_CONSENT_MESSAGE = """
[自動通知] この会議は録音・文字起こしされます。
録音データは90日後に自動削除されます。
録音に同意しない場合は「/opt-out」とチャットしてください。
"""
```

#### 保持期間ポリシー

| データ種別 | 保持期間 | 削除方法 | 根拠 |
|-----------|---------|---------|------|
| **録音ファイル** | 90日 | 物理削除（GCS自動削除ポリシー） | 個人情報保護法 |
| **文字起こし** | 90日 | 論理削除→7日後物理削除 | 監査対応期間 |
| **議事録** | 無期限 | 削除なし（PII除去済み） | 業務記録 |
| **同意ログ** | 1年 | 物理削除 | コンプライアンス |
| **メタデータ** | 1年 | 物理削除 | 監査対応 |

```sql
-- GCS自動削除ポリシー設定
-- gsutil lifecycle set lifecycle.json gs://soulkun-meeting-recordings
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 90}
  }]
}
```

#### 自動削除手順

```python
# lib/meetings/retention.py

async def cleanup_expired_recordings():
    """90日超過の録音データを削除する（日次バッチ）"""

    expiry_date = datetime.now() - timedelta(days=90)

    # 1. 対象レコードを取得
    expired_meetings = await MeetingRecording.filter(
        created_at__lt=expiry_date,
        is_deleted=False
    ).all()

    for meeting in expired_meetings:
        async with transaction():
            # 2. GCSから録音ファイルを削除
            await delete_from_gcs(meeting.recording_url)

            # 3. 文字起こしデータを削除
            await MeetingTranscript.filter(
                meeting_id=meeting.id
            ).delete()

            # 4. 論理削除フラグを設定
            meeting.is_deleted = True
            meeting.deleted_at = datetime.now()
            await meeting.save()

            # 5. 監査ログに記録
            await audit_log(
                action="meeting_recording_deleted",
                resource_id=meeting.id,
                reason="retention_policy_90_days"
            )

    return len(expired_meetings)
```

#### アクセス権限設計

| 権限レベル | 録音ファイル | 文字起こし | 議事録 | 備考 |
|-----------|-------------|-----------|-------|------|
| **参加者** | ○ | ○ | ○ | 自分が参加した会議のみ |
| **上長** | ○ | ○ | ○ | 部下が参加した会議（組織階層判定） |
| **管理者** | ○ | ○ | ○ | 同一organization_id内のみ |
| **システム** | ○ | ○ | ○ | バッチ処理用 |
| **外部** | × | × | × | 一切アクセス不可 |

```python
# lib/meetings/access_control.py

async def check_meeting_access(
    user: User,
    meeting_id: str,
    access_type: str  # "recording" | "transcript" | "minutes"
) -> bool:
    """会議データへのアクセス権限を確認"""

    meeting = await Meeting.get(meeting_id)

    # 1. organization_idチェック（必須）
    if user.organization_id != meeting.organization_id:
        return False

    # 2. 参加者チェック
    is_participant = await MeetingParticipant.filter(
        meeting_id=meeting_id,
        user_id=user.id
    ).exists()

    if is_participant:
        return True

    # 3. 組織階層による上長チェック
    participant_ids = await MeetingParticipant.filter(
        meeting_id=meeting_id
    ).values_list("user_id", flat=True)

    accessible_users = await get_subordinates(user)

    if any(p_id in accessible_users for p_id in participant_ids):
        return True

    # 4. 管理者チェック
    if user.role in ["admin", "system"]:
        return True

    return False
```

#### PII除去処理

文字起こしから議事録を生成する際、PIIを自動除去します：

```python
# lib/meetings/pii_sanitizer.py

MEETING_PII_PATTERNS = [
    # 電話番号（会議中に読み上げられたもの）
    (r"\b0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}\b", "[電話番号]"),

    # メールアドレス
    (r"[\w\.\-]+@[\w\.\-]+\.\w+", "[メールアドレス]"),

    # クレジットカード番号
    (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "[カード番号]"),

    # 住所パターン
    (r"[都道府県市区町村].{5,30}[番号丁目]", "[住所]"),

    # 社員番号
    (r"\b[A-Z]{2,3}[-]?\d{4,6}\b", "[社員番号]"),
]

def sanitize_transcript_for_minutes(transcript: str) -> str:
    """文字起こしからPIIを除去して議事録用にする"""
    sanitized = transcript
    for pattern, replacement in MEETING_PII_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized
```

#### 監査ログ設計

| イベント | 記録内容 | 保持期間 |
|---------|---------|---------|
| 録音開始 | meeting_id, start_time, participants_count | 1年 |
| 録音終了 | meeting_id, end_time, file_size | 1年 |
| 文字起こし完了 | meeting_id, word_count, processing_time | 1年 |
| 議事録生成 | meeting_id, minutes_id, token_count | 1年 |
| 録音アクセス | user_id, meeting_id, access_type | 1年 |
| 録音削除 | meeting_id, reason, deleted_by | 1年 |
| 同意取得 | meeting_id, user_id, consent_type | 1年 |
| オプトアウト | meeting_id, user_id, reason | 1年 |

> **注意**: 監査ログにはPII（名前、メールアドレス等）を含めず、IDのみを記録します。

---

### ■ Phase Cの依存関係

**前提条件:**
- Phase 1（タスク管理基盤）が完成していること
- ChatWork API連携が確立していること
- OpenAI API連携が確立していること

**Phase Cが前提となるPhase:**
- Phase C2（ナレッジ化）にはPhase 3（ナレッジ系）が必要

### ■ Phase Cの詳細

**詳細設計、実装ガイド、リスク対策、効果測定等の完全な情報は、以下の別紙を参照してください:**

**📄 v10.1 Addendum - Phase C配置最終決定 v1.1（2026-01-15）**

**Addendum v1.1の内容:**
- エグゼクティブサマリー
- 背景と哲学の転換
- 実装スケジュール詳細
- **9つの鉄壁保証**（v1.0の6つ + v1.1で3つ追加）
- データベース設計（v1.1改善版）
  - **tenant_id/organization_id 同義宣言**
  - **department_id/confidentiality_level 追加**（Phase 3.5準拠）
  - **created_by/updated_by 追加**（v10.1準拠）
- **状態遷移責務表 + 楽観ロック実装**（二重起動防止）
- **監査ログ統合設計**（v10.1第7.3章準拠）
- **Phase C2準備設計**（ナレッジ化：embedding/chunks）
- **Phase 1-B統合詳細**（タスク統合）
- 実装ガイド
- リスク管理
- 効果測定
- 次のアクション

**技術的負債の解消:**
- v1.0時点: 69.5h（約1.7週間分）
- v1.1時点: **0h**（完全解消）
---

（続く...）


---

**[📁 目次に戻る](00_README.md)**
