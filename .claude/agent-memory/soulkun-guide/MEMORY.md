# Soul-kun Zoom議事録処理フロー

## 1. Webhookエンドポイント
- **ファイル**: `/Users/kikubookair/soul-kun/chatwork-webhook/routes/zoom.py`
- **関数**: `zoom_webhook()` (L28)
- **エンドポイント**: `/zoom-webhook`
- **HTTPメソッド**: POST, GET

### リクエストフロー
1. Flask でリクエスト受信
2. HMAC-SHA256署名検証 (`verify_zoom_webhook_signature`)
3. イベントタイプ判定
   - `endpoint.url_validation` → チャレンジ応答
   - `recording.completed` → 議事録生成パイプライン開始
4. 即座に200応答（Zoomタイムアウト防止）
5. バックグラウンドスレッドで非同期処理開始

## 2. 議事録処理フロー（詳細順序）

### Step 1: Webhookハンドラー
- **ファイル**: `/Users/kikubookair/soul-kun/handlers/zoom_webhook_handler.py` (L36-149)
- **関数**: `handle_zoom_webhook_event(event_type, payload, pool, organization_id, get_ai_response_func)`
- **戻り値**: `HandlerResult`

**処理内容**:
- Zoom meeting_id, topic, host_email, recording_files を抽出（L65-70）
- VTTファイル有無チェック（L73-75）
- Google Calendar照合（オプショナル、Phase 3）（L96）
- ChatWorkルーム自動振り分け（Phase 4）（L108-110）
- `ZoomBrainInterface.process_zoom_minutes()` 呼び出し（L127）

### Step 2: Zoom Brain インターフェース
- **ファイル**: `/Users/kikubookair/soul-kun/lib/meetings/zoom_brain_interface.py` (L88-405)
- **クラス**: `ZoomBrainInterface`
- **メインメソッド**: `process_zoom_minutes()` (L88-405)

**11段階の処理**:

| Step | 処理内容 | 関数/メソッド | エラー時の動作 |
|------|---------|--------------|--------------|
| 1 | Zoom APIからRecording取得 | `_find_recording()` | 「直近のZoomミーティングの録画が見つからなかった」メッセージを返す |
| 2 | VTT Transcript URL検索（指数バックオフ3回: 30s+60s+120s） | `zoom_client.find_transcript_url()` | 3回失敗後、retry=Trueで終了 |
| 3 | VTTダウンロード | `zoom_client.download_transcript()` | 「文字起こしがまだ準備中」メッセージを返す |
| 4 | VTTパース | `parse_vtt()` | 「文字起こしが空」メッセージを返す |
| 5 | PII除去 | `TranscriptSanitizer.sanitize()` | スキップしない（必須） |
| 6 | 重複チェック + DB保存 | `MeetingDB.find_meeting_by_source_id()`, `create_meeting()` | 既に処理済みなら「議事録は既に作成済み」を返す |
| 7 | LLM議事録生成 | `_generate_minutes()` → `get_ai_response_func()` | 失敗時は minutes=None（Step 8以降は実行） |
| 8 | 録画URL取得 | `zoom_client.find_recording_play_url()` | None でもスキップ |
| 9 | Google Docs保存 | `create_meeting_docs_publisher().publish_to_google_docs()` | 失敗時はログ警告のみ |
| 10 | タスク自動抽出 | `extract_and_create_tasks()` | 失敗時はログ警告のみ |
| 11 | ChatWork用メッセージ組み立て | `_build_delivery_message()` or `_build_transcript_only_message()` | 常に成功 |

**重要**: Step 6で重複チェック時に `dedup_hash` (SHA256: source+topic+start_time) を使用。source_meeting_id=None の場合のフォールバック。

### Step 3: VTT パーサー
- **ファイル**: `/Users/kikubookair/soul-kun/lib/meetings/vtt_parser.py` (L100-191)
- **関数**: `parse_vtt(vtt_content: str) -> VTTTranscript`

**処理**:
- WebVTT形式をパース（タイムスタンプ + 話者名 + テキスト）
- セグメント化（VTTSegment）
- 話者リスト抽出（重複排除）
- 総再生秒数計算

### Step 4: PII除去
- **ファイル**: `/Users/kikubookair/soul-kun/lib/meetings/transcript_sanitizer.py`
- **クラス**: `TranscriptSanitizer` (L64-138)
- **メインメソッド**: `sanitize(text: str) -> Tuple[str, int]`

**除去対象パターン**:
1. **会議固有パターン** (MEETING_EXTRA_PATTERNS):
   - クレジットカード番号: `1234-5678-9012-3456` → `[CARD]`
   - 日本の住所（都道府県+番地）→ `[ADDRESS]`
   - 社員番号（AA-1234等）→ `[EMPLOYEE_ID]`
   - マイナンバー（1234 5678 9012）→ `[MY_NUMBER]`
2. **既存パターン** (MASK_PATTERNS from memory_sanitizer.py):
   - 電話番号、メールアドレス、個人名など

**長文対応**: チャンク分割処理（chunk_size=1000文字、overlap=50文字）

### Step 5: LLM議事録生成
- **ファイル**: `/Users/kikubookair/soul-kun/lib/meetings/minutes_generator.py` (L244-276, L465-496)
- **関数**:
  - `build_chatwork_minutes_prompt(transcript_text, meeting_title)` (L244)
  - `_generate_minutes()` in zoom_brain_interface.py (L465)

**プロンプト設定**:
- **System Prompt**: `CHATWORK_MINUTES_SYSTEM_PROMPT` (L65-87)
- **ユーザーメッセージ**: 会議タイトル + トランスクリプト
- **出力形式**: プレーンテキスト（Vision 12.2.4準拠）
  - `■ 主題（00:00〜）` セクション形式
  - タイムスタンプ付き時系列記述
  - 「■ タスク一覧」セクション
  - HTMLタグなしのプレーンテキスト

**重要**: Brain経由で LLM呼び出し（`get_ai_response_func()` を呼び出し側が注入）。Brain bypass禁止（CLAUDE.md §1）。

### Step 6: ChatWork送信
- **ファイル**: `/Users/kikubookair/soul-kun/chatwork-webhook/routes/zoom.py` (L126-170)
- **関数**: `send_chatwork_message(room_id, message)`

**メッセージ形式**:
```
[info][title]会議名 - 議事録[/title]
🎬 録画: {recording_url}
📄 Google Docs: {document_url}

（議事録テキスト）

✅ タスク: X件作成
⚠️ 担当者不明: Y件
[/info]
```

**フォールバック**: minutes生成失敗時は「トランスクリプト概要メッセージ」を送信

## 3. 関連する環境変数

| 環境変数名 | 設定値 | 用途 |
|-----------|-------|------|
| `ENABLE_ZOOM_WEBHOOK` | `true` or `1` | Zoom webhook処理の有効/無効 |
| `ENABLE_GOOGLE_CALENDAR` | `true` or `1` | Google Calendar照合の有効/無効（デフォルト: disabled） |
| `ENABLE_ZOOM_MEETING_MINUTES` | `true` | capability_bridge.py で feature flag (L362) |
| `ZOOM_OAUTH_URL` | `https://zoom.us/oauth/token` | Zoom OAuth エンドポイント（デフォルト） |
| `ZOOM_API_BASE` | `https://api.zoom.us/v2` | Zoom API ベースURL（デフォルト） |
| `ENABLE_GOOGLE_MEET_MINUTES` | `true` | Google Meet議事録の有効/無効 |

**Secret Manager経由で取得** (lib/secrets.py):
- `zoom-webhook-secret-token`（HMAC検証用）
- `zoom-account-id`
- `zoom-client-id`
- `zoom-client-secret`

## 4. エラーハンドリング

### Webhook層 (routes/zoom.py)
| エラー条件 | HTTP Status | メッセージ | 致命性 |
|-----------|------------|---------|--------|
| リクエスト本文が空 | 400 | "Empty body" | 致命的 |
| Secret Token未設定 | 500 | "Server configuration error" | 致命的 |
| JSON パースエラー | 400 | "Invalid JSON" | 致命的 |
| 署名検証失敗 | 403 | "Invalid signature" | 致命的（不正リクエスト） |
| plainToken 不足 | 400 | "Missing plainToken" | 致命的（url_validation） |
| Webhook feature flag無効 | 200 | "disabled" | OK（処理スキップ） |

### 議事録生成層 (zoom_brain_interface.py)
| エラー条件 | メッセージ | retry フラグ | 処理継続 |
|-----------|---------|----------|--------|
| Recording未検出 | 「直近のZoomミーティングの録画が見つからなかった」 | false | 停止 |
| VTT未準備（3回リトライ後） | 「文字起こしがまだ準備中」 | true | 停止 |
| VTTダウンロード失敗 | 「文字起こしがまだ準備中」 | false | 停止 |
| VTT空 | 「文字起こしが空」 | false | 停止 |
| 重複処理 | 「議事録は既に作成済み」 | false | 成功扱い（already_processed=true） |
| LLM生成失敗 | （スキップ、トランスクリプトのみ送信） | false | 継続 |
| Google Docs保存失敗 | （ログ警告、処理継続） | false | 継続 |
| タスク抽出失敗 | （ログ警告、処理継続） | false | 継続 |

### ChatWork送信層 (routes/zoom.py L148-156)
```python
try:
    sent = send_chatwork_message(room_id, result.message)
    if sent:
        print(f"✅ ChatWork送信完了")
    else:
        print(f"⚠️ ChatWork送信失敗（API拒否）。議事録はDB保存済み")
except Exception as send_err:
    print(f"⚠️ ChatWork送信失敗: {type(send_err).__name__}")
    # 議事録はDB保存済みのため、送信失敗は致命的ではない
```

**重要**: ChatWork送信は「最善努力」。失敗してもDB保存済みのため影響なし。

## 5. キー設計思想

| 設計原則 | 実装例 |
|---------|-------|
| **CLAUDE.md §1** (全入力は脳を通る) | `get_ai_response_func()` は Brain側から注入。Brain bypass禁止 |
| **CLAUDE.md §3-2 #8** (PII除去) | VTT話者名は DB保存しない。sanitized_transcript のみ保存 |
| **CLAUDE.md §3-2 #6** (async ブロッキング) | `asyncio.to_thread()` で同期API呼び出しをラップ |
| **冪等性** | `dedup_hash` (SHA256) で二重処理防止 |
| **指数バックオフ** | VTT未準備時は 30s→60s→120s の3回リトライ |
| **即座応答** | Webhook受信後すぐ200応答、処理はバックグラウンドスレッド実行 |
| **脳の判断を尊重** | ChatWork投稿判断は Brain側が実施。ハンドラーは結果生成のみ |

## 6. 重要なファイルマップ

```
Webhook Entry Point
    ↓
chatwork-webhook/routes/zoom.py::zoom_webhook()
    ↓ (署名検証)
handlers/zoom_webhook_handler.py::handle_zoom_webhook_event()
    ↓ (calendar照合, room振り分け)
lib/meetings/zoom_brain_interface.py::ZoomBrainInterface.process_zoom_minutes()
    ├─ Step 1-2: lib/meetings/zoom_api_client.py (Recording/VTT URL検索)
    ├─ Step 3: lib/meetings/vtt_parser.py (VTTパース)
    ├─ Step 4: lib/meetings/transcript_sanitizer.py (PII除去)
    ├─ Step 5: lib/meetings/minutes_generator.py (プロンプト構築)
    ├─ Step 7: get_ai_response_func() (Brain経由で LLM呼び出し)
    ├─ Step 9: lib/meetings/docs_brain_integration.py (Google Docs)
    ├─ Step 10: lib/meetings/task_extractor.py (タスク抽出)
    └─ Step 11: 3点セットメッセージ組み立て
    ↓
ChatWork API送信 (routes/zoom.py L149)
```

## 7. テストエントリーポイント
- `tests/test_zoom_webhook_handler.py` - Webhook → handler
- `tests/test_zoom_brain_interface.py` - Brain interface
- `tests/test_zoom_api_client.py` - Zoom APIクライアント
- `tests/test_vtt_parser.py` - VTTパーサー
- `tests/test_transcript_sanitizer.py` - PII除去

## 8. デバッグ用ログレベル
- `logger.info()`: 主要な処理開始/完了、既存課題検出
- `logger.debug()`: VTT段数、file_type スキャン結果、timestamp解析
- `logger.warning()`: Calendar lookup失敗、Google Docs失敗（非致命的）
- `logger.error()`: 全体的なエラー発生
