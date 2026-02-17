# 診断レポート: MCP Tools未使用 + カレンダー→MVV誤回答

**日付**: 2026-02-18
**鉄則#11**: Step1完了 → Step2（診断ログ追加）→ Step3待ち（本番ログ確認）

## 仮説（3AI合議済み: Claude + Codex + Gemini 全員一致）

LLM Brain（新しい脳）が本番で初期化に失敗し、旧パス（キーワードマッチング方式）にサイレントフォールバックしている。

## 診断ログ5箇所

1. `initialization.py`: LLMBrain初期化の成功/失敗（exc_info付き）
2. `message_processing.py`: ルーティング判定（flag vs brain_obj）
3. `main.py`: 旧パスget_ai_response呼び出し検出
4. `llm_inference.py`: LLM Brainパスのツール選択結果（PII除外）
5. `build_context.py`: LLMに渡すツール数・名前一覧
