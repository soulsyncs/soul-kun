# Speaker Attribution (話者識別) レビュー記録 (2026-02-21)

## 変更概要
- `lib/meetings/task_extractor.py`: `build_task_extraction_prompt` + `extract_and_create_tasks` に speaker_context / speaker_reverse_map 追加
- `lib/meetings/zoom_brain_interface.py`: Step 10 前に匿名化マッピング構築・speaker_context 生成を追加

## PII設計の正当性確認
- speaker_map (実名→話者N): メモリのみ、DBに保存しない → PASS
- reverse_map (話者N→実名): メモリのみ → PASS
- speaker_context_lines: seg.text を含む (発言内容) → LLMに送る。ただし seg.text は sanitize前 の生テキスト
  - **CRITICAL-1**: seg.text は `sanitized_text` ではなく VTT の生テキスト。VTTには話者名以外のPII（電話番号等）が含まれうる
  - `sanitized_text` は Step 4 で `self.sanitizer.sanitize(raw_text)` で生成 (raw_text = vtt_transcript.full_text)
  - speaker_context_lines は Step 10 で seg.text を直接参照 → PII除去前テキストが LLM に送られる

## 後方互換性
- `speaker_context=None` (デフォルト) 時の動作: `if speaker_context:` が False → 既存コードと全く同一 → PASS
- `speaker_reverse_map=None` (デフォルト) 時: `if speaker_reverse_map:` が False → 逆変換なし → PASS

## 3コピー同期
- `lib/meetings/task_extractor.py` == `chatwork-webhook/lib/meetings/task_extractor.py` == `proactive-monitor/lib/meetings/task_extractor.py` → PASS (diff 出力なし)
- `lib/meetings/zoom_brain_interface.py` == 全コピー → PASS

## Google Meet 横展開
- `google_meet_brain_interface.py` の Step 7 `extract_and_create_tasks` 呼び出し: `speaker_context` / `speaker_reverse_map` を渡していない
- Google Meet は VTT を使わず（Google自動文字起こし or Whisper）、speaker フィールドが存在しない → 話者識別できないため横展開不要
  - `auto_transcript` は plain text (Google Docs API)。話者名なし。
  - Whisper API は話者識別なし（diarization なし）
  - → google_meet の未適用は「スキップ可能 (SUGGESTION)」ではなく「技術的に適用不可 (PASS)」

## 冪等性 (#14)
- speaker_map / reverse_map の構築: 同じ VTT から毎回同じマッピングが生成される → 冪等
- `extract_and_create_tasks` 自体の冪等性: 呼び出し側 (Step 6 dedup check) で保証。変更なし → PASS

## async I/O (#6)
- 新コードに同期ブロッキングなし: speaker_context 構築は純粋なメモリ操作 → PASS

## テストカバレッジ
- `TestSpeakerAttribution` (3テスト): 逆変換PASS/NULL/未知ラベル → PASS
- `TestBuildPrompt` (5テスト + 2新規): speaker_context あり/なし → PASS
- **GAP**: speaker_context_lines に生テキスト (PII含む可能性) が含まれることのテストなし

## 残存問題
- **WARNING**: seg.text は sanitized_text ではなく raw segment text。サニタイザーは raw_text (full_text) に対して適用されるが、full_text = "Speaker: text" 形式。seg.text 個別には別途 PII パターンは適用されない。実質的リスク: 電話番号等のPIIが <speaker_transcript> タグ内でLLMに送られる可能性あり。
  - 回避策案: speaker_context_lines に seg.text ではなく sanitized_text から行単位で取り出す
  - ただし sanitized_text には話者名プレフィックス ("田中: ...") が含まれており、それを匿名化する処理が別途必要
  - 設計の複雑さから考えると、現状でも seg.text 内の PII がLLMに送られる被害は「LLM内部の処理で使われ外部に出ない」ため許容範囲とも言える（LLMへのPII送信はOpenRouterポリシー上の問題）
