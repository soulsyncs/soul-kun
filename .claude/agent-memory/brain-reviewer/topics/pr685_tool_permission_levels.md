# PR #685 Tool権限レベル定義 レビューメモ (2026-02-22)

## 変更内容
- `lib/brain/constants.py`: `TOOL_REQUIRED_LEVELS: Dict[str, int]` (38 Tool) + `TOOL_PERMISSION_DENIED_MESSAGE` 追加
- `lib/brain/tool_converter.py`: `_ensure_loaded()` で `TOOL_REQUIRED_LEVELS.get(key, cap.get("required_level", 1))` に変更
- 3コピー同期: PASS (lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/ 全一致確認済み)

## 重要な発見

### TOOL_REQUIRED_LEVELS の流れ
1. `_ensure_loaded()` → `ToolMetadata.required_permission_level` にセット
2. `ToolMetadata.to_dict()` → `"required_permission_level"` キーで辞書に含まれる
3. `get_tool_metadata(tool_name)` で参照可能になる
4. **BUT**: `authorization_gate.py` / `approval_gate.py` は `required_permission_level` を一切参照していない

### TOOL_PERMISSION_DENIED_MESSAGE の問題
- `constants.py` に定義されたが、コードベース全体で `TOOL_PERMISSION_DENIED_MESSAGE` をimportしている箇所はゼロ
- `execution.py` に既存の `ERROR_MESSAGES["permission_denied"]` があるが、こちらも呼び出し箇所はない（定義だけ）
- 新規 `TOOL_PERMISSION_DENIED_MESSAGE` は `execution.py` の既存メッセージと**重複・競合**
- `{required}` プレースホルダー: `str.format(required=N)` で使う想定だが、呼ぶ側がまだ存在しない

### フォールバック Level 1 の安全性問題
- `TOOL_REQUIRED_LEVELS.get(key, cap.get("required_level", 1))` の最終フォールバックは Level 1
- `cap.get("required_level", 1)`: 実際の registry.py は `required_level` キーを一切定義していないので、常にフォールバック 1 になる
- つまり **未知の Tool は全て Level 1（業務委託でも使える）** になる
- ただし現在 `required_permission_level` を実際に enforcement している箇所がないので実害はゼロ（将来問題）

### 既存 required_level との関係
- `SYSTEM_CAPABILITIES` (registry.py) に `"required_level"` キーが定義されているツールは実際には0件
- `cap.get("required_level", 1)` は常に 1 を返していた（PR前から）
- PR後: `TOOL_REQUIRED_LEVELS.get(key, 1)` で38ツールにのみ正しいレベルを設定

## 判定: FAIL（CRITICAL 1件、WARNING 2件）

### CRITICAL-1: 権限チェックが未配線（enforcement なし）
`TOOL_REQUIRED_LEVELS` は `ToolMetadata` にセットされるが、
`authorization_gate.py` / `approval_gate.py` は `required_permission_level` を参照しない。
定義だけ存在し、実際の権限拒否が発生しない。セキュリティ上の誤解を与える危険がある。

### WARNING-1: TOOL_PERMISSION_DENIED_MESSAGE が未使用かつ重複
- importしている箇所: 0
- `execution.py:87` に既存の `ERROR_MESSAGES["permission_denied"]` と重複

### WARNING-2: フォールバック Level 1 の方向性問題（将来リスク）
- 未知Toolが Level 1 になる設計は、enforcement が実装された際に権限昇格バグになりうる
- セキュリティ原則: 不明なものはデフォルト拒否 (fail-closed) が正しい
- 将来 enforcement 実装時に必ず修正が必要

## 既存バグ（pre-existing, このPRは関係なし）
- `execution.py:87` の `ERROR_MESSAGES["permission_denied"]` も呼び出し箇所なし (pre-existing)
- `approval_gate.py` は `required_permission_level` を参照しない (pre-existing)
